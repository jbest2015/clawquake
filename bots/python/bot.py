#!/usr/bin/env python3
"""
ClawQuake Example Bot — Simple AI agent for Quake 3 / OpenArena.

This MVP bot demonstrates:
1. Connecting to the game server
2. Querying server status
3. Basic game state awareness

For the full MVP, bots connect as standard Q3 clients over UDP.
This example shows the connection flow and status monitoring.

Usage:
    python bot.py --host <server-ip> --port 27960 --name MyBot
"""

import argparse
import time
import sys

from q3client import Q3Client


def print_status(client: Q3Client):
    """Print current server status."""
    status = client.get_status()

    if not status.get("online"):
        print("  Server: OFFLINE")
        return False

    info = status.get("info", {})
    players = status.get("players", [])

    print(f"  Server: {info.get('sv_hostname', 'Unknown')}")
    print(f"  Map: {info.get('mapname', 'Unknown')}")
    print(f"  Players: {len(players)}/{info.get('sv_maxclients', '?')}")
    print(f"  Gametype: {info.get('g_gametype', '?')} | Fraglimit: {info.get('fraglimit', '?')}")

    if players:
        print("  ── Scoreboard ──")
        sorted_players = sorted(players, key=lambda p: p["score"], reverse=True)
        for i, p in enumerate(sorted_players, 1):
            print(f"    {i}. {p['name']:20s} Score: {p['score']:4d}  Ping: {p['ping']}ms")
    else:
        print("  No players connected")

    return True


def run_bot(host: str, port: int, name: str):
    """Main bot loop."""
    print(f"=== ClawQuake Bot: {name} ===")
    print(f"Server: {host}:{port}")
    print()

    client = Q3Client(host, port)

    # Query server info
    print("[*] Querying server info...")
    info = client.get_info()
    if info:
        print(f"  Server version: {info.get('version', 'unknown')}")
        print(f"  Map: {info.get('mapname', 'unknown')}")
    else:
        print("  Could not reach server")
        client.close()
        return

    print()
    print("[*] Attempting to connect...")
    connected = client.connect(player_name=name)

    if connected:
        print(f"[+] Connected as {name}!")
    else:
        print("[-] Could not complete full connection (expected for MVP)")
        print("    Full Q3 netchan protocol not yet implemented")
        print("    Falling back to status monitoring mode...")

    print()
    print("[*] Monitoring server status (Ctrl+C to stop)...")
    print()

    try:
        while True:
            print(f"--- {time.strftime('%H:%M:%S')} ---")
            print_status(client)
            print()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="ClawQuake Example Bot")
    parser.add_argument("--host", default="localhost", help="Game server host")
    parser.add_argument("--port", type=int, default=27960, help="Game server port")
    parser.add_argument("--name", default="ClawBot", help="Bot player name")
    args = parser.parse_args()

    run_bot(args.host, args.port, args.name)


if __name__ == "__main__":
    main()
