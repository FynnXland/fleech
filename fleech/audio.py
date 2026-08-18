"""Mikrofon-Aufnahme (Push-to-Talk): start() beim Druecken, stop() liefert das Segment."""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
import wave
from collections import deque

import numpy as np

log = logging.getLogger(__name__)


def _linux_default_input():
    """Linux: das ALSA-'pulse'-Geraet als Standard-Input (Index oder None).

    Das rohe ALSA-'default' geht an PipeWire VORBEI und greift direkt eine
    Hardware ab (real beobachtet: Onboard-Line-In statt USB-Mikrofon → Stille).
    Das 'pulse'-Plugin routet ueber PipeWire/PulseAudio und folgt damit der
    System-Mikrofonwahl des Nutzers (KDE-Einstellungen), inklusive sauberem
    Resampling auf jede angefragte Rate. Rohe hw-Geraete sind unter PipeWire
    ohnehin exklusiv belegt ("Device unavailable").
    """
    import sounddevice as sd

    for idx, d in enumerate(sd.query_devices()):
        if d["name"] in ("pulse", "pipewire") and d["max_input_channels"] > 0:
            return idx
    return None  # kein Pulse-Plugin: sounddevice-Default verwenden


def list_pulse_sources() -> list[str]:
    """Linux: echte Mikrofone (PipeWire-Sources, ohne Monitore) als Anzeigenamen."""
    import pulsectl

    names = []
    with pulsectl.Pulse("fleech-list-sources") as pulse:
        for src in pulse.source_list():
            if getattr(src, "monitor_of_sink", None) not in (None, 0xFFFFFFFF):
                continue  # Monitor-Source (Systemaudio) — nie als Mikrofon anbieten
            names.append(src.description or src.name)
    return names


def list_input_devices() -> list[str]:
    """Waehlbare Mikrofone als Anzeigenamen — fuer Einstellungen und Onboarding.

    Best-Effort: Eine leere Liste ist ein akzeptables Ergebnis, ein Absturz beim
    Oeffnen der Einstellungen waere keins."""
    # Linux: echte Mikrofone von PipeWire listen (rohe ALSA-hw-Geraete sind dort
    # exklusiv belegt und wuerden nur tote Auswahl-Eintraege erzeugen).
    if sys.platform.startswith("linux"):
        try:
            return list_pulse_sources()
        except Exception:
            log.exception("PipeWire-Quellen nicht abfragbar — falle auf sounddevice zurueck.")
    try:
        import sounddevice as sd

        names = []
        for dev in sd.query_devices():
            if dev["max_input_channels"] > 0 and dev["name"] not in names:
                names.append(dev["name"])
        return names
    except Exception:
        log.exception("Audio-Geraete nicht abfragbar.")
        return []


def _linux_resolve_source(device_name: str):
    """Wunsch-Mikrofon (Anzeigename/Source-Name) → PULSE_SOURCE + pulse-Device.

    Das ALSA-pulse-Plugin liest PULSE_SOURCE beim Stream-Open — so laeuft auch
    eine explizite Auswahl ueber PipeWire (statt ueber rohe, belegte hw-Geraete).
    Rueckgabe None = kein Treffer (Aufrufer versucht ALSA-Namensaufloesung).
    """
    import os

    import pulsectl

    try:
        with pulsectl.Pulse("fleech-select-source") as pulse:
            for src in pulse.source_list():
                if device_name in (src.name, src.description):
                    os.environ["PULSE_SOURCE"] = src.name
                    return _linux_default_input()
    except Exception:
        log.debug("PipeWire-Source-Aufloesung fehlgeschlagen.", exc_info=True)
    return None


def _default_input_name(sd) -> str:
    """Name des Geraets, das der Systemstandard gerade meint ("" = nicht ermittelbar)."""
    try:
        return str(sd.query_devices(kind="input")["name"])
    except Exception:
        log.debug("Standard-Eingabegeraet nicht abfragbar.", exc_info=True)
        return ""


