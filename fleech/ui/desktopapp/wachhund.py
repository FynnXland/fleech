"""Wenn die Verarbeitung ungewöhnlich lange dauert: sagen, dass sie noch läuft.

Der Anlass: Am 2026-09-24 brauchte ein Diktat 8 Minuten 31 Sekunden, weil die
Grafikkarte von fremden Programmen ausgelastet war. Die Pille zeigte die ganze Zeit
nur den Ladekreis — von „hängt" nicht zu unterscheiden. Der Nutzer hielt das Diktat
für verloren.

Gemessen an 454 Diktaten (18.08.–29.09.): Vom Sprechen bis zum eingefügten Text
vergehen im Median 2,3 s, im 95. Perzentil 9,2 s. Lange Diktate brauchen legitim
länger (645 s Audio → 43 s). Die Schwelle wächst deshalb mit der Aufnahmelänge und
liegt über dem, was im Alltag vorkommt — die Meldung erscheint nur, wenn wirklich
etwas klemmt.
"""

from __future__ import annotations

import logging
import time

from ..state import AppState

log = logging.getLogger(__name__)

GRUND_S = 12.0        # über dem 95. Perzentil der Gesamtdauer (9,2 s)
PRO_AUDIO_S = 0.05    # je Sekunde Aufnahme — 645 s Audio ergeben 44 s Schwelle


def schwelle_s(audio_s: float) -> float:
    """Ab wann eine Verarbeitung als ungewöhnlich lang gilt."""
    return GRUND_S + PRO_AUDIO_S * max(0.0, audio_s)


def meldung(dauer_s: float) -> str:
    minuten, sekunden = divmod(int(dauer_s), 60)
    return f"Dauert länger als üblich … {minuten}:{sekunden:02d}"


class WachhundMixin:
    def _baue_wachhund(self) -> None:
        """Einmal beim Start. QTimer OHNE Parent: `DesktopApp` ist kein QObject —
        `QTimer(self)` hat hier schon einmal den Start verhindert (CLAUDE.md)."""
        from PySide6.QtCore import QTimer

        uhr = QTimer()
        uhr.setInterval(1000)
        uhr.timeout.connect(self._wachhund_tick)
        self._wachhund = uhr
        self._verarbeitung_seit = None
        self._wachhund_gemeldet = False
        self.bus.state_changed.connect(self._wachhund_zustand)

    def _wachhund_zustand(self, state) -> None:
        if state is AppState.PROCESSING:
            if self._verarbeitung_seit is None:
                self._verarbeitung_seit = time.monotonic()
                self._wachhund_gemeldet = False
            self._wachhund.start()
        else:
            if self._wachhund_gemeldet and self._verarbeitung_seit is not None:
                log.info("Verarbeitung dauerte %.0f s (ungewoehnlich lang).",
                         time.monotonic() - self._verarbeitung_seit)
            self._verarbeitung_seit = None
            self._wachhund.stop()

    def _wachhund_tick(self) -> None:
        seit = self._verarbeitung_seit
        if seit is None:
            return
        dauer = time.monotonic() - seit
        audio = getattr(self, "_letzte_aufnahme", None)
        rate = getattr(getattr(getattr(self, "config", None), "audio", None),
                       "samplerate", 16000) or 16000
        audio_s = (len(audio) / rate) if audio is not None else 0.0
        if dauer < schwelle_s(audio_s):
            return
        if not self._wachhund_gemeldet:
            self._wachhund_gemeldet = True
            log.warning("Verarbeitung laeuft seit %.0f s (%.0f s Audio) — "
                        "ungewoehnlich lang.", dauer, audio_s)
        self.bus.progress.emit(meldung(dauer))
