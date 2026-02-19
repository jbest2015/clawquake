
"""
Launch a ClawQuake match with Codex, Claude, and Anti-Gravity.
Usage: python scripts/play_match.py
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.clawquake_sdk import ClawQuakeClient

API_URL = "http://localhost:8000"

def main():
    print(f"Connecting to {API_URL}...")
    
    # Define Agents
    agents = [
        {"user": "codex_agent", "email": "codex@test.local", "pass": "pass123", "bot": "CodexBot", "strategy": "circlestrafe"},
        {"user": "claude_agent", "email": "claude@test.local", "pass": "pass123", "bot": "ClaudeBot", "strategy": "competition_reference"},
        {"user": "antigravity_agent", "email": "antigravity@test.local", "pass": "pass123", "bot": "AntiGravBot", "strategy": "antigravity"},
    ]

    with ClawQuakeClient(API_URL) as client:
        
        for agent in agents:
            username = agent["user"]
            print(f"\n--- Processing {username} ---")
            
            # 1. Auth
            try:
                print(f"Logging in as {username}...")
                resp = client.login(username, agent["pass"])
            except Exception:
                print(f"Registering {username}...")
                resp = client.register(username, agent["email"], agent["pass"])
            
            # Set JWT for Key Creation
            client.jwt_token = resp['access_token']
            client.api_key = None
            
            # 2. Key
            key_name = f"match_key_{int(time.time())}"
            print(f"Creating key {key_name}...")
            k_resp = client.create_key(key_name)
            api_key = k_resp['key']
            
            # Switch to API Key for subsequent actions
            client.jwt_token = None
            client.api_key = api_key
            
            # 3. Bot
            bot_name = agent["bot"]
            print(f"Ensuring bot {bot_name} exists...")
            my_bots = client.list_bots()
            target_bot = next((b for b in my_bots if b['name'] == bot_name), None)
            
            if not target_bot:
                print(f"Registering bot {bot_name}...")
                target_bot = client.register_bot(bot_name)
            else:
                print(f"Bot {bot_name} found (ID: {target_bot['id']})")
                
            # 4. Queue
            print(f"Joining queue...")
            try:
                client.join_queue(target_bot['id'])
                print(f"SUCCESS: {bot_name} queued!")
            except Exception as e:
                print(f"Queue failed (maybe already queued?): {e}")

    print("\n\nAll agents processed.")
    print("Match should start automatically when 2+ bots are queued.")
    print("Spectate at: http://localhost/dashboard.html")

if __name__ == "__main__":
    main()
