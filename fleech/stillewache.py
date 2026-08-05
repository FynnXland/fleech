"""Wann ist eine laufende Aufnahme wegen einer Sprechpause zu Ende?

## Warum es das gibt

Fleech kannte zwei Wege, ein Diktat zu beenden: die Taste loslassen (Hold) oder
sie ein zweites Mal druecken (Toggle). Beide verlangen, dass man am Ende wieder
zur Tastatur greift. Der Freihand-Modus konnte es besser — er hoerte von selbst
auf —, aber nur um den Preis eines Startworts, und das hat sich als der falsche
Handel erwiesen: Ein dauerhaft offenes Mikrofon in einem Raum, in dem auch mal
ein Video laeuft, laesst sich per Sprache nicht zuverlaessig ausloesen. Jeder
Fehlstart tippt Text in das gerade fokussierte Fenster.

Der Modus „Anstupsen" nimmt die gute Haelfte: Tastendruck startet, die Stille
beendet. Ausloesen kann nur noch, wer die Taste drueckt.

## Warum dieselben Zahlen wie im Freihand-Modus

Die Fensterlaenge ist NICHT frei gewaehlt, sondern gemessen — dieselbe Messung,
die den Freihand-Modus brauchbar gemacht hat:

    Fensterlaenge   Sprache erkannt (bei laufender Rede)
    0,2 s                 0,0 %
    0,8 s                98,6 %
    1,0 s               100,0 %

Silero-VAD verlangt `min_speech_duration_ms=200`; auf einem einzelnen 0,2-s-Block
meldet es deshalb NIE Sprache. Wer hier ein kleineres Fenster nimmt, schneidet
jedes Diktat nach genau `stille_s` ab — das ist real passiert. Die Konstante wird
deshalb aus `freihand` bezogen und nicht neu hingeschrieben: zwei Stellen mit
demselben kalibrierten Wert laufen frueher oder spaeter auseinander.

Dieses Modul kennt weder Qt noch ein Audiogeraet: Es bekommt fertiges Audio und
eine VAD-Funktion hineingereicht.
"""

from __future__ import annotations

import logging

import numpy as np

from .freihand import SAMPLERATE, VAD_FENSTER_S

log = logging.getLogger(__name__)

# Vor Ablauf dieser Zeit endet nie etwas. Wer die Taste drueckt und einen Moment
# ueberlegt, bevor er losredet, soll nicht ins Leere laufen — und ganz kurze
# Aufnahmen sind ohnehin nichts, was sich zu verarbeiten lohnt.
MIN_LAUFZEIT_S = 1.5


class Stillewache:
    """Beobachtet eine laufende Aufnahme und meldet, wann sie zu Ende ist.

    Bewusst zustandsbehaftet statt einer reinen Funktion: Die Uhr, seit wann es
    still ist, muss zwischen zwei Pruefungen ueberleben. `jetzt` wird
    hineingereicht, damit Tests ohne echtes Warten auskommen.
    """

    def __init__(self, vad, stille_s: float = 2.0, samplerate: int = SAMPLERATE):
        self._vad = vad                       # callable(np.ndarray) -> bool
        self.stille_s = max(1.0, min(6.0, float(stille_s or 2.0)))
        self.samplerate = int(samplerate or SAMPLERATE)
        self._letzte_sprache = 0.0
        self._start = 0.0
        self._laeuft = False

    @property
    def laeuft(self) -> bool:
        return self._laeuft

    def start(self, jetzt: float) -> None:
        self._laeuft = True
        self._start = jetzt
        # Als haette gerade jemand gesprochen: Sonst liefe die Stille-Uhr schon
        # waehrend des Luftholens und beendete die Aufnahme, bevor sie beginnt.
        self._letzte_sprache = jetzt

    def stop(self) -> None:
        self._laeuft = False

    def fertig(self, audio, jetzt: float) -> bool:
        """Ist die Aufnahme zu Ende? `audio` ist alles bisher Aufgenommene."""
        if not self._laeuft:
            return False
        if jetzt - self._start < MIN_LAUFZEIT_S:
            return False
        if self._ist_sprache(self._fenster(audio)):
            self._letzte_sprache = jetzt
            return False
        return jetzt - self._letzte_sprache >= self.stille_s

    def stille_seit(self, jetzt: float) -> float:
        """Wie lange es schon still ist — fuer die Anzeige in der Pille."""
        if not self._laeuft:
            return 0.0
        return max(0.0, jetzt - self._letzte_sprache)

    # -- innen ------------------------------------------------------------------------

    def _fenster(self, audio) -> np.ndarray:
        """Die letzten VAD_FENSTER_S Sekunden — mehr braucht das VAD nicht, und
        das ganze Diktat zu pruefen wuerde mit jeder Sekunde teurer."""
        if audio is None or not len(audio):
            return np.zeros(0, dtype=np.float32)
        noetig = int(VAD_FENSTER_S * self.samplerate)
        return np.asarray(audio, dtype=np.float32).reshape(-1)[-noetig:]

    def _ist_sprache(self, audio) -> bool:
        if self._vad is None or not len(audio):
            # Ohne VAD gilt alles als Sprache: Der Modus endet dann nie von selbst,
            # aber er schneidet auch nie etwas ab. Von zwei Fehlern der harmlosere —
            # die Taste beendet die Aufnahme weiterhin.
            return True
        try:
            return bool(self._vad(audio))
        except Exception:
            log.debug("VAD-Fehler — Fenster gilt als Sprache.", exc_info=True)
            return True
