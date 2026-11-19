# Source provenance and limitations

- `services/hackbrowser/server.py` and `start_chromium_headless.sh` were collected from the user's running Ubuntu server and adapted only via portable paths and environment variables. This is a custom MCP bridge controlling modern Chromium via local CDP, not the historical Electron HackBrowser project.
- `services/gateway/` reconstructs the two Python gateway functions from the user's working export; the JWT gateway implements the working `Mcp-Method`/`Mcp-Name` header forwarding and injects a ZAP security key only after successful authorization.
- PocMap source was **not** included in the export. The installer downloads the public `pocmap[server]==2.9.1` release from PyPI.
- ZAP add-on is installed through `zap.sh -addoninstall mcp`. Its core/ZAP image and MCP add-on versions can move as upstream releases change; test on the deployment host.
- The original Caddyfile was absent (unreadable to the collector), so Caddy configuration is generated for each deployment rather than copied. No original CloudFront distribution, AWS configuration, database data, user credentials, or TLS private keys are included.
- Keycloak realm clients and scopes are re-created from a sanitized configuration snapshot; existing user data is not migrated.
- Check third-party upstream licenses and commercial redistribution terms before selling, especially Docker images and any source you did not author.
