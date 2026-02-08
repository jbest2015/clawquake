"""
RCON Pool — Multi-server RCON management.

Wraps the existing rcon.py to support multiple game servers,
tracking which servers are busy and distributing load.
"""

import logging
import socket
from typing import Optional

logger = logging.getLogger("clawquake.rcon_pool")


class RconPool:
    """
    Manages RCON connections to multiple Quake 3 game servers.
    Tracks which servers are busy (hosting active matches).
    """

    def __init__(self, servers: list[dict]):
        """
        servers: list of {"id": str, "host": str, "port": int, "rcon_password": str}
        """
        self.servers = {s["id"]: s for s in servers}
        self._busy: set[str] = set()

    def get_available_server(self) -> Optional[dict]:
        """Find a server that is not currently busy."""
        for server_id, server in self.servers.items():
            if server_id not in self._busy:
                return server
        return None

    def mark_busy(self, server_id: str):
        """Mark a server as hosting an active match."""
        self._busy.add(server_id)
        logger.info(f"Server {server_id} marked busy")

    def mark_free(self, server_id: str):
        """Mark a server as available again."""
        self._busy.discard(server_id)
        logger.info(f"Server {server_id} marked free")

    def is_busy(self, server_id: str) -> bool:
        return server_id in self._busy

    def get_server(self, server_id: str) -> Optional[dict]:
        return self.servers.get(server_id)

    def send_rcon(self, server_id: str, command: str, timeout: float = 2.0) -> str:
        """Send an RCON command to a specific server."""
        server = self.servers.get(server_id)
        if not server:
            logger.error(f"Unknown server: {server_id}")
            return ""

        packet = (
            b"\xff\xff\xff\xff"
            + f"rcon {server['rcon_password']} {command}".encode("ascii")
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server["host"], server["port"]))
            data, _ = sock.recvfrom(4096)
            response = data[4:].decode("ascii", errors="replace")
            if response.startswith("print\n"):
                response = response[6:]
            return response.strip()
        except socket.timeout:
            return ""
        finally:
            sock.close()

    def get_status(self, server_id: str, timeout: float = 2.0) -> dict:
        """Query a specific server's status via getstatus."""
        server = self.servers.get(server_id)
        if not server:
            return {"online": False, "players": [], "info": {}}

        packet = b"\xff\xff\xff\xff" + b"getstatus"

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server["host"], server["port"]))
            data, _ = sock.recvfrom(8192)
            return self._parse_status(data)
        except socket.timeout:
            return {"online": False, "players": [], "info": {}}
        finally:
            sock.close()

    @staticmethod
    def _parse_status(data: bytes) -> dict:
        """Parse Q3 getstatus response."""
        text = data[4:].decode("ascii", errors="replace")
        lines = text.strip().split("\n")

        result = {"online": True, "players": [], "info": {}}
        if len(lines) < 2:
            return result

        info_line = lines[1] if lines[0].startswith("statusResponse") else lines[0]
        parts = info_line.split("\\")
        for i in range(1, len(parts) - 1, 2):
            result["info"][parts[i]] = parts[i + 1]

        player_start = 2 if lines[0].startswith("statusResponse") else 1
        for line in lines[player_start:]:
            tokens = line.strip().split()
            if len(tokens) >= 3:
                result["players"].append({
                    "score": int(tokens[0]),
                    "ping": int(tokens[1]),
                    "name": " ".join(tokens[2:]).strip('"'),
                })

        return result

    def list_all(self) -> list[dict]:
        """List all servers with their current status."""
        result = []
        for server_id, server in self.servers.items():
            status = self.get_status(server_id)
            result.append({
                "id": server_id,
                "host": server["host"],
                "port": server["port"],
                "busy": server_id in self._busy,
                "online": status.get("online", False),
                "player_count": len(status.get("players", [])),
                "players": status.get("players", []),
                "map": status.get("info", {}).get("mapname", "unknown"),
            })
        return result