def resolve_input_device(device, on_fallback=None):
    """Mehrdeutigen Mikrofon-NAMEN auf einen eindeutigen Geraete-Index abbilden.

    Windows listet dasselbe Mikrofon unter mehreren Host-APIs (MME, DirectSound,
    WASAPI, WDM-KS) — sounddevice wirft dann "Multiple input devices found". Wir
    bevorzugen die Standard-Host-API des Systems (das ist genau das Geraet, das der
    Nutzer als Windows-Standard nutzt), sonst den ersten Treffer. Index wird
    unveraendert durchgereicht; None = Systemstandard.

    Linux: None und Mikrofon-Namen werden ueber PipeWire aufgeloest (pulse-Device
    + PULSE_SOURCE), NICHT ueber rohe ALSA-hw-Geraete.

    on_fallback(name): wird gerufen, wenn das gewaehlte Mikrofon nicht mehr da ist
    und stattdessen der Systemstandard genommen wird (Befund B-7). `name` ist das
    Geraet, ueber das dann wirklich aufgenommen wird.
    """
    is_linux = sys.platform.startswith("linux")
    if device is None:
        if is_linux:
            import os

            os.environ.pop("PULSE_SOURCE", None)  # zurueck zum Systemstandard
            return _linux_default_input()
        return None
    if isinstance(device, int):
        return device
    if is_linux:
        resolved = _linux_resolve_source(device)
        if resolved is not None:
            return resolved
    import sounddevice as sd

    matches = [
        (idx, d) for idx, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0 and d["name"] == device
    ]
    if not matches:
        log.warning("Mikrofon %r nicht gefunden — nutze Systemstandard.", device)
        # Befund B-7: Bis 5.10.3 blieb es bei dieser Zeile im Protokoll. Wessen
        # Interface aus war, diktierte ab da ueber die Webcam — und merkte es erst
        # an schlechter Erkennung. Der Aufrufer meldet es jetzt sichtbar.
        if on_fallback is not None:
            try:
                on_fallback(_default_input_name(sd))
            except Exception:
                log.debug("Meldung ueber Geraete-Rueckfall fehlgeschlagen.", exc_info=True)
        return None
    if len(matches) == 1:
        return matches[0][0]
    try:
        default_hostapi = sd.default.hostapi
    except Exception:
        default_hostapi = None
    for idx, d in matches:
        if d["hostapi"] == default_hostapi:
            log.info("Mikrofon %r mehrdeutig → Index %d (Standard-Host-API).", device, idx)
            return idx
    return matches[0][0]


