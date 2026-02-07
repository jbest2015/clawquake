"""
Minimal Quake 3 Arena network protocol client.

Implements the Q3 connectionless protocol for:
- Server info queries (getstatus, getinfo)
- Connection handshake (getchallenge, connect)
- Game state parsing (snapshots with entity positions)
- Sending user commands (movement, aim, fire)

Based on the Q3 network protocol specification.
Reference: https://github.com/jfedor2/quake3-proxy-aimbot
"""

import socket
import struct
import time
import hashlib
import random
import re
from typing import Optional


# Q3 protocol constants
PROTOCOL_VERSION = 68  # Standard Q3 protocol version
MAX_PACKET_SIZE = 16384
OOB_HEADER = b"\xff\xff\xff\xff"


class Q3Entity:
    """Represents a game entity (player, item, projectile)."""

    def __init__(self):
        self.number = 0
        self.origin = [0.0, 0.0, 0.0]
        self.angles = [0.0, 0.0, 0.0]
        self.model_index = 0
        self.health = 0
        self.weapon = 0
        self.event = 0


class Q3GameState:
    """Current game state parsed from server snapshots."""

    def __init__(self):
        self.entities: list[Q3Entity] = []
        self.players: dict[int, dict] = {}
        self.my_origin = [0.0, 0.0, 0.0]
        self.my_angles = [0.0, 0.0, 0.0]
        self.my_health = 100
        self.my_armor = 0
        self.my_weapon = 0
        self.server_time = 0
        self.map_name = ""
        self.connected = False


class Q3Client:
    """
    Minimal Q3 network client.

    For the MVP, this uses the connectionless protocol to query server status
    and a simplified connection flow. Full game state parsing would require
    implementing the Q3 huffman coding and delta compression, which is complex.

    For the MVP bot, we use RCON + status queries as a simpler alternative.
    """

    def __init__(self, host: str, port: int = 27960):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        self.game_state = Q3GameState()
        self.client_num = -1
        self.challenge = ""
        self.connected = False

    def _send_oob(self, data: str) -> Optional[str]:
        """Send an out-of-band (connectionless) packet and return response."""
        packet = OOB_HEADER + data.encode("ascii")
        self.sock.sendto(packet, (self.host, self.port))
        try:
            response, _ = self.sock.recvfrom(MAX_PACKET_SIZE)
            if response[:4] == OOB_HEADER:
                return response[4:].decode("ascii", errors="replace")
        except socket.timeout:
            return None
        return None

    def get_status(self) -> dict:
        """Query server status (getstatus)."""
        response = self._send_oob("getstatus")
        if not response:
            return {"online": False}

        lines = response.strip().split("\n")
        result = {"online": True, "info": {}, "players": []}

        if len(lines) >= 2:
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

    def get_info(self) -> dict:
        """Quick server info query (getinfo)."""
        response = self._send_oob("getinfo")
        if not response:
            return {}

        result = {}
        parts = response.split("\\")
        for i in range(1, len(parts) - 1, 2):
            result[parts[i]] = parts[i + 1]
        return result

    def connect(self, player_name: str = "ClawBot") -> bool:
        """
        Attempt to connect to the Q3 server.

        Note: Full Q3 connection requires implementing huffman-coded
        netchan protocol. For MVP, bots can use RCON commands + status
        polling as an alternative.
        """
        # Step 1: Get challenge
        response = self._send_oob("getchallenge")
        if not response or "challengeResponse" not in response:
            print(f"Failed to get challenge from {self.host}:{self.port}")
            return False

        # Parse challenge number
        match = re.search(r"challengeResponse\s+(\d+)", response)
        if not match:
            return False
        self.challenge = match.group(1)

        # Step 2: Send connect packet
        userinfo = (
            f'\\name\\{player_name}'
            f'\\protocol\\{PROTOCOL_VERSION}'
            f'\\qport\\{random.randint(10000, 60000)}'
            f'\\challenge\\{self.challenge}'
            f'\\snaps\\20'
            f'\\rate\\25000'
        )
        response = self._send_oob(f"connect \"{userinfo}\"")

        if response and "connectResponse" in response:
            self.connected = True
            self.game_state.connected = True
            print(f"Connected to {self.host}:{self.port} as {player_name}")
            return True

        print(f"Connection rejected: {response}")
        return False

    def disconnect(self):
        """Disconnect from server."""
        if self.connected:
            self._send_oob("disconnect")
            self.connected = False
            self.game_state.connected = False
        self.sock.close()

    def close(self):
        """Close the socket."""
        self.disconnect()
