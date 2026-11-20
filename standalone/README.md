# HackBrowser MCP — standalone Docker (Linux)

This is **only HackBrowser**, without PocMap, OWASP ZAP, PostgreSQL,
Keycloak or the full OCI deployment. It is intended for **local development**.

Prerequisites: Linux Docker Engine with the Docker Compose plugin, a compatible
`linux/amd64` or `linux/arm64` host, and enough memory for Chromium.

```bash
git clone https://github.com/Gandalem/hackbrowser.git
cd hackbrowser
docker compose -f standalone/compose.yml up -d --build
docker compose -f standalone/compose.yml ps
```

Connect a local MCP client to **`http://127.0.0.1:8765/mcp`**.
Your MCP client must support streamable HTTP.

```bash
# Check the GUI browser is alive (through the MCP browser_status tool).
docker compose -f standalone/compose.yml logs --tail=40 hackbrowser

# Stop only the container (persistent Chromium profile volume is preserved).
docker compose -f standalone/compose.yml down
```

## Security

- **No authentication** in this standalone image. It is published only on the
  Docker host's `127.0.0.1`. Do not expose port 8765 through a public proxy.
- Chromium CDP 9223 is **not published** outside the container.
- Chromium runs as a non-root user with Docker capabilities dropped. The
  default Docker launch uses `--no-sandbox`; therefore treat the browser as
  an untrusted-content process. Run it on a trusted development host and
  do not browse hostile sites or share its profile across users.
- The named volume retains logins after `down`. Removing it deletes local
  browser profile data; `down` alone does not.
- This setup is **not** a public ChatGPT connector. For remote ChatGPT with
  HTTPS/OAuth use the [full deployment](../MCP-Deployment/README.md).
- A Linux ARM64 image was built and started in GitHub Actions with live MCP discovery and CDP checks. Other host architectures and local Docker configurations need independent verification.
