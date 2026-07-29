"""Lokales STT via faster-whisper (Standard-Backend)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np

from .base import STTEngine, resample_to_16k

log = logging.getLogger(__name__)

# Ab dieser Nicht-Sprache-Wahrscheinlichkeit gilt ein Segment als Geraeusch statt
# Sprache. Hoeher als Whispers eingebaute 0.6 — siehe _keep_segment.
_NO_SPEECH_MAX = 0.8


def _nvidia_search_roots() -> list:
    search_roots = list(sys.path)
    # Gepackte App (PyInstaller): nvidia-Libs liegen im _internal-/_MEIPASS-Ordner.
    if getattr(sys, "frozen", False):
        search_roots.append(str(Path(sys.executable).parent / "_internal"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            search_roots.append(meipass)
    return search_roots


def _register_cuda_dlls() -> None:
    """cuBLAS/cuDNN aus den nvidia-pip-Wheels fuer ctranslate2 auffindbar machen.

    Windows: ctranslate2 laedt cublas64_12.dll/cudnn*.dll ueber den PATH — die
    pip-Wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12) legen sie aber nur in
    site-packages ab → bin-Ordner in PATH/add_dll_directory eintragen.

    Linux: LD_LIBRARY_PATH wird von glibc nur beim Prozessstart gelesen — zur
    Laufzeit setzen bringt nichts. Stattdessen die Libraries per ctypes mit
    RTLD_GLOBAL VORLADEN: ctranslate2s spaeteres dlopen("libcudnn.so.9") findet
    dann die bereits geladene Library. Die cudnn-Sublibs (libcudnn_ops.so.9 …)
    loesen sich danach ueber deren eigenes $ORIGIN-RPATH auf.
    """
    if sys.platform == "win32":
        for entry in _nvidia_search_roots():
            base = Path(entry) / "nvidia"
            if not base.is_dir():
                continue
            for bin_dir in base.glob("*/bin"):
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(str(bin_dir))
                except OSError:
                    pass
        return

    if sys.platform.startswith("linux"):
        import ctypes

        # Reihenfolge: cublasLt vor cublas (Abhaengigkeit), dann cudnn.
        patterns = ("libcublasLt.so.*", "libcublas.so.*", "libcudnn.so.*")
        loaded: set[str] = set()
        for entry in _nvidia_search_roots():
            base = Path(entry) / "nvidia"
            if not base.is_dir():
                continue
            for lib_dir in sorted(base.glob("*/lib")):
                for pattern in patterns:
                    for lib in sorted(lib_dir.glob(pattern)):
                        if lib.name in loaded or lib.is_dir():
                            continue
                        try:
                            ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                            loaded.add(lib.name)
                        except OSError:
                            log.debug("CUDA-Lib nicht ladbar: %s", lib, exc_info=True)
        if loaded:
            log.debug("CUDA-Libs vorgeladen: %s", ", ".join(sorted(loaded)))


class FasterWhisperSTT(STTEngine):
    def __init__(self, cfg):
        self.cfg = cfg
        self._model = None
        self._on_cpu = False

    def _load_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        log.info(
            "Lade faster-whisper %s (device=%s, compute_type=%s) …",
            self.cfg.model_size, device, compute_type,
        )
        return WhisperModel(self.cfg.model_size, device=device, compute_type=compute_type)

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        _register_cuda_dlls()
        try:
            self._model = self._load_model(self.cfg.device, self.cfg.compute_type)
        except Exception as exc:
            if self.cfg.device == "cpu":
                raise
            log.warning("GPU-Init fehlgeschlagen (%s) — falle auf CPU/int8 zurueck.", exc)
            self._fall_back_to_cpu()

    def _fall_back_to_cpu(self) -> None:
        self._model = self._load_model("cpu", "int8")
        self._on_cpu = True

    def _keep_segment(self, seg) -> bool:
        """Ist dieses Segment wirklich Sprache — oder hat Whisper Musik geraten?

        Der Anlass ist real: Laeuft beim Diktieren Musik, hoert das Mikrofon sie mit.
        Whisper macht daraus Text und mischt dabei Sprachen („…Denn Sie ладно, da
        sind schon mal ein bisschen más schnell"). Das Ergebnis landete bisher
        ungefiltert im Dokument.

        Whisper bewertet jedes Segment selbst mit `no_speech_prob`. Der EINGEBAUTE
        Filter (`no_speech_threshold`) verwirft aber nur, wenn ZUSAETZLICH
        `avg_logprob` unter der Schwelle liegt — und bei Musik-Halluzinationen ist
        das Modell von seinem Unsinn oft ueberzeugt. Deshalb hier die getrennte,
        strengere Pruefung: Eine hohe Nicht-Sprache-Wahrscheinlichkeit genuegt.

        Bewusst konservativ (0.8 statt der eingebauten 0.6): Lieber ein Musikfetzen
        zu viel — den faengt danach der Fremdschrift-Guard — als ein verschlucktes
        echtes Wort. Verworfenes wird IMMER geloggt, nie stillschweigend entfernt.
        """
        nsp = getattr(seg, "no_speech_prob", 0.0) or 0.0
        if nsp < _NO_SPEECH_MAX:
            return True
        log.info("STT-Segment verworfen (keine Sprache, %.0f %% — Musik/Geraeusch?): %s",
                 nsp * 100, (seg.text or "").strip()[:80])
        return False

    def _run(self, audio: np.ndarray, initial_prompt: str | None = None) -> str:
        # "auto" (oder leer) = Whisper bestimmt die Sprache selbst — fuer
        # zweisprachiges Diktat (deutsch/englisch gemischt).
        language = None if self.cfg.language in ("", "auto") else self.cfg.language
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=self.cfg.vad_filter,
            beam_size=5,
            initial_prompt=initial_prompt,
        )
        # segments ist ein Generator — CUDA-Fehler tauchen erst hier auf.
        return " ".join(seg.text.strip() for seg in segments
                        if self._keep_segment(seg)).strip()

    def transcribe(
        self, audio: np.ndarray, samplerate: int, initial_prompt: str | None = None
    ) -> str:
        self._ensure_model()
        audio = resample_to_16k(audio, samplerate)
        try:
            return self._run(audio, initial_prompt)
        except RuntimeError as exc:
            message = str(exc).lower()
            cuda_problem = any(s in message for s in ("cublas", "cudnn", "cuda"))
            if self._on_cpu or not cuda_problem:
                raise
            log.warning("GPU-Transkription fehlgeschlagen (%s) — falle auf CPU/int8 zurueck.", exc)
            self._fall_back_to_cpu()
            return self._run(audio, initial_prompt)
