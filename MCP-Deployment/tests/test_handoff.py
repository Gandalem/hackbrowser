"""Manual takeover safety and accessibility regressions."""
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent / "services/hackbrowser"
spec = importlib.util.spec_from_file_location("tested_handoff", ROOT / "handoff.py")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)
server_spec = importlib.util.spec_from_file_location("tested_handoff_server", ROOT / "server.py")
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)

TARGET = {"id": "tab", "url": "https://example.org", "type": "page"}
VIEWPORT = {"width": 800, "height": 600}


class ManualHandoffTests(unittest.TestCase):
    def setUp(self):
        self.time = [0.0]
        self.state = handoff.ManualHandoff(clock=lambda: self.time[0])

    def test_lease_blocks_ai_but_not_status(self):
        started = self.state.begin("tab", VIEWPORT)
        self.assertTrue(started["active"])
        self.assertTrue(self.state.status()["active"])
        self.assertNotIn("control_token", self.state.status())
        with self.assertRaisesRegex(RuntimeError, "Manual control"):
            self.state.assert_ai_allowed()
        self.assertEqual(
            self.state.authenticate(started["control_token"], "tab"), VIEWPORT
        )
        result = self.state.finish(started["control_token"])
        self.assertTrue(result["returned_to_ai"])
        self.state.assert_ai_allowed()

    def test_expiry_releases_ai_without_refresh(self):
        self.state.begin("tab", VIEWPORT)
        self.time[0] += handoff.HANDOFF_TTL_SECONDS + 1
        self.assertFalse(self.state.status()["active"])
        self.state.assert_ai_allowed()

    def test_different_token_target_and_lease_collision_fail_closed(self):
        started = self.state.begin("tab", VIEWPORT)
        with self.assertRaises(RuntimeError):
            self.state.begin("other", VIEWPORT)
        for token, tab in (("wrong", "tab"), (started["control_token"], "other")):
            with self.assertRaises(ValueError):
                self.state.authenticate(token, tab)
        with self.assertRaises(ValueError):
            self.state.finish("wrong")
        self.assertTrue(self.state.status()["active"])

    def test_viewport_must_be_valid(self):
        for bad in ({"width": 800, "height": 0},
                    {"width": True, "height": 600}, {}):
            with self.assertRaises(ValueError):
                self.state.begin("tab", bad)

    def test_lock_waits_for_running_ai_action(self):
        locked = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        def ai_action():
            with self.state.lock:
                locked.set()
                release.wait(2)
            finished.set()
        thread = threading.Thread(target=ai_action)
        thread.start()
        self.assertTrue(locked.wait(1))
        # This test does not leave workers or browser tabs behind.
        release.set()
        self.assertTrue(finished.wait(1))
        thread.join()
        self.state.begin("tab", VIEWPORT)
        with self.assertRaises(RuntimeError):
            with self.state.lock:
                self.state.assert_ai_allowed()


class ServerManualToolTests(unittest.TestCase):
    def setUp(self):
        self.state = handoff.ManualHandoff()
        self.old = server._manual_handoff
        server._manual_handoff = self.state

    def tearDown(self):
        server._manual_handoff = self.old

    def _begin(self):
        with mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value=VIEWPORT):
            return server.browser_handoff_begin("tab")

    def test_begin_returns_token_only_to_caller_and_status_hides_it(self):
        session = self._begin()
        self.assertTrue(session["active"])
        public = server.browser_handoff_status()
        self.assertTrue(public["active"])
        self.assertNotIn(session["control_token"], str(public))

    def test_manual_click_once_and_return(self):
        session = self._begin()
        with mock.patch.object(server, "_verification_state", return_value={}), \
             mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value=VIEWPORT), \
             mock.patch.object(server, "_click_at") as click:
            result = server.browser_handoff_input(
                session["control_token"], "tab", "click", x=120, y=200
            )
        self.assertTrue(result["ok"])
        click.assert_called_once_with("tab", 120, 200)
        self.assertTrue(server.browser_handoff_end(session["control_token"])["ok"])
        self.state.assert_ai_allowed()

    def test_ai_cdp_mutation_rejected_during_takeover(self):
        session = self._begin()
        with mock.patch.object(server, "_cdp_raw") as raw:
            with self.assertRaisesRegex(RuntimeError, "Manual control"):
                server._cdp("Input.dispatchMouseEvent", {"type": "mousePressed"}, "tab")
            raw.assert_not_called()
        server.browser_handoff_end(session["control_token"])

    def test_ai_browser_tab_mutation_rejected(self):
        self._begin()
        with mock.patch.object(server, "_browser_cdp_raw") as raw:
            with self.assertRaises(RuntimeError):
                server._browser_cdp("Target.closeTarget", {"targetId": "tab"})
            raw.assert_not_called()

    def test_manual_click_refuses_challenge(self):
        session = self._begin()
        with mock.patch.object(server, "_verification_state", return_value={
            "verification_reason": "CAPTCHA"
        }), mock.patch.object(server, "_click_at") as click:
            with self.assertRaisesRegex(RuntimeError, "verification"):
                server.browser_handoff_input(session["control_token"], "tab",
                                             "click", x=10, y=10)
            click.assert_not_called()

    def test_scroll_requires_authorized_token_and_matching_viewport(self):
        session = self._begin()
        with self.assertRaises(ValueError):
            server.browser_handoff_input("wrong", "tab", "scroll_down")
        with mock.patch.object(server, "_verification_state", return_value={}), \
             mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value=VIEWPORT), \
             mock.patch.object(server, "_cdp") as cdp:
            good = server.browser_handoff_input(
                session["control_token"], "tab", "scroll_down", pixels=400
            )
        self.assertTrue(good["ok"])
        cdp.assert_called_once()
        self.assertEqual(cdp.call_args.args[0], "Input.dispatchMouseEvent")
        self.assertEqual(cdp.call_args.args[1]["deltaY"], 400)

    def test_wrong_viewport_does_not_click(self):
        session = self._begin()
        with mock.patch.object(server, "_verification_state", return_value={}), \
             mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value={
                 "width": 900, "height": 600,
             }), mock.patch.object(server, "_click_at") as click:
            with self.assertRaisesRegex(ValueError, "Viewport changed"):
                server.browser_handoff_input(session["control_token"], "tab",
                                             "click", x=80, y=80)
            click.assert_not_called()

    def test_invalid_actions_and_coordinates(self):
        session = self._begin()
        for action in ("type", "keyboard", "javascript"):
            with self.assertRaises(ValueError):
                server.browser_handoff_input(session["control_token"], "tab", action)
        with mock.patch.object(server, "_verification_state", return_value={}), \
             mock.patch.object(server, "_target", return_value=TARGET), \
             mock.patch.object(server, "_evaluate", return_value=VIEWPORT):
            with self.assertRaises(ValueError):
                server.browser_handoff_input(session["control_token"], "tab",
                                             "click", x=801, y=20)


if __name__ == "__main__":
    unittest.main()
