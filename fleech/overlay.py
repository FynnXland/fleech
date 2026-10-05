"""M4: Live-Overlay — rohe, streamende ASR-Vorschau waehrend des Sprechens.

Reines Best-Effort-„ich hoere dich"-Feedback, komplett entkoppelt vom Commit-Pfad
(STT→Routing→LLM→Injection). Fehler hier duerfen das Diktat nie beeintraechtigen.

Aufbau:
- OverlayWindow: rahmenloses, nicht aktivierbares Immer-oben-Fenster (Tkinter in
  eigenem Thread). WS_EX_NOACTIVATE ist Pflicht — das Overlay darf dem Ziel-Textfeld
  niemals den Fokus klauen, sonst geht das spaetere Strg+V daneben.
- PreviewStreamer: transkribiert periodisch das bisher aufgenommene Audio ueber ein
  gleitendes Fenster (whisper_streaming-Stil). Segmente, die aus dem Fenster
  herauswandern, werden als Text „eingefroren" und nicht erneut dekodiert.
- PreviewModel: kleines, separates faster-whisper-Modell, damit das grosse
  Commit-Modell nicht blockiert wird.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


# -- Overlay-Fenster ------------------------------------------------------------------


class OverlayWindow:
    """Tk laeuft in einem eigenen Thread; Steuerung ausschliesslich ueber die Queue."""

    MAX_CHARS = 300  # nur das Ende langer Vorschauen anzeigen

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fleech-overlay", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Overlay-Fenster konnte nicht initialisiert werden.")

    def show(self) -> None:
        self._queue.put(("show", None))

    def set_text(self, text: str) -> None:
        self._queue.put(("text", text))

    def hide(self) -> None:
        self._queue.put(("hide", None))

    # -- Tk-Thread -------------------------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._root = root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.88)
            root.configure(bg="#1e1e1e")

            screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
            width = int(screen_w * 0.5)
            self._label = tk.Label(
                root, text="", fg="#e8e8e8", bg="#1e1e1e",
                font=("Segoe UI", 11), wraplength=width - 28, justify="left", anchor="w",
            )
            self._label.pack(fill="both", expand=True, padx=14, pady=10)
            root.geometry(f"{width}x72+{(screen_w - width) // 2}+{screen_h - 160}")
            root.update_idletasks()
            self._prevent_focus_steal(root)
        except Exception:
            log.exception("Overlay-Init fehlgeschlagen — Vorschau bleibt aus.")
            self._ready.set()
            return
        self._ready.set()
        root.after(50, self._poll)
        root.mainloop()

    @staticmethod
    def _prevent_focus_steal(root) -> None:
        """WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW: nie Fokus nehmen, nicht in der Taskbar."""
        if sys.platform != "win32":
            return
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def _poll(self) -> None:
        try:
            while True:
                cmd, arg = self._queue.get_nowait()
                if cmd == "show":
                    self._label.config(text="🎤 …")
                    self._root.deiconify()
                elif cmd == "text":
                    text = arg or "🎤 …"
                    if len(text) > self.MAX_CHARS:
                        text = "…" + text[-self.MAX_CHARS :]
                    self._label.config(text=text)
                elif cmd == "hide":
                    self._root.withdraw()
        except queue.Empty:
            pass
        self._root.after(50, self._poll)


# -- Streaming-Transkription -----------------------------------------------------------


@dataclass
class PreviewSegment:
    text: str
    start: float  # Sekunden, relativ zum Fensteranfang
    end: float


class PreviewStreamer:
    """Gleitendes Fenster: periodisch dekodieren, herausgewanderte Segmente einfrieren.

    Vollstaendig injizierbar (snapshot_fn/transcribe_fn/on_text) und damit ohne
    Audio-Hardware und echtes Modell testbar.
    """

    # Stille-Gate: das Preview-Modell laeuft ohne VAD (Latenz) und halluziniert bei
    # Stille Phantomtexte. Liegt der RMS-Pegel des aktuellen Fensters unter dieser
    # Schwelle, wird der Dekodierlauf uebersprungen (billig: ein numpy-Aggregat).
    SILENCE_RMS = 0.004

    def __init__(
        self,
        snapshot_fn,
        transcribe_fn,
        on_text,
        samplerate: int = 16000,
        interval: float = 0.5,  # Dekodier-Takt: 0.5 s fuehlt sich fluessig an; das
                                # small-Modell dekodiert das Fenster in ~0.1–0.3 s
        # (GPU) — der schnellere Takt kostet praktisch keine zusaetzliche Last.
        window_seconds: float = 12.0,
        freeze_margin_seconds: float = 4.0,
        min_audio_seconds: float = 0.8,
        silence_rms: float | None = None,
    ):
        self.snapshot_fn = snapshot_fn
        self.transcribe_fn = transcribe_fn
        self.on_text = on_text
        self.samplerate = samplerate
        self.interval = interval
        self.window_seconds = window_seconds
        self.freeze_margin_seconds = freeze_margin_seconds
        self.min_audio_seconds = min_audio_seconds
        self.silence_rms = self.SILENCE_RMS if silence_rms is None else silence_rms
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frozen = ""
        self._window_start = 0.0
        self._dekodiert_bis = 0   # Samples, die beim letzten Lauf schon da waren

    def start(self) -> None:
        self._frozen = ""
        self._window_start = 0.0
        self._dekodiert_bis = 0
        # Jeder Lauf bekommt SEIN eigenes Stopp-Signal und liest es als Argument,
        # nicht als Attribut. Sonst saehe ein alter, noch rechnender Lauf nach dem
        # naechsten start() das NEUE, ungesetzte Signal und liefe einfach weiter.
        ereignis = threading.Event()
        self._stop = ereignis
        self._thread = threading.Thread(target=self._loop, args=(ereignis,),
                                        name="fleech-preview", daemon=True)
        self._thread.start()

    def stop(self, warten: bool = False) -> None:
        """Vorschau beenden. Wartet standardmaessig NICHT auf den laufenden Lauf.

        Frueher: `join(timeout=2)`. Aufgerufen wird `stop()` aber beim Aufnahme-
        Ende — und das laeuft im Tastatur-Hook von Windows. Ein Hook, der zu lange
        braucht, wird von Windows ohne Meldung entfernt; danach tut kein Hotkey
        mehr etwas. Im Log dauerte der letzte Vorschau-Lauf unter GPU-Last bis zu
        10 s, die 2 s liefen also voll aus. Ein gestoppter Lauf rechnet jetzt
        allein zu Ende und verwirft sein Ergebnis (siehe `_tick`)."""
        self._stop.set()
        if warten and self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self, ereignis: threading.Event | None = None) -> None:
        if ereignis is None:          # direkter Aufruf (Tests): das aktuelle Signal
            ereignis = self._stop
        while not ereignis.wait(self.interval):
            try:
                self._tick(ereignis)
            except Exception:
                # Best-Effort: ein kaputter Tick darf weder Loop noch Diktat reissen.
                log.debug("Preview-Tick fehlgeschlagen.", exc_info=True)

    def _tick(self, ereignis: threading.Event | None = None) -> None:
        audio = self.snapshot_fn()
        window = audio[int(self._window_start * self.samplerate) :]
        duration = window.size / self.samplerate
        if duration < self.min_audio_seconds:
            return
        # Stille-Gate: kein Dekodierlauf (und damit keine Whisper-Phantomtexte),
        # solange im Fenster kein echtes Sprachsignal liegt.
        if self.silence_rms > 0 and \
                float(np.sqrt(np.mean(np.square(window)))) < self.silence_rms:
            return
        # Zweites Gate: Ist seit dem letzten Lauf nur STILLE dazugekommen, ergaebe
        # derselbe Lauf denselben Text. Das Fenster-Gate oben greift dann nicht —
        # es sieht die Sprache von vorhin im Fenster und liess in jeder Sprechpause
        # dasselbe Audio immer wieder durch Whisper laufen.
        neu = audio[self._dekodiert_bis:]
        if self.silence_rms > 0 and neu.size and \
                float(np.sqrt(np.mean(np.square(neu)))) < self.silence_rms:
            return
        self._dekodiert_bis = audio.size

        segments = list(self.transcribe_fn(window))
        if ereignis is not None and ereignis.is_set():
            # Waehrend dieses Laufs gestoppt: Das Ergebnis gehoert zu einer
            # beendeten Aufnahme und darf weder Zustand noch Anzeige anfassen.
            return

        if duration > self.window_seconds:
            # Segmente, die weit genug vor dem Fensterende liegen, einfrieren und
            # das Fenster hinter das letzte eingefrorene Segment schieben.
            keep_after = duration - self.freeze_margin_seconds
            frozen_parts: list[str] = []
            cut = 0.0
            remaining: list[PreviewSegment] = []
            for seg in segments:
                if seg.end <= keep_after:
                    frozen_parts.append(seg.text.strip())
                    cut = seg.end
                else:
                    remaining.append(seg)
            if frozen_parts:
                self._frozen = (self._frozen + " " + " ".join(frozen_parts)).strip()
                self._window_start += cut
                segments = remaining

        live = " ".join(seg.text.strip() for seg in segments).strip()
        self.on_text((self._frozen + " " + live).strip())


class PreviewModel:
    """Kleines faster-whisper-Modell nur fuer die Vorschau (getrennt vom Commit-Modell)."""

    def __init__(self, model_size: str = "small", language: str = "de", samplerate: int = 16000):
        self.model_size = model_size
        self.language = language
        self.samplerate = samplerate
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            from .stt.faster_whisper_stt import _register_cuda_dlls, waehle_rechenart

            _register_cuda_dlls()
            log.info("Lade Preview-Modell %s …", self.model_size)
            try:
                # Wie das Diktat: int8 auf der Grafikkarte halbiert den Speicher.
                self._model = WhisperModel(self.model_size, device="auto",
                                           compute_type=waehle_rechenart("auto", "auto"))
            except Exception as exc:
                log.warning("Preview-Modell GPU-Init fehlgeschlagen (%s) — CPU/int8.", exc)
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe_segments(self, audio: np.ndarray) -> list[PreviewSegment]:
        self.load()
        from .stt.base import resample_to_16k

        audio = resample_to_16k(audio, self.samplerate)
        t0 = time.perf_counter()
        segments, _info = self._model.transcribe(
            audio,
            language=self.language or None,
            beam_size=1,  # Tempo schlaegt Qualitaet — die Vorschau ist Best-Effort
            vad_filter=False,
            condition_on_previous_text=False,
        )
        result = [PreviewSegment(seg.text, seg.start, seg.end) for seg in segments]
        log.debug("Preview-Dekodierung: %.2f s", time.perf_counter() - t0)
        return result


if __name__ == "__main__":
    # Manueller UI-Test ohne Mikrofon:  python -m fleech.overlay
    logging.basicConfig(level=logging.INFO)
    win = OverlayWindow()
    win.show()
    demo = "also ich wollte nur sagen dass das projekt ziemlich gut läuft und wir im zeitplan sind"
    words = demo.split()
    for i in range(1, len(words) + 1):
        win.set_text(" ".join(words[:i]))
        time.sleep(0.25)
    time.sleep(1.5)
    win.hide()
    time.sleep(0.5)
