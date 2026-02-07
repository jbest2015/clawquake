#!/bin/bash
set -e

BASEPATH="/usr/share/games/quake3"
HOMEPATH="/root/.q3a"

# Create home directory for runtime data
mkdir -p "$HOMEPATH/baseoa"

# Copy config to home path
cp "$BASEPATH/baseoa/server.cfg" "$HOMEPATH/baseoa/server.cfg"

echo "=== ClawQuake Game Server ==="
echo "Starting ioquake3 dedicated server (OpenArena)..."
echo "UDP Port: 27960"
echo "RCON enabled"

exec /usr/lib/ioquake3/ioq3ded \
    +set fs_basepath "$BASEPATH" \
    +set fs_homepath "$HOMEPATH" \
    +set fs_game baseoa \
    +set dedicated 2 \
    +set net_port 27960 \
    +set com_hunkMegs 128 \
    +exec server.cfg
