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


class FakeMenuItem:
    def __init__(self, title="", callback=None):
        self.title = title
        self.callback = callback


class FakeTimer:
    def __init__(self, callback, interval):
        self.callback = callback
        self.interval = interval
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def fire(self):
        self.callback(self)


class FakeApp:
    def __init__(self, name, title=None, icon=None, template=None, quit_button="Quit"):
        self.name = name
        self.title = title
        self.icon = icon
        self.template = template
        self.quit_button = quit_button
        self.menu = []
        self.ran = False
        self.on_run = None

    def run(self):
        self.ran = True
        if self.on_run is not None:
            self.on_run(self)


class FakeRumps:
    """Just enough rumps to prove the binding, with no AppKit anywhere."""

    separator = "---"

    def __init__(self, events=None):
        self.apps: list[FakeApp] = []
        self.timers: list[FakeTimer] = []
        self.quit_calls = 0
        if events is not None:
            self.events = events

    def App(self, *args, **kwargs):
        app = FakeApp(*args, **kwargs)
        self.apps.append(app)
        return app

    def MenuItem(self, title="", callback=None):
        return FakeMenuItem(title, callback)

    def Timer(self, callback, interval):
        timer = FakeTimer(callback, interval)
        self.timers.append(timer)
        return timer

    def quit_application(self, *_):
        self.quit_calls += 1


class FakeController:
    def __init__(self, snapshots=None):
        self.snapshots = list(snapshots or [(IDLE, None)])

    def recording_snapshot(self):
        return self.snapshots[0] if len(self.snapshots) == 1 else self.snapshots.pop(0)


def build(rumps, controller=None, hotkey=REGISTERED, url="http://127.0.0.1:8765"):
    settings = mock.Mock(history_persist=False)
    return macos_tray.MacTray(rumps, url, settings, controller or FakeController(), lambda: hotkey)


class TrayBindingTest(unittest.TestCase):
    """Base for the rumps-binding tests: AppKit does not exist on this machine, so
    the one native call (hiding the Dock icon) is stubbed rather than left to fail
    loudly into the suite's output."""

    def setUp(self):
        mock.patch.object(macos_tray, "_set_accessory_policy").start()
        self.addCleanup(mock.patch.stopall)


class MenuStructureTest(TrayBindingTest):
    def test_rumps_own_quit_item_is_disabled(self):
        # Not cosmetic: rumps' built-in Quit calls quit_application() directly, which
        # goes through terminate_ and never comes back — a visible way out that would
        # skip the ordered teardown entirely.
        rumps = FakeRumps()
        build(rumps)
        self.assertIsNone(rumps.apps[0].quit_button)

    def test_the_only_quit_in_the_menu_tears_down_before_terminating(self):
        rumps = FakeRumps()
        tray = build(rumps)
        order = []
        tray.run_loop(lambda: None, lambda: order.append("teardown"))
        quits = [i for i in rumps.apps[0].menu if isinstance(i, FakeMenuItem) and i.title == "Quitter"]
        self.assertEqual(len(quits), 1)
        quits[0].callback(None)
        self.assertEqual(order, ["teardown"])
        self.assertEqual(rumps.quit_calls, 1)

    def test_the_two_state_lines_are_not_clickable(self):
        rumps = FakeRumps()
        build(rumps)
        status, shortcut = rumps.apps[0].menu[0], rumps.apps[0].menu[1]
        self.assertIsNone(status.callback)      # no callback → macOS greys it out
        self.assertIsNone(shortcut.callback)

    def test_the_icon_starts_as_a_template_image(self):
        rumps = FakeRumps()
        build(rumps)
        self.assertTrue(rumps.apps[0].template)
        self.assertTrue(rumps.apps[0].icon.endswith(ICON_IDLE))


