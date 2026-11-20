# HackBrowser MCP

**Your AI browser. Your server. Your control.**

A self-hosted **GUI Chromium browser** for MCP agents. Let an AI browse real pages via Playwright and CDP, view screenshots in ChatGPT, and pause when a person needs to handle a login or verification. No remote browser-cloud account required.

> **Public beta:** Works with an existing GUI Chromium instance on Linux. The local Docker path below is new and requires runtime validation on your host. The project does not yet offer isolated multi-user sessions or fully automatic CAPTCHA handoff.

[Standalone browser](standalone/README.md) · [Full server + OAuth](MCP-Deployment/README.md) · [MCP tools](docs/TOOLS.md) · [Demo walkthrough](docs/DEMO.md) · [Releases](https://github.com/Gandalem/hackbrowser/releases)

## What makes it useful?

| | Feature | How it helps |
|---|---|---|
| 1 | **Real GUI Chromium in a CLI server** | Xvfb renders a real GUI browser without a physical monitor; Playwright connects through local CDP |
| 2 | **AI-friendly Observe → Act** | AI receives concise, numbered element references rather than long CSS selectors |
| 3 | **Human-assisted verification** | Screenshot MCP App can relay manual CAPTCHA input or clicks, without automated solving |
| 4 | **Conservative workflows** | Up to 8 safe browsing steps; pause on login/verification; explicit resume |
| 5 | **Self-hosted** | Choose a local-only Docker browser or full Linux systemd/OAuth deployment |

### Quickstart: browser only (Linux Docker)

Requires Docker Engine, Compose plugin, and enough resources for GUI Chromium. **This standalone setup is intended for one local developer, not public deployment.**

```bash
git clone https://github.com/Gandalem/hackbrowser.git
cd hackbrowser
docker compose -f standalone/compose.yml up -d --build
docker compose -f standalone/compose.yml ps
```

Configure a **local MCP client** to connect to `http://127.0.0.1:8765/mcp` using Streamable HTTP. The Docker host only publishes this port to its own loopback address. The GUI CDP port **9223 stays inside the container**.

> **Security:** Local-only standalone MCP has no authentication. Do not publish or reverse-proxy its port to the Internet. Docker Chromium uses `--no-sandbox`, runs as non-root, and is not a security isolation boundary. For remote ChatGPT connections use the full HTTPS/OAuth deployment, not the standalone port.

See [standalone setup and limitations](standalone/README.md).

### Try with an AI

Once your MCP client is connected, try:

> Open the Wikipedia page about Gundam. Observe the page, use an element reference to follow a safe link, and return the page title and a screenshot.

The agent can call `browser_navigate`, then `browser_observe`, then `browser_act` using a fresh `snapshot_id` and `ref`, and `browser_screenshot`. Element references expire after 90 seconds or a page change. Sensitive actions are denied by the semantic interface; advanced existing tools remain available for explicitly user-controlled operations.

## ChatGPT and remote servers

The **full MCP Deployment** installs three independent MCP backends and provides a reverse proxy and optional Keycloak OAuth:

| MCP | Purpose | Tools |
|---|---|---:|
| **HackBrowser** | GUI Chromium, screenshots, human verification, workflows, Observe/Act | **22** |
| PocMap | CVE/PoC intelligence | 22 |
| OWASP ZAP | Web security testing | 17 |
| **Total** | | **61** |

```bash
git clone https://github.com/Gandalem/hackbrowser.git
cd hackbrowser/MCP-Deployment
# Consult the full installation modes before proceeding:
less README.md
```

Use the [full installation and authentication guide](MCP-Deployment/README.md) for Ubuntu/Debian, systemd, Caddy, Keycloak, existing server migration and OCI. This installer configures the whole suite; standalone Docker does **not**.

## Verified behavior and current limitations

- Tested on an OCI GUI Chromium deployment: page navigation, clickable elements, new tabs, scrolling, screenshot and bounded workflow resume.
- CI checks Python syntax, unit tests and MCP tool discovery. **Docker standalone has not yet been exercised on every supported CPU/OS combination.**
- Semantic Observe/Act is new in this beta: it deliberately blocks unknown button actions, unsafe destinations and sensitive form input. Re-observe if a reference expires.
- CAPTCHA/manual login is performed by a person. An end-to-end real CAPTCHA → workflow resume demonstration remains to be validated.
- The full server currently **shares one GUI profile across authenticated MCP users**. Do not use it for multiple untrusted users.
- Host permissions, sites' terms, sandbox configuration, authentication and network boundaries are still the operator's responsibility.

## Contributing and source

Bug reports and reproducible improvements are welcome. Include your OS, architecture, Chromium version, MCP client, redacted logs and a minimal reproduction. Never post tokens, credentials, private URLs or browser profiles.

[Source provenance](MCP-Deployment/docs/PROVENANCE.md) · [License](LICENSE) · [Release/OCI CI](docs/RELEASE.md)

This repository packages a new MCP bridge alongside original and third-party components. Preserve original author credits and check upstream licenses before redistribution.
