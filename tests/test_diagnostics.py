import contextlib
import unittest
from pathlib import Path
from unittest import mock

import aparte
from aparte import diagnostics
from aparte.config import Settings
from aparte.diagnostics import collect_checks, collect_diagnostics
from aparte.macos_hotkey import HotkeyState

I18N_JS = Path(aparte.__file__).resolve().parent / "assets" / "i18n.js"


class DiagnosticsTest(unittest.TestCase):
    def test_essential_checks_are_present(self):
        keys = {c.key for c in collect_checks(Settings())}
        self.assertIn("whisper_backend", keys)
        self.assertIn("recorder", keys)
        self.assertIn("paste", keys)

    def test_missing_essential_checks_carry_a_fix_command(self):
        for check in collect_checks(Settings()):
            if check.essential and not check.ok:
                self.assertTrue(check.fix, f"{check.key} should expose a fix command")

    def test_collect_diagnostics_shape(self):
        data = collect_diagnostics(Settings())
        self.assertEqual(set(data["summary"]), {"ready", "can_transcribe", "can_record", "can_insert"})
        self.assertTrue(all({"key", "label", "ok", "category"} <= set(c) for c in data["checks"]))
        # ready implies every essential check passed
        essentials = [c for c in data["checks"] if c["essential"]]
        self.assertEqual(data["summary"]["ready"], all(c["ok"] for c in essentials))


class MacDiagnosticsTest(unittest.TestCase):
    """On macOS the check list is different — TCC permissions, no ALSA/paste —
    but the same summary and panel must keep working. Permissions are mocked;
    the machine here is Linux."""

    def _mac_env(self, mic="authorized", accessibility=True, model_cached=True):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(diagnostics, "is_macos", return_value=True))
        stack.enter_context(
            mock.patch.object(diagnostics, "_whisper_model_cached", return_value=model_cached)
        )
        stack.enter_context(
            mock.patch("aparte.macos_permissions.microphone_authorization", return_value=mic)
        )
        stack.enter_context(
            mock.patch("aparte.macos_permissions.accessibility_trusted", return_value=accessibility)
        )
        # The hotkey check self-requests a running server when given no state; keep
        # the default off the network. Individual tests override it or pass a state.
        stack.enter_context(
            mock.patch.object(diagnostics, "_query_hotkey_state", return_value=None)
        )
        return stack

    def test_the_macos_list_has_permissions_and_no_linux_only_checks(self):
        with self._mac_env():
            keys = {c.key for c in collect_checks(Settings())}
        self.assertLessEqual(
            {"whisper_backend", "recorder", "mic_permission", "accessibility", "model_ready"},
            keys,
        )
        self.assertNotIn("paste", keys)  # synthetic paste is M3
        self.assertNotIn("tray", keys)  # PyGObject tray is Linux-only

    def test_the_summary_does_not_crash_without_a_paste_check(self):
        with self._mac_env():
            data = collect_diagnostics(Settings())
        self.assertEqual(
            set(data["summary"]), {"ready", "can_transcribe", "can_record", "can_insert"}
        )
        self.assertTrue(data["summary"]["can_insert"])  # pbcopy is always there

    def test_a_denied_microphone_fails_and_points_to_settings(self):
        with self._mac_env(mic="denied"):
            checks = collect_checks(Settings())
        mic = next(c for c in checks if c.key == "mic_permission")
        self.assertFalse(mic.ok)
        self.assertIn("Settings", mic.detail)

    def test_an_authorized_microphone_passes(self):
        with self._mac_env(mic="authorized"):
            checks = collect_checks(Settings())
        mic = next(c for c in checks if c.key == "mic_permission")
        self.assertTrue(mic.ok)

    def test_the_cli_doctor_surfaces_a_permission_that_has_no_shell_fix(self):
        import io

        from aparte import cli

        with self._mac_env(mic="denied"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.print_doctor(Settings())
        text = out.getvalue()
        # The microphone permission carries no `fix`; without the guidance branch
        # in print_doctor its remedy would never reach a CLI user.
        self.assertIn("Microphone permission", text)
        self.assertIn("System Settings", text)


class MacHotkeyCheckTest(unittest.TestCase):
    """The macOS global-shortcut check (M5d): registered → the combo; refused →
    the OSStatus; unconfigured → install-hotkey; and, from the CLI with no server
    answering, a static reply from the config. Its detail is dynamic, so it must
    carry no i18n detail key. The machine here is Linux; the platform is mocked."""

    def _mac_env(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(diagnostics, "is_macos", return_value=True))
        stack.enter_context(mock.patch.object(diagnostics, "_whisper_model_cached", return_value=True))
        stack.enter_context(mock.patch("aparte.macos_permissions.microphone_authorization", return_value="authorized"))
        stack.enter_context(mock.patch("aparte.macos_permissions.accessibility_trusted", return_value=True))
        stack.enter_context(mock.patch.object(diagnostics, "_query_hotkey_state", return_value=None))
        return stack

    def _hotkey(self, checks):
        return next(c for c in checks if c.key == "hotkey")

    def test_a_registered_shortcut_passes_and_shows_the_combo(self):
        state = HotkeyState(registered=True, configured_key="ctrl+opt+d")
        with self._mac_env():
            hk = self._hotkey(collect_checks(Settings(), hotkey_state=state))
        self.assertTrue(hk.ok)
        self.assertEqual(hk.detail, "⌃⌥D")

    def test_a_refused_shortcut_fails_and_carries_the_osstatus(self):
        state = HotkeyState(configured_key="ctrl+opt+d", status=-9878, error="taken")
        with self._mac_env():
            hk = self._hotkey(collect_checks(Settings(), hotkey_state=state))
        self.assertFalse(hk.ok)
        self.assertIn("⌃⌥D", hk.detail)
        self.assertIn("-9878", hk.detail)

    def test_no_configured_shortcut_points_at_install_hotkey(self):
        # Server up (state present) but nothing configured — opt in with install-hotkey.
        with self._mac_env():
            hk = self._hotkey(collect_checks(Settings(), hotkey_state=HotkeyState()))
        self.assertFalse(hk.ok)
        self.assertIn("install-hotkey", hk.detail)

    def test_the_cli_falls_back_to_the_config_when_no_server_answers(self):
        # No in-process state and _query returns None: the configured combo tells
        # the user to start the app. This branch is CLI-only (English is fine there).
        with self._mac_env():
            hk = self._hotkey(collect_checks(Settings(hotkey="ctrl+opt+d")))
        self.assertFalse(hk.ok)
        self.assertIn("⌃⌥D", hk.detail)

    def test_the_check_is_never_essential(self):
        # The app still dictates from the browser without a shortcut, so a missing
        # one must not flip the "ready" summary to false.
        with self._mac_env():
            hk = self._hotkey(collect_checks(Settings(), hotkey_state=HotkeyState()))
        self.assertFalse(hk.essential)

    def test_the_hotkey_detail_carries_no_static_i18n_key(self):
        # A check.hotkey.detail key would overwrite the dynamic detail and could
        # contradict the icon (the config-check convention). Label yes, detail no.
        i18n = I18N_JS.read_text(encoding="utf-8")
        self.assertIn('"check.hotkey.label"', i18n)
        self.assertNotIn('"check.hotkey.detail"', i18n)


if __name__ == "__main__":
    unittest.main()
