"""
ClawQuake Process Manager — Launches and manages agent_runner subprocesses for matches.

Handles spawning bot processes, monitoring their completion, timeouts, and force-kill.
"""

import asyncio
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("clawquake.process_manager")

# ── Constants ────────────────────────────────────────────────────

DEFAULT_MATCH_DURATION = int(os.environ.get("MATCH_DURATION", "120"))
PROCESS_TIMEOUT_BUFFER = 30  # extra seconds before force-kill
AGENT_RUNNER_PATH = os.environ.get(
    "AGENT_RUNNER_PATH",
    os.path.join(os.path.dirname(__file__), "..", "agent_runner.py"),
)


# ── Data Classes ─────────────────────────────────────────────────

@dataclass
class BotProcess:
    """Tracks a single bot subprocess."""
    match_id: int
    bot_id: int
    bot_name: str
    process: Optional[subprocess.Popen] = None
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    return_code: Optional[int] = None


@dataclass
class MatchProcessGroup:
    """All processes for a single match."""
    match_id: int
    bot_processes: dict[int, BotProcess] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    duration: int = DEFAULT_MATCH_DURATION
    server_id: Optional[str] = None
    finalized: bool = False


# ── Process Manager ──────────────────────────────────────────────

class BotProcessManager:
    """
    Manages agent_runner subprocesses for active matches.

    Responsibilities:
    - Launch bot processes for a match
    - Monitor process completion
    - Enforce match duration timeouts
    - Force-kill runaway processes
    - Track active matches
    """

    def __init__(
        self,
        agent_runner_path: str = AGENT_RUNNER_PATH,
        orchestrator_url: str = "http://localhost:8000",
        internal_secret: str = "",
    ):
        self.agent_runner_path = os.path.abspath(agent_runner_path)
        self.orchestrator_url = orchestrator_url
        self.internal_secret = internal_secret
        self._matches: dict[int, MatchProcessGroup] = {}

    def launch_bot(
        self,
        match_id: int,
        bot_id: int,
        bot_name: str,
        strategy_path: str,
        server_url: str,
        duration: int = DEFAULT_MATCH_DURATION,
    ) -> BotProcess:
        """
        Spawn an agent_runner subprocess for a single bot.

        Args:
            match_id: Match this bot is playing in
            bot_id: Bot's database ID
            bot_name: Bot's display name
            strategy_path: Path to the strategy .py file
            server_url: QuakeJS server WebSocket URL
            duration: Match duration in seconds

        Returns:
            BotProcess tracking object
        """
        cmd = [
            "python", self.agent_runner_path,
            "--strategy", strategy_path,
            "--name", bot_name,
            "--server", server_url,
            "--duration", str(duration),
            "--match-id", str(match_id),
            "--bot-id", str(bot_id),
            "--results", f"results/match_{match_id}_bot_{bot_id}.json",
        ]

        if self.orchestrator_url:
            cmd.extend(["--orchestrator-url", self.orchestrator_url])
        if self.internal_secret:
            cmd.extend(["--internal-secret", self.internal_secret])

        logger.info(
            f"Launching bot {bot_name} (id={bot_id}) for match {match_id} "
            f"on server {server_url}"
        )

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Start in a new process group so we can kill the whole group
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
        except FileNotFoundError:
            logger.error(
                f"Failed to launch bot: agent_runner not found at {self.agent_runner_path}"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to launch bot {bot_name}: {e}")
            raise

        bot_proc = BotProcess(
            match_id=match_id,
            bot_id=bot_id,
            bot_name=bot_name,
            process=process,
        )

        # Track in match group
        if match_id not in self._matches:
            self._matches[match_id] = MatchProcessGroup(
                match_id=match_id,
                duration=duration,
            )
        self._matches[match_id].bot_processes[bot_id] = bot_proc

        return bot_proc

    def launch_match(
        self,
        match_id: int,
        bots: list[dict],
        server_url: str,
        duration: int = DEFAULT_MATCH_DURATION,
    ) -> MatchProcessGroup:
        """
        Launch all bots for a match.

        Args:
            match_id: Match ID
            bots: List of {"bot_id": int, "bot_name": str, "strategy_path": str}
            server_url: QuakeJS server URL
            duration: Match duration in seconds

        Returns:
            MatchProcessGroup with all launched processes
        """
        for bot_info in bots:
            self.launch_bot(
                match_id=match_id,
                bot_id=bot_info["bot_id"],
                bot_name=bot_info["bot_name"],
                strategy_path=bot_info["strategy_path"],
                server_url=server_url,
                duration=duration,
            )

        group = self._matches[match_id]
        group.server_id = server_url
        logger.info(
            f"Match {match_id}: launched {len(bots)} bots on {server_url}"
        )
        return group

    def check_match(self, match_id: int) -> dict:
        """
        Check the status of all processes in a match.

        Returns:
            {"all_finished": bool, "bots": {bot_id: {"finished": bool, "return_code": int|None}}}
        """
        if match_id not in self._matches:
            return {"all_finished": True, "bots": {}, "error": "Match not found"}

        group = self._matches[match_id]
        result = {"all_finished": True, "bots": {}}

        for bot_id, bot_proc in group.bot_processes.items():
            if bot_proc.process and not bot_proc.finished:
                rc = bot_proc.process.poll()
                if rc is not None:
                    bot_proc.finished = True
                    bot_proc.return_code = rc
                else:
                    result["all_finished"] = False

            result["bots"][bot_id] = {
                "finished": bot_proc.finished,
                "return_code": bot_proc.return_code,
                "bot_name": bot_proc.bot_name,
            }

        return result

    def is_match_timed_out(self, match_id: int) -> bool:
        """Check if a match has exceeded its duration + buffer."""
        if match_id not in self._matches:
            return False

        group = self._matches[match_id]
        elapsed = time.time() - group.started_at
        return elapsed > (group.duration + PROCESS_TIMEOUT_BUFFER)

    async def wait_for_match(
        self,
        match_id: int,
        poll_interval: float = 2.0,
    ) -> dict:
        """
        Async wait for all processes in a match to complete.
        Force-kills if match times out.

        Returns:
            Final status dict from check_match()
        """
        while True:
            status = self.check_match(match_id)

            if status["all_finished"]:
                return status

            if self.is_match_timed_out(match_id):
                logger.warning(f"Match {match_id} timed out, force-killing")
                self.kill_match(match_id)
                return self.check_match(match_id)

            await asyncio.sleep(poll_interval)

    def kill_match(self, match_id: int):
        """Force-kill all processes in a match."""
        if match_id not in self._matches:
            return

        group = self._matches[match_id]
        for bot_id, bot_proc in group.bot_processes.items():
            if bot_proc.process and not bot_proc.finished:
                try:
                    # Kill the entire process group
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(bot_proc.process.pid), signal.SIGTERM)
                    else:
                        bot_proc.process.terminate()
                    logger.info(
                        f"Match {match_id}: terminated bot {bot_proc.bot_name} "
                        f"(pid={bot_proc.process.pid})"
                    )
                except ProcessLookupError:
                    pass  # Already dead
                except Exception as e:
                    logger.error(
                        f"Error killing bot {bot_proc.bot_name}: {e}"
                    )
                finally:
                    bot_proc.finished = True
                    bot_proc.return_code = -1

    def kill_bot(self, match_id: int, bot_id: int):
        """Force-kill a single bot process."""
        if match_id not in self._matches:
            return
        bot_proc = self._matches[match_id].bot_processes.get(bot_id)
        if bot_proc and bot_proc.process and not bot_proc.finished:
            try:
                bot_proc.process.terminate()
                bot_proc.finished = True
                bot_proc.return_code = -1
            except Exception as e:
                logger.error(f"Error killing bot {bot_id}: {e}")

    def cleanup_match(self, match_id: int):
        """Remove a match from tracking after finalization."""
        self._matches.pop(match_id, None)

    def active_matches(self) -> list[dict]:
        """Get status of all active matches."""
        result = []
        for match_id, group in self._matches.items():
            status = self.check_match(match_id)
            elapsed = time.time() - group.started_at
            result.append({
                "match_id": match_id,
                "server_id": group.server_id,
                "elapsed_seconds": round(elapsed, 1),
                "duration": group.duration,
                "bot_count": len(group.bot_processes),
                "all_finished": status["all_finished"],
                "finalized": group.finalized,
                "bots": status["bots"],
            })
        return result

    def active_match_count(self) -> int:
        """Number of matches still running."""
        return sum(
            1 for m in self._matches.values()
            if not self.check_match(m.match_id)["all_finished"]
        )
