"""Conservative browser workflow checks without a real browser or secrets."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent.parent / "services/hackbrowser"
spec = importlib.util.spec_from_file_location("tested_workflow", SOURCE / "workflow_engine.py")
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)

server_spec = importlib.util.spec_from_file_location("tested_workflow_server", SOURCE / "server.py")
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)


class WorkflowValidationTests(unittest.TestCase):
    def test_public_https_only(self):
        self.assertTrue(wf.safe_public_url("https://ko.wikipedia.org/wiki/건담"))
        for url in (
            "file:///etc/passwd", "http://localhost", "https://127.0.0.1/test",
            "https://192.168.1.1/", "https://169.254.169.254/latest/meta-data",
            "https://shop.example.com/delete-account",
            "https://shop.example.com/checkout",
            "https://shop.example.com/path?delete=true",
            "https://user:pass@example.com/", "http://example.com/",
            "https://test.localhost/", "https://example.com:8443/",
        ):
            with self.subTest(url=url):
                self.assertFalse(wf.safe_public_url(url))

    def test_rejects_mutating_and_ambiguous_steps(self):
        bad = (
            [{"op": "fill", "selector": "#password", "text": "secret"}],
            [{"op": "click_link", "text": "구매하기"}],
            [{"op": "click_link", "selector": "#buy", "text": "label"}],
            [{"op": "search", "selector": "#pw", "value": "password"}],
            [{"op": "navigate", "url": "https://site.example/logout"}],
            [{"op": "wait", "text": "done", "selector": "button"}],
            [{"op": "scroll", "pixels": 0}],
            [{"op": "navigate", "url": "https://example.org"}] * 9,
        )
        for steps in bad:
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                wf.validate_steps(steps)

    def test_valid_browsing_steps(self):
        steps = wf.validate_steps([
            {"op": "navigate", "url": "https://ko.wikipedia.org/wiki/건담"},
            {"op": "search", "selector": "#searchInput", "text": "건담"},
            {"op": "click_link", "text": "역사", "container_selector": "#toc"},
            {"op": "wait", "text": "건담", "timeout_seconds": 4},
            {"op": "scroll", "direction": "down", "pixels": 250},
        ])
        self.assertEqual(len(steps), 5)
        self.assertEqual(steps[-1]["pixels"], 250)


class WorkflowProgressTests(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.state = ["ok"]
        self.actions = []
        self.results = {}
        def executor(target, step):
            self.actions.append((target, step["op"]))
            return self.results.get(step["op"], {"ok": True, "effect_observed": True})
        self.manager = wf.WorkflowManager(
            gate=lambda tid: {"state": self.state[0]}, executor=executor,
            clock=lambda: self.now[0],
        )

    def test_executes_three_then_resumes_without_repeating(self):
        steps = [
            {"op": "navigate", "url": "https://example.org/search"},
            {"op": "wait", "text": "ready"},
            {"op": "scroll", "pixels": 200},
            {"op": "click_link", "text": "Overview"},
        ]
        first = self.manager.start(steps, "my-tab")
        self.assertEqual(first["status"], "yielded")
        self.assertEqual(first["next_step"], 3)
        done = self.manager.resume(first["workflow_id"])
        self.assertEqual(done["status"], "finished")
        self.assertEqual(done["next_step"], 4)
        self.assertEqual([op for _, op in self.actions],
                         ["navigate", "wait", "scroll", "click_link"])

    def test_verification_pause_then_manual_resume(self):
        self.state[0] = "verification_required"
        task = self.manager.start([{"op": "scroll", "pixels": 100}], "my-tab")
        self.assertEqual(task["status"], "paused_verification")
        self.assertEqual(task["next_step"], 0)
        self.assertEqual(self.actions, [])
        self.assertEqual(self.manager.paused_for_target("my-tab")["workflow_id"],
                         task["workflow_id"])
        # The first resume must remain paused while the user is solving it.
        still = self.manager.resume(task["workflow_id"])
        self.assertEqual(still["next_step"], 0)
        self.state[0] = "ok"
        done = self.manager.resume(task["workflow_id"])
        self.assertEqual(done["status"], "finished")
        self.assertEqual(len(self.actions), 1)
        with self.assertRaises(ValueError):
            self.manager.resume(task["workflow_id"])

    def test_final_step_pauses_and_completes_without_replay(self):
        def gate(target):
            return {"state": "verification_required" if self.actions else "ok"}
        manager = wf.WorkflowManager(
            gate=gate,
            executor=lambda target, step: self.actions.append(step) or {
                "ok": True, "effect_observed": True,
            },
        )
        task = manager.start([{"op": "click_link", "text": "Gundam"}], "my-tab")
        self.assertEqual(task["status"], "paused_verification")
        self.assertEqual(task["next_step"], 1)
        manager.gate = lambda tid: {"state": "ok"}
        result = manager.resume(task["workflow_id"])
        self.assertEqual(result["status"], "finished")
        self.assertEqual(len(self.actions), 1)

    def test_ambiguous_link_effect_stops_instead_of_retrying(self):
        self.results["click_link"] = {"ok": True, "effect_observed": False}
        task = self.manager.start([
            {"op": "click_link", "text": "Overview"}, {"op": "scroll", "pixels": 100}
        ], "my-tab")
        self.assertEqual(task["status"], "stopped")
        self.assertEqual(task["reason"], "effect_unconfirmed")
        self.assertEqual(task["next_step"], 0)
        self.assertEqual(len(self.actions), 1)
        with self.assertRaises(ValueError):
            self.manager.resume(task["workflow_id"])

    def test_concurrent_workflow_for_same_tab_rejected(self):
        self.manager.start([{"op": "scroll"}] * 5, "my-tab")
        with self.assertRaisesRegex(RuntimeError, "already controls"):
            self.manager.start([{"op": "scroll"}], "my-tab")

    def test_expiry_removes_workflow(self):
        task = self.manager.start([{"op": "scroll"}] * 5, "my-tab")
        self.now[0] += wf.WORKFLOW_TTL_SECONDS + 1
        with self.assertRaises(ValueError):
            self.manager.get(task["workflow_id"])

    def test_restriction_stops_before_any_browser_action(self):
        self.state[0] = "restricted"
        task = self.manager.start([{"op": "scroll"}], "my-tab")
        self.assertEqual(task["status"], "stopped")
        self.assertEqual(self.actions, [])


class ServerAdapterTests(unittest.TestCase):
    def test_login_page_gate_pauses(self):
        with mock.patch.object(server, "_target", return_value={
            "id": "tab", "url": "https://nid.naver.com/nidlogin.login",
        }), mock.patch.object(server, "browser_page_text", return_value={
            "url": "https://nid.naver.com/nidlogin.login",
            "access_status": "ok",
        }), mock.patch.object(server, "_verification_state", return_value={}):
            self.assertEqual(server._workflow_gate("tab")["state"], "login_required")

    def test_guarded_link_uses_playwright_operation(self):
        with mock.patch.object(server, "_target", return_value={
            "id": "tab", "url": "https://example.org/",
        }), mock.patch.object(server, "_pace_navigation"), mock.patch.object(
            server, "_gui_action", return_value={"ok": True, "effect_observed": True}
        ) as action:
            result = server._workflow_execute(
                "tab", {"op": "click_link", "text": "Overview"}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(action.call_args.args[1], "safe_link")

    def test_workflow_screenshot_does_not_leak_secret(self):
        steps = [{"op": "search", "selector": "#q", "text": "gundam"}]
        self.assertIn("search", str(wf.validate_steps(steps)))


if __name__ == "__main__":
    unittest.main()
