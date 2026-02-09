FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install ioquake3 client, Xvfb for virtual display, FFmpeg for capture,
# mesa for software OpenGL rendering (LLVMpipe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openarena \
    xvfb \
    ffmpeg \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libopenal1 \
    libsdl2-2.0-0 \
    x11-utils \
    netcat-openbsd \
    ca-certificates \
    nginx-light \
    && rm -rf /var/lib/apt/lists/*

# Copy OpenArena data into the ioquake3 base path expected by entrypoint
RUN mkdir -p /usr/share/games/quake3/baseoa && \
    cp -r /usr/share/games/openarena/baseoa/* /usr/share/games/quake3/baseoa/

# Create directories for HLS output and OpenArena config
RUN mkdir -p /var/www/stream /root/.openarena/baseoa

# Client config for spectator mode
RUN echo 'set name "ClawQuake_Spectator"' > /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set cg_thirdPerson 1' >> /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set cg_draw2D 1' >> /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set r_mode -1' >> /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set r_fullscreen 0' >> /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set r_customwidth 1280' >> /root/.openarena/baseoa/autoexec.cfg && \
    echo 'set r_customheight 720' >> /root/.openarena/baseoa/autoexec.cfg

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# HLS stream served on port 8080
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
