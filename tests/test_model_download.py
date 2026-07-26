import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aparte import model_download
from aparte.config import Settings


class RepoIdTest(unittest.TestCase):
    """What a model name stands for on the Hub, and when there is nothing to fetch."""

    def test_a_plain_size_becomes_the_faster_whisper_repository(self):
        self.assertEqual(model_download.repo_id("small"), "Systran/faster-whisper-small")

    def test_a_name_with_a_slash_is_already_a_repository(self):
        self.assertEqual(model_download.repo_id("openai/whisper-large-v3"), "openai/whisper-large-v3")

    def test_an_empty_name_asks_for_nothing(self):
        self.assertIsNone(model_download.repo_id(""))
        self.assertIsNone(model_download.repo_id("   "))

    def test_a_model_given_as_a_path_is_already_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(model_download.repo_id(directory))


class CacheRootTest(unittest.TestCase):
    """Follow the cache the user actually configured, the way the library reads it."""

    def _root(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            return model_download.cache_root()

    def test_hf_hub_cache_points_straight_at_the_repositories(self):
        self.assertEqual(
            self._root({"HF_HUB_CACHE": "/data/hub", "HF_HOME": "/data/hf"}), Path("/data/hub")
        )

    def test_hf_home_holds_them_under_hub(self):
        self.assertEqual(self._root({"HF_HUB_CACHE": "", "HF_HOME": "/data/hf"}), Path("/data/hf/hub"))

    def test_without_either_it_is_the_usual_place(self):
        root = self._root({"HF_HUB_CACHE": "", "HF_HOME": ""})
        self.assertEqual(root, Path.home() / ".cache" / "huggingface" / "hub")


class BytesOnDiskTest(unittest.TestCase):
    """The progress is what the disk holds — the one thing that cannot be wrong."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HF_HUB_CACHE": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.blobs = Path(self.tmp.name) / "models--Systran--faster-whisper-small" / "blobs"
        self.blobs.mkdir(parents=True)

    def _repo(self):
        return "Systran/faster-whisper-small"

    def test_nothing_downloaded_is_zero_not_an_error(self):
        self.assertEqual(model_download.bytes_on_disk(self._repo()), 0)

    def test_an_absent_repository_is_zero(self):
        self.assertEqual(model_download.bytes_on_disk("Systran/faster-whisper-medium"), 0)

    def test_a_file_still_downloading_counts(self):
        (self.blobs / "abc.incomplete").write_bytes(b"x" * 1024)
        self.assertEqual(model_download.bytes_on_disk(self._repo()), 1024)

    def test_a_finished_file_still_counts(self):
        # The reason we sum every blob rather than only the ``.incomplete`` ones:
        # huggingface_hub renames on completion, so counting the incomplete files
        # alone would drop the progress back to nothing each time one finished —
        # a bar that runs backwards in front of the user.
        (self.blobs / "abc").write_bytes(b"x" * 4096)
        (self.blobs / "def.incomplete").write_bytes(b"y" * 512)
        self.assertEqual(model_download.bytes_on_disk(self._repo()), 4608)


class ExpectedBytesTest(unittest.TestCase):
    """An unknown total must stay unknown: no invented percentage."""

    def test_without_huggingface_hub_the_size_is_unknown(self):
        with mock.patch.dict("sys.modules", {"huggingface_hub": None}):
            self.assertIsNone(model_download.expected_bytes("Systran/faster-whisper-small"))

    def test_a_hub_that_refuses_to_answer_leaves_it_unknown(self):
        api = mock.Mock()
        api.return_value.model_info.side_effect = OSError("offline")
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(HfApi=api)}):
            self.assertIsNone(model_download.expected_bytes("Systran/faster-whisper-small"))

    def test_it_sums_the_files_the_hub_reports(self):
        info = mock.Mock(siblings=[mock.Mock(size=1000), mock.Mock(size=2000)])
        api = mock.Mock()
        api.return_value.model_info.return_value = info
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(HfApi=api)}):
            self.assertEqual(model_download.expected_bytes("Systran/faster-whisper-small"), 3000)

    def test_a_repository_without_sizes_is_unknown_rather_than_zero(self):
        info = mock.Mock(siblings=[mock.Mock(size=None)])
        api = mock.Mock()
        api.return_value.model_info.return_value = info
        with mock.patch.dict("sys.modules", {"huggingface_hub": mock.Mock(HfApi=api)}):
            self.assertIsNone(model_download.expected_bytes("Systran/faster-whisper-small"))


class StartTest(unittest.TestCase):
    """What the application decides before spending anyone's bandwidth."""

    def setUp(self):
        model_download.reset_for_tests()
        self.addCleanup(model_download.reset_for_tests)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HF_HUB_CACHE": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_nothing_observable_before_anything_starts(self):
        # The route 404s on this, exactly like the recorder and tray routes.
        self.assertIsNone(model_download.snapshot())
        self.assertIsNone(model_download.progress())

    def test_a_model_already_in_the_cache_starts_no_download(self):
        (Path(self.tmp.name) / "models--Systran--faster-whisper-small" / "snapshots").mkdir(
            parents=True
        )
        with mock.patch.object(model_download.threading, "Thread") as thread:
            model_download.start(Settings(model="small", transcriber="auto"))
        thread.assert_not_called()
        self.assertEqual(model_download.snapshot()["state"], model_download.READY)

    def test_another_backend_keeps_its_weights_elsewhere(self):
        # openai-whisper and whisper.cpp do not read this cache; fetching 500 MB
        # of faster-whisper for them would be bandwidth nobody uses.
        with mock.patch.object(model_download.threading, "Thread") as thread:
            model_download.start(Settings(model="small", transcriber="openai-whisper"))
        thread.assert_not_called()
        state = model_download.snapshot()
        self.assertEqual(state["state"], model_download.UNAVAILABLE)
        self.assertEqual(state["reason"], "backend")

    def test_a_model_given_as_a_path_needs_no_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(model_download.threading, "Thread") as thread:
                model_download.start(Settings(model=directory, transcriber="auto"))
        thread.assert_not_called()
        self.assertEqual(model_download.snapshot()["reason"], "local-model")

    def test_a_missing_model_starts_one_thread_and_says_so(self):
        with mock.patch.object(model_download.threading, "Thread") as thread:
            model_download.start(Settings(model="small", transcriber="auto"))
            state = model_download.snapshot()
            self.assertEqual(state["state"], model_download.DOWNLOADING)
            self.assertEqual(state["repo"], "Systran/faster-whisper-small")
            self.assertIsNone(state["total_bytes"])
            thread.assert_called_once()
            # Daemon: a download must never be what keeps Aparté from closing.
            self.assertTrue(thread.call_args.kwargs["daemon"])

            # Called again while it runs, it starts nothing more.
            thread.return_value.is_alive.return_value = True
            model_download.start(Settings(model="small", transcriber="auto"))
            thread.assert_called_once()

    def test_the_progress_is_re_read_from_disk_on_each_look(self):
        blobs = Path(self.tmp.name) / "models--Systran--faster-whisper-small" / "blobs"
        blobs.mkdir(parents=True)
        with mock.patch.object(model_download.threading, "Thread"):
            model_download.start(Settings(model="small", transcriber="auto"))
        self.assertEqual(model_download.progress()["downloaded_bytes"], 0)
        (blobs / "abc.incomplete").write_bytes(b"x" * 2048)
        self.assertEqual(model_download.progress()["downloaded_bytes"], 2048)


class InterfaceTest(unittest.TestCase):
    """The band that shows the download. Written against the files rather than a
    browser: what matters here is that nothing is said in one language only, and
    that the promises the design makes are actually in the stylesheet."""

    ASSETS = Path(__file__).resolve().parent.parent / "src" / "aparte" / "assets"

    def _read(self, name):
        return (self.ASSETS / name).read_text(encoding="utf-8")

    def test_every_string_exists_in_both_languages(self):
        # A key written once would be announced in English to a French screen
        # reader — and this band is the first thing a new install shows.
        i18n = self._read("i18n.js")
        for key in (
            "model.downloading",
            "model.ready",
            "model.failed",
            "model.progress",
            "model.progress_unknown",
            "model.once",
        ):
            self.assertEqual(i18n.count(f'"{key}"'), 2, key)

    def test_the_page_watches_the_read_only_route(self):
        self.assertIn("/api/model-state", self._read("app.js"))

    def test_only_the_phase_sentence_is_a_live_region(self):
        # The byte count changes every second: inside the live region it would
        # repeat itself endlessly in a screen reader's ear.
        html = self._read("index.html")
        notice = html[html.index('id="model-notice"') : html.index("</section>", html.index('id="model-notice"'))]
        self.assertEqual(notice.count("aria-live"), 1)
        self.assertIn('id="model-line" aria-live="polite"', notice)

    def test_the_sliding_bar_has_its_reduced_motion_counterpart(self):
        # A 30% fragment that no longer slides reads as "30% downloaded" and
        # lies; the byte count below keeps the state readable without it.
        css = self._read("app.css")
        reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :]
        self.assertIn(".notice-meter.unknown", reduced)

    def test_the_band_takes_no_colour_flat(self):
        # The spotlight rule: only the recording disc may be a saturated flat.
        css = self._read("app.css")
        band = css[css.index(".notice {") : css.index("@keyframes notice-slide")]
        self.assertNotIn("--brand-fill", band)
        self.assertIn("var(--surface-2)", band)


