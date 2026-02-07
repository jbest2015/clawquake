#!/bin/bash
set -e

BASEPATH="/usr/share/games/quake3"
HOMEPATH="/root/.q3a"

# Create home directory for runtime data
mkdir -p "$HOMEPATH/baseq3"

# Copy config to home path
cp "$BASEPATH/baseq3/server.cfg" "$HOMEPATH/baseq3/server.cfg"

echo "=== ClawQuake Game Server ==="
echo "Starting ioquake3 dedicated server..."
echo "UDP Port: 27960"
echo "RCON enabled"

exec ioq3ded \
    +set fs_basepath "$BASEPATH" \
    +set fs_homepath "$HOMEPATH" \
    +set dedicated 2 \
    +set net_port 27960 \
    +set com_hunkMegs 128 \
    +exec server.cfg
