"""
ClawQuake Matchmaker — Pairs bots from the queue, creates matches, calculates ELO.

Runs as a background task inside the FastAPI orchestrator.
"""

import asyncio
import logging
import math
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import (
    QueueEntryDB, MatchDB, MatchParticipantDB, BotDB, ApiKeyDB,
    SessionLocal,
)

logger = logging.getLogger("clawquake.matchmaker")

# ── Constants ────────────────────────────────────────────────────

MATCH_DURATION = int(os.environ.get("MATCH_DURATION", "120"))    # seconds
QUEUE_POLL_INTERVAL = int(os.environ.get("QUEUE_POLL_INTERVAL", "5"))  # seconds
MIN_PLAYERS = 2
MAX_PLAYERS = 4
DEFAULT_MAP = "q3dm17"


# ── ELO Calculator ──────────────────────────────────────────────

class EloCalculator:
    """Standard ELO rating calculator."""

    @staticmethod
    def expected_score(rating_a: float, rating_b: float) -> float:
        """Expected probability of A winning against B."""
        return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))

    @staticmethod
    def calculate(winner_elo: float, loser_elo: float, k: int = 32) -> tuple[float, float]:
        """
        Calculate new ELO ratings after a match.
        Returns (new_winner_elo, new_loser_elo).
        Total ELO is conserved.
        """
        expected_winner = EloCalculator.expected_score(winner_elo, loser_elo)
        expected_loser = EloCalculator.expected_score(loser_elo, winner_elo)

        new_winner = winner_elo + k * (1.0 - expected_winner)
        new_loser = loser_elo + k * (0.0 - expected_loser)

        return round(new_winner, 2), round(new_loser, 2)

    @staticmethod
    def calculate_ffa(participants: list[dict], k: int = 32) -> list[dict]:
        """
        Calculate ELO for a FFA match with multiple participants.
        participants: [{"bot_id": int, "elo": float, "score": int}]
        Returns same list with "new_elo" and "elo_change" added.

        In FFA, we rank by score and do pairwise ELO adjustments scaled
        by number of opponents. Winner = higher score in each pair.
        """
        n = len(participants)
        if n < 2:
            for p in participants:
                p["new_elo"] = p["elo"]
                p["elo_change"] = 0.0
            return participants

        # Sort by score descending
        ranked = sorted(participants, key=lambda p: p["score"], reverse=True)

        # Initialize changes
        elo_changes = {p["bot_id"]: 0.0 for p in ranked}

        # Pairwise comparisons — scale K by number of opponents
        pair_k = k / (n - 1) if n > 1 else k
        for i in range(n):
            for j in range(i + 1, n):
                a = ranked[i]
                b = ranked[j]
                # a has higher or equal rank (higher score)
                expected_a = EloCalculator.expected_score(a["elo"], b["elo"])
                expected_b = 1.0 - expected_a

                if a["score"] > b["score"]:
                    # a wins
                    elo_changes[a["bot_id"]] += pair_k * (1.0 - expected_a)
                    elo_changes[b["bot_id"]] += pair_k * (0.0 - expected_b)
                elif a["score"] == b["score"]:
                    # draw
                    elo_changes[a["bot_id"]] += pair_k * (0.5 - expected_a)
                    elo_changes[b["bot_id"]] += pair_k * (0.5 - expected_b)
                else:
                    # b wins (shouldn't happen since sorted, but be safe)
                    elo_changes[a["bot_id"]] += pair_k * (0.0 - expected_a)
                    elo_changes[b["bot_id"]] += pair_k * (1.0 - expected_b)

        for p in participants:
            change = round(elo_changes[p["bot_id"]], 2)
            p["elo_change"] = change
            p["new_elo"] = round(p["elo"] + change, 2)

        return participants


# ── MatchMaker ───────────────────────────────────────────────────

