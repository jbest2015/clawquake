FROM awakenedpower/quakejs-rootless:latest

# Copy custom nginx config (adds websocket proxy /ws -> localhost:27960)
COPY nginx.conf /etc/nginx/nginx-custom.conf

# Copy custom entrypoint (patches JS for wss:// and https://)
COPY entrypoint.sh /entrypoint-custom.sh

USER root
RUN chmod +x /entrypoint-custom.sh
USER 1000

ENTRYPOINT ["/entrypoint-custom.sh"]
