#!/bin/bash
set -e

# Create nginx temp directories at runtime
mkdir -p /tmp/client_temp /tmp/proxy_temp_path /tmp/fastcgi_temp /tmp/uwsgi_temp /tmp/scgi_temp

cd /home/quakejs/www

# --- Patch index.html ---
# The base entrypoint does: sed to replace 'quakejs: with window.location.hostname
# We go further: use protocol-aware URLs
# Content server (fs_cdn): use same origin (no port needed, served by same nginx)
# Game server (+connect): use same hostname on port 443 with /ws path
# This way everything goes through the HTTPS reverse proxy

cat > /tmp/index_patch.js << 'PATCH'
// Detect protocol and build URLs accordingly
var proto = window.location.protocol;
var host = window.location.hostname;
var wsProto = (proto === 'https:') ? 'wss:' : 'ws:';
var httpPort = (proto === 'https:') ? '443' : '8080';
var args = ['+set', 'fs_cdn', host + ':' + httpPort, '+connect', host + ':' + httpPort];
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
				var host = window.location.hostname;
				var wsProto = (proto === 'https:') ? 'wss:' : 'ws:';
				var httpPort = (proto === 'https:') ? '443' : '8080';
				var args = ['+set', 'fs_cdn', host + ':' + httpPort, '+connect', host + ':' + httpPort];'''

content = re.sub(old_pattern, new_code, content)
with open('index.html', 'w') as f:
    f.write(content)
print('index.html patched successfully')
" || {
    echo "Python patch failed, using sed fallback"
    # Fallback: just set the known good values
    sed -i "s|var args = .*//custom args.*|var args = ['+set', 'fs_cdn', window.location.hostname + ':' + (window.location.protocol === 'https:' ? '443' : '8080'), '+connect', window.location.hostname + ':' + (window.location.protocol === 'https:' ? '443' : '8080')];|" index.html
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
  +set sv_pure 0
