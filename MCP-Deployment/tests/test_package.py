import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class SourceTests(unittest.TestCase):
    def test_python_syntax(self):
        for f in list((ROOT / "services").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
            ast.parse(f.read_text(), filename=str(f))

    def test_shell_syntax(self):
        for f in ["install.sh", "uninstall.sh", "status.sh", "renew-share.sh", "scripts/deploy_release.sh", "scripts/ensure_korean_fonts.sh"]:
            subprocess.run(["bash", "-n", str(ROOT / f)], check=True)

    def test_no_runtime_credentials_bundled(self):
        self.assertFalse((ROOT / "runtime/private.env").exists())
        self.assertFalse((ROOT / "runtime/secrets").exists())
        self.assertFalse(any(ROOT.rglob("*.pem")))
        self.assertFalse(any(ROOT.rglob("*.key")))

    def test_korean_fonts_in_installer_and_existing_server_deployment(self):
        installer = (ROOT / "install.sh").read_text()
        deployer = (ROOT / "scripts/deploy_release.sh").read_text()
        helper = (ROOT / "scripts/ensure_korean_fonts.sh").read_text()

        self.assertIn('bash "$ROOT/scripts/ensure_korean_fonts.sh"', installer)
        self.assertIn('bash "$ROOT/scripts/ensure_korean_fonts.sh"', deployer)
        self.assertLess(
            deployer.index('bash "$ROOT/scripts/ensure_korean_fonts.sh"'),
            deployer.index("systemctl restart mcpstack-chromium.service"),
        )
        self.assertIn("fonts-noto-cjk", helper)
        self.assertIn("fonts-nanum", helper)
        self.assertIn("fontconfig", helper)
        self.assertIn("fc-cache -f", helper)
        self.assertIn("':lang=ko'", helper)
        self.assertIn("runuser -u mcpstack --", helper)
        self.assertIn("apt-get install -y --no-install-recommends", helper)

    def test_release_reconfigures_and_reloads_caddy(self):
        script = (ROOT / "scripts/deploy_release.sh").read_text()
        self.assertIn('source "$ROOT/runtime/private.env"', script)
        self.assertIn('python3 "$ROOT/scripts/render_config.py"', script)
        self.assertIn('caddy caddy validate --config /etc/caddy/Caddyfile', script)
        self.assertIn('caddy caddy reload --config /etc/caddy/Caddyfile', script)
        self.assertIn('"$BACKUP/runtime/caddy/Caddyfile"', script)
        self.assertLess(
            script.index('python3 "$ROOT/scripts/render_config.py"'),
            script.index('systemctl restart mcpstack-chromium.service'),
        )
        self.assertLess(
            script.index('caddy caddy validate --config /etc/caddy/Caddyfile'),
            script.rindex('caddy caddy reload --config /etc/caddy/Caddyfile'),
        )

    def test_deployment_preflights_mcp_apps_before_restarting(self):
        deployer = (ROOT / "scripts/deploy_release.sh").read_text()
        self.assertIn('from mcp.server.apps import Apps', deployer)
        self.assertIn("runpy.run_path(", deployer)
        self.assertLess(deployer.index("runpy.run_path("),
                        deployer.index("systemctl restart mcpstack-chromium.service"))

    def test_hackbrowser_tools(self):
        tree = ast.parse((ROOT / "services/hackbrowser/server.py").read_text())
        exported = [
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "mcp" and d.func.attr == "tool"
                    for d in node.decorator_list)
        ]
        # All 8 browser actions must remain ordinary MCP tools, even if a
        # separate Apps extension serves their ui:// screenshot template.
        app_exported = [
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "apps" and d.func.attr == "tool"
                    for d in node.decorator_list)
        ]
        self.assertEqual(len(exported), 11)
        for name in ("browser_screenshot", "browser_keypress", "browser_scroll", "browser_wait_for"):
            self.assertIn(name, exported)
        self.assertEqual(app_exported, [])

    def test_caddy_modes(self):
        for mode, public, oauth, site in (
            ("local", "http://127.0.0.1:8088", "0", ":8088"),
            ("public", "https://example.com", "1", "example.com"),
            ("external", "https://example.com", "1", ":8088"),
        ):
            with tempfile.TemporaryDirectory() as td:
                env = dict(os.environ, MCP_INSTALL_ROOT=td, CADDY_MODE=mode,
                           PUBLIC_BASE_URL=public, ENABLE_OAUTH=oauth)
                subprocess.run([sys.executable, str(ROOT / "scripts/render_config.py")],
                               env=env, check=True, stdout=subprocess.DEVNULL)
                content = (Path(td) / "runtime/caddy/Caddyfile").read_text()
                self.assertTrue(content.startswith(site + " {"))
                self.assertIn("handle /share/*", content)
                self.assertNotIn("handle /captures/*", content)
                self.assertIn("127.0.0.1:8790", content)
                self.assertEqual("@oauth_mcp" in content, oauth == "1")
                self.assertIn("127.0.0.1:8790", content)

    def test_manifest(self):
        import yaml
        data = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        self.assertEqual(set(data["services"]), {"zap", "keycloak", "postgres", "caddy"})
        self.assertEqual(data["services"]["zap"]["network_mode"], "host")

    def test_keycloak_loopback_port_requires_non_internal_uplink(self):
        import yaml
        data = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        networks = data["networks"]
        keycloak = data["services"]["keycloak"]
        postgres = data["services"]["postgres"]
        self.assertTrue(networks["oauth_internal"]["internal"])
        self.assertFalse(networks["oauth_uplink"].get("internal", False))
        self.assertEqual(postgres["networks"], ["oauth_internal"])
        self.assertNotIn("ports", postgres)
        self.assertIn("oauth_internal", keycloak["networks"])
        self.assertIn("oauth_uplink", keycloak["networks"])
        self.assertIn("127.0.0.1:8081:8080", keycloak["ports"])
        # The tagged release deployer must apply Compose network changes to
        # already running OAuth installations, not only update source files.
        deployer = (ROOT / "scripts/deploy_release.sh").read_text()
        self.assertIn("--profile oauth up -d postgres keycloak", deployer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
