"""Fetch the speech model at launch, and let the interface watch it happen.

The model (~500 MB) has always downloaded itself on the first transcription. The
problem was never the download, it was the silence: a fresh install pressed the
shortcut and waited minutes with nothing on screen, then got its dictation. On a
Mac, where the install is meant to be "open it, grant two permissions", that
silence reads as a broken application.

So Aparté fetches it **itself**, on a thread, as the server comes up, and
publishes what it knows. Two rules hold the design:

- **The application triggers, never an HTTP route.** Same reason as the recorder
  and the menu-bar icon on Darwin: a route that started a 500 MB download would
  be a system effect reachable from a browser. The interface only observes, over
  a read-only route.
- **Nothing is invented.** The progress is what the disk actually holds, not a
  callback the library does not promise. When the expected size is unknown the
  state says so instead of showing a percentage that means nothing.

The fact lives in this module's memory, local to the process that downloads —
like ``macos_tray._BUILD_OUTCOME``. A ``doctor`` running beside it sees nothing
here; it keeps reading ``model_ready`` off the cache, which is the persistent
truth.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from .config import Settings

# faster-whisper resolves a plain size to this organisation on the Hub. A name
# that already carries a slash is a repository id and passes through untouched.
_FASTER_WHISPER_REPO = "Systran/faster-whisper-{size}"

# The backends whose model comes from the Hub. "auto" belongs here: it tries
# faster-whisper first, which is what a default install ends up running.
_HUB_BACKENDS = frozenset({"auto", "faster-whisper"})

READY = "ready"
DOWNLOADING = "downloading"
ERROR = "error"
# We cannot fetch it ahead of time — another backend, a model given as a path, or
# no huggingface_hub. Not a failure: the first transcription downloads it the way
# it always has.
UNAVAILABLE = "unavailable"

_lock = threading.Lock()
_state: dict | None = None
_thread: threading.Thread | None = None


def repo_id(model: str) -> str | None:
    """The Hub repository a model name stands for, or None when there is nothing
    to fetch — an empty name, or a directory the user points at directly."""
    model = (model or "").strip()
    if not model:
        return None
    if Path(model).expanduser().exists():
        return None
    if "/" in model:
        return model
    return _FASTER_WHISPER_REPO.format(size=model)


def cache_root() -> Path:
    """Where huggingface_hub keeps its repositories. Read from the environment
    the same way the library does, so a user who moved their cache is followed."""
    hub = os.getenv("HF_HUB_CACHE")
    if hub:
        return Path(hub).expanduser()
    home = os.getenv("HF_HOME")
    if home:
        return Path(home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def repo_dir(repo: str) -> Path:
    return cache_root() / ("models--" + repo.replace("/", "--"))


def bytes_on_disk(repo: str) -> int:
    """What the cache already holds for this repository.

    Sum **every** blob, not only the ``.incomplete`` ones: huggingface_hub
    downloads into ``<sha>.incomplete`` and renames on completion, so counting
    only the incomplete files would make the progress fall back to nothing each
    time a file finished."""
    blobs = repo_dir(repo) / "blobs"
    try:
        return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
    except OSError:
        return 0


def expected_bytes(repo: str) -> int | None:
    """The repository's total size, asked of the Hub. None when it cannot be
    known — offline, an old huggingface_hub, a repository without file metadata.
    The caller must then show an honest indeterminate state."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return None
    try:
        info = HfApi().model_info(repo, files_metadata=True)
    except Exception:
        return None
    sizes = [getattr(s, "size", None) for s in getattr(info, "siblings", None) or []]
    known = [s for s in sizes if isinstance(s, int) and s > 0]
    return sum(known) or None


def _set(**fields) -> None:
    global _state
    with _lock:
        _state = {**(_state or {}), **fields}


def snapshot() -> dict | None:
    """What the interface may observe, or None when this process never started a
    download — the route 404s then, as the recorder and tray routes do."""
    with _lock:
        return dict(_state) if _state is not None else None


def _download(repo: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        _set(state=UNAVAILABLE, reason="huggingface_hub")
        return
    _set(state=DOWNLOADING, total_bytes=expected_bytes(repo))
    try:
        snapshot_download(repo)
    except Exception as exc:  # network, proxy, checksum, disk
        _set(state=ERROR, error=f"{type(exc).__name__}: {exc}")
        return
    _set(state=READY, downloaded_bytes=bytes_on_disk(repo))


def start(settings: Settings) -> None:
    """Begin fetching the model if it is missing. Returns at once; the download
    runs on a daemon thread so it can never hold up the shutdown. Calling twice
    does nothing the second time."""
    global _thread
    if settings.transcriber not in _HUB_BACKENDS:
        # openai-whisper and whisper.cpp keep their weights elsewhere; fetching a
        # faster-whisper repository for them would download 500 MB nobody uses.
        _set(state=UNAVAILABLE, reason="backend", model=settings.model)
        return
    repo = repo_id(settings.model)
    if repo is None:
        _set(state=UNAVAILABLE, reason="local-model", model=settings.model)
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
    if (repo_dir(repo) / "snapshots").is_dir():
        _set(state=READY, model=settings.model, repo=repo)
        return
    _set(state=DOWNLOADING, model=settings.model, repo=repo, total_bytes=None, error=None)
    thread = threading.Thread(target=_download, args=(repo,), daemon=True)
    with _lock:
        _thread = thread
    thread.start()


def progress() -> dict | None:
    """The state, with the byte count refreshed from disk. Read on each request
    rather than tracked as the download runs: the disk is the one place that
    cannot be wrong."""
    state = snapshot()
    if state is None:
        return None
    repo = state.get("repo")
    if repo and state.get("state") == DOWNLOADING:
        state["downloaded_bytes"] = bytes_on_disk(repo)
    return state


def reset_for_tests() -> None:
    global _state, _thread
    with _lock:
        _state = None
        _thread = None