class ReadyHookTest(TrayBindingTest):
    def test_on_ready_fires_from_the_timer_not_before_the_loop(self):
        # RegisterEventHotKey needs a live NSApplication: registering before run()
        # would attach the shortcut to nothing.
        rumps = FakeRumps()
        tray = build(rumps)
        fired = []
        rumps.apps[0].on_run = lambda app: rumps.timers[0].fire()
        tray.run_loop(lambda: fired.append("ready"))
        self.assertEqual(fired, ["ready"])

    def test_the_ready_timer_is_a_hand_made_one_shot(self):
        # rumps.Timer repeats by construction; a second tick must not re-register.
        rumps = FakeRumps()
        tray = build(rumps)
        fired = []
        tray.run_loop(lambda: fired.append("ready"))
        ready = rumps.timers[0]
        ready.fire()
        ready.fire()
        self.assertEqual(fired, ["ready"])
        self.assertTrue(ready.stopped)

    def test_a_raising_ready_hook_does_not_take_the_menu_bar_down(self):
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        rumps.timers[0].fire()      # must not propagate out of the timer callback

    def test_close_stops_both_timers(self):
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        tray.close()
        self.assertTrue(all(timer.stopped for timer in rumps.timers))
        tray.close()   # idempotent: the teardown may run twice


class BeforeQuitHookTest(TrayBindingTest):
    def test_the_hook_is_used_when_the_installed_rumps_has_one(self):
        registered = []
        events = mock.Mock(before_quit=mock.Mock(register=registered.append))
        rumps = FakeRumps(events=events)
        tray = build(rumps)
        order = []
        tray.run_loop(lambda: None, lambda: order.append("teardown"))
        self.assertEqual(len(registered), 1)
        registered[0]()                      # macOS terminating by another path
        self.assertEqual(order, ["teardown"])

    def test_a_rumps_without_events_still_runs(self):
        # Duck-typed on purpose: not every release has rumps.events, and an
        # AttributeError at startup would cost the whole tray.
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        self.assertTrue(rumps.apps[0].ran)


class RefreshTest(TrayBindingTest):
    def test_the_menu_bar_follows_the_recorder(self):
        rumps = FakeRumps()
        controller = FakeController([(IDLE, None), (RECORDING, 7.0)])
        tray = build(rumps, controller)
        app = rumps.apps[0]
        self.assertEqual(app.title, "")
        tray.refresh()
        self.assertEqual(app.title, "0:07")
        self.assertTrue(app.icon.endswith(ICON_RECORDING))
        self.assertEqual(app.menu[0].title, "Micro ouvert")

    def test_an_unchanged_state_does_not_rewrite_the_icon(self):
        # The icon is rebuilt from disk on every assignment; at four ticks a second
        # that would be pure churn.
        rumps = FakeRumps()
        tray = build(rumps, FakeController([(IDLE, None)]))
        app = rumps.apps[0]
        app.icon = "sentinel"
        tray.refresh()
        self.assertEqual(app.icon, "sentinel")

    def test_a_refresh_failure_never_kills_the_timer(self):
        # A frozen icon showing a stale state is worse than one bad pixel.
        rumps = FakeRumps()
        tray = build(rumps)
        tray.run_loop(lambda: None, lambda: None)
        with mock.patch.object(tray, "refresh", side_effect=RuntimeError("boom")):
            rumps.timers[1].fire()


class BuildTrayTest(unittest.TestCase):
    def setUp(self):
        self.notify = mock.patch.object(macos_tray, "notify").start()
        self.addCleanup(mock.patch.stopall)

    def _build(self):
        return macos_tray.build_tray("http://x", mock.Mock(history_persist=False), FakeController(), lambda: None)

    def test_a_missing_rumps_falls_back_in_silence(self):
        # An install without the [macos] extra is a choice, not a bug: doctor says
        # how to get the icon back, and the server runs exactly as before.
        with mock.patch.object(macos_tray, "_rumps", side_effect=ImportError("no rumps")):
            self.assertIsNone(self._build())
        self.notify.assert_not_called()

    def test_an_unexpected_failure_is_loud(self):
        # M6 exists to close M8's main usability defect. A silently missing icon
        # would quietly recreate the very bug it fixes.
        with mock.patch.object(macos_tray, "_rumps", return_value=FakeRumps()), \
             mock.patch.object(macos_tray, "MacTray", side_effect=RuntimeError("no status bar")):
            self.assertIsNone(self._build())
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs.get("urgency"), "critical")


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
