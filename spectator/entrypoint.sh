#!/bin/bash
set -e

DISPLAY_NUM=99
RESOLUTION="1280x720x24"
GAME_SERVER="${GAME_SERVER_HOST:-gameserver}"
GAME_PORT="${GAME_SERVER_PORT:-27960}"
HLS_DIR="/var/www/stream"
FPS=30
Q3_BIN="${Q3_BIN:-/usr/games/openarena}"

echo "=== ClawQuake Spectator ==="
echo "Game server: ${GAME_SERVER}:${GAME_PORT}"
echo "Resolution: ${RESOLUTION}"

# Start Xvfb (virtual framebuffer)
echo "Starting Xvfb on :${DISPLAY_NUM}..."
Xvfb :${DISPLAY_NUM} -screen 0 ${RESOLUTION} -ac +extension GLX &
sleep 2
export DISPLAY=:${DISPLAY_NUM}

# Start nginx for HLS serving
echo "Starting nginx for HLS delivery..."
nginx &
NGINX_PID=$!

# Wait for game server to be ready
echo "Waiting briefly for game server..."
for i in $(seq 1 5); do
    if nc -zvu -w1 ${GAME_SERVER} ${GAME_PORT} >/dev/null 2>&1; then
        echo "Game server is ready!"
        break
    fi
    echo "  Attempt ${i}/5 - waiting..."
    sleep 1
done

# Start ioquake3 client in spectator mode
echo "Starting ioquake3 client as spectator..."
if [ ! -x "${Q3_BIN}" ]; then
    echo "ERROR: ioquake3 binary not found at ${Q3_BIN}"
    exit 1
fi

LIBGL_ALWAYS_SOFTWARE=1 "${Q3_BIN}" \
    +set s_initsound 0 \
    +set r_mode -1 \
    +set r_customwidth 1280 \
    +set r_customheight 720 \
    +set r_fullscreen 0 \
    +set com_hunkMegs 128 \
    +set cl_allowDownload 1 \
    +connect ${GAME_SERVER}:${GAME_PORT} &

Q3_PID=$!
sleep 5

# Start FFmpeg to capture Xvfb and output HLS
echo "Starting FFmpeg HLS capture..."
ffmpeg \
    -f x11grab -video_size 1280x720 -framerate ${FPS} -i :${DISPLAY_NUM} \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -g $((FPS * 2)) -keyint_min ${FPS} \
    -f hls \
    -hls_time 2 \
    -hls_list_size 10 \
    -hls_flags delete_segments+append_list \
    -hls_segment_filename "${HLS_DIR}/segment_%03d.ts" \
    "${HLS_DIR}/stream.m3u8" &

FFMPEG_PID=$!

echo "Spectator streaming active!"
echo "HLS available at http://localhost:8080/stream/stream.m3u8"

# Wait for either process to exit
wait ${Q3_PID} ${FFMPEG_PID} ${NGINX_PID}
