"""
Regression tests for legacy single-server RCON helpers.
"""

import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")

import rcon


class RaisingSocket:
    def __init__(self, exc):
        self.exc = exc

    def settimeout(self, timeout):
        return None

    def sendto(self, packet, addr):
        raise self.exc

    def recvfrom(self, size):
        raise AssertionError("recvfrom should not be called after send failure")

    def close(self):
        return None


def test_get_server_status_handles_socket_errors(monkeypatch):
    monkeypatch.setattr(rcon.socket, "socket", lambda *args, **kwargs: RaisingSocket(socket.gaierror(-3, "boom")))
    status = rcon.get_server_status()
    assert status == {"online": False, "players": [], "info": {}}


def test_send_rcon_handles_socket_errors(monkeypatch):
    monkeypatch.setattr(rcon.socket, "socket", lambda *args, **kwargs: RaisingSocket(OSError("no route")))
    assert rcon.send_rcon("status") == ""
