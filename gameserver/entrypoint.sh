#!/bin/bash
set -e

# OpenArena data lives under /usr/share/games/openarena (not quake3)
BASEPATH="/usr/share/games/openarena"
HOMEPATH="/root/.q3a"

# Create home directory for runtime data
mkdir -p "$HOMEPATH/baseoa"

# Copy config to home path and inject RCON password from env
# Copy config; also check the installed server lib path
if [ -f "$BASEPATH/baseoa/server.cfg" ]; then
    cp "$BASEPATH/baseoa/server.cfg" "$HOMEPATH/baseoa/server.cfg"
elif [ -f "/usr/lib/openarena-server/baseoa/server.cfg" ]; then
    cp "/usr/lib/openarena-server/baseoa/server.cfg" "$HOMEPATH/baseoa/server.cfg"
fi
if [ -n "$RCON_PASSWORD" ]; then
    sed -i "s/set rconPassword \"\"/set rconPassword \"$RCON_PASSWORD\"/" "$HOMEPATH/baseoa/server.cfg"
    echo "RCON password set from environment"
fi

echo "=== ClawQuake Game Server ==="
echo "Starting ioquake3 dedicated server (OpenArena)..."
echo "UDP Port: 27960"
echo "RCON enabled"

# Use OpenArena's dedicated server binary if available, else ioquake3
if [ -x /usr/lib/openarena-server/openarena-server ]; then
    BINARY=/usr/lib/openarena-server/openarena-server
elif [ -x /usr/games/openarena-server ]; then
    BINARY=/usr/games/openarena-server
else
    BINARY=/usr/lib/ioquake3/ioq3ded
fi

echo "Using binary: $BINARY"

exec $BINARY \
    +set fs_basepath "$BASEPATH" \
    +set fs_homepath "$HOMEPATH" \
    +set fs_game baseoa \
    +set dedicated 2 \
    +set net_port 27960 \
    +set com_hunkMegs 128 \
    +exec server.cfg
