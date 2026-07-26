"""macOS menu-bar icon (M6) — what it shows, decided in pure Python.

On Mac nothing else tells the user the microphone is open: no window, and an
``accessory`` application draws nothing. During the M8 native validation the tester
pressed the shortcut, got no feedback, believed nothing had happened, pressed again
— and stopped the recording the first press had just started. The code was correct;
the silence was the defect. This module is the fix.

It is split so that everything decidable is decided **here**, without AppKit: the
labels (French and English), the elapsed-time format, and :func:`tray_view`, which
maps a controller snapshot plus the shortcut's registration state onto what the menu
bar should display. The thin ``rumps`` binding that puts it on screen lives further
down and is the only native part.

The state line, the icon and the timer are three separate signals, on purpose: the
recording state must be readable without colour (DESIGN.md, "la règle du daltonien"),
and the icons are **template** images — macOS tints them itself, black on a light
menu bar, white on a dark one. No fixed colour would do: the menu bar is translucent
over the user's wallpaper, so nothing there can be contrast-checked by calculation,
which is what DESIGN.md requires of every colour.
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from . import history
from .clipboard import copy_text
from .macos_hotkey import safe_hotkey_label
from .macos_recording import ERROR, IDLE, PROCESSING, RECORDING
from .notify import notify

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Template PNGs: black plus alpha, tinted by macOS. Shapes taken from the brand mark
# — the three bars at rest, a filled disc while recording — so the silhouette alone
# carries the state.
ICON_IDLE = "aparte-menubar.png"
ICON_RECORDING = "aparte-menubar-recording.png"

# The tray polls the controller this often. Fast, and deliberately **not** slowed
# down while idle: the latency that matters is idle → recording, the one that made
# the M8 tester doubt his own press, and it is governed by the tick running while
# idle. The cost is two attribute reads and a string compare, four times a second.
POLL_SECONDS = 0.25

# Shown next to the icon while transcribing. Not a spinner and not a lie about the
# microphone still being open — just a third, non-chromatic state.
PROCESSING_TITLE = "…"


LABELS = {
    "fr": {
        "idle": "Prêt à dicter",
        "recording": "Micro ouvert",
        "processing": "Transcription en cours…",
        "error": "La dernière dictée a échoué",
        "shortcut": "Raccourci : {key}",
        "shortcut_none": "Aucun raccourci — aparte install-hotkey",
        "shortcut_failed": "Raccourci indisponible : {key}",
        "open": "Ouvrir Aparté",
        "copy": "Copier la dernière dictée",
        "settings": "Réglages",
        "quit": "Quitter",
    },
    "en": {
        "idle": "Ready to dictate",
        "recording": "Microphone open",
        "processing": "Transcribing…",
        "error": "The last dictation failed",
        "shortcut": "Shortcut: {key}",
        "shortcut_none": "No shortcut — aparte install-hotkey",
        "shortcut_failed": "Shortcut unavailable: {key}",
        "open": "Open Aparté",
        "copy": "Copy the last dictation",
        "settings": "Settings",
        "quit": "Quit",
    },
}


def labels() -> dict[str, str]:
    # A menu-bar menu belongs to the desktop, so it follows the desktop's language
    # rather than the browser's or the dictation setting — same rule as the GTK tray.
    language = os.getenv("LC_ALL") or os.getenv("LC_MESSAGES") or os.getenv("LANG") or ""
    return LABELS["fr"] if language.lower().startswith("fr") else LABELS["en"]


def format_elapsed(seconds: float) -> str:
    """Seconds as ``m:ss``, or ``h:mm:ss`` past the hour."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}:{secs:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class TrayView:
    """Everything the menu bar shows, for one poll tick."""

    icon: str
    title: str
    status: str
    shortcut: str


def _shortcut_line(hotkey_state, texts: dict[str, str]) -> str:
    """What the menu says about the global shortcut.

    Reads the **real registration**, not the configured value: saying "configured"
    would be a half-truth the day Carbon refuses the combination, and that day is
    exactly when the user needs to be told. ``None`` — no state published yet —
    reads as "no shortcut", which is what an unconfigured install has.

    The label always goes through ``safe_hotkey_label``: a hand-edited config can
    hold an unparseable combo, and a menu must never fail to draw because of it.
    """
    if hotkey_state is None or not hotkey_state.configured_key:
        return texts["shortcut_none"]
    key = safe_hotkey_label(hotkey_state.configured_key)
    template = "shortcut" if hotkey_state.registered else "shortcut_failed"
    return texts[template].format(key=key)


