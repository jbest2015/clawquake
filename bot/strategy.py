"""
Strategy module loader for ClawQuake agent competition.

Each agent gets a strategy file (e.g. strategies/samclaw.py) that defines:

    STRATEGY_NAME = "My Strategy"
    STRATEGY_VERSION = "1.0"

    def on_spawn(ctx):
        '''Called when the bot enters the game. Initialize state.'''
        ctx.kills = 0

    async def tick(bot, game, ctx):
        '''Called every game tick (~20Hz). Return list of action strings.'''
        actions = []
        nearest = game.nearest_player()
        if nearest:
            pos = nearest['position']
            actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")
            actions.append("attack")
        return actions

The StrategyLoader uses exec() to load strategy files into a fresh namespace,
enabling hot-reload without stale module cache issues.
"""

import os
import time
import logging
import traceback
import asyncio

logger = logging.getLogger('clawquake.strategy')


class StrategyContext:
    """Mutable bag of state that persists across ticks within a match.

    The strategy's tick() function receives this and can store anything:
        ctx.target_id = 3
        ctx.last_dodge_time = game.server_time
        ctx.kill_count = ctx.get('kill_count', 0) + 1

    Context survives hot-reloads -- only the functions change, state persists.
    """

    _RESERVED = frozenset({
        'load_time', 'tick_count', 'strategy_name', 'strategy_version',
        '_data', '_RESERVED',
    })

    def __init__(self):
        self._data = {}
        self.load_time = time.time()
        self.tick_count = 0
        self.strategy_name = "unnamed"
        self.strategy_version = "0"

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getattr__(self, name):
        if name.startswith('_') or name in self._RESERVED:
            return object.__getattribute__(self, name)
        return self._data.get(name)

    def __setattr__(self, name, value):
        if name.startswith('_') or name in self._RESERVED:
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def reset(self):
        """Clear all user-defined state (called on strategy reload if desired)."""
        self._data.clear()
        self.tick_count = 0


class StrategyLoader:
    """Loads and hot-reloads strategy files via exec().

    Usage:
        loader = StrategyLoader("strategies/my_strategy.py")
        actions = await loader.tick(bot, game)

        # Check for file changes periodically:
        if loader.check_reload():
            print("Strategy updated!")
    """

    def __init__(self, strategy_path):
        self.path = os.path.abspath(strategy_path)
        self._namespace = {}
        self._mtime = 0
        self._ctx = StrategyContext()
        self._load()

    def _load(self):
        """Load (or reload) the strategy file."""
        with open(self.path, 'r') as f:
            code = f.read()

        ns = {'__builtins__': __builtins__}
        exec(compile(code, self.path, 'exec'), ns)
        self._namespace = ns
        self._mtime = os.path.getmtime(self.path)

        # Extract metadata
        self._ctx.strategy_name = ns.get('STRATEGY_NAME',
                                          os.path.basename(self.path))
        self._ctx.strategy_version = ns.get('STRATEGY_VERSION', '0')
        self._ctx.load_time = time.time()

        # Call on_spawn if defined
        on_spawn = ns.get('on_spawn')
        if on_spawn:
            try:
                on_spawn(self._ctx)
            except Exception as e:
                logger.error(f"on_spawn error: {e}\n{traceback.format_exc()}")

        logger.info(f"Strategy loaded: {self._ctx.strategy_name} "
                     f"v{self._ctx.strategy_version} from {self.path}")

    def check_reload(self):
        """Check if strategy file changed on disk; reload if so."""
        try:
            current_mtime = os.path.getmtime(self.path)
            if current_mtime > self._mtime:
                logger.info(f"Strategy file changed, reloading: {self.path}")
                self._load()
                return True
        except OSError:
            pass
        return False

    async def tick(self, bot, game):
        """Call the strategy's tick function. Returns list of action strings."""
        tick_fn = self._namespace.get('tick')
        if not tick_fn:
            return []

        self._ctx.tick_count += 1

        try:
            result = tick_fn(bot, game, self._ctx)
            # Support both sync and async tick functions
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.error(f"Strategy tick error: {e}\n{traceback.format_exc()}")
            return []

    @property
    def context(self):
        return self._ctx

    @property
    def name(self):
        return self._ctx.strategy_name

    @property
    def version(self):
        return self._ctx.strategy_version
