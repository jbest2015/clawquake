#!/bin/bash
set -e

# Create nginx temp directories at runtime
mkdir -p /tmp/client_temp /tmp/proxy_temp_path /tmp/fastcgi_temp /tmp/uwsgi_temp /tmp/scgi_temp

cd /home/quakejs/www

# --- Patch index.html ---
# The base entrypoint does: sed to replace 'quakejs: with window.location.hostname
# We go further: keep the browser client on window.location.host so it works
# both when loaded directly on :8080 and when reverse-proxied through /play/.

cat > /tmp/index_patch.js << 'PATCH'
// Detect protocol and build URLs accordingly
var proto = window.location.protocol;
var originHost = window.location.host;

// Player name: allow passing ?name=... from the parent dashboard, and persist it
// for direct loads (prevents showing up as "UnnamedPlayer").
var qs = new URLSearchParams(window.location.search || '');
var playerName = qs.get('name');
try {
  if (!playerName) playerName = localStorage.getItem('clawquake_player_name');
} catch (e) {}
playerName = (playerName || '').replace(/[\\\\\";]/g, '').trim().slice(0, 20);
if (!playerName) playerName = 'ClawQuakePlayer';
try { localStorage.setItem('clawquake_player_name', playerName); } catch (e) {}

var args = [
  // Use direct cvar command instead of +set to avoid startup-variable ordering quirks.
  '+name', playerName,
  // Default humans to spectator mode so viewing doesn't affect matches.
  // Quake 3 encodes team in userinfo as key "t" (0=free, 1=red, 2=blue, 3=spectator).
  // Setting it before connect is more reliable than trying to run "team spectator"
  // after the client has already spawned.
  '+set', 't', '3',
  // Some builds use the string-based cvar instead; set both.
  '+set', 'team', 'spectator',
  // UI layer team selection cvars used by many Q3 frontends.
  '+set', 'ui_team', '3',
  '+set', 'ui_teamName', 'spectator',
  '+set', 'fs_cdn', originHost,
  '+connect', originHost
];
PATCH

# Replace the args line in index.html with our protocol-aware version
# First, copy the original index.html
cp index.html index.html.bak

# Use python to do the replacement since sed gets messy with JS
python3 -c "
import re
with open('index.html', 'r') as f:
    content = f.read()

# Replace the args assignment line (handles various formats from sed or manual edits)
old_pattern = r'var args = \[.*?\];[^\n]*//custom args.*'
new_code = '''var proto = window.location.protocol;
				var originHost = window.location.host;
				var qs = new URLSearchParams(window.location.search || '');
				var playerName = qs.get('name');
				try {
					if (!playerName) playerName = localStorage.getItem('clawquake_player_name');
				} catch (e) {}
				playerName = (playerName || '').replace(/[\\\\\";]/g, '').trim().slice(0, 20);
				if (!playerName) playerName = 'ClawQuakePlayer';
				try { localStorage.setItem('clawquake_player_name', playerName); } catch (e) {}
				var args = ['+name', playerName, '+set', 't', '3', '+set', 'team', 'spectator', '+set', 'ui_team', '3', '+set', 'ui_teamName', 'spectator', '+set', 'fs_cdn', originHost, '+connect', originHost];'''

content = re.sub(old_pattern, new_code, content)

# Disable getQueryCommands() injection: it mis-parses key=value params like ?name=John
# into [+name, +John], which can break argument ordering relative to +connect.
content = content.replace('args.push.apply(args, getQueryCommands());',
                          '// args.push.apply(args, getQueryCommands()); // disabled in ClawQuake')

# Force human browser clients into spectator mode after startup.
# We do this post-boot using Cvar_Set so the engine has registered userinfo cvars.
if 'function clawquakeForceSpectator' not in content:
    content = content.replace(
        'ioq3.callMain(args);',
        '''ioq3.callMain(args);

\t\t\t\tfunction clawquakeForceSpectator() {
\t\t\t\t\ttry {
\t\t\t\t\t\tif (!ioq3 || !ioq3.ccall) return;
\t\t\t\t\t\tioq3.ccall('Cvar_Set', 'number', ['string','string'], ['t', '3']);
\t\t\t\t\t\tioq3.ccall('Cvar_Set', 'number', ['string','string'], ['team', 'spectator']);
\t\t\t\t\t\tioq3.ccall('Cvar_Set', 'number', ['string','string'], ['ui_team', '3']);
\t\t\t\t\t\tioq3.ccall('Cvar_Set', 'number', ['string','string'], ['ui_teamName', 'spectator']);
\t\t\t\t\t\tif (ioq3.runPostSets) ioq3.runPostSets();
\t\t\t\t\t} catch (e) {}
\t\t\t\t}
\t\t\t\tsetTimeout(clawquakeForceSpectator, 1500);
\t\t\t\tsetTimeout(clawquakeForceSpectator, 3000);
\t\t\t\tsetTimeout(clawquakeForceSpectator, 6000);'''
    )
with open('index.html', 'w') as f:
    f.write(content)
print('index.html patched successfully')
" || {
    echo "Python patch failed, using sed fallback"
    # Fallback: just set the known good values
    sed -i "s|var args = .*//custom args.*|var args = ['+name', 'ClawQuakePlayer', '+set', 'fs_cdn', window.location.host, '+connect', window.location.host];|" index.html
}

# --- Patch ioquake3.js (browser client) ---
# Change ws:// to use wss:// when on HTTPS page
# Line ~16597: var url = 'ws://' + addr + ':' + port;
cd /home/quakejs/www
if [ -f ioquake3.js ]; then
    echo "Patching ioquake3.js for WSS support..."
    sed -i "s|var url = 'ws://' + addr + ':' + port;|var url = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + addr + ':' + port + '/ws';|" ioquake3.js
    echo "ioquake3.js patched"
fi

# --- Patch content server URL (http:// -> protocol-aware) ---
# Line ~15277: var url = 'http://' + fs_cdn + '/assets/manifest.json';
if [ -f ioquake3.js ]; then
    echo "Patching ioquake3.js for HTTPS content server..."
    sed -i "s|var url = 'http://' + fs_cdn|var url = window.location.protocol + '//' + fs_cdn|" ioquake3.js
    echo "Content server URL patched"
fi

# Use our custom nginx config
cp /etc/nginx/nginx-custom.conf /etc/nginx/nginx.conf

# Start Nginx web server (serves static files + proxies websocket)
echo "Starting web server on port 8080..."
nginx -c /etc/nginx/nginx.conf

sleep 1

if ! (echo > /dev/tcp/localhost/8080) 2>/dev/null; then
    echo "ERROR: Web server failed to start!"
    cat /tmp/error.log
    exit 1
fi

cd /quakejs

echo "Starting QuakeJS game server..."
# QuakeJS bots currently do not provide cp/vdr pure-checksum payloads by default.
# Force non-pure mode so usercmds are accepted and bots can fully enter the match.
exec node build/ioq3ded.js \
  +set fs_game baseq3 \
  +set dedicated 1 \
  +set fs_cdn "localhost:8080" \
  +exec server.cfg \
  +set sv_timeout 10 \
  +set sv_zombietime 1 \
  +set sv_pure 0
