"""Ensure the deployed browser backend is GUI-only, with no headless fallback."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class GuiOnlyTests(unittest.TestCase):
    def test_launcher_runs_gui_on_private_cdp(self):
        gui = (ROOT / "services/hackbrowser/start_chromium_gui.sh").read_text()
        self.assertIn("exec xvfb-run", gui)
        self.assertIn("--remote-debugging-address=127.0.0.1", gui)
        self.assertIn("--remote-debugging-port=9223", gui)
        self.assertNotIn("--headless=new", gui)
        self.assertNotIn(" --headless ", gui)
        self.assertNotIn("--no-sandbox", gui)
        self.assertFalse((ROOT / "services/hackbrowser/start_chromium_headless.sh").exists())

    def test_bridge_uses_gui_port_only(self):
        script = (ROOT / "services/hackbrowser/server.py").read_text()
        tree = ast.parse(script)
        bindings = {t.id: node.value for node in tree.body
                    if isinstance(node, ast.Assign) for t in node.targets
                    if isinstance(t, ast.Name)}
        self.assertEqual(ast.literal_eval(bindings["CDP_PORT"]), 9223)
        self.assertIn("GUI Chromium", script)

    def test_install_and_upgrade_disable_legacy_unit(self):
        setup = (ROOT / "scripts/configure_gui_chromium.sh").read_text()
        install = (ROOT / "install.sh").read_text()
        upgrade = (ROOT / "scripts/deploy_release.sh").read_text()
        status = (ROOT / "status.sh").read_text()
        for item in ("systemctl disable --now mcpstack-chromium.service",
                     "systemctl mask --now mcpstack-chromium.service",
                     "mcpstack-gui-chromium.service", "HACKBROWSER_CDP_PORT=9223"):
            self.assertIn(item, setup)
        for item in (install, upgrade):
            self.assertIn('bash "$ROOT/scripts/configure_gui_chromium.sh"', item)
        self.assertIn('mcpstack-gui-chromium.service', status)
        self.assertIn('9223', status)
        self.assertIn('9222', status)


if __name__ == "__main__":
    unittest.main()
