import ast
import importlib.util
import json
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
        for f in ["install.sh", "uninstall.sh", "status.sh", "renew-share.sh", "scripts/deploy_release.sh"]:
            subprocess.run(["bash", "-n", str(ROOT / f)], check=True)

    def test_no_runtime_credentials_bundled(self):
        self.assertFalse((ROOT / "runtime/private.env").exists())
        self.assertFalse((ROOT / "runtime/secrets").exists())
        self.assertFalse(any(ROOT.rglob("*.pem")))
        self.assertFalse(any(ROOT.rglob("*.key")))

    def test_hackbrowser_tools(self):
        tree = ast.parse((ROOT / "services/hackbrowser/server.py").read_text())
        exported = [
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "tool" for d in node.decorator_list)
        ]
        self.assertEqual(len(exported), 8)

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
