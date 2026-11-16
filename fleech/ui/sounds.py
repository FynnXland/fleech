"""UI-Sounds: kurz, dezent, nicht-blockierend ueber sounddevice abgespielt.

Jeder Sound ist einzeln abschaltbar, die Gesamtlautstaerke regelbar. Drei Klangstile:
- "warm":    Standard seit 6.6.0 — Kenney „Interface Sounds" (CC0) aus
             assets/sounds/warm/, siehe THIRD-PARTY-NOTICES.md
- "chimes":  die frueheren Zwei-Ton-Chimes (Sinus mit Huellkurve), im Code erzeugt
- "click":   minimale, trockene Ticks, im Code erzeugt
"""

from __future__ import annotations

import logging
import wave

import numpy as np

from ..resources import asset

log = logging.getLogger(__name__)

SR = 44100
EVENTS = ("start", "stop", "commit", "error")
PRESETS = ("warm", "chimes", "click")
DEFAULT_PRESET = "warm"

# Die Dateien liegen nahe der Vollaussteuerung; dieser Faktor bringt sie beim
# Abspielen auf die Lautheit der Hoerprobe (bei 40 % rund 60 % der alten Chimes).
_DATEI_PEGEL = 0.6
# Die synthetischen Klaenge laufen weiter mit dem Faktor von frueher.
_SYNTH_PEGEL = 0.5


def _tone(freq: float, seconds: float, *, attack=0.005, release=0.06, harmonic=0.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    wave_ = np.sin(2 * np.pi * freq * t)
    if harmonic:
        wave_ += harmonic * np.sin(2 * np.pi * freq * 2 * t)
    env = np.ones_like(t)
    n = env.size
    a, r = int(attack * SR), int(release * SR)
    if a + r > n:  # Huellkurve darf nie laenger sein als der Ton selbst
        scale = n / (a + r)
        a, r = int(a * scale), n - int(a * scale)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if r:
        env[-r:] = np.linspace(1, 0, r)
    return (wave_ * env).astype(np.float32)


def _seq(*parts: np.ndarray, gap: float = 0.02) -> np.ndarray:
    silence = np.zeros(int(SR * gap), dtype=np.float32)
    out = []
    for i, p in enumerate(parts):
        if i:
            out.append(silence)
        out.append(p)
    return np.concatenate(out)


def _synth_preset(name: str) -> dict[str, np.ndarray]:
    if name == "click":
        tick = _tone(1800, 0.02, release=0.015)
        return {
            "start": tick,
            "stop": _tone(1200, 0.02, release=0.015),
            "commit": _seq(tick, _tone(2200, 0.02, release=0.015), gap=0.03),
            "error": _seq(_tone(300, 0.05), _tone(300, 0.05), gap=0.05),
        }
    return {  # "chimes"
        "start": _seq(_tone(660, 0.07, harmonic=0.3), _tone(880, 0.09, harmonic=0.3)),
        "stop": _seq(_tone(880, 0.07, harmonic=0.3), _tone(660, 0.09, harmonic=0.3)),
        "commit": _tone(1046, 0.10, harmonic=0.4, release=0.08),
        "error": _seq(_tone(392, 0.09), _tone(330, 0.12), gap=0.04),
    }


def _lade_wav(pfad) -> np.ndarray:
    with wave.open(str(pfad)) as w:
        if w.getsampwidth() != 2 or w.getframerate() != SR or w.getnchannels() != 1:
            raise ValueError(f"{pfad.name}: erwartet 16 Bit, {SR} Hz, mono")
        roh = w.readframes(w.getnframes())
    return np.frombuffer(roh, dtype=np.int16).astype(np.float32) / 32768.0


def _build_preset(name: str) -> dict[str, np.ndarray]:
    """Samples des Klangstils, schon mit seinem Pegel verrechnet.

    Fehlt eine Datei des Standardsets (kaputte Installation), klingt Fleech
    lieber nach den alten Chimes als gar nicht."""
    if name in ("chimes", "click"):
        return {k: v * _SYNTH_PEGEL for k, v in _synth_preset(name).items()}
    try:
        return {ev: _lade_wav(asset(f"sounds/{DEFAULT_PRESET}/{ev}.wav")) * _DATEI_PEGEL
                for ev in EVENTS}
    except Exception:
        log.warning("Klangdateien fehlen oder sind unlesbar — spiele die alten Chimes.",
                    exc_info=True)
        return _build_preset("chimes")


class SoundPlayer:
    """Config-getrieben: settings.sounds entscheidet, was wie laut gespielt wird."""

    def __init__(self, settings):
        self.settings = settings  # usersettings.SoundSettings (live-Referenz)
        self._preset_name = None
        self._samples: dict[str, np.ndarray] = {}

    def _ensure_preset(self) -> None:
        if self._preset_name != self.settings.preset:
            self._samples = _build_preset(self.settings.preset)
            self._preset_name = self.settings.preset

    def play(self, event: str, volume_factor: float = 1.0) -> None:
        """event: start | stop | commit | error — nicht-blockierend, Best-Effort.

        volume_factor: situative Reduktion (z. B. Gaming-Modus), multiplikativ
        zur Nutzer-Lautstaerke.
        """
        s = self.settings
        if not s.enabled or not getattr(s, event, False) or s.volume <= 0:
            return
        gain = float(np.clip(s.volume, 0.0, 1.0)) * float(np.clip(volume_factor, 0.0, 1.0))
        if gain <= 0:
            return
        try:
            import sounddevice as sd

            self._ensure_preset()
            sample = self._samples.get(event)
            if sample is None:
                return
            sd.play(sample * gain, SR)
        except Exception:
            log.debug("UI-Sound %s fehlgeschlagen.", event, exc_info=True)
