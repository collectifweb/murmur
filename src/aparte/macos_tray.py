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
from dataclasses import dataclass
from pathlib import Path

from .macos_hotkey import safe_hotkey_label
from .macos_recording import ERROR, IDLE, PROCESSING, RECORDING

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
