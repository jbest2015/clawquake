FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install OpenArena dedicated server + game data (all from Debian repos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openarena-server \
    openarena-088-data \
    openarena-data \
    && rm -rf /var/lib/apt/lists/*

# Copy server config (OpenArena uses /usr/share/games/openarena, not quake3)
COPY server.cfg /usr/share/games/openarena/baseoa/server.cfg
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Game server port (UDP)
EXPOSE 27960/udp

ENTRYPOINT ["/entrypoint.sh"]
