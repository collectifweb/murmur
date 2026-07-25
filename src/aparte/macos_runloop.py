"""macOS run loop + global-shortcut lifecycle for the resident server (M5b).

``RegisterEventHotKey`` only delivers events while a live AppKit run loop pumps
them, and that run loop must own the main thread. So on macOS the HTTP server
moves to a daemon thread (exactly as it does under the GTK tray on Linux) and
this module runs the AppKit loop on the main thread, owning the whole shortcut
lifecycle:

    NSApplication ready → register hotkey → run loop (blocks) → ordered teardown

Two seams keep it testable on the Linux dev machine, where no run loop exists:

- ``run_loop(on_ready)`` — the real one is the injected default; a test passes a
  fake that fires ``on_ready`` (the moment registration must happen) then returns.
- ``register`` — the real Carbon façade by default; a fake in tests.

The native AppKit/Carbon imports live inside :func:`_appkit_run_loop`, reached
only on a real Mac; the module itself stays importable everywhere.
"""

from __future__ import annotations

import sys
import threading
import time

from .macos_hotkey import (
    HotkeyDispatcher,
    HotkeyError,
    HotkeyState,
    register_hotkey,
    safe_hotkey_label,
)
from .notify import notify


def serve_macos(server, controller, settings, *, register=register_hotkey, run_loop=None) -> None:
    """Serve on a daemon thread; own the shortcut and the AppKit loop on the main one.

    Blocks until the app quits, then tears down in a fixed order. ``register`` and
    ``run_loop`` are injected in tests so no native code runs off macOS.
    """
    if run_loop is None:
        run_loop = _appkit_run_loop

    spec = getattr(settings, "hotkey", "") or ""
    # The dispatcher filters repeats at arrival and calls toggle() on its own
    # worker, so the Carbon callback never blocks the run loop (see macos_hotkey).
    dispatcher = HotkeyDispatcher(controller.toggle)

    # doctor and the read-only /api/hotkey-state route read the shortcut's state
    # from the handler class. Publish an initial snapshot before serving, so a
    # request landing before on_ready() sees "configured, not yet registered"
    # rather than nothing. The server keeps the handler class here.
    handler_cls = server.RequestHandlerClass
    handler_cls.hotkey_state = HotkeyState(configured_key=spec or None)

    threading.Thread(target=server.serve_forever, daemon=True).start()

    handle: object | None = None

    def on_ready() -> None:
        # Fired once the run loop is live (NSApplication exists) — the hotkey must
        # be registered here, not before, or Carbon has no target to attach to.
        nonlocal handle
        if not spec:
            # No shortcut configured — run `aparte install-hotkey` to set one. The
            # server still serves the web UI and browser dictation; doctor points
            # the user at install-hotkey.
            handler_cls.hotkey_state = HotkeyState(configured_key=None)
            return
        try:
            handle = register(spec, dispatcher.trigger)
        except HotkeyError as exc:
            # The server keeps serving the web UI and browser dictation; only the
            # global shortcut is dead. Make it observable (the state below, doctor,
            # a startup notification) instead of crashing or failing in silence.
            handler_cls.hotkey_state = HotkeyState(
                configured_key=spec, status=exc.status, error=str(exc)
            )
            _notify_register_failure(spec, exc)
        else:
            handler_cls.hotkey_state = HotkeyState(registered=True, configured_key=spec)

    try:
        run_loop(on_ready)
    except KeyboardInterrupt:
        print("\nStopping desktop server.")
    finally:
        # Ordered teardown. Drop the hotkey first so no trigger arrives mid-shutdown;
        # drain the dispatcher (bounded join of any in-flight toggle) before the
        # controller discards a live recording; the server goes last.
        if handle is not None:
            handle.unregister()
        dispatcher.close()
        controller.shutdown()
        server.shutdown()
        server.server_close()


def _notify_register_failure(spec: str, exc: HotkeyError) -> None:
    # The shortcut is the primary macOS trigger, so a refused registration must not
    # fail silently. stderr is swallowed by launchd for a login-item server, so the
    # notification is the real feedback at startup; doctor and /api/hotkey-state
    # carry the durable, scriptable version.
    print(f"aparte: could not register the shortcut {spec!r}: {exc}", file=sys.stderr)
    try:
        notify(
            "⚠️ Raccourci indisponible",
            f"macOS a refusé {safe_hotkey_label(spec)}. Choisis-en un autre : aparte install-hotkey.",
            urgency="critical",
        )
    except Exception:
        pass


def run_hotkey_diagnostic(
    spec: str,
    *,
    register=register_hotkey,
    run_loop=None,
    clock=time.monotonic,
    emit=print,
) -> int:
    """M8 native check: register ``spec`` live and log each RAW Carbon event.

    This is the manual-smoke tool (``aparte install-hotkey --diagnostic``). It
    deliberately bypasses :class:`HotkeyDispatcher` and wires ``on_trigger``
    straight to the backend, so the count reflects **what the OS actually
    delivers** — its whole purpose is to answer the question the Linux tests
    can't: does one physical press yield exactly one ``kEventHotKeyPressed``, or
    does macOS repeat/duplicate it? The inter-press delta printed alongside lets
    you eyeball a double-tap against the 250 ms debounce window. It also prints
    the real ``OSStatus`` — the other M8 unknown (is ⌃⌥D free on this machine).

    ``register``/``run_loop`` are injected in tests; on a Mac the defaults drive
    the real Carbon registration on a live AppKit loop. Returns the press count."""
    if run_loop is None:
        run_loop = _appkit_run_loop

    seen = {"count": 0, "last": None}

    def on_trigger() -> None:
        seen["count"] += 1
        now = clock()
        gap = "" if seen["last"] is None else f"  (+{now - seen['last']:.3f}s since last)"
        seen["last"] = now
        emit(f"press #{seen['count']} received{gap}")

    handle: object | None = None

    def on_ready() -> None:
        nonlocal handle
        try:
            handle = register(spec, on_trigger)
        except HotkeyError as exc:
            where = "" if exc.status is None else f" (OSStatus {exc.status})"
            emit(f"registration refused{where}: {exc}")
            return
        emit(f"registered {safe_hotkey_label(spec)} ({spec}) — press it; Ctrl-C to stop")

    try:
        run_loop(on_ready)
    except KeyboardInterrupt:
        emit("\nstopping")
    finally:
        if handle is not None:
            handle.unregister()
    return seen["count"]


def _appkit_run_loop(on_ready) -> None:
    """Run the AppKit event loop on the main thread until the app quits.

    Native — imported lazily and confined here. Not covered by the Linux unit
    tests (which inject a fake run loop); validated by hand in the M8 smoke suite.
    """
    import signal

    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    # Accessory: a resident agent with no Dock icon and no menu bar — Aparté here
    # is a shortcut listener, not a window. (Dock presence is an M6 decision.)
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    # Register now that the run loop's application object exists.
    on_ready()
    # Restore the default SIGINT handler so Ctrl-C stops a foreground run, like the
    # GTK tray does (tray.py); AppHelper would otherwise swallow it.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    AppHelper.runEventLoop()
