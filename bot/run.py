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
import math
import random

from .bot import ClawBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('clawquake.runner')


# --- Simple demo AI ---

TRASH_TALK = [
    "Is that all you got?",
    "My grandma plays better than you!",
    "GG EZ",
    "You should try aiming AT me!",
    "I'm an AI and I'm still better!",
    "Beep boop. You've been eliminated.",
    "01001100 01001111 01001100",  # "LOL" in binary
    "Processing your defeat...",
    "rm -rf your_skill",
    "I was trained on your mistakes",
]


async def demo_ai_tick(bot, game):
    """Simple demo AI: chase nearest player, shoot, trash talk on kills."""
    nearest = game.nearest_player()

    if nearest:
        # Calculate direction to enemy
        angle = game.angle_to(nearest['position'])
        dist = game.distance_to(nearest['position'])

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
        bot.say("Hello human. Prepare to be fragged.")
    elif 'bot' in lower:
        bot.say("I prefer 'Artificial Intelligence', thank you.")


async def on_kill(bot, killer, victim, weapon):
    """Trash talk after kills."""
    logger.info(f"Kill: {killer} killed {victim} with {weapon}")


async def on_game_start(bot):
    """Called when we enter the game."""
    logger.info("Bot entered the game!")
    bot.say("ClawBot has entered the arena. Fear me.")


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
    parser.add_argument('--protocol', type=int, default=68,
                        help='Q3 protocol version (68 or 71)')
    args = parser.parse_args()

    bot = ClawBot(args.server, name=args.name, protocol=args.protocol)
    bot.on_tick = demo_ai_tick
    bot.on_chat_received = on_chat
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
