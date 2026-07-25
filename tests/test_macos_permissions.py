import sys
import unittest
from unittest import mock

from aparte import macos_permissions


class MicrophoneAuthorizationTest(unittest.TestCase):
    """AVFoundation returns an int enum; we translate it to a stable string and
    never let a missing framework or a surprise value raise."""

    def _with_avfoundation(self, status):
        fake = mock.Mock()
        fake.AVMediaTypeAudio = "soun"
        fake.AVCaptureDevice.authorizationStatusForMediaType_.return_value = status
        return mock.patch.dict(sys.modules, {"AVFoundation": fake})

    def test_each_status_maps_to_its_name(self):
        for value, name in [(0, "not_determined"), (1, "restricted"), (2, "denied"), (3, "authorized")]:
            with self._with_avfoundation(value):
                self.assertEqual(macos_permissions.microphone_authorization(), name)

    def test_an_unexpected_value_is_unknown(self):
        with self._with_avfoundation(99):
            self.assertEqual(macos_permissions.microphone_authorization(), "unknown")

    def test_a_missing_framework_is_unknown_not_an_error(self):
        # sys.modules[name] = None makes `import name` raise ImportError.
        with mock.patch.dict(sys.modules, {"AVFoundation": None}):
            self.assertEqual(macos_permissions.microphone_authorization(), "unknown")


class AccessibilityTrustedTest(unittest.TestCase):
    """AXIsProcessTrusted reads without prompting; unknown maps to None, never a raise."""

    def _with_appservices(self, trusted):
        fake = mock.Mock()
        fake.AXIsProcessTrusted.return_value = trusted
        return mock.patch.dict(sys.modules, {"ApplicationServices": fake})

    def test_trusted_is_true(self):
        with self._with_appservices(True):
            self.assertIs(macos_permissions.accessibility_trusted(), True)

    def test_untrusted_is_false(self):
        with self._with_appservices(False):
            self.assertIs(macos_permissions.accessibility_trusted(), False)

    def test_a_missing_framework_is_none_not_an_error(self):
        with mock.patch.dict(sys.modules, {"ApplicationServices": None, "HIServices": None}):
            self.assertIsNone(macos_permissions.accessibility_trusted())


class PromptAccessibilityTest(unittest.TestCase):
    """The active grant flow — it prompts, unlike the passive read. Mocked; the
    real dialog only shows on a Mac (M8)."""

    def _with_prompt(self, trusted):
        fake = mock.Mock()
        fake.kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
        fake.AXIsProcessTrustedWithOptions.return_value = trusted
        return fake, mock.patch.dict(sys.modules, {"ApplicationServices": fake})

    def test_it_passes_the_prompt_option_and_returns_the_state(self):
        fake, patch = self._with_prompt(True)
        with patch:
            self.assertIs(macos_permissions.prompt_accessibility(), True)
        options = fake.AXIsProcessTrustedWithOptions.call_args.args[0]
        self.assertEqual(options, {"AXTrustedCheckOptionPrompt": True})

    def test_a_denied_prompt_returns_false(self):
        _fake, patch = self._with_prompt(False)
        with patch:
            self.assertIs(macos_permissions.prompt_accessibility(), False)

    def test_a_missing_framework_is_none(self):
        with mock.patch.dict(sys.modules, {"ApplicationServices": None, "HIServices": None}):
            self.assertIsNone(macos_permissions.prompt_accessibility())


class OpenAccessibilitySettingsTest(unittest.TestCase):
    def test_it_opens_the_accessibility_pane(self):
        with mock.patch.object(macos_permissions.subprocess, "run") as run:
            self.assertTrue(macos_permissions.open_accessibility_settings())
        self.assertEqual(run.call_args.args[0], ["open", macos_permissions._ACCESSIBILITY_PANE])

    def test_a_failure_to_open_is_false_not_a_raise(self):
        with mock.patch.object(macos_permissions.subprocess, "run", side_effect=OSError):
            self.assertFalse(macos_permissions.open_accessibility_settings())


class RequestMicrophoneAccessTest(unittest.TestCase):
    """The prompt PortAudio never triggers.

    Measured on Big Sur (M8): opening an input stream while the status is
    "not_determined" records silence without asking anything. AVFoundation is
    what asks, and the answer has to be waited for — returning early would
    capture the very silence this call prevents.
    """

    def _with_avfoundation(self, before, after, *, answers=True):
        """A fake AVFoundation whose status flips once the completion handler runs."""
        statuses = iter([before] + [after] * 20)
        fake = mock.Mock()
        fake.AVMediaTypeAudio = "soun"
        fake.AVCaptureDevice.authorizationStatusForMediaType_.side_effect = lambda _: next(statuses)

        def request(_media, completion):
            if answers:
                completion(True)

        fake.AVCaptureDevice.requestAccessForMediaType_completionHandler_.side_effect = request
        return fake, mock.patch.dict(sys.modules, {"AVFoundation": fake})

    def test_an_undetermined_status_prompts_and_returns_the_answer(self):
        fake, patched = self._with_avfoundation(0, 3)  # not_determined → authorized
        with patched:
            self.assertEqual(macos_permissions.request_microphone_access(), "authorized")
        fake.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_called_once()

    def test_a_refusal_comes_back_as_denied(self):
        fake, patched = self._with_avfoundation(0, 2)  # not_determined → denied
        with patched:
            self.assertEqual(macos_permissions.request_microphone_access(), "denied")

    def test_an_already_settled_status_never_prompts(self):
        # macOS shows the dialog once; asking again would only add a pointless wait.
        for status, name in [(3, "authorized"), (2, "denied"), (1, "restricted")]:
            fake, patched = self._with_avfoundation(status, status)
            with patched:
                self.assertEqual(macos_permissions.request_microphone_access(), name)
            fake.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()

    def test_an_unanswered_dialog_gives_up_on_the_timeout(self):
        # The user walked away: bounded wait, then report what we know.
        fake, patched = self._with_avfoundation(0, 0, answers=False)
        with patched:
            self.assertEqual(
                macos_permissions.request_microphone_access(timeout=0.01), "not_determined"
            )

    def test_a_missing_framework_degrades_instead_of_raising(self):
        with mock.patch.dict(sys.modules, {"AVFoundation": None}):
            self.assertEqual(macos_permissions.request_microphone_access(), "unknown")


class GuideAccessibilityOnceTest(unittest.TestCase):
    """Prompt + open Settings, but at most once per process — a user who declines
    on purpose must not be nagged on every failed insertion."""

    def setUp(self):
        # Reset the module-level anti-spam flag so tests don't leak into each other.
        macos_permissions._guided_this_process = False
        self.addCleanup(setattr, macos_permissions, "_guided_this_process", False)

    def test_it_prompts_and_opens_settings_the_first_time_only(self):
        with mock.patch.object(macos_permissions, "prompt_accessibility") as prompt:
            with mock.patch.object(macos_permissions, "open_accessibility_settings") as open_settings:
                macos_permissions.guide_accessibility_once()
                macos_permissions.guide_accessibility_once()
        prompt.assert_called_once()
        open_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
