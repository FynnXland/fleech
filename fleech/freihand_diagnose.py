"""Fehlersuche am Startwort: aufheben, was die Pruefung tatsaechlich gehoert hat.

## Warum es das braucht

Die Startwort-Probe in den Einstellungen trifft zuverlaessig, der Freihand-Betrieb
nicht — gemeldet und nicht erklaerbar. Alles, was sich ohne echtes Signal
vergleichen liess, zeigt Gleichstand:

- Dieselbe Erkennung, dasselbe Modell, dieselbe Abtastrate (16 kHz).
- Dieselbe Zustandsmaschine, blockweise gegen ein Stueck am Stueck gefahren:
  in fuenf Szenen (Pegel 1,0 bis 0,15, viel und wenig Stille) fuenfmal Gleichstand.
- Beide Audio-Stroeme auf demselben Geraet: keine auffaellige Abweichung.

Was fehlt, ist das Signal aus dem Moment, in dem es scheitert. Raten hilft hier
nicht weiter — vier Runden Vermutungen sind genug.

## Was aufgezeichnet wird, und was nicht

NUR das Fenster, das die Startwort-Pruefung ohnehin gerade ansieht: zwei Sekunden,
und auch nur dann, wenn das VAD dort Sprache gemeldet hat. Kein Diktat, kein
Dauermitschnitt. Die Dateien liegen sichtbar in einem eigenen Ordner, tragen den
erkannten Text im Namen und sind nach 60 Stueck durchgerollt.

**Standardmaessig aus.** Der Schalter sagt ausdruecklich, dass Audio gespeichert
wird — eine Diagnose, die man versehentlich anlaesst, waere genau der
Vertrauensbruch, den der Freihand-Modus sonst vermeidet.
"""

from __future__ import annotations

import logging
import re
import wave

import numpy as np

log = logging.getLogger(__name__)

ORDNER_NAME = "freihand-diagnose"

# Wie viele Aufnahmen aufgehoben werden. 60 Fenster à 2 s sind rund vier Minuten
# Sprache und etwa 4 MB — genug fuer einen Testlauf, wenig genug, um niemanden
# zu ueberraschen, der den Ordner spaeter findet.
MAX_DATEIEN = 60


def _sicherer_name(text: str) -> str:
    """Erkannten Text in einen Dateinamen verwandeln (kurz, ohne Sonderzeichen)."""
    text = re.sub(r"[^\w\s-]", "", (text or "").strip())
    text = re.sub(r"\s+", "-", text)[:40]
    return text or "nichts-gehoert"


def _schreibe_wav(pfad, audio: np.ndarray, samplerate: int) -> None:
    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(pfad), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(samplerate))
        wav.writeframes(pcm.tobytes())


def _rolle_ab(ordner) -> None:
    """Aelteste Dateien loeschen, bis der Deckel wieder passt."""
    dateien = sorted(ordner.glob("*.wav"))
    for alt in dateien[:max(0, len(dateien) - MAX_DATEIEN)]:
        try:
            alt.unlink()
        except OSError:
            log.debug("Diagnose-Datei nicht loeschbar: %s", alt, exc_info=True)


def baue_mitschnitt(ordner, samplerate: int = 16000, uhr=None):
    """Rueckgabe: callable(audio, text, treffer) zum Hineinreichen in den Lauscher.

    `ordner` ist ein Path; er wird beim ersten Schreiben angelegt. `uhr` ist
    injizierbar, damit Tests feste Dateinamen bekommen.
    """
    import time

    uhr = uhr or (lambda: time.strftime("%H%M%S"))
    zaehler = {"n": 0}

    def mitschneiden(audio, text: str, treffer: bool) -> None:
        if audio is None or not len(audio):
            return
        ordner.mkdir(parents=True, exist_ok=True)
        zaehler["n"] += 1
        name = (f"{uhr()}_{zaehler['n']:03d}_"
                f"{'TREFFER' if treffer else 'daneben'}_{_sicherer_name(text)}.wav")
        try:
            _schreibe_wav(ordner / name, audio, samplerate)
        except Exception:
            log.debug("Diagnose-Aufnahme nicht schreibbar.", exc_info=True)
            return
        _rolle_ab(ordner)

    return mitschneiden
