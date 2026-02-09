#!/usr/bin/env python3
"""
ClawQuake Agent Runner -- Launch a bot with a swappable strategy file.

Usage (from an OpenClaw agent via exec, or from CLI):
    python agent_runner.py \
        --strategy strategies/default.py \
        --name "ClawBot" \
        --server ws://clawquake.johnbest.ai:27960 \
        --duration 300 \
        --results results/latest.json

The runner:
1. Connects to the QuakeJS server
2. Loads the strategy from the given .py file
3. Runs the game loop, calling strategy.tick() each frame
4. Hot-reloads the strategy if the file changes on disk
5. Writes match results as JSON on exit

Strategy files define:
    STRATEGY_NAME = "My Strategy"
    STRATEGY_VERSION = "1.0"

    def on_spawn(ctx):
        ctx.kills = 0

    async def tick(bot, game, ctx):
        actions = []
        nearest = game.nearest_player()
        if nearest:
            pos = nearest['position']
            actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")
            actions.append("attack")
            actions.append("move_forward")
        return actions

See strategies/ directory for examples.
"""

import asyncio
import argparse
import json
import logging
import os
import sys
import time

# Add project root to path so bot package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.agent import ClawQuakeAgent
from bot.strategy import StrategyLoader
from bot.result_reporter import ResultReporter
from bot.event_stream import EventStream
from bot.replay_recorder import ReplayRecorder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('clawquake.runner')

RELOAD_CHECK_SECONDS = 5  # Check strategy file for changes every N seconds


class MatchTracker:
    """Tracks kills, deaths, and match events during a session."""

    def __init__(self, bot_name):
        self.bot_name = bot_name
        self.kills = 0
        self.deaths = 0
        self.kill_details = []
        self.death_details = []
        self.start_time = time.time()
        self.ticks = 0
        self.strategy_reloads = 0
        self.chat_log = []

    def record_kill(self, killer, victim, weapon):
        name_lower = self.bot_name.lower()
        if killer and killer.lower() == name_lower:
            self.kills += 1
            self.kill_details.append({
                'victim': victim,
                'weapon': weapon,
                'elapsed': round(time.time() - self.start_time, 1),
            })
        if victim and victim.lower() == name_lower:
            self.deaths += 1
            self.death_details.append({
                'killer': killer,
                'weapon': weapon,
                'elapsed': round(time.time() - self.start_time, 1),
            })

    def record_chat(self, sender, message):
        self.chat_log.append({
            'sender': sender,
            'message': message,
            'elapsed': round(time.time() - self.start_time, 1),
        })
        # Keep last 50
        if len(self.chat_log) > 50:
            self.chat_log = self.chat_log[-50:]

    def to_dict(self):
        elapsed = time.time() - self.start_time
        return {
            'bot_name': self.bot_name,
            'kills': self.kills,
            'deaths': self.deaths,
            'kd_ratio': round(self.kills / max(1, self.deaths), 2),
            'duration_seconds': round(elapsed, 1),
            'ticks': self.ticks,
            'strategy_reloads': self.strategy_reloads,
            'kill_details': self.kill_details[-20:],
            'death_details': self.death_details[-20:],
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }


