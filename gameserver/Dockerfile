FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install ioquake3 dedicated server + wget for OpenArena data
RUN apt-get update && apt-get install -y --no-install-recommends \
    quake3-server \
    wget \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download OpenArena game data (pak files)
RUN mkdir -p /usr/share/games/quake3/baseq3 && \
    cd /tmp && \
    wget -q "https://github.com/OpenArena/gamecode/releases/download/engine%2F0.8.8/openarena-0.8.8.zip" -O openarena.zip && \
    unzip -q openarena.zip && \
    cp openarena-0.8.8/baseoa/*.pk3 /usr/share/games/quake3/baseq3/ 2>/dev/null || true && \
    rm -rf /tmp/openarena* || true

# Alternative: download individual pak files from a mirror if the above fails
RUN if [ ! -f /usr/share/games/quake3/baseq3/pak0.pk3 ]; then \
    cd /tmp && \
    wget -q "https://raw.githubusercontent.com/nrempel/q3-server/master/baseq3/pak0.pk3" -O /usr/share/games/quake3/baseq3/pak0.pk3 2>/dev/null || true; \
    fi

# Copy server config
COPY server.cfg /usr/share/games/quake3/baseq3/server.cfg
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Game server port (UDP)
EXPOSE 27960/udp

ENTRYPOINT ["/entrypoint.sh"]
