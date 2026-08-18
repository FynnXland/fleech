"""Kein-Ton-Wache: melden, dass das Mikrofon nichts liefert — waehrend des Diktats.

Befund H-B2: Von 1603 Aufnahmen blieben 198 ohne jedes Transkript, weil schlicht
kein Ton ankam — im schlimmsten belegten Fall nach 163 Sekunden Rede, die danach
nirgends mehr existiert. Der Pegel war die ganze Zeit bekannt (`Recorder.level`),
wurde aber nur benutzt, um die Wellenlinie zu zeichnen. Und die taeuscht: Ihre
Automatik verstaerkt blosses Rauschen bis 45-fach, ein totes Mikrofon sieht dort
aus wie ein leises, funktionierendes.

Die Wache haengt bewusst im Takt, den es schon gibt — der Waveform-Timer der
Pille fragt alle 50 ms den Pegel ab, im GUI-Thread. Kein eigener Timer, kein
eigener Thread, und die Pruefung laeuft genau dann, wenn sie gebraucht wird:
waehrend einer Aufnahme mit sichtbarer Pille.

Mixin statt eigener Klasse — aus demselben Grund wie die uebrigen Teilgebiete
(siehe `desktopapp/__init__.py`).
"""

from __future__ import annotations

import logging

from ..overlaypille.konstanten import (
    KEIN_TON_AB_S,
    KEIN_TON_FENSTER_S,
    KEIN_TON_SCHWELLE,
)

log = logging.getLogger(__name__)


class KeinTonMixin:
    # Vom Mikrofon kam in DIESER Aufnahme nichts — genau einmal gemeldet,
    # zurueckgesetzt in `_on_record_start`. Bewusst als Klassenvorgabe und nicht
    # in `DesktopApp.__init__`: Der Konstruktor traegt schon die halbe App, und
    # das Feld gehoert zu diesem Teilgebiet (der `level_provider` der Pille liest
    # es, bevor je eine Aufnahme lief).
    _kein_ton_gemeldet = False

    def _pegel_fuer_pille(self) -> float:
        """Pegel fuer die Wellenlinie — und im selben Takt die Kein-Ton-Wache.

        Beide Aufnahmewege liefern hier ihren Pegel: Beim Freihand-Diktat laeuft
        der Recorder nicht, sein Pegel bliebe 0 und die Pille zeigte eine tote
        Linie, obwohl aufgenommen wird.

        Die Wache ist bewusst gekapselt: Wirft sie, darf das nicht die Anzeige
        mitreissen (die Waveform schluckt Fehler ohnehin, aber dann waere auch
        der Pegel weg).
        """
        try:
            self._pruefe_kein_ton()
        except Exception:
            log.debug("Kein-Ton-Wache fehlgeschlagen.", exc_info=True)
        return max(self.recorder.level, self._freihand_level())

    def _pruefe_kein_ton(self) -> None:
        """Laeuft im GUI-Thread. Warnt genau einmal je Aufnahme, stoppt nichts."""
        if not self.recorder.recording or self.recorder.paused:
            # Pause heisst „ich rede gerade absichtlich nicht"; beim Freihand-Weg
            # laeuft der Recorder gar nicht. In beiden Faellen waere die Warnung
            # falsch — und eine stehende muss weg.
            self.overlay.set_kein_ton(False)
            return
        if self.recorder.position < KEIN_TON_AB_S:
            return  # am Anfang ist Stille normal (Taste gedrueckt, Luft geholt)
        pegel = self.recorder.rohpegel_max(KEIN_TON_FENSTER_S)
        if pegel >= KEIN_TON_SCHWELLE:
            # Es kommt (wieder) Ton — eine stehende Warnung nimmt sich zurueck.
            self.overlay.set_kein_ton(False)
            return
        if self._kein_ton_gemeldet:
            return  # genau EINMAL je Aufnahme: eine Warnung, kein Dauerfeuer
        self._kein_ton_gemeldet = True
        log.warning(
            "Kein Ton vom Mikrofon: lautester Rohpegel %.5f in %.0f s "
            "(Schwelle %.4f) — Geraet pruefen.",
            pegel, KEIN_TON_FENSTER_S, KEIN_TON_SCHWELLE,
        )
        self.overlay.set_kein_ton(True)