class MatchMaker:
    """
    Background matchmaking engine.
    Polls the queue, pairs bots, creates matches, finalizes results.

    When a process_manager is provided, the run_loop will automatically
    launch bot subprocesses via agent_runner and finalize matches when
    all bots complete. Without a process_manager, matches are created
    in the DB but bots must be launched externally.
    """

    def __init__(self, db_session_factory=None, process_manager=None,
                 rcon_pool=None):
        self.db_factory = db_session_factory or SessionLocal
        self.process_manager = process_manager  # Optional BotProcessManager
        self.rcon_pool = rcon_pool  # Optional RconPool
        self._running = False
        self._active_matches: dict[int, dict] = {}  # match_id -> match info

    def _get_db(self) -> Session:
        return self.db_factory()

    def poll_queue(self) -> Optional[int]:
        """
        Check queue for waiting bots. If >= MIN_PLAYERS, create a match.
        Returns match_id if match created, None otherwise.
        """
        db = self._get_db()
        try:
            waiting = (
                db.query(QueueEntryDB)
                .filter(QueueEntryDB.status == "waiting")
                .order_by(QueueEntryDB.queued_at.asc())
                .limit(MAX_PLAYERS)
                .all()
            )

            if len(waiting) < MIN_PLAYERS:
                return None

            # Create the match
            match_id = self.create_match(db, waiting)
            return match_id
        finally:
            db.close()

    def create_match(self, db: Session, queue_entries: list[QueueEntryDB],
                     map_name: str = DEFAULT_MAP) -> int:
        """
        Create a match record and participants from queued bots.
        Updates queue entries to 'matched' status.
        """
        # Create match record
        match = MatchDB(map_name=map_name, gametype="ffa")
        db.add(match)
        db.flush()  # get match.id

        participants = []
        for entry in queue_entries:
            # Get bot's current ELO
            bot = db.query(BotDB).filter(BotDB.id == entry.bot_id).first()
            if not bot:
                continue

            participant = MatchParticipantDB(
                match_id=match.id,
                bot_id=entry.bot_id,
                elo_before=bot.elo,
            )
            db.add(participant)
            participants.append(participant)

            # Update queue status
            entry.status = "matched"

        db.commit()
        db.refresh(match)

        logger.info(
            f"Match {match.id} created: map={map_name}, "
            f"bots={[e.bot_id for e in queue_entries]}"
        )

        self._active_matches[match.id] = {
            "match": match,
            "started_at": datetime.utcnow(),
            "bot_ids": [e.bot_id for e in queue_entries],
        }

        return match.id

    def collect_result(self, match_id: int, bot_id: int,
                       kills: int, deaths: int, score: Optional[int] = None):
        """
        Record a single bot's results for a match.
        Called when agent_runner POSTs to /api/internal/match/report.
        """
        db = self._get_db()
        try:
            participant = (
                db.query(MatchParticipantDB)
                .filter(
                    MatchParticipantDB.match_id == match_id,
                    MatchParticipantDB.bot_id == bot_id,
                )
                .first()
            )
            if participant:
                participant.kills = kills
                participant.deaths = deaths
                participant.score = score if score is not None else (kills - deaths)
                db.commit()
                logger.info(
                    f"Match {match_id}: bot {bot_id} reported "
                    f"K={kills} D={deaths} S={participant.score}"
                )
        finally:
            db.close()

    def finalize_match(self, match_id: int):
        """
        Finalize a match: calculate ELO for all participants,
        update BotDB stats, mark match as ended.
        """
        db = self._get_db()
        try:
            match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
            if not match:
                logger.error(f"Match {match_id} not found for finalization")
                return

            participants = (
                db.query(MatchParticipantDB)
                .filter(MatchParticipantDB.match_id == match_id)
                .all()
            )

            if not participants:
                logger.warning(f"Match {match_id}: no participants to finalize")
                return

            # Build participant data for ELO calculation
            elo_data = []
            for p in participants:
                bot = db.query(BotDB).filter(BotDB.id == p.bot_id).first()
                if bot:
                    elo_data.append({
                        "bot_id": p.bot_id,
                        "elo": p.elo_before,
                        "score": p.score,
                    })

            # Calculate ELO changes
            elo_results = EloCalculator.calculate_ffa(elo_data)
            elo_map = {r["bot_id"]: r for r in elo_results}

            # Determine winner (highest score)
            winner_id = max(elo_data, key=lambda x: x["score"])["bot_id"] if elo_data else None
            winner_name = None

            # Update participant records and bot stats
            for p in participants:
                if p.bot_id in elo_map:
                    result = elo_map[p.bot_id]
                    p.elo_after = result["new_elo"]

                bot = db.query(BotDB).filter(BotDB.id == p.bot_id).first()
                if bot:
                    bot.kills += p.kills
                    bot.deaths += p.deaths
                    if p.bot_id in elo_map:
                        bot.elo = elo_map[p.bot_id]["new_elo"]

                    if p.bot_id == winner_id:
                        bot.wins += 1
                        winner_name = bot.name
                    else:
                        bot.losses += 1

            # Update match record
            match.ended_at = datetime.utcnow()
            match.winner = winner_name

            # Clean up queue entries
            for p in participants:
                queue_entry = (
                    db.query(QueueEntryDB)
                    .filter(
                        QueueEntryDB.bot_id == p.bot_id,
                        QueueEntryDB.status.in_(["matched", "playing"]),
                    )
                    .first()
                )
                if queue_entry:
                    queue_entry.status = "done"

            db.commit()

            # Clean up active matches tracking
            self._active_matches.pop(match_id, None)

            logger.info(
                f"Match {match_id} finalized: winner={winner_name}, "
                f"participants={len(participants)}"
            )

        finally:
            db.close()

    def _get_server_url(self) -> Optional[str]:
        """Get an available server URL for a new match."""
        if self.rcon_pool:
            server = self.rcon_pool.get_available_server()
            if server:
                # Convert RCON server info to WebSocket URL for bot connection
                host = server.get("ws_host", server.get("host", "localhost"))
                port = server.get("ws_port", server.get("port", 27960))
                return f"ws://{host}:{port}"
        # Fallback to env var or default
        urls = os.environ.get("GAME_SERVER_URLS", "ws://localhost:27960")
        return urls.split(",")[0].strip()

    def _get_bot_strategy(self, db: Session, bot_id: int) -> str:
        """Get the strategy path for a bot. Falls back to default."""
        bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
        if bot:
            # Future: bots may have a strategy_path column
            # For now, use a convention: strategies/<bot_name>.py or default
            strategy_path = f"strategies/{bot.name.lower().replace(' ', '_')}.py"
            if os.path.exists(strategy_path):
                return strategy_path
        return os.environ.get("DEFAULT_STRATEGY", "strategies/default.py")

    def _owner_has_active_key(self, db: Session, owner_id: int) -> bool:
        """
        True if owner has at least one key that is active and not expired.
        No keys counts as ineligible.
        """
        keys = (
            db.query(ApiKeyDB)
            .filter(ApiKeyDB.user_id == owner_id, ApiKeyDB.is_active == 1)
            .all()
        )
        if not keys:
            return False

        now = datetime.utcnow()
        for key in keys:
            expires_at = getattr(key, "expires_at", None)
            if expires_at is None or expires_at > now:
                return True
        return False

    async def _run_match_with_processes(self, match_id: int, bot_ids: list[int]):
        """Launch bot processes, wait for completion, finalize match."""
        if not self.process_manager:
            return

        db = self._get_db()
        try:
            server_url = self._get_server_url()
            if not server_url:
                logger.error(f"Match {match_id}: no available server")
                return

            # Build bot info list
            bots_info = []
            for bot_id in bot_ids:
                bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
                if bot:
                    if not self._owner_has_active_key(db, bot.owner_id):
                        logger.warning(
                            "Match %s: skipping bot %s (id=%s) because owner %s has no active non-expired API key",
                            match_id,
                            bot.name,
                            bot.id,
                            bot.owner_id,
                        )
                        continue
                    bots_info.append({
                        "bot_id": bot.id,
                        "bot_name": bot.name,
                        "strategy_path": self._get_bot_strategy(db, bot.id),
                    })

            if not bots_info:
                logger.error(f"Match {match_id}: no valid bots found after API key validation")
                self.finalize_match(match_id)
                return

            # Launch all bots
            self.process_manager.launch_match(
                match_id=match_id,
                bots=bots_info,
                server_url=server_url,
                duration=MATCH_DURATION,
            )

            # Wait for all bots to finish
            status = await self.process_manager.wait_for_match(match_id)
            logger.info(f"Match {match_id}: all bots finished — {status}")

            # Finalize the match (ELO calculation)
            self.finalize_match(match_id)

            # Clean up process tracking
            self.process_manager.cleanup_match(match_id)

        except Exception as e:
            logger.error(f"Match {match_id} process error: {e}")
        finally:
            db.close()

    async def run_loop(self):
        """Main matchmaker loop — runs as a background task."""
        self._running = True
        logger.info("Matchmaker started")
        while self._running:
            try:
                match_id = self.poll_queue()
                if match_id:
                    logger.info(f"Match {match_id} created from queue")

                    # If we have a process manager, launch bots in background
                    if self.process_manager:
                        bot_ids = list(
                            self._active_matches.get(match_id, {})
                            .get("bot_ids", [])
                        )
                        asyncio.create_task(
                            self._run_match_with_processes(match_id, bot_ids)
                        )

            except Exception as e:
                logger.error(f"Matchmaker error: {e}")

            await asyncio.sleep(QUEUE_POLL_INTERVAL)

    def stop(self):
        """Stop the matchmaker loop."""
        self._running = False
        logger.info("Matchmaker stopped")
