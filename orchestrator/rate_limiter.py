"""
ClawQuake Rate Limiter — Sliding-window rate limiting middleware for FastAPI.

Limits requests per IP address per time window. Configurable per-route
via the ``RateLimit`` dependency.

Usage:
    from rate_limiter import RateLimiter, RateLimit

    limiter = RateLimiter()
    app.add_middleware(limiter.middleware_class)

    @app.post("/api/auth/register")
    def register(
        _rl: None = Depends(RateLimit(max_calls=5, window_seconds=60)),
        ...
    ):
        ...
"""

import logging
import os
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger("clawquake.rate_limiter")

# ── Global defaults (overridable via env) ─────────────────────

DEFAULT_MAX_CALLS = int(os.environ.get("RATE_LIMIT_MAX_CALLS", "60"))
DEFAULT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # seconds

# Exempt paths that should never be rate-limited
EXEMPT_PATHS = frozenset({
    "/api/health",
    "/api/status",
    "/docs",
    "/openapi.json",
})


# ── Sliding-Window Store ──────────────────────────────────────

class SlidingWindowStore:
    """
    In-memory sliding-window rate limiter.

    Each key tracks a list of timestamps. Expired entries are
    pruned on every check call.

    For production at scale, swap for Redis + EVALSHA.
    """

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_calls: int, window: float) -> tuple[bool, dict]:
        """
        Check whether a request is allowed.

        Returns (allowed, info) where info contains:
          - remaining: how many calls left
          - reset: seconds until window resets
          - limit: the max calls
        """
        now = time.monotonic()
        cutoff = now - window

        # Prune expired entries
        timestamps = self._windows[key]
        timestamps[:] = [t for t in timestamps if t > cutoff]

        remaining = max(0, max_calls - len(timestamps))
        reset = round(timestamps[0] - cutoff, 1) if timestamps else 0.0

        if len(timestamps) >= max_calls:
            return False, {
                "remaining": 0,
                "reset": reset,
                "limit": max_calls,
            }

        timestamps.append(now)
        return True, {
            "remaining": remaining - 1,
            "reset": round(window, 1),
            "limit": max_calls,
        }

    def clear(self, key: Optional[str] = None):
        """Clear one key or all keys (useful for testing)."""
        if key:
            self._windows.pop(key, None)
        else:
            self._windows.clear()


# ── Global store instance ─────────────────────────────────────

_store = SlidingWindowStore()


def get_store() -> SlidingWindowStore:
    """Get the global rate-limit store (inject in tests)."""
    return _store


# ── FastAPI Dependency ────────────────────────────────────────

class RateLimit:
    """
    FastAPI dependency for per-endpoint rate limiting.

    Example:
        @app.post("/api/auth/register")
        def register(
            _rl: None = Depends(RateLimit(max_calls=5, window_seconds=60)),
            ...
        ):
    """

    def __init__(
        self,
        max_calls: int = DEFAULT_MAX_CALLS,
        window_seconds: int = DEFAULT_WINDOW,
        key_func=None,
    ):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._key_func = key_func

    def _get_key(self, request: Request) -> str:
        """Build a rate-limit key from request."""
        if self._key_func:
            return self._key_func(request)

        # Default: IP + path
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        return f"rl:{client_ip}:{path}"

    def __call__(self, request: Request):
        path = request.url.path
        if path in EXEMPT_PATHS:
            return None

        key = self._get_key(request)
        store = get_store()
        allowed, info = store.check(key, self.max_calls, self.window_seconds)

        if not allowed:
            logger.warning(
                f"Rate limit exceeded: {key} "
                f"(limit={info['limit']}, reset_in={info['reset']}s)"
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "retry_after_seconds": info["reset"],
                    "limit": info["limit"],
                },
                headers={"Retry-After": str(int(info["reset"]))},
            )

        return None


# ── Convenience: Global rate limit for all endpoints ──────────

class GlobalRateLimit:
    """
    Per-IP rate limiter applied at the app level.

    Usage:
        limiter = GlobalRateLimit(max_calls=120, window_seconds=60)

        @app.middleware("http")
        async def rate_limit_middleware(request, call_next):
            limiter.check(request)
            return await call_next(request)
    """

    def __init__(
        self,
        max_calls: int = DEFAULT_MAX_CALLS,
        window_seconds: int = DEFAULT_WINDOW,
    ):
        self.max_calls = max_calls
        self.window_seconds = window_seconds

    def check(self, request: Request):
        path = request.url.path
        if path in EXEMPT_PATHS:
            return

        client_ip = request.client.host if request.client else "unknown"
        key = f"global:{client_ip}"

        store = get_store()
        allowed, info = store.check(key, self.max_calls, self.window_seconds)

        if not allowed:
            logger.warning(
                f"Global rate limit exceeded: {client_ip} "
                f"(limit={info['limit']}, reset_in={info['reset']}s)"
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Too many requests",
                    "retry_after_seconds": info["reset"],
                },
                headers={"Retry-After": str(int(info["reset"]))},
            )
