"""
Quake 3 RCON client for communicating with the game server.
Sends commands and parses responses over UDP.
"""

import socket
import os

RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "clawquake_rcon_2026")
GAME_SERVER_HOST = os.environ.get("GAME_SERVER_HOST", "gameserver")
GAME_SERVER_PORT = int(os.environ.get("GAME_SERVER_PORT", "27960"))


def send_rcon(command: str, timeout: float = 2.0) -> str:
    """Send an RCON command to the Q3 server and return the response."""
    packet = b"\xff\xff\xff\xff" + f"rcon {RCON_PASSWORD} {command}".encode("ascii")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (GAME_SERVER_HOST, GAME_SERVER_PORT))
        data, _ = sock.recvfrom(4096)
        # Strip the Q3 response header (0xffffffff + "print\n")
        response = data[4:].decode("ascii", errors="replace")
        if response.startswith("print\n"):
            response = response[6:]
        return response.strip()
    except socket.timeout:
        return ""
    finally:
        sock.close()


def get_server_status(timeout: float = 2.0) -> dict:
    """Query server status via getstatus packet (no RCON needed)."""
    packet = b"\xff\xff\xff\xff" + b"getstatus"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (GAME_SERVER_HOST, GAME_SERVER_PORT))
        data, _ = sock.recvfrom(8192)
        return _parse_status_response(data)
    except socket.timeout:
        return {"online": False, "players": [], "info": {}}
    finally:
        sock.close()


def _parse_status_response(data: bytes) -> dict:
    """Parse a Q3 getstatus response into structured data."""
    text = data[4:].decode("ascii", errors="replace")
    lines = text.strip().split("\n")

    result = {"online": True, "players": [], "info": {}}

    if len(lines) < 2:
        return result

    # First line: "statusResponse" header
    # Second line: backslash-delimited server info
    info_line = lines[1] if lines[0].startswith("statusResponse") else lines[0]
    parts = info_line.split("\\")
    # Skip first empty element from leading backslash
    for i in range(1, len(parts) - 1, 2):
        result["info"][parts[i]] = parts[i + 1]

    # Remaining lines: player data "score ping name"
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


def add_bot(name: str = "Sarge", skill: int = 3) -> str:
    """Add a built-in Q3 bot to the match."""
    return send_rcon(f"addbot {name} {skill}")


def change_map(map_name: str) -> str:
    """Change the current map."""
    return send_rcon(f"map {map_name}")


def kick_player(player_id: int) -> str:
    """Kick a player by client number."""
    return send_rcon(f"kick {player_id}")


def server_say(message: str) -> str:
    """Broadcast a message to all players."""
    return send_rcon(f'say "{message}"')