def audio_to_wav_bytes(audio: np.ndarray, samplerate: int = 16000) -> bytes:
    """float32 [-1,1] → 16-bit-PCM-WAV im Speicher (fuer Cloud-STT und Formel-Modus)."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


# Stille an der Nahtstelle nach einer Pause. Kurz genug, um nicht zu stoeren,
# lang genug, dass die Erkennung dort eine Sprechpause sieht statt eines Schnitts.
_RESUME_GAP_S = 0.35

# Wie weit der Rohpegel-Verlauf zurueckreicht. Die Kein-Ton-Wache der Pille fragt
# ein 5-s-Fenster ab (Befund H-B2); 10 s Vorrat sind grosszuegig genug fuer
# spaetere Fragen und kosten bei ~50 Bloecken je Sekunde nur ein paar hundert
# Zahlenpaare.
_ROHPEGEL_VORRAT_S = 10.0


class Recorder:
    """Nimmt Mono-Float32-Audio auf. Nicht reentrant: ein Segment zur Zeit."""

    def __init__(self, samplerate: int = 16000, device: int | str | None = None):
        self.samplerate = samplerate
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._level = 0.0  # RMS des letzten Audio-Blocks (fuer die Overlay-Waveform)
        self._samples = 0  # bisher aufgenommene Samples (fuer Zeitstempel-Splitting)
        # Roher Pegelverlauf: (Zeitpunkt, RMS) je Audio-Block, ungeglaettet und
        # unskaliert. Die Waveform verstaerkt ihren Pegel automatisch (bis 45-fach)
        # — dort sind „Mikrofon tot" und „Mikrofon leise" nicht zu unterscheiden.
        # Fuer die Kein-Ton-Wache braucht es genau die ungeschminkte Zahl.
        self._rohpegel: deque[tuple[float, float]] = deque()
        # PortAudio-Statuscodes dieser Aufnahme (Overflow, Geraet weg). Gezaehlt
        # statt Zeile fuer Zeile geloggt (Befund B-6).
        self._status_zaehler = 0
        # Tatsaechliche Capture-Rate: weicht ab, wenn das Geraet die Wunschrate nicht
        # kann (direktes hw-Geraet, z. B. Focusrite: min. 44,1 kHz). Nach aussen
        # liefert der Recorder IMMER self.samplerate (Rueck-Resampling in _to_target).
        self._capture_rate = samplerate
        self._paused = False   # Aufnahme laeuft, sammelt aber nicht (siehe pause())
        # Callable(name) | None: Das gewaehlte Mikrofon ist weg, aufgenommen wird
        # ueber den Systemstandard (Befund B-7). Die Desktop-App haengt sich hier
        # ein und meldet es einmal je Sitzung.
        self.on_device_fallback = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Aufnahme anhalten: der Stream laeuft weiter, aber nichts wird gesammelt.

        Absicht: mitten im Diktat kurz mit jemandem sprechen, ohne das Diktat zu
        verlieren. Der Stream bleibt bewusst offen — ihn zu schliessen und neu zu
        oeffnen kostet unter Windows spuerbar Zeit und kann das Geraet wechseln.
        """
        self._paused = True

    def resume(self) -> None:
        """Weiter aufnehmen — mit einer kurzen Stille an der Nahtstelle.

        Ohne diese Stille stossen die beiden Haelften hart aneinander (das
        Dazwischen faellt ja weg) und Whisper klebt die letzten und ersten Woerter
        zu einem Wort zusammen. Eine kurze Pause ist genau das Signal, das ein
        Sprecher an dieser Stelle ohnehin gemacht haette.
        """
        if not self._paused:
            return
        self._paused = False
        if self._stream is None:
            return
        stille = np.zeros((int(self._capture_rate * _RESUME_GAP_S), 1), dtype=np.float32)
        with self._lock:
            self._frames.append(stille)
            self._samples += len(stille)

    def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd  # lazy: erlaubt Tests ohne Audio-Hardware

        with self._lock:
            self._frames = []
            self._samples = 0
            self._rohpegel.clear()  # der Pegelverlauf gilt je Aufnahme
        self._status_zaehler = 0
        self._paused = False        # eine neue Aufnahme beginnt nie pausiert
        device = resolve_input_device(self.device, self.on_device_fallback)
        try:
            self._stream = self._open_stream(sd, device, self.samplerate)
            self._capture_rate = self.samplerate
        except sd.PortAudioError:
            # Wunschrate nicht unterstuetzt → native Geraeterate nehmen und spaeter
            # zurueckrechnen (die Pipeline bekommt weiterhin self.samplerate-Audio).
            native = int(sd.query_devices(device, "input")["default_samplerate"])
            log.info(
                "Mikrofon kann %d Hz nicht — Aufnahme mit %d Hz + Resampling.",
                self.samplerate, native,
            )
            self._stream = self._open_stream(sd, device, native)
            self._capture_rate = native
        self._stream.start()

    def _open_stream(self, sd, device, samplerate: int):
        return sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            device=device,
            callback=self._callback,
        )

    def _to_target(self, audio: np.ndarray) -> np.ndarray:
        """Capture-Rate → Wunschrate (lineare Interpolation, fuer Sprache voellig ok)."""
        src, dst = self._capture_rate, self.samplerate
        if src == dst or audio.size == 0:
            return audio
        target_len = int(round(audio.size * dst / src))
        x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self._status_zaehler += 1
            if self._status_zaehler == 1:
                # Befund B-6: Overflow oder ein verschwundenes Geraet erklaeren
                # spaeter das leere Transkript — bis 5.10.4 stand das nur in
                # log.debug und war im Normalbetrieb damit unsichtbar. Nur das
                # ERSTE Auftreten je Aufnahme kommt sichtbar ins Protokoll; ein
                # dauerhafter Overflow wuerde es sonst zuschuetten.
                log.info("Audio-Status: %s (weitere werden nur gezaehlt).", status)
            else:
                log.debug("Audio-Status: %s", status)
        if self._paused:
            # Pegel auf 0 ziehen, damit die Waveform in der Pille wirklich ruht —
            # ein zappelnder Balken waehrend einer Pause waere ein falsches Signal.
            self._level = 0.0
            return
        self._level = float(np.sqrt(np.mean(np.square(indata))))
        jetzt = time.monotonic()
        with self._lock:
            self._frames.append(indata.copy())
            self._samples += len(indata)
            self._rohpegel.append((jetzt, self._level))
            grenze = jetzt - _ROHPEGEL_VORRAT_S
            while self._rohpegel and self._rohpegel[0][0] < grenze:
                self._rohpegel.popleft()

    @property
    def position(self) -> float:
        """Sekunden seit Aufnahmestart — praezise aus den gelieferten Samples (fuer
        Zeitstempel-Splitting im Inline-Formel-Modus), nicht aus der Wanduhr."""
        return self._samples / self._capture_rate if self._capture_rate else 0.0

    @property
    def level(self) -> float:
        """Aktueller Eingangspegel (RMS, ~0–0.5) — billig, fuer die Live-Waveform."""
        return self._level if self._stream is not None else 0.0

    @property
    def status_zaehler(self) -> int:
        """Wie oft PortAudio in dieser Aufnahme einen Status gemeldet hat."""
        return self._status_zaehler

    def rohpegel_max(self, sekunden: float = 5.0) -> float:
        """Lautester ROHER RMS der letzten Sekunden (0.0 = es kam nichts).

        Absichtlich ungeglaettet und unskaliert, anders als `level`, das die
        Waveform zeichnet: Deren Automatik verstaerkt ein blosses Rauschen bis
        24-fach, sodass ein totes Mikrofon aussieht wie eine leise, aber
        funktionierende Aufnahme (Befund H-B2). Ein Maximum statt eines
        Mittelwerts, weil eine einzige gesprochene Silbe im Fenster bereits
        beweist, dass Ton ankommt.
        """
        if self._stream is None:
            return 0.0
        grenze = time.monotonic() - max(0.0, sekunden)
        with self._lock:
            werte = [rms for zeit, rms in self._rohpegel if zeit >= grenze]
        return max(werte) if werte else 0.0

    def snapshot(self) -> np.ndarray:
        """Kopie des bisher aufgenommenen Audios, ohne die Aufnahme zu stoeren (M4-Preview)."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._frames)[:, 0].copy()
        return self._to_target(audio)

    def tail(self, sekunden: float) -> np.ndarray:
        """Nur die LETZTEN Sekunden — fuer die Stille-Wache im Anstupsen-Modus.

        Bewusst nicht `snapshot()`: Die Wache laeuft mehrmals pro Sekunde, und
        `snapshot()` kopiert jedes Mal das gesamte bisherige Diktat. Bei einem
        langen Diktat waere das mit jeder Sekunde teurer — fuer eine Frage, die
        immer nur die letzte Sekunde betrifft.
        """
        noetig = int(max(0.0, sekunden) * self._capture_rate)
        if not noetig:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            gesammelt, laenge = [], 0
            for block in reversed(self._frames):
                gesammelt.append(block)
                laenge += len(block)
                if laenge >= noetig:
                    break
            audio = np.concatenate(list(reversed(gesammelt)))[-noetig:, 0].copy()
        return self._to_target(audio)

    def stop(self) -> np.ndarray:
        """Beendet die Aufnahme und gibt das Segment als 1-D-float32-Array zurueck."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._paused = False
        if self._status_zaehler > 1:
            # Einmal am Ende die Summe — sonst waere nur das erste von hundert
            # Aussetzern sichtbar und man haelt es fuer einen Ausrutscher.
            log.info("PortAudio meldete %dx einen Status in dieser Aufnahme.",
                     self._status_zaehler)
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            frames, self._frames = self._frames, []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return self._to_target(np.concatenate(frames)[:, 0])
