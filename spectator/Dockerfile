FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install ioquake3 client, Xvfb for virtual display, FFmpeg for capture,
# mesa for software OpenGL rendering (LLVMpipe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ioquake3 \
    xvfb \
    ffmpeg \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libopenal1 \
    libsdl2-2.0-0 \
    x11-utils \
    netcat-openbsd \
    wget \
    unzip \
    ca-certificates \
    nginx-light \
    && rm -rf /var/lib/apt/lists/*

# Download OpenArena 0.8.8 game data
RUN mkdir -p /usr/share/games/quake3/baseoa && \
    cd /tmp && \
    wget -q "https://download.tuxfamily.org/openarena/rel/088/openarena-0.8.8.zip" -O openarena.zip && \
    unzip -q openarena.zip && \
    cp -r openarena-0.8.8/baseoa/* /usr/share/games/quake3/baseoa/ && \
    rm -rf /tmp/openarena*

# Create directories for HLS output
RUN mkdir -p /var/www/stream /root/.q3a/baseoa

# Client config for spectator mode
RUN echo 'set name "ClawQuake_Spectator"' > /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set cg_thirdPerson 1' >> /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set cg_draw2D 1' >> /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set r_mode -1' >> /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set r_fullscreen 0' >> /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set r_customwidth 1280' >> /root/.q3a/baseoa/autoexec.cfg && \
    echo 'set r_customheight 720' >> /root/.q3a/baseoa/autoexec.cfg

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# HLS stream served on port 8080
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
