"""
ClawQuake Bot - AI-controllable Quake 3 bot with batched command support.

This is the high-level wrapper around Q3Client that provides:
  - Simple action API (move, aim, shoot, chat)
  - Batched command support (send multiple actions per tick)
  - Game state queries (who's around, my health, where am I)
  - Event callbacks for AI agents

Designed to be controlled by an OpenClaw AI agent plugin.
"""

import asyncio
import math
import logging
import time

from .client import Q3Client
from .defs import entityType_t, weapon_t, configstr_t
from .snapshot import Snapshot, PlayerState

logger = logging.getLogger('clawquake.bot')


class GameView:
    """Read-only view of the current game state for AI consumption."""

    def __init__(self, bot):
        self._bot = bot

    @property
    def my_position(self):
        """My (x, y, z) position."""
        ps = self._bot.client.player_state
        if ps:
            return ps.origin
        return (0, 0, 0)

    @property
    def my_velocity(self):
        """My (x, y, z) velocity."""
        ps = self._bot.client.player_state
        if ps:
            return ps.velocity
        return (0, 0, 0)

    @property
    def my_viewangles(self):
        """My (pitch, yaw, roll) view angles."""
        ps = self._bot.client.player_state
        if ps:
            return ps.viewangles
        return (0, 0, 0)

    @property
    def my_weapon(self):
        """My current weapon ID."""
        ps = self._bot.client.player_state
        if ps:
            return ps.weapon
        return 0

    @property
    def my_weapon_name(self):
        """My current weapon name."""
        try:
            return weapon_t(self.my_weapon).name
        except ValueError:
            return f"weapon_{self.my_weapon}"

    @property
    def my_health(self):
        """My health value."""
        ps = self._bot.client.player_state
        if ps:
            return ps.health
        return 0

    @property
    def my_client_num(self):
        """My client number."""
        return self._bot.client.client_num

    @property
    def server_time(self):
        """Current server time."""
        return self._bot.client.server_time

    @property
    def players(self):
        """List of visible players as dicts."""
        result = []
        entities = self._bot.client.get_players()
        for num, ent in entities.items():
            if ent.client_num == self.my_client_num:
                continue  # Skip self
            name = self._bot.client.get_player_name(ent.client_num)
            result.append({
                'client_num': ent.client_num,
                'name': name,
                'position': ent.origin,
                'weapon': ent.weapon,
                'entity_num': num,
            })
        return result

    @property
    def entities(self):
        """All entities in current snapshot."""
        snap = self._bot.client.current_snapshot
        if snap:
            return snap.entities
        return {}

    def distance_to(self, target_pos):
        """Calculate distance from me to a target position."""
        my = self.my_position
        dx = target_pos[0] - my[0]
        dy = target_pos[1] - my[1]
        dz = target_pos[2] - my[2]
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    def angle_to(self, target_pos):
        """Calculate yaw angle from me to a target position."""
        my = self.my_position
        dx = target_pos[0] - my[0]
        dy = target_pos[1] - my[1]
        return math.degrees(math.atan2(dy, dx))

    def nearest_player(self):
        """Find the nearest visible player. Returns player dict or None."""
        players = self.players
        if not players:
            return None
        return min(players, key=lambda p: self.distance_to(p['position']))

    def to_dict(self):
        """Export game state as a JSON-serializable dict for AI consumption."""
        return {
            'my_position': list(self.my_position),
            'my_velocity': list(self.my_velocity),
            'my_viewangles': list(self.my_viewangles),
            'my_weapon': self.my_weapon_name,
            'my_health': self.my_health,
            'my_client_num': self.my_client_num,
            'server_time': self.server_time,
            'players': self.players,
        }


