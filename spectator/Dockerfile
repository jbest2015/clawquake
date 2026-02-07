FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install ioquake3 client, Xvfb for virtual display, FFmpeg for capture,
# mesa for software OpenGL rendering (LLVMpipe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    quake3 \
    xvfb \
    ffmpeg \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libopenal1 \
    libsdl2-2.0-0 \
    x11-utils \
    wget \
    unzip \
    ca-certificates \
    nginx-light \
    && rm -rf /var/lib/apt/lists/*

# Download OpenArena game data
RUN mkdir -p /usr/share/games/quake3/baseq3 && \
    cd /tmp && \
    wget -q "https://github.com/OpenArena/gamecode/releases/download/engine%2F0.8.8/openarena-0.8.8.zip" -O openarena.zip && \
    unzip -q openarena.zip && \
    cp openarena-0.8.8/baseoa/*.pk3 /usr/share/games/quake3/baseq3/ 2>/dev/null || true && \
    rm -rf /tmp/openarena* || true

# Create directories for HLS output
RUN mkdir -p /var/www/stream /root/.q3a/baseq3

# Client config for spectator mode
RUN echo 'set name "ClawQuake_Spectator"' > /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set cg_thirdPerson 1' >> /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set cg_draw2D 1' >> /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set r_mode 6' >> /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set r_fullscreen 0' >> /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set r_customwidth 1280' >> /root/.q3a/baseq3/autoexec.cfg && \
    echo 'set r_customheight 720' >> /root/.q3a/baseq3/autoexec.cfg

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# HLS stream served on port 8080
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