class DownloadTest(unittest.TestCase):
    """The thread's own path: what it publishes when it works, and when it fails."""

    def setUp(self):
        model_download.reset_for_tests()
        self.addCleanup(model_download.reset_for_tests)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HF_HUB_CACHE": self.tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_without_the_library_it_says_so_instead_of_failing(self):
        # Not an error: the first transcription downloads it the way it always has.
        with mock.patch.dict("sys.modules", {"huggingface_hub": None}):
            model_download._download("Systran/faster-whisper-small")
        state = model_download.snapshot()
        self.assertEqual(state["state"], model_download.UNAVAILABLE)
        self.assertEqual(state["reason"], "huggingface_hub")

    def test_a_failed_download_is_named_not_swallowed(self):
        hub = mock.Mock(snapshot_download=mock.Mock(side_effect=OSError("no route to host")))
        with mock.patch.dict("sys.modules", {"huggingface_hub": hub}):
            with mock.patch.object(model_download, "expected_bytes", return_value=None):
                model_download._download("Systran/faster-whisper-small")
        state = model_download.snapshot()
        self.assertEqual(state["state"], model_download.ERROR)
        self.assertIn("no route to host", state["error"])

    def test_a_finished_download_reports_ready(self):
        hub = mock.Mock(snapshot_download=mock.Mock(return_value="/somewhere"))
        with mock.patch.dict("sys.modules", {"huggingface_hub": hub}):
            with mock.patch.object(model_download, "expected_bytes", return_value=486_000_000):
                model_download._download("Systran/faster-whisper-small")
        self.assertEqual(model_download.snapshot()["state"], model_download.READY)
