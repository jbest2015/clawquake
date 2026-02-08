"""
KillTracker module for ClawQuake bots.

Handles parsing of Quake 3 server kill messages (obituaries) and tracking
match statistics (kills, deaths, K/D ratio).
"""

import re
import time
import logging

logger = logging.getLogger('clawquake.kill_tracker')

class KillTracker:
    """
    Parses Q3 kill messages and tracks combat statistics.
    
    Handles various obituary formats and color codes.
    """

    def __init__(self, bot_name):
        self.bot_name = bot_name
        self.kills = 0
        self.deaths = 0
        self.kill_log = []   # List of {time, victim, weapon}
        self.death_log = []  # List of {time, killer, weapon}
        self.start_time = time.time()
        
        # Compile regex patterns for kill messages
        # Handles:
        # 1. "Victim was <action> by Killer"
        # 2. "Victim was <action> by Killer's <weapon>"
        # 3. "Victim almost dodged Killer's <weapon>"
        # 4. "Killer killed Victim"
        self._patterns = [
            # "Victim was railgunned by Killer"
            re.compile(r"(.+) was .+ by (.+)'s (.+)"),
            re.compile(r"(.+) was .+ by (.+)"),
            # "Victim almost dodged Killer's rocket"
            re.compile(r"(.+) almost dodged (.+)'s (.+)"),
            # "Killer killed Victim"
            re.compile(r"(.+) killed (.+)")
        ]

    @property
    def kd_ratio(self):
        """Calculate Kill/Death ratio."""
        return round(self.kills / max(1, self.deaths), 2)

    def parse_server_command(self, text):
        """
        Parse a server command text for kill messages.
        Returns (killer, victim, weapon) tuple if a kill is detected, else None.
        """
        # We only care about print commands for obituaries
        if not text.startswith("print "):
            return None

        # Extract message content (strip "print " prefix and quotes)
        msg_raw = text[6:].strip('"').strip()
        
        # Clean up the message
        # 1. Remove newlines
        msg = msg_raw.replace('\\n', '').replace('\n', '').strip()
        # 2. Remove color codes (^0-^9, ^x)
        clean_msg = re.sub(r'\^[0-9a-zA-Z]', '', msg).strip()

        # Check if it looks like a kill message
        if not any(k in clean_msg for k in [' was ', ' killed ', ' almost dodged ']):
            return None

        # Try to match patterns
        killer, victim, weapon = None, None, "unknown"

        # Pattern 1: "Victim was <action> by Killer's <weapon>"
        match = self._patterns[0].search(clean_msg)
        if match:
            victim, killer, weapon = match.groups()
        else:
            # Pattern 2: "Victim was <action> by Killer"
            match = self._patterns[1].search(clean_msg)
            if match:
                victim, killer = match.groups()
                # Try to extract weapon from action
                action_match = re.search(r"was (.+) by", clean_msg)
                if action_match:
                    action = action_match.group(1).strip()
                    # Map common actions to weapons
                    if 'railgun' in action: weapon = 'railgun'
                    elif 'melted' in action: weapon = 'plasmagun'
                    elif 'pummel' in action: weapon = 'gauntlet'
                    elif 'shotgun' in action: weapon = 'shotgun'
                    elif 'machinegun' in action: weapon = 'machinegun'
                    elif 'grenade' in action: weapon = 'grenade'
                    elif 'rocket' in action: weapon = 'rocket'
                    elif 'lightning' in action: weapon = 'lightning'
                    elif 'bfg' in action: weapon = 'bfg'
                    else: weapon = action # Use action as weapon name
            else:
                # Pattern 3: "Victim almost dodged Killer's <weapon>"
                match = self._patterns[2].search(clean_msg)
                if match:
                    victim, killer, weapon = match.groups()
                else:
                    # Pattern 4: "Killer killed Victim"
                    match = self._patterns[3].search(clean_msg)
                    if match:
                        killer, victim = match.groups()

        if killer and victim:
            # Normalize names
            killer = killer.strip()
            victim = victim.strip()
            weapon = weapon.strip()
            return killer, victim, weapon
            
        return None

    def record(self, killer, victim, weapon):
        """Record a kill event and update stats."""
        name_lower = self.bot_name.lower()
        killer_lower = killer.lower()
        victim_lower = victim.lower()

        # Case 1: We killed someone
        if killer_lower == name_lower and victim_lower != name_lower:
            self.kills += 1
            self.kill_log.append({
                'time': time.time(),
                'victim': victim,
                'weapon': weapon,
                'elapsed': round(time.time() - self.start_time, 1)
            })
            logger.info(f"KILL: {self.bot_name} fragged {victim} with {weapon}")

        # Case 2: We died
        if victim_lower == name_lower:
            self.deaths += 1
            self.death_log.append({
                'time': time.time(),
                'killer': killer,
                'weapon': weapon,
                'elapsed': round(time.time() - self.start_time, 1)
            })
            if killer_lower == name_lower:
                 logger.info(f"SUICIDE: {self.bot_name} killed themselves with {weapon}")
            else:
                 logger.info(f"DEATH: {self.bot_name} killed by {killer} with {weapon}")

    def to_dict(self):
        """Export stats as dictionary."""
        return {
            'kills': self.kills,
            'deaths': self.deaths,
            'kd_ratio': self.kd_ratio,
            'kill_log': self.kill_log,
            'death_log': self.death_log
        }