def tray_view(snapshot: tuple[str, float | None], hotkey_state, texts: dict[str, str]) -> TrayView:
    """Map one controller snapshot onto the icon, the title and the two menu lines.

    ``snapshot`` is taken whole — ``RecordingController.recording_snapshot()`` — and
    never re-read field by field, so the state and the duration always describe the
    same instant.
    """
    state, elapsed = snapshot
    icon = ICON_RECORDING if state == RECORDING else ICON_IDLE
    if state == RECORDING:
        # A transition landing between the two lock-free reads leaves the duration
        # unknown; the icon still says recording, and the timer joins a tick later.
        title = "" if elapsed is None else format_elapsed(elapsed)
    elif state == PROCESSING:
        title = PROCESSING_TITLE
    else:
        title = ""
    status = texts[state if state in (IDLE, RECORDING, PROCESSING, ERROR) else IDLE]
    return TrayView(icon=icon, title=title, status=status, shortcut=_shortcut_line(hotkey_state, texts))


# -- The rumps binding (native, macOS only) ---------------------------------------

# Delay before the one-shot timer that fires on_ready. Small: the global shortcut is
# registered from there, and nothing can trigger a dictation until it is.
READY_DELAY_SECONDS = 0.05


def _rumps():
    """Import rumps, lazily. Absent off macOS, and absent without the [macos] extra."""
    import rumps

    return rumps


def _set_accessory_policy() -> None:
    """No Dock icon, no application menu — Aparté lives in the menu bar.

    rumps does not set the policy itself (it expects a bundle with LSUIElement, which
    only arrives in M7), so a plain `python -m aparte` run would otherwise grow a Dock
    icon. Native; a failure here is cosmetic and must never cost the tray.
    """
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def build_tray(url, settings, controller, hotkey_state) -> "MacTray | None":
    """The menu-bar icon, or None when it cannot exist.

    Two failure modes, deliberately treated differently. A **missing dependency** is
    an installation choice — silent fallback, and `aparte doctor` says how to get the
    icon. Anything **unexpected** is loud: M6 exists to close M8's main usability
    defect (nothing on screen says the microphone is open), so a swallowed exception
    here would quietly recreate the very bug it fixes.
    """
    try:
        rumps = _rumps()
    except Exception:
        return None
    try:
        return MacTray(rumps, url, settings, controller, hotkey_state)
    except Exception as exc:
        print(f"aparte: could not build the menu-bar icon: {exc}", file=sys.stderr)
        try:
            notify(
                "⚠️ Pas d'icône de barre de menus",
                f"{exc} Rien n'indiquera que le micro est ouvert.",
                urgency="critical",
            )
        except Exception:
            pass
        return None


