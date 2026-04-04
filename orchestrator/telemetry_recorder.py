"""
TelemetryRecorder — Captures per-bot telemetry frames during matches
and persists them as gzipped JSON files with a SQLite index.

Usage:
    recorder = TelemetryRecorder(db_session_factory, telemetry_dir="telemetry")
    telemetry_hub.register_hook(recorder.on_frame)

    recorder.start_recording(match_id=34, bot_ids=[7, 10])
    # ... match runs, frames flow via on_frame hook ...
    await recorder.stop_recording(match_id=34)
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("clawquake.telemetry_recorder")

TELEMETRY_DIR = os.environ.get("TELEMETRY_DIR", "telemetry")


class TelemetryRecorder:
    """Captures telemetry frames in-memory during matches, writes to disk on stop."""

    def __init__(self, db_session_factory, telemetry_dir: str = TELEMETRY_DIR):
        self._db_factory = db_session_factory
        self._dir = Path(telemetry_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Active recordings: {match_id: {bot_id: [frames]}}
        self._buffers: dict[int, dict[int, list[dict]]] = {}
        # Track which bot_ids belong to which match
        self._bot_to_match: dict[int, int] = {}
        # Bot name lookup (set at start_recording)
        self._bot_names: dict[int, str] = {}

    def start_recording(self, match_id: int, bots: list[dict]) -> None:
        """Begin recording for a match. bots = [{"id": N, "name": "..."}]."""
        self._buffers[match_id] = {}
        for bot in bots:
            bot_id = bot["id"]
            self._buffers[match_id][bot_id] = []
            self._bot_to_match[bot_id] = match_id
            self._bot_names[bot_id] = bot.get("name", f"bot-{bot_id}")
        logger.info("Recording started for match %d: %s",
                     match_id, [b["name"] for b in bots])

    def on_frame(self, bot_id: int, frame: dict[str, Any]) -> None:
        """Synchronous hook — called from TelemetryHub.publish(). Just appends."""
        match_id = self._bot_to_match.get(bot_id)
        if match_id is None:
            return
        buf = self._buffers.get(match_id, {}).get(bot_id)
        if buf is not None:
            buf.append(frame)

    async def stop_recording(self, match_id: int) -> list[dict]:
        """Stop recording and write files. Returns index entries."""
        buffers = self._buffers.pop(match_id, {})
        if not buffers:
            logger.warning("No recording buffers for match %d", match_id)
            return []

        # Clean up bot_to_match
        for bot_id in buffers:
            self._bot_to_match.pop(bot_id, None)

        # Write files in thread executor to avoid blocking event loop
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, self._write_files, match_id, buffers
        )
        return entries

    def _write_files(self, match_id: int, buffers: dict[int, list[dict]]) -> list[dict]:
        """Write gzipped JSON files and insert DB index rows. Runs in thread."""
        match_dir = self._dir / str(match_id)
        match_dir.mkdir(parents=True, exist_ok=True)

        entries = []
        for bot_id, frames in buffers.items():
            bot_name = self._bot_names.get(bot_id, f"bot-{bot_id}")
            if not frames:
                logger.info("Match %d bot %s: 0 frames, skipping", match_id, bot_name)
                continue

            # Compute summary stats
            summary = self._compute_summary(frames)

            payload = {
                "match_id": match_id,
                "bot_id": bot_id,
                "bot_name": bot_name,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "tick_count": len(frames),
                "duration_s": summary["duration_s"],
                "summary": summary,
                "frames": frames,
            }

            file_path = match_dir / f"{bot_id}.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            file_size = file_path.stat().st_size

            logger.info("Match %d bot %s: %d frames, %.1fs, %d bytes gzipped",
                        match_id, bot_name, len(frames),
                        summary["duration_s"], file_size)

            # Insert DB index row
            entry = {
                "match_id": match_id,
                "bot_id": bot_id,
                "bot_name": bot_name,
                "file_path": str(file_path),
                "tick_count": len(frames),
                "duration_s": summary["duration_s"],
                "file_size_bytes": file_size,
            }
            self._insert_index_row(entry)
            entries.append(entry)

        # Clean up bot names
        for bot_id in buffers:
            self._bot_names.pop(bot_id, None)

        return entries

    def _insert_index_row(self, entry: dict) -> None:
        """Insert a TelemetryRecordingDB row."""
        try:
            from models import TelemetryRecordingDB
            db = self._db_factory()
            try:
                row = TelemetryRecordingDB(
                    match_id=entry["match_id"],
                    bot_id=entry["bot_id"],
                    bot_name=entry["bot_name"],
                    file_path=entry["file_path"],
                    tick_count=entry["tick_count"],
                    duration_s=entry["duration_s"],
                    file_size_bytes=entry["file_size_bytes"],
                )
                db.add(row)
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.exception("Failed to insert telemetry index row")

    def _compute_summary(self, frames: list[dict]) -> dict:
        """Compute aggregate stats from frame data."""
        if not frames:
            return {"duration_s": 0.0}

        first_ts = frames[0].get("ts", 0)
        last_ts = frames[-1].get("ts", 0)
        duration_s = last_ts - first_ts if last_ts > first_ts else 0.0

        total = len(frames)
        enemies_visible = 0
        firing_ticks = 0
        attack_in_actions = 0
        health_sum = 0
        health_count = 0
        weapon_usage: dict[str, int] = {}

        for f in frames:
            state = f.get("state", f)  # frames may nest state or be flat

            # Enemies visible
            players = state.get("players", [])
            if players:
                enemies_visible += 1

            # Firing state
            if f.get("firing") or state.get("firing"):
                firing_ticks += 1

            # Strategy actions
            actions = f.get("actions_taken", [])
            if any("attack" in a for a in actions):
                attack_in_actions += 1

            # Health
            hp = state.get("my_health")
            if hp is not None:
                health_sum += hp
                health_count += 1

            # Weapon
            wp = state.get("my_weapon", "unknown")
            weapon_usage[wp] = weapon_usage.get(wp, 0) + 1

        return {
            "duration_s": round(duration_s, 1),
            "total_ticks": total,
            "ticks_enemies_visible": enemies_visible,
            "ticks_firing": firing_ticks,
            "ticks_attack_in_actions": attack_in_actions,
            "ticks_enemies_visible_not_firing": max(0, enemies_visible - firing_ticks),
            "avg_health": round(health_sum / health_count, 1) if health_count else 0,
            "weapon_usage": weapon_usage,
            "pct_time_enemies_visible": round(100 * enemies_visible / total, 1) if total else 0,
            "pct_time_firing": round(100 * firing_ticks / total, 1) if total else 0,
        }

    def load_recording(self, file_path: str) -> dict:
        """Load a gzipped telemetry file."""
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            return json.load(f)
