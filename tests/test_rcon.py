"""
Tests for RCON pool: server management, status parsing, load balancing.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from rcon_pool import RconPool


def make_servers():
    """Create a test server list."""
    return [
        {"id": "server-1", "host": "localhost", "port": 27961, "rcon_password": "test1"},
        {"id": "server-2", "host": "localhost", "port": 27962, "rcon_password": "test2"},
        {"id": "server-3", "host": "localhost", "port": 27963, "rcon_password": "test3"},
    ]


class TestRconPool:

    def test_pool_init(self):
        """Pool should initialize with all servers available."""
        pool = RconPool(make_servers())
        assert len(pool.servers) == 3
        assert not pool.is_busy("server-1")

    def test_get_available_server(self):
        """Should return an available server."""
        pool = RconPool(make_servers())
        server = pool.get_available_server()
        assert server is not None
        assert server["id"] in ("server-1", "server-2", "server-3")

    def test_get_available_server_none_free(self):
        """Should return None when all servers are busy."""
        pool = RconPool(make_servers())
        pool.mark_busy("server-1")
        pool.mark_busy("server-2")
        pool.mark_busy("server-3")
        assert pool.get_available_server() is None

    def test_mark_busy_free(self):
        """Busy servers should be excluded, freed servers available again."""
        pool = RconPool(make_servers())
        pool.mark_busy("server-1")
        assert pool.is_busy("server-1")

        # server-2 and server-3 still available
        available = pool.get_available_server()
        assert available["id"] in ("server-2", "server-3")

        # Free server-1
        pool.mark_free("server-1")
        assert not pool.is_busy("server-1")

    def test_mark_free_idempotent(self):
        """Freeing an already-free server should not error."""
        pool = RconPool(make_servers())
        pool.mark_free("server-1")  # already free
        assert not pool.is_busy("server-1")

    def test_get_server_by_id(self):
        """Should return server config by ID."""
        pool = RconPool(make_servers())
        server = pool.get_server("server-2")
        assert server is not None
        assert server["port"] == 27962

    def test_get_server_unknown(self):
        """Should return None for unknown server ID."""
        pool = RconPool(make_servers())
        assert pool.get_server("server-999") is None

    def test_list_all(self):
        """list_all should return info for all servers."""
        # Use a pool with no real network — get_status will timeout
        pool = RconPool([
            {"id": "s1", "host": "192.0.2.1", "port": 99999, "rcon_password": "x"},
        ])
        # Override get_status to avoid real network calls
        pool.get_status = lambda sid, **kw: {"online": False, "players": [], "info": {}}

        result = pool.list_all()
        assert len(result) == 1
        assert result[0]["id"] == "s1"
        assert result[0]["online"] is False


class TestStatusParsing:

    def test_parse_status_response(self):
        """Parse a real Q3 getstatus response."""
        raw = (
            b"\xff\xff\xff\xffstatusResponse\n"
            b"\\mapname\\q3dm17\\sv_hostname\\ClawQuake Arena"
            b"\\g_gametype\\0\\fraglimit\\50\n"
            b'3 45 "Player1"\n'
            b'1 67 "Player2"\n'
        )
        result = RconPool._parse_status(raw)
        assert result["online"] is True
        assert result["info"]["mapname"] == "q3dm17"
        assert len(result["players"]) == 2
        assert result["players"][0]["name"] == "Player1"
        assert result["players"][0]["score"] == 3
        assert result["players"][1]["ping"] == 67

    def test_parse_status_empty(self):
        """Parse a status response with no players."""
        raw = (
            b"\xff\xff\xff\xffstatusResponse\n"
            b"\\mapname\\q3dm17\\sv_hostname\\Empty Server\n"
        )
        result = RconPool._parse_status(raw)
        assert result["online"] is True
        assert len(result["players"]) == 0
        assert result["info"]["mapname"] == "q3dm17"

    def test_parse_status_minimal(self):
        """Parse a minimal status response."""
        raw = b"\xff\xff\xff\xffstatusResponse\n\\mapname\\q3dm1\n"
        result = RconPool._parse_status(raw)
        assert result["online"] is True
        assert result["info"]["mapname"] == "q3dm1"
