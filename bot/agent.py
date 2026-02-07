"""
ClawQuake Agent Interface - OpenClaw plugin for AI-controlled Quake 3 bots.

This module provides the interface between an OpenClaw AI agent and the
ClawQuake bot. The agent receives game state as structured data and
returns batched commands.

## Quick Start (for AI agents):

```python
from bot.agent import ClawQuakeAgent

agent = ClawQuakeAgent("ws://clawquake.johnbest.ai:27960", name="MyBot")
await agent.connect()

# Game loop - call this repeatedly
state = agent.get_state()      # Get current game state as dict
agent.send_actions([            # Send batch of actions
    "move_forward",
    "attack",
    "say 'Get rekt!'",
])
```

## Available Actions:
  - move_forward, move_back, move_left, move_right
  - jump, attack
  - weapon <1-9>
  - say <message>          (all chat / trash talk)
  - say_team <message>     (team chat)
  - raw <console_command>  (raw Q3 console command)

## Game State Dict:
```json
{
    "connected": true,
    "my_position": [100.0, 200.0, 50.0],
    "my_velocity": [0.0, 0.0, 0.0],
    "my_viewangles": [0.0, 90.0, 0.0],
    "my_weapon": "WP_MACHINEGUN",
    "my_health": 100,
    "my_client_num": 2,
    "server_time": 123456,
    "players": [
        {
            "client_num": 0,
            "name": "Sarge",
            "position": [300.0, 400.0, 50.0],
            "weapon": 2,
            "entity_num": 0
        }
    ],
    "recent_chat": [...],
    "recent_kills": [...]
}
```
"""

import asyncio
import logging

from .bot import ClawBot, GameView

logger = logging.getLogger('clawquake.agent')

# Map of simple action names to bot methods
ACTION_MAP = {
    'move_forward': 'move_forward',
    'forward': 'move_forward',
    'move_back': 'move_back',
    'back': 'move_back',
    'move_left': 'move_left',
    'left': 'move_left',
    'strafe_left': 'move_left',
    'move_right': 'move_right',
    'right': 'move_right',
    'strafe_right': 'move_right',
    'jump': 'jump',
    'attack': 'attack',
    'shoot': 'attack',
    'fire': 'attack',
}


class ClawQuakeAgent:
    """
    OpenClaw-compatible agent interface for ClawQuake.

    Provides a simple get_state() / send_actions() loop that AI agents
    can use to play Quake 3.
    """

    def __init__(self, server_url, name="ClawBot", protocol=68):
        self.bot = ClawBot(server_url, name=name, protocol=protocol)
        self._state_ready = asyncio.Event()
        self._latest_state = {}
        self._connected = False

        # Wire up callbacks
        self.bot.on_tick = self._on_tick
        self.bot.on_chat_received = self._on_chat
        self.bot.on_game_start = self._on_game_start
        self.bot.on_game_end = self._on_game_end

    async def connect(self):
        """Connect to the server. Call this once before the game loop."""
        await self.bot.client.connect()

    async def run_background(self, fps=20):
        """Run the client loop in the background. Returns a task handle."""
        return asyncio.create_task(self.bot.client.run(fps=fps))

    async def disconnect(self):
        """Disconnect from the server."""
        await self.bot.stop()
        self._connected = False

    def get_state(self):
        """
        Get the current game state as a JSON-serializable dict.

        Returns the latest snapshot data including:
        - Player position, velocity, angles, weapon, health
        - Visible enemies with positions
        - Recent chat messages
        - Recent kill events
        """
        state = {
            'connected': self._connected,
            'server_time': self.bot.client.server_time,
        }

        if self._connected and self.bot.game:
            state.update(self.bot.game.to_dict())
            state['recent_chat'] = self.bot.chat_log[-10:]
            state['recent_kills'] = self.bot.kill_log[-10:]

        return state

    def send_actions(self, actions):
        """
        Send a batch of actions to execute.

        Args:
            actions: List of action strings. Examples:
                ["move_forward", "attack", "say Get rekt!"]

        Each action is one of:
            - Simple movement: move_forward, move_back, move_left, move_right, jump
            - Combat: attack, shoot, fire
            - Weapon switch: weapon 1, weapon 2, ... weapon 9
            - Chat: say <message>, say_team <message>
            - Raw command: raw <console_command>
        """
        for action in actions:
            self._execute_action(action)

    def _execute_action(self, action):
        """Execute a single action string."""
        action = action.strip()
        lower = action.lower()

        # Simple mapped actions
        if lower in ACTION_MAP:
            getattr(self.bot, ACTION_MAP[lower])()
            return

        # Weapon switch
        if lower.startswith('weapon '):
            try:
                num = int(action.split()[1])
                self.bot.use_weapon(num)
            except (IndexError, ValueError):
                logger.warning(f"Invalid weapon action: {action}")
            return

        # Chat
        if lower.startswith('say '):
            self.bot.say(action[4:])
            return
        if lower.startswith('say_team '):
            self.bot.say_team(action[9:])
            return

        # Raw command
        if lower.startswith('raw '):
            self.bot.execute(action[4:])
            return

        logger.warning(f"Unknown action: {action}")

    # --- Internal callbacks ---

    async def _on_tick(self, bot, game):
        """Store latest state on each tick."""
        self._latest_state = game.to_dict()
        self._state_ready.set()

    async def _on_chat(self, bot, sender, message):
        """Log chat."""
        logger.info(f"[CHAT] {sender}: {message}")

    async def _on_game_start(self, bot):
        """Mark as connected."""
        self._connected = True
        logger.info("Agent connected to game")

    async def _on_game_end(self, bot, reason):
        """Mark as disconnected."""
        self._connected = False
        logger.info(f"Agent disconnected: {reason}")


async def run_agent_demo(server_url="ws://clawquake.johnbest.ai:27960", name="ClawBot"):
    """
    Demo: Run a simple agent that chases and shoots enemies.

    This shows how an OpenClaw agent would interact with the game.
    """
    import random

    agent = ClawQuakeAgent(server_url, name=name)
    await agent.connect()

    # Start the network loop in background
    task = await agent.run_background()

    try:
        while True:
            await asyncio.sleep(0.5)  # AI thinks at 2 Hz

            state = agent.get_state()
            if not state.get('connected'):
                continue

            # Simple AI logic
            actions = []
            players = state.get('players', [])

            if players:
                # Move toward nearest enemy and shoot
                actions.append('move_forward')
                actions.append('attack')

                # Random strafe
                if random.random() < 0.3:
                    actions.append('move_left' if random.random() < 0.5 else 'move_right')

                # Occasional trash talk
                if random.random() < 0.02:
                    trash = random.choice([
                        "Processing your defeat...",
                        "GG EZ",
                        "I'm just an AI, what's your excuse?",
                        "Beep boop. Target acquired.",
                    ])
                    actions.append(f"say {trash}")
            else:
                # Explore
                actions.append('move_forward')
                if random.random() < 0.1:
                    actions.append('jump')

            agent.send_actions(actions)

    except KeyboardInterrupt:
        pass
    finally:
        await agent.disconnect()
        task.cancel()
