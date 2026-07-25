"""M5b — the macOS run loop + shortcut lifecycle (serve_macos), proven under Linux.

No AppKit run loop or Carbon registration runs here: both are injected. The test
locks the observable orchestration — the server moves to a daemon thread, the
shortcut is registered with the configured combo once the loop is ready, a press
reaches toggle() off the calling thread, teardown runs in a fixed order, and a
registration failure keeps the server serving instead of crashing.
"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from aparte import macos_runloop
from aparte.macos_hotkey import HotkeyError, HotkeyState
from aparte.macos_runloop import run_hotkey_diagnostic, serve_macos


class FakeServer:
    """serve_forever() blocks until shutdown(), like the real ThreadingHTTPServer.

    ``RequestHandlerClass`` mirrors the real server attribute serve_macos reaches
    through to publish the shortcut state; each instance gets its own fake handler
    class so one test's hotkey_state never leaks into another's."""

    def __init__(self, order):
        self.order = order
        self.serving = threading.Event()
        self._stop = threading.Event()
        self.RequestHandlerClass = type("FakeHandler", (), {"hotkey_state": None})

    def serve_forever(self):
        self.serving.set()
        self._stop.wait(5.0)

    def shutdown(self):
        self.order.append("server.shutdown")
        self._stop.set()

    def server_close(self):
        self.order.append("server.server_close")


class FakeController:
    def __init__(self, order):
        self.order = order
        self.toggle_thread = None
        self.toggled = threading.Event()

    def toggle(self):
        self.toggle_thread = threading.current_thread()
        self.toggled.set()

    def shutdown(self):
        self.order.append("controller.shutdown")


class FakeHandle:
    def __init__(self, order):
        self.order = order

    def unregister(self):
        self.order.append("hotkey.unregister")


class FakeRegister:
    """Captures what serve_macos asked to register; can raise instead."""

    def __init__(self, handle=None, error=None):
        self.handle = handle
        self.error = error
        self.spec = None
        self.on_trigger = None

    def __call__(self, spec, on_trigger):
        self.spec = spec
        self.on_trigger = on_trigger
        if self.error is not None:
            raise self.error
        return self.handle


class ServeMacosTest(unittest.TestCase):
    def setUp(self):
        self.order = []
        self.controller = FakeController(self.order)
        self.server = FakeServer(self.order)
        # A registration failure now fires a critical notification. Stub notify at
        # the module level: the real one imports gi (GTK), which fails here and
        # poisons the module for the rest of the suite (CLAUDE.md M4 trap).
        self.notify = mock.patch.object(macos_runloop, "notify").start()
        self.addCleanup(mock.patch.stopall)

    def _state(self):
        return self.server.RequestHandlerClass.hotkey_state

    def _run(self, settings, register, *, press=False):
        """Drive serve_macos with a fake run loop that fires on_ready, then quits."""

        def run_loop(on_ready):
            on_ready()                       # NSApplication ready → register here
            if press:
                register.on_trigger()        # the OS delivers one hotkey press
                self.assertTrue(self.controller.toggled.wait(2.0))
            # returning simulates the user quitting the app

        serve_macos(
            self.server, self.controller, settings, register=register, run_loop=run_loop
        )

    def test_the_shortcut_is_registered_with_the_configured_combo(self):
        register = FakeRegister(handle=FakeHandle(self.order))
        self._run(SimpleNamespace(hotkey="cmd+shift+d"), register)
        self.assertEqual(register.spec, "cmd+shift+d")
        # The state doctor and /api/hotkey-state read reflects the live registration.
        self.assertEqual(self._state(), HotkeyState(registered=True, configured_key="cmd+shift+d"))

    def test_no_shortcut_is_registered_when_none_is_configured(self):
        # Empty hotkey = no shortcut (the user must run `aparte install-hotkey`).
        # The server still comes up and tears down cleanly, just with no handle.
        register = FakeRegister(handle=FakeHandle(self.order))
        self._run(SimpleNamespace(hotkey=""), register)
        self.assertIsNone(register.spec)                 # register never called
        self.assertTrue(self.server.serving.is_set())
        self.assertEqual(self.order, ["controller.shutdown", "server.shutdown", "server.server_close"])
        # doctor reads "configured_key is None" → points the user at install-hotkey.
        self.assertEqual(self._state(), HotkeyState(configured_key=None))
        self.notify.assert_not_called()

    def test_the_server_starts_on_its_own_thread(self):
        register = FakeRegister(handle=FakeHandle(self.order))
        self._run(SimpleNamespace(hotkey="ctrl+opt+d"), register)
        self.assertTrue(self.server.serving.is_set())

    def test_a_press_reaches_toggle_off_the_calling_thread(self):
        register = FakeRegister(handle=FakeHandle(self.order))
        self._run(SimpleNamespace(hotkey="ctrl+opt+d"), register, press=True)
        self.assertIsNotNone(self.controller.toggle_thread)
        self.assertIsNot(self.controller.toggle_thread, threading.current_thread())

    def test_teardown_runs_in_order(self):
        register = FakeRegister(handle=FakeHandle(self.order))
        self._run(SimpleNamespace(hotkey="ctrl+opt+d"), register, press=True)
        self.assertEqual(
            self.order,
            ["hotkey.unregister", "controller.shutdown", "server.shutdown", "server.server_close"],
        )

    def test_a_registration_failure_keeps_serving_and_still_tears_down(self):
        # A reserved/taken combo raises HotkeyError; the server must survive and the
        # teardown still run — just without a hotkey handle to unregister.
        register = FakeRegister(error=HotkeyError("taken", status=-9878))
        self._run(SimpleNamespace(hotkey="ctrl+opt+d"), register)
        self.assertEqual(
            self.order,
            ["controller.shutdown", "server.shutdown", "server.server_close"],
        )

    def test_a_registration_failure_is_observable_and_notified(self):
        # The failure lands in the state (registered false, OSStatus + message kept)
        # AND fires a critical notification, so it never fails in silence.
        register = FakeRegister(error=HotkeyError("taken", status=-9878))
        self._run(SimpleNamespace(hotkey="ctrl+opt+d"), register)
        state = self._state()
        self.assertFalse(state.registered)
        self.assertEqual(state.configured_key, "ctrl+opt+d")
        self.assertEqual(state.status, -9878)
        self.assertIn("taken", state.error)
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")


class RunHotkeyDiagnosticTest(unittest.TestCase):
    """The M8 native smoke tool: register live, count RAW events per press (it
    bypasses the dispatcher on purpose), print the OSStatus. Native pieces injected."""

    def test_it_counts_raw_events_and_unregisters(self):
        lines, order = [], []
        register = FakeRegister(handle=FakeHandle(order))

        def run_loop(on_ready):
            on_ready()                 # registers, capturing on_trigger
            register.on_trigger()      # two OS-delivered presses
            register.on_trigger()

        count = run_hotkey_diagnostic(
            "ctrl+opt+d", register=register, run_loop=run_loop,
            clock=lambda: 0.0, emit=lines.append,
        )
        self.assertEqual(count, 2)
        self.assertEqual(register.spec, "ctrl+opt+d")
        self.assertIn("hotkey.unregister", order)          # teardown ran
        self.assertTrue(any("press #2" in line for line in lines))

    def test_a_refused_combo_reports_the_osstatus_and_counts_zero(self):
        lines = []
        register = FakeRegister(error=HotkeyError("taken", status=-9878))

        def run_loop(on_ready):
            on_ready()                 # registration fails; no events follow

        count = run_hotkey_diagnostic(
            "ctrl+opt+d", register=register, run_loop=run_loop, emit=lines.append,
        )
        self.assertEqual(count, 0)
        self.assertTrue(any("OSStatus -9878" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
