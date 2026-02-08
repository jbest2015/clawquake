#!/usr/bin/env python3
"""
ClawQuake Bot Runner - connects a simple AI bot to a QuakeJS server.

Usage:
    python -m bot.run --server ws://clawquake.johnbest.ai:27960 --name "ClawBot"

This is the standalone runner for testing. For AI agent integration,
use the ClawBot class directly from your agent code.
"""

import asyncio
import argparse
import logging
import random

from .bot import ClawBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('clawquake.runner')


# --- Demo runtime config ---

DEMO_CONFIG = {
    "trash_talk_rate": 0.03,
    "slash_chat": False,
}


async def demo_ai_tick(bot, game):
    """Simple demo AI: chase nearest player, shoot, strafe, and taunt."""
    nearest = game.nearest_player()

    if nearest:
        # Calculate direction to enemy
        dist = game.distance_to(nearest['position'])
        bot.aim_at(nearest['position'])

        # Move toward enemy
        bot.move_forward()

        # Shoot if close enough
        if dist < 1000:
            bot.attack()

        # Strafe randomly for some evasion
        if random.random() < 0.3:
            if random.random() < 0.5:
                bot.move_left()
            else:
                bot.move_right()

        # Jump occasionally
        if random.random() < 0.1:
            bot.jump()

        # Trash talk while engaging
        if random.random() < DEMO_CONFIG["trash_talk_rate"]:
            bot.taunt(use_slash=DEMO_CONFIG["slash_chat"])
    else:
        # No enemies visible, explore
        bot.move_forward()
        if random.random() < 0.05:
            if random.random() < 0.5:
                bot.move_left()
            else:
                bot.move_right()


async def on_chat(bot, sender, message):
    """Respond to chat messages."""
    logger.info(f"Chat [{sender}]: {message}")
    # Respond to greetings
    lower = message.lower()
    if any(word in lower for word in ['hi', 'hello', 'hey']):
        bot.taunt("Hello human. Prepare to be fragged.", use_slash=DEMO_CONFIG["slash_chat"])
    elif 'bot' in lower:
        bot.taunt("I prefer 'Artificial Intelligence', thank you.", use_slash=DEMO_CONFIG["slash_chat"])


async def on_kill(bot, killer, victim, weapon):
    """Trash talk after kills."""
    logger.info(f"Kill: {killer} killed {victim} with {weapon}")
    my_name = (bot.client.userinfo.get('name') or '').lower()
    if killer and killer.lower() == my_name:
        bot.taunt(use_slash=DEMO_CONFIG["slash_chat"])


async def on_game_start(bot):
    """Called when we enter the game."""
    logger.info("Bot entered the game!")
    bot.taunt("ClawBot has entered the arena. Fear me.", use_slash=DEMO_CONFIG["slash_chat"])


async def on_game_end(bot, reason):
    """Called when disconnected."""
    logger.info(f"Game ended: {reason}")


async def main():
    parser = argparse.ArgumentParser(description='ClawQuake Bot')
    parser.add_argument('--server', default='ws://clawquake.johnbest.ai:27960',
                        help='QuakeJS WebSocket server URL')
    parser.add_argument('--name', default='ClawBot',
                        help='Bot player name')
    parser.add_argument('--fps', type=int, default=20,
                        help='Client frame rate')
    parser.add_argument('--protocol', type=int, default=71,
                        help='Q3 protocol version (default: 71 for QuakeJS)')
    parser.add_argument('--pure-checksums', default='',
                        help='Raw cp payload for pure servers: \"<cgame> <ui> @ <refs...> <encoded>\"')
    parser.add_argument('--trash-talk-rate', type=float, default=0.03,
                        help='Chance [0..1] to send a taunt each combat tick (default: 0.03)')
    parser.add_argument('--slash-chat', action='store_true',
                        help='Send chat as slash-prefixed commands (e.g. /say ...)')
    args = parser.parse_args()

    pure = args.pure_checksums.strip() or None
    DEMO_CONFIG["trash_talk_rate"] = max(0.0, min(1.0, args.trash_talk_rate))
    DEMO_CONFIG["slash_chat"] = bool(args.slash_chat)

    bot = ClawBot(args.server, name=args.name, protocol=args.protocol, pure_checksums=pure)
    bot.on_tick = demo_ai_tick
    bot.on_chat_received = on_chat
    bot.on_kill = on_kill
    bot.on_game_start = on_game_start
    bot.on_game_end = on_game_end

    logger.info(f"Starting ClawBot connecting to {args.server}")

    try:
        await bot.start(fps=args.fps)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await bot.stop()


if __name__ == '__main__':
    asyncio.run(main())