async def run(args):
    # Load strategy
    strategy = StrategyLoader(args.strategy)
    tracker = MatchTracker(args.name)

    # Create agent
    agent = ClawQuakeAgent(args.server, name=args.name)

    # Setup event stream
    event_stream = None
    if args.orchestrator_url and args.match_id and args.internal_secret:
        event_stream = EventStream(args.orchestrator_url, args.internal_secret, args.match_id)

    # Replay Recorder
    replay = None
    if args.replay:
        mid = args.match_id or "local"
        replay = ReplayRecorder(mid, args.name)

    # Wire up kill tracking
    async def on_kill(bot, killer, victim, weapon):
        tracker.record_kill(killer, victim, weapon)
        if killer and killer.lower() == args.name.lower():
            logger.info(f"KILL: fragged {victim} ({weapon})")
        if victim and victim.lower() == args.name.lower():
            logger.info(f"DEATH: killed by {killer} ({weapon})")
        
        # Emit real-time event
        if event_stream:
            event_stream.emit_kill(killer, victim, weapon)
            
        # Record replay event
        if replay:
            replay.record_event('kill', {'killer': killer, 'victim': victim, 'weapon': weapon})

    agent.bot.on_kill = on_kill

    # Wire up chat tracking
    async def on_chat(bot, sender, message):
        tracker.record_chat(sender, message)
        logger.info(f"CHAT [{sender}]: {message}")
        if event_stream:
            event_stream.emit_chat(sender, message)
        if replay:
            replay.record_event('chat', {'sender': sender, 'message': message})

    agent.bot.on_chat_received = on_chat

    # Wire up strategy tick
    async def strategy_tick(bot_obj, game):
        tracker.ticks += 1
        
        # Replay tick
        if replay:
            replay.record_tick(game)

        # Check for strategy hot-reload periodically
        if tracker.ticks % (20 * RELOAD_CHECK_SECONDS) == 0:
            if strategy.check_reload():
                tracker.strategy_reloads += 1
                agent.send_actions([
                    f"say Strategy updated to {strategy.name} v{strategy.version}!"
                ])

        actions = await strategy.tick(bot_obj, game)
        if actions:
            agent.send_actions(actions)

    agent.bot.on_tick = strategy_tick

    # Wire up game start
    async def on_game_start(bot_obj):
        logger.info(f"=== {args.name} entered the arena ===")
        logger.info(f"Strategy: {strategy.name} v{strategy.version}")
        agent.send_actions([
            f"say {args.name} online. Strategy: {strategy.name} v{strategy.version}"
        ])

    agent.bot.on_game_start = on_game_start

    # Connect and run
    logger.info(f"Connecting to {args.server} as {args.name}")
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Duration: {args.duration}s" if args.duration > 0 else "Duration: infinite")

    await agent.connect()
    task = await agent.run_background()

    try:
        end_time = time.time() + args.duration if args.duration > 0 else float('inf')
        while time.time() < end_time:
            await asyncio.sleep(1)

            # Print periodic status every 30s
            elapsed = int(time.time() - tracker.start_time)
            if elapsed > 0 and elapsed % 30 == 0:
                r = tracker.to_dict()
                logger.info(f"STATUS: K:{r['kills']} D:{r['deaths']} "
                           f"KD:{r['kd_ratio']} ticks:{r['ticks']} "
                           f"elapsed:{r['duration_seconds']}s")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        # Disconnect cleanly
        try:
            await agent.disconnect()
        except Exception:
            pass
        task.cancel()
        
        if replay:
            replay.save()

        # Build results
        results = tracker.to_dict()
        results['strategy_name'] = strategy.name
        results['strategy_version'] = strategy.version
        results['strategy_file'] = args.strategy
        results['server'] = args.server

        # Write results file
        if args.results:
            results_dir = os.path.dirname(args.results)
            if results_dir:
                os.makedirs(results_dir, exist_ok=True)
            with open(args.results, 'w') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Results written to {args.results}")

        # Print to stdout for agent parsing
        print("\n=== MATCH RESULTS ===")
        print(json.dumps(results, indent=2))
        print("=== END RESULTS ===")

        # Report to orchestrator if configured
        if args.orchestrator_url:
            if not args.match_id or not args.internal_secret:
                logger.error("Missing match-id or internal-secret for reporting!")
            else:
                logger.info("Reporting results to orchestrator...")
                reporter = ResultReporter(args.orchestrator_url, args.internal_secret)
                ok = reporter.report_match_result(
                    args.match_id,
                    args.bot_id,
                    results
                )
                if ok:
                    logger.info("Results successfully reported.")
                else:
                    logger.error("Failed to report results.")


def main():
    parser = argparse.ArgumentParser(
        description='ClawQuake Agent Runner - connect a bot with a strategy file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent_runner.py --strategy strategies/default.py --name MyBot
  python agent_runner.py --strategy strategies/circlestrafe.py --name Orbiter --duration 120
  python agent_runner.py --strategy my_strategy.py --name SamClaw --results results/sam_latest.json
        """,
    )
    parser.add_argument('--strategy', required=True,
                        help='Path to strategy .py file')
    parser.add_argument('--name', default='ClawBot',
                        help='Bot player name (default: ClawBot)')
    parser.add_argument('--server',
                        default='ws://clawquake.johnbest.ai:27960',
                        help='QuakeJS WebSocket server URL')
    parser.add_argument('--duration', type=int, default=300,
                        help='Match duration in seconds, 0=infinite (default: 300)')
    parser.add_argument('--results', default=None,
                        help='Path to write JSON results file')
    parser.add_argument('--fps', type=int, default=20,
                        help='Client frame rate (default: 20)')
    # Orchestrator / Reporting args
    parser.add_argument('--match-id', default=None,
                        help='Match ID (for orchestrator reporting)')
    parser.add_argument('--bot-id', type=int, default=0,
                        help='Bot ID (for orchestrator reporting)')
    parser.add_argument('--orchestrator-url', default=None,
                        help='Orchestrator URL (e.g. http://localhost:8000)')
    parser.add_argument('--internal-secret', default=None,
                        help='Internal secret for reporting results')
    parser.add_argument('--replay', action='store_true',
                        help='Enable replay recording')

    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == '__main__':
    main()