class MacTray:
    """The menu-bar icon: it **observes** the recorder, it never drives it.

    Owning the run loop. ``rumps.App.run()`` calls ``AppHelper.runEventLoop()`` — the
    very thing :func:`aparte.macos_runloop._appkit_run_loop` calls — and there is only
    one main thread. So when a tray exists, rumps runs the loop and this class
    provides :meth:`run_loop` as a drop-in for the M5 runner. ``serve_macos`` keeps
    everything else: the shortcut, the published state, the ordered teardown.

    Two hooks matter and both are handed in by ``serve_macos``:

    - ``on_ready`` — fired from a one-shot timer once the loop is live, because
      ``RegisterEventHotKey`` needs a running ``NSApplication`` to attach to;
    - ``on_quit`` — the ordered, idempotent teardown, called by the "Quit" item
      **before** terminating. ``rumps.quit_application()`` goes through
      ``NSApplication.terminate_``, which never returns from ``run()``: without this,
      the normal way out would skip the teardown entirely.
    """

    def __init__(self, rumps, url, settings, controller, hotkey_state) -> None:
        self._rumps = rumps
        self._url = url
        self._settings = settings
        self._controller = controller
        self._hotkey_state = hotkey_state
        self._texts = labels()

        self._on_ready = None
        self._on_quit = None
        self._ready_fired = False
        self._ready_timer = None
        self._poll_timer = None
        self._view: TrayView | None = None

        # quit_button=None is not optional: rumps otherwise adds its own Quit item
        # wired straight to quit_application(), i.e. a visible way out that skips the
        # teardown. The only Quit in this menu is the one built below.
        self._app = rumps.App(
            "Aparté",
            title="",
            icon=str(ASSETS_DIR / ICON_IDLE),
            template=True,
            quit_button=None,
        )
        self._status_item = rumps.MenuItem("")
        self._shortcut_item = rumps.MenuItem("")
        # No callback → macOS greys the item out. These two lines are read, not clicked.
        self._app.menu = [
            self._status_item,
            self._shortcut_item,
            rumps.separator,
            rumps.MenuItem(self._texts["open"], callback=self._open),
            rumps.MenuItem(self._texts["copy"], callback=self._copy_last),
            rumps.MenuItem(self._texts["settings"], callback=self._open_settings),
            rumps.separator,
            rumps.MenuItem(self._texts["quit"], callback=self._quit),
        ]
        self.refresh()

    # -- The run loop -----------------------------------------------------------

    def run_loop(self, on_ready, on_quit=None) -> None:
        """Run the AppKit loop through rumps. Blocks until the app terminates."""
        self._on_ready = on_ready
        self._on_quit = on_quit
        try:
            _set_accessory_policy()
        except Exception as exc:  # a Dock icon is ugly, never fatal
            print(f"aparte: could not hide the Dock icon: {exc}", file=sys.stderr)
        # SIGINT is left alone here, unlike the plain runner: rumps installs its own
        # Mach interrupt inside run(), so anything set before would be overwritten.
        self._ready_timer = self._rumps.Timer(self._fire_ready, READY_DELAY_SECONDS)
        self._ready_timer.start()
        self._poll_timer = self._rumps.Timer(self._tick, POLL_SECONDS)
        self._poll_timer.start()
        self._hook_before_quit()
        self._app.run()

    def _fire_ready(self, _timer=None) -> None:
        # rumps.Timer repeats by construction, so the one-shot is made by hand: stop
        # first, and latch, so a raising on_ready cannot be run twice.
        if self._ready_fired:
            return
        self._ready_fired = True
        self._stop_timer(self._ready_timer)
        try:
            if self._on_ready is not None:
                self._on_ready()
        except Exception as exc:
            # serve_macos already handles a refused shortcut; this catches the rest,
            # so an unexpected failure costs the shortcut, not the whole menu bar.
            print(f"aparte: startup hook failed: {exc}", file=sys.stderr)

    def _hook_before_quit(self) -> None:
        """Second net: tear down on applicationWillTerminate_ too, if rumps has it.

        Duck-typed on purpose — `rumps.events` does not exist in every release, and an
        AttributeError at startup would cost the whole tray. The Quit item stays the
        primary path; this only catches the ways out that bypass it.
        """
        register = getattr(getattr(getattr(self._rumps, "events", None), "before_quit", None), "register", None)
        if register is None:
            return
        try:
            register(lambda *_: self._quit_hook())
        except Exception:
            pass

    def _quit_hook(self) -> None:
        if self._on_quit is not None:
            self._on_quit()

    def close(self) -> None:
        """Stop the timers. First step of the teardown, and safe to repeat."""
        self._stop_timer(self._ready_timer)
        self._stop_timer(self._poll_timer)
        self._ready_timer = None
        self._poll_timer = None

    @staticmethod
    def _stop_timer(timer) -> None:
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    # -- What it shows ----------------------------------------------------------

    def _tick(self, _timer=None) -> None:
        try:
            self.refresh()
        except Exception as exc:
            # A drawing failure must not kill the timer: it would freeze the icon on
            # a stale state, which is worse than the wrong pixel.
            print(f"aparte: could not refresh the menu bar: {exc}", file=sys.stderr)

    def refresh(self) -> None:
        """Read one snapshot and push what changed. Called four times a second."""
        view = tray_view(self._controller.recording_snapshot(), self._hotkey_state(), self._texts)
        previous, self._view = self._view, view
        if previous is None or view.icon != previous.icon:
            self._app.icon = str(ASSETS_DIR / view.icon)
        if previous is None or view.title != previous.title:
            self._app.title = view.title
        if previous is None or view.status != previous.status:
            self._status_item.title = view.status
        if previous is None or view.shortcut != previous.shortcut:
            self._shortcut_item.title = view.shortcut

    # -- Menu actions -----------------------------------------------------------

    def _open(self, _=None) -> None:
        webbrowser.open(self._url)

    def _open_settings(self, _=None) -> None:
        webbrowser.open(f"{self._url}/#settings")

    def _copy_last(self, _=None) -> None:
        text = history.last(self._settings.history_persist)
        if text:
            # Off the UI thread: copying shells out, and a slow clipboard tool would
            # otherwise freeze the whole menu.
            threading.Thread(target=copy_text, args=(text,), daemon=True).start()

    def _quit(self, _=None) -> None:
        # Teardown first, terminate second: terminate_ never comes back.
        self._quit_hook()
        self._rumps.quit_application()
