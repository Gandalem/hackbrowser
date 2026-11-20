# Standalone HackBrowser MCP (Linux/amd64 and Linux/arm64).
# Builds a single local-only browser container without PocMap, ZAP, Keycloak.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    chromium xvfb xauth curl ca-certificates fonts-noto-cjk fonts-nanum \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r mcp && useradd -r -g mcp -m -d /home/mcp mcp \
    && mkdir -p /home/mcp/.local/share/hackbrowser-mcp \
    && chown -R mcp:mcp /home/mcp

WORKDIR /app
COPY MCP-Deployment/services/hackbrowser/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY MCP-Deployment/services/hackbrowser/ /app/
COPY standalone/start.sh /app/start.sh
RUN chmod 755 /app/start.sh && chown -R mcp:mcp /app

USER mcp
ENV HOME=/home/mcp HACKBROWSER_MCP_HOST=0.0.0.0 HACKBROWSER_MCP_PORT=8765 \
    XDG_CACHE_HOME=/tmp/chromium-cache XDG_CONFIG_HOME=/tmp/chromium-config
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl --noproxy '*' -fsS http://127.0.0.1:9223/json/version >/dev/null || exit 1
CMD ["/bin/bash", "/app/start.sh"]