class ClawBot:
    """
    High-level AI-controllable Quake 3 bot.

    Provides a simple API for AI agents to:
      - Observe the game state
      - Send actions (move, aim, shoot, chat)
      - Send batched commands (multiple actions per tick)

    Example:
        bot = ClawBot("ws://server:27960", name="ClawBot")
        bot.on_tick = my_ai_callback
        await bot.start()
    """

    def __init__(self, server_url, name="ClawBot", protocol=68):
        self.client = Q3Client(server_url, name=name, protocol=protocol)
        self.game = GameView(self)
        self._action_queue = []
        self._chat_log = []
        self._kill_log = []

        # Wire up client callbacks
        self.client.on_snapshot = self._on_snapshot
        self.client.on_chat = self._on_chat
        self.client.on_connected = self._on_connected
        self.client.on_disconnected = self._on_disconnected
        self.client.on_command = self._on_command

        # AI callbacks
        self.on_tick = None         # async fn(bot, game_state: GameView)
        self.on_chat_received = None  # async fn(bot, sender, message)
        self.on_kill = None         # async fn(bot, killer, victim, weapon)
        self.on_game_start = None   # async fn(bot)
        self.on_game_end = None     # async fn(bot, reason)

    async def start(self, fps=20):
        """Connect and start the game loop."""
        await self.client.connect()
        await self.client.run(fps=fps)

    async def stop(self):
        """Disconnect from the server."""
        await self.client.disconnect()

    # --- Action API (queue actions for next tick) ---

    def move_forward(self):
        """Move forward."""
        self._action_queue.append("+forward")
        self._action_queue.append("-forward")

    def move_back(self):
        """Move backward."""
        self._action_queue.append("+back")
        self._action_queue.append("-back")

    def move_left(self):
        """Strafe left."""
        self._action_queue.append("+moveleft")
        self._action_queue.append("-moveleft")

    def move_right(self):
        """Strafe right."""
        self._action_queue.append("+moveright")
        self._action_queue.append("-moveright")

    def jump(self):
        """Jump."""
        self._action_queue.append("+moveup")
        self._action_queue.append("-moveup")

    def attack(self):
        """Fire current weapon."""
        self._action_queue.append("+attack")
        self._action_queue.append("-attack")

    def use_weapon(self, weapon_num):
        """Switch to a weapon by number (1-9)."""
        self._action_queue.append(f"weapon {weapon_num}")

    def say(self, message):
        """Send chat message to all players (trash talk!)."""
        self.client.say(message)

    def say_team(self, message):
        """Send team chat message."""
        self.client.say_team(message)

    def execute(self, command):
        """Execute a raw Q3 console command."""
        self._action_queue.append(command)

    def execute_batch(self, commands):
        """Execute multiple commands at once (batched)."""
        self._action_queue.extend(commands)

    # --- Client callbacks ---

    async def _on_snapshot(self, client, snapshot):
        """Called each time we receive a new game state snapshot."""
        # Flush queued actions
        if self._action_queue:
            self.client.queue_commands(self._action_queue)
            self._action_queue.clear()

        # Call AI tick
        if self.on_tick:
            try:
                await self.on_tick(self, self.game)
            except Exception as e:
                logger.error(f"AI tick error: {e}", exc_info=True)

    async def _on_chat(self, client, sender, message):
        """Called when a chat message is received."""
        self._chat_log.append({
            'time': time.time(),
            'sender': sender,
            'message': message,
        })
        # Keep last 50 messages
        if len(self._chat_log) > 50:
            self._chat_log = self._chat_log[-50:]

        if self.on_chat_received:
            await self.on_chat_received(self, sender, message)

    async def _on_connected(self, client):
        """Called when we enter the game."""
        logger.info(f"Bot entered game as client {client.client_num}")
        if self.on_game_start:
            await self.on_game_start(self)

    async def _on_disconnected(self, client, reason):
        """Called when we're disconnected."""
        logger.info(f"Bot disconnected: {reason}")
        if self.on_game_end:
            await self.on_game_end(self, reason)

    async def _on_command(self, client, seq, text):
        """Called for each server command."""
        # Detect kill events (obituary)
        if text.startswith("print ") and "\\n" in text:
            # Kill messages look like: print "PlayerA was railgunned by PlayerB\n"
            msg = text.split('"')[1] if '"' in text else text[6:]
            msg = msg.strip('\\n').strip()
            if ' was ' in msg or ' killed ' in msg:
                self._kill_log.append({
                    'time': time.time(),
                    'message': msg,
                })

    # --- State queries ---

    @property
    def chat_log(self):
        """Recent chat messages."""
        return list(self._chat_log)

    @property
    def kill_log(self):
        """Recent kill messages."""
        return list(self._kill_log)

    @property
    def is_alive(self):
        """Check if bot is alive and in-game."""
        return self.client.is_active
