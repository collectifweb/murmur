from __future__ import annotations

import ctypes
import glob
import os
import shutil
import subprocess
import sysconfig
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import hallucinations


class TranscriptionError(RuntimeError):
    pass


_cuda_preloaded = False


def _preload_cuda_libraries() -> None:
    """Load pip-provided CUDA runtime libs (``nvidia-*-cu12``) into the process.

    ctranslate2 dlopens ``libcublas``/``libcudnn`` by soname but does not look in
    pip's ``site-packages/nvidia/*/lib`` directories. Preloading them globally
    with their absolute path lets the later soname lookup resolve to the already
    loaded library, so GPU transcription works without the user exporting
    ``LD_LIBRARY_PATH``. Best-effort and idempotent; missing libs are ignored so
    the caller can fall back to CPU.
    """
    global _cuda_preloaded
    if _cuda_preloaded:
        return
    _cuda_preloaded = True
    nvidia_root = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    if not os.path.isdir(nvidia_root):
        return
    # Order matters: dependencies (cublas, nvrtc) before cudnn aggregates.
    patterns = (
        "cublas/lib/libcublas*.so*",
        "cuda_nvrtc/lib/libnvrtc*.so*",
        "cudnn/lib/libcudnn*.so*",
    )
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(nvidia_root, pattern))):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


@dataclass(frozen=True)
class Transcript:
    text: str
    backend: str


class Transcriber:
    def transcribe(self, audio_path: Path) -> Transcript:
        raise NotImplementedError


class TextFileTranscriber(Transcriber):
    def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript(audio_path.read_text(encoding="utf-8"), "text")


class FasterWhisperTranscriber(Transcriber):
    # Substrings that signal a GPU is present but the CUDA runtime is unusable
    # (missing libcublas/libcudnn). Such failures can surface either when the
    # model is constructed or lazily on the first inference call.
    _CUDA_ERROR_HINTS = ("cublas", "cudnn", "cuda", "libcu", "gpu")
    # What a refused `vad_filter` looks like: no onnxruntime, or a faster-whisper old
    # enough not to take the argument at all.
    _VAD_ERROR_HINTS = ("vad", "onnx", "silero")

    def __init__(
        self,
        model: str,
        language: str | None = None,
        device: str = "auto",
        compute_type: str = "auto",
        hotwords: Sequence[str] = (),
    ) -> None:
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        # faster-whisper takes the user's vocabulary as one string. Empty means
        # "no bias at all", and that is not the same as an empty string: a blank
        # hint still enters the decoder's prompt.
        self.hotwords = ", ".join(hotwords) or None
        # Trim silence before decoding. Not a setting: a capture with no speech has
        # nothing to transcribe, whoever is dictating. Turned off for good on the
        # first refusal (see _decode).
        self.vad_filter = True
        self.model = self._load_model(device, compute_type)

    def _load_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        if device != "cpu":
            _preload_cuda_libraries()
        try:
            return WhisperModel(self.model_name, device=device, compute_type=compute_type)
        except Exception as exc:
            if device == "cpu" or not self._is_cuda_error(exc):
                raise TranscriptionError(
                    f"Could not load faster-whisper model '{self.model_name}': {exc}"
                ) from exc
            return self._load_cpu_model()

    def _load_cpu_model(self):
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        except Exception as cpu_exc:
            raise TranscriptionError(
                f"Could not load faster-whisper model '{self.model_name}' on CPU: {cpu_exc}"
            ) from cpu_exc
        self.device = "cpu"
        self.compute_type = "int8"
        return model

    @classmethod
    def _is_cuda_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(hint in message for hint in cls._CUDA_ERROR_HINTS)

    @classmethod
    def _is_vad_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(hint in message for hint in cls._VAD_ERROR_HINTS)

    def _decode(self, audio_path: Path) -> str:
        """One decoding pass, silence trimmed first.

        Without the VAD, a capture with no speech in it makes Whisper hallucinate in
        a loop until it hits its token limit: measured on a Mac on 25/07, two minutes
        of computation ending in a string of symbols delivered to the user, while the
        recorder stayed stuck on "processing" and the shortcut could start nothing.
        Trimming the silent stretches first turns that capture into an empty result,
        and "an empty output touches nothing" does the rest.

        The join stays inside the try: faster-whisper returns a generator, so a decode
        failure surfaces while iterating, not on the call — that is what the CUDA
        fallback above needs to catch.
        """
        options = {"language": self.language, "hotwords": self.hotwords}
        if self.vad_filter:
            # Absent rather than False when it is off: a version old enough to refuse
            # the VAD refuses the argument itself, whatever its value.
            options["vad_filter"] = True
        try:
            segments, _info = self.model.transcribe(str(audio_path), **options)
            return " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        except Exception as exc:
            if not self.vad_filter or not self._is_vad_error(exc):
                raise
            # The VAD needs onnxruntime, and older faster-whisper versions take no
            # such argument. Transcribing without it beats not transcribing.
            self.vad_filter = False
            return self._decode(audio_path)

    def transcribe(self, audio_path: Path) -> Transcript:
        try:
            text = self._decode(audio_path)
        except Exception as exc:
            # CUDA can fail lazily on the first real inference; retry once on CPU.
            if self.device == "cpu" or not self._is_cuda_error(exc):
                raise TranscriptionError(str(exc)) from exc
            self.model = self._load_cpu_model()
            text = self._decode(audio_path)
        # Le filtre est ici, et pas dans polish.py, pour couvrir aussi les
        # chemins qui ne polissent pas : `--no-polish`, le raccourci global,
        # l'aperçu au fil de la parole.
        return Transcript(hallucinations.strip(text), "faster-whisper")


class OpenAIWhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str | None = None) -> None:
        import whisper

        self.whisper = whisper
        self.language = language
        self.model = whisper.load_model(model)

    def transcribe(self, audio_path: Path) -> Transcript:
        result = self.model.transcribe(str(audio_path), language=self.language)
        return Transcript(hallucinations.strip(str(result.get("text", "")).strip()), "openai-whisper")


class WhisperCppTranscriber(Transcriber):
    def __init__(self, executable: str, model: str, language: str | None = None) -> None:
        self.executable = executable
        self.model = model
        self.language = language

    def transcribe(self, audio_path: Path) -> Transcript:
        command = [self.executable, "-m", self.model, "-f", str(audio_path), "-nt"]
        if self.language:
            command.extend(["-l", self.language])
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            raise TranscriptionError(completed.stderr.strip() or "whisper.cpp failed")
        return Transcript(hallucinations.strip(completed.stdout.strip()), "whisper.cpp")


def build_transcriber(
    backend: str = "auto",
    model: str = "small",
    language: str | None = None,
    whisper_cpp: str | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    hotwords: Sequence[str] = (),
) -> Transcriber:
    """Build a transcriber for ``backend``.

    ``hotwords`` is the user's own vocabulary, nudging Whisper toward those
    spellings when the audio is ambiguous. Only faster-whisper accepts it;
    openai-whisper and whisper.cpp have no equivalent, so the setting quietly
    does nothing there rather than promising what the backend cannot deliver.
    """
    if backend == "text":
        return TextFileTranscriber()
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(model, language, device, compute_type, hotwords)
    if backend == "openai-whisper":
        return OpenAIWhisperTranscriber(model, language)
    if backend == "whisper.cpp":
        executable = whisper_cpp or shutil.which("whisper-cli") or shutil.which("main")
        if not executable:
            raise TranscriptionError("whisper.cpp executable not found")
        return WhisperCppTranscriber(executable, model, language)
    if backend != "auto":
        raise TranscriptionError(f"Unknown transcriber backend: {backend}")

    try:
        return FasterWhisperTranscriber(model, language, device, compute_type, hotwords)
    except Exception:
        pass
    try:
        return OpenAIWhisperTranscriber(model, language)
    except Exception:
        pass
    executable = whisper_cpp or shutil.which("whisper-cli") or shutil.which("main")
    if executable:
        return WhisperCppTranscriber(executable, model, language)

    raise TranscriptionError(
        "No local Whisper backend found. Install faster-whisper, openai-whisper, "
        "or set APARTE_WHISPER_CPP to a whisper.cpp executable."
    )

