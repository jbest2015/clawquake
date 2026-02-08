"""
Tests for the rate limiter module.
"""

import os
import sys
import time

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")

from fastapi.exceptions import HTTPException
from rate_limiter import (
    SlidingWindowStore,
    RateLimit,
    GlobalRateLimit,
    EXEMPT_PATHS,
    get_store,
)


# ── SlidingWindowStore Tests ──────────────────────────────────

class TestSlidingWindowStore:

    def test_allows_within_limit(self):
        store = SlidingWindowStore()
        for i in range(5):
            allowed, info = store.check("test:key", max_calls=5, window=60)
            assert allowed is True

    def test_blocks_over_limit(self):
        store = SlidingWindowStore()
        for i in range(5):
            store.check("test:over", max_calls=5, window=60)

        allowed, info = store.check("test:over", max_calls=5, window=60)
        assert allowed is False
        assert info["remaining"] == 0
        assert info["limit"] == 5

    def test_remaining_count_decreases(self):
        store = SlidingWindowStore()
        _, info = store.check("test:rem", max_calls=3, window=60)
        assert info["remaining"] == 2

        _, info = store.check("test:rem", max_calls=3, window=60)
        assert info["remaining"] == 1

        _, info = store.check("test:rem", max_calls=3, window=60)
        assert info["remaining"] == 0

    def test_separate_keys_independent(self):
        store = SlidingWindowStore()
        for i in range(3):
            store.check("key:a", max_calls=3, window=60)

        # Key A is exhausted
        allowed_a, _ = store.check("key:a", max_calls=3, window=60)
        assert allowed_a is False

        # Key B is fresh
        allowed_b, _ = store.check("key:b", max_calls=3, window=60)
        assert allowed_b is True

    def test_clear_single_key(self):
        store = SlidingWindowStore()
        for i in range(5):
            store.check("test:clear", max_calls=5, window=60)

        store.clear("test:clear")
        allowed, _ = store.check("test:clear", max_calls=5, window=60)
        assert allowed is True

    def test_clear_all_keys(self):
        store = SlidingWindowStore()
        store.check("k1", max_calls=1, window=60)
        store.check("k2", max_calls=1, window=60)
        store.clear()

        a1, _ = store.check("k1", max_calls=1, window=60)
        a2, _ = store.check("k2", max_calls=1, window=60)
        assert a1 is True
        assert a2 is True

    def test_window_expiry(self):
        """Entries older than the window are pruned."""
        store = SlidingWindowStore()

        # Fill up the limit
        for i in range(3):
            store.check("test:expiry", max_calls=3, window=0.1)

        # Wait for window to expire
        time.sleep(0.15)

        # Should be allowed again
        allowed, info = store.check("test:expiry", max_calls=3, window=0.1)
        assert allowed is True
        assert info["remaining"] == 2


# ── RateLimit Dependency Tests ────────────────────────────────

class TestRateLimitDependency:

    def _make_app(self, max_calls=3, window_seconds=60):
        """Create a minimal FastAPI app with rate limiting."""
        app = FastAPI()

        @app.get("/limited")
        def limited_endpoint(
            _rl: None = Depends(RateLimit(max_calls=max_calls, window_seconds=window_seconds)),
        ):
            return {"ok": True}

        @app.get("/api/health")
        def health():
            return {"status": "ok"}

        return app

    def test_allows_under_limit(self):
        app = self._make_app(max_calls=5)
        # Clear global store before test
        get_store().clear()

        with TestClient(app) as client:
            for _ in range(5):
                res = client.get("/limited")
                assert res.status_code == 200

    def test_blocks_over_limit(self):
        app = self._make_app(max_calls=3)
        get_store().clear()

        with TestClient(app) as client:
            for _ in range(3):
                res = client.get("/limited")
                assert res.status_code == 200

            res = client.get("/limited")
            assert res.status_code == 429
            body = res.json()
            assert "retry_after_seconds" in body["detail"]

    def test_429_has_retry_after_header(self):
        app = self._make_app(max_calls=1)
        get_store().clear()

        with TestClient(app) as client:
            client.get("/limited")  # Use up the limit
            res = client.get("/limited")
            assert res.status_code == 429
            assert "Retry-After" in res.headers

    def test_exempt_paths_not_limited(self):
        app = self._make_app(max_calls=1)
        get_store().clear()

        with TestClient(app) as client:
            # Health endpoint should never be rate-limited
            for _ in range(10):
                res = client.get("/api/health")
                assert res.status_code == 200

    def test_different_paths_get_separate_limits(self):
        app = FastAPI()
        get_store().clear()

        @app.get("/a")
        def endpoint_a(_rl=Depends(RateLimit(max_calls=2, window_seconds=60))):
            return {"path": "a"}

        @app.get("/b")
        def endpoint_b(_rl=Depends(RateLimit(max_calls=2, window_seconds=60))):
            return {"path": "b"}

        with TestClient(app) as client:
            # Use up /a's limit
            client.get("/a")
            client.get("/a")
            res = client.get("/a")
            assert res.status_code == 429

            # /b should still be fine
            res = client.get("/b")
            assert res.status_code == 200


# ── GlobalRateLimit Tests ─────────────────────────────────────

class TestGlobalRateLimit:

    def test_global_limit_blocks(self):
        limiter = GlobalRateLimit(max_calls=3, window_seconds=60)
        get_store().clear()

        app = FastAPI()

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            from fastapi.responses import JSONResponse
            try:
                limiter.check(request)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content=e.detail)
            return await call_next(request)

        @app.get("/anything")
        def anything():
            return {"ok": True}

        with TestClient(app) as client:
            for _ in range(3):
                res = client.get("/anything")
                assert res.status_code == 200

            res = client.get("/anything")
            assert res.status_code == 429

    def test_global_limit_exempt_paths(self):
        limiter = GlobalRateLimit(max_calls=1, window_seconds=60)
        get_store().clear()

        app = FastAPI()

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            from fastapi.responses import JSONResponse
            try:
                limiter.check(request)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content=e.detail)
            return await call_next(request)

        @app.get("/api/health")
        def health():
            return {"status": "ok"}

        with TestClient(app) as client:
            # Even with limit=1, health is always available
            for _ in range(5):
                res = client.get("/api/health")
                assert res.status_code == 200
