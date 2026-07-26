"""M6a — what the macOS menu bar shows, decided without AppKit.

No rumps, no NSStatusItem: this file locks the pure half of the tray — the two
languages, the elapsed-time format, and the mapping from a controller snapshot plus
the shortcut's registration state onto icon, title and menu lines. The native
binding is exercised (with a fake rumps) in test_macos_runloop.
"""

import unittest
from unittest import mock

from aparte import macos_tray
from aparte.macos_hotkey import HotkeyState
from aparte.macos_recording import ERROR, IDLE, PROCESSING, RECORDING
from aparte.macos_tray import ICON_IDLE, ICON_RECORDING, format_elapsed, labels, tray_view

REGISTERED = HotkeyState(registered=True, configured_key="ctrl+opt+d")


def view(state, elapsed=None, hotkey=REGISTERED, texts=None):
    return tray_view((state, elapsed), hotkey, texts or macos_tray.LABELS["fr"])


class ElapsedFormatTest(unittest.TestCase):
    def test_it_reads_like_a_stopwatch(self):
        self.assertEqual(format_elapsed(0), "0:00")
        self.assertEqual(format_elapsed(7), "0:07")
        self.assertEqual(format_elapsed(59.9), "0:59")   # truncated, never rounded up
        self.assertEqual(format_elapsed(60), "1:00")
        self.assertEqual(format_elapsed(3599), "59:59")

    def test_past_the_hour_it_grows_a_field(self):
        self.assertEqual(format_elapsed(3600), "1:00:00")
        self.assertEqual(format_elapsed(3661), "1:01:01")

    def test_a_negative_clock_reads_zero_rather_than_raising(self):
        # A clock that went backwards must never make the menu bar throw.
        self.assertEqual(format_elapsed(-2), "0:00")


class IconAndTitleTest(unittest.TestCase):
    def test_only_recording_changes_the_icon(self):
        self.assertEqual(view(IDLE).icon, ICON_IDLE)
        self.assertEqual(view(RECORDING, 3).icon, ICON_RECORDING)
        self.assertEqual(view(PROCESSING).icon, ICON_IDLE)
        self.assertEqual(view(ERROR).icon, ICON_IDLE)

    def test_the_timer_shows_only_while_the_microphone_is_open(self):
        self.assertEqual(view(RECORDING, 7).title, "0:07")
        self.assertEqual(view(IDLE).title, "")
        self.assertEqual(view(ERROR).title, "")

    def test_transcribing_says_so_without_claiming_the_mic_is_open(self):
        self.assertEqual(view(PROCESSING).title, "…")

    def test_a_duration_lost_to_a_transition_keeps_the_recording_icon(self):
        # The lock-free read can catch a transition between its two fields. The state
        # is what matters — the icon stays right, the timer joins one tick later.
        transient = view(RECORDING, None)
        self.assertEqual(transient.icon, ICON_RECORDING)
        self.assertEqual(transient.title, "")


class StatusLineTest(unittest.TestCase):
    def test_each_state_has_its_own_sentence(self):
        self.assertEqual(view(IDLE).status, "Prêt à dicter")
        self.assertEqual(view(RECORDING, 1).status, "Micro ouvert")
        self.assertEqual(view(PROCESSING).status, "Transcription en cours…")
        self.assertEqual(view(ERROR).status, "La dernière dictée a échoué")

    def test_an_unknown_state_falls_back_instead_of_crashing_the_menu(self):
        self.assertEqual(view("something-new").status, "Prêt à dicter")

    def test_english_says_the_same_things(self):
        english = macos_tray.LABELS["en"]
        self.assertEqual(view(RECORDING, 1, texts=english).status, "Microphone open")
        self.assertEqual(view(PROCESSING, texts=english).status, "Transcribing…")


class ShortcutLineTest(unittest.TestCase):
    def test_a_live_registration_shows_the_combination(self):
        self.assertEqual(view(IDLE).shortcut, "Raccourci : ⌃⌥D")

    def test_no_shortcut_configured_names_the_command_that_creates_one(self):
        line = view(IDLE, hotkey=HotkeyState(configured_key=None)).shortcut
        self.assertEqual(line, "Aucun raccourci — aparte install-hotkey")

    def test_a_refused_combination_is_not_reported_as_working(self):
        # "configured" is a half-truth once Carbon has refused: registered is the
        # only honest source, and this is exactly when the user needs to be told.
        refused = HotkeyState(configured_key="ctrl+opt+d", status=-9878, error="taken")
        self.assertEqual(view(IDLE, hotkey=refused).shortcut, "Raccourci indisponible : ⌃⌥D")

    def test_an_unparseable_combo_from_a_hand_edited_config_still_draws(self):
        broken = HotkeyState(registered=True, configured_key="ctrl+nope")
        self.assertEqual(view(IDLE, hotkey=broken).shortcut, "Raccourci : ctrl+nope")

    def test_no_published_state_reads_as_no_shortcut(self):
        self.assertEqual(view(IDLE, hotkey=None).shortcut, "Aucun raccourci — aparte install-hotkey")

    def test_english_shortcut_lines(self):
        english = macos_tray.LABELS["en"]
        self.assertEqual(view(IDLE, texts=english).shortcut, "Shortcut: ⌃⌥D")
        self.assertEqual(
            view(IDLE, hotkey=HotkeyState(configured_key=None), texts=english).shortcut,
            "No shortcut — aparte install-hotkey",
        )


class LanguageTest(unittest.TestCase):
    def test_the_menu_follows_the_desktop_language(self):
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "fr_CA.UTF-8"}):
            self.assertEqual(labels()["quit"], "Quitter")
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "en_US.UTF-8"}):
            self.assertEqual(labels()["quit"], "Quit")

    def test_no_language_at_all_falls_back_to_english(self):
        with mock.patch.dict("os.environ", {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
            self.assertEqual(labels()["quit"], "Quit")

    def test_both_languages_carry_exactly_the_same_keys(self):
        # A label added on one side only is a menu item that reads in the wrong
        # language, or a KeyError while drawing the menu.
        self.assertEqual(set(macos_tray.LABELS["fr"]), set(macos_tray.LABELS["en"]))


if __name__ == "__main__":
    unittest.main()
