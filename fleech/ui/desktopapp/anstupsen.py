"""Anstupsen: die Stille-Wache, die im Nudge-Modus das Ende der Rede erkennt.

Aus `desktop.py` hierher gezogen (5.10.5): drei zusammengehoerige Methoden mit
eigenem Zustand (`_stillewache`, `_stillewache_laedt`, `_nudge_timer`) — ein Thema,
kein Kern-Lebenszyklus. Der Aufnahmeweg selbst (`_on_record_start`/`_process_locked`)
bleibt in `desktop.py`; von hier aus wird nur `controller.stop_if_active()` gerufen.

Mixin statt eigener Klasse — aus demselben Grund wie die uebrigen Teilgebiete
(siehe `desktopapp/__init__.py`).
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class AnstupsenMixin:
    """Stille-Wache des Anstupsen-Modus: Timer, VAD-Laden, Tick."""

    def _nudge_tick(self) -> None:
        """GUI-Thread. Nur billige Arbeit: VAD auf einer Sekunde Audio (1–4 ms)."""
        try:
            if self.settings.recording.mode != "nudge" or not self.controller.active:
                wache = getattr(self, "_stillewache", None)
                if wache is not None and wache.laeuft:
                    wache.stop()
                return
            wache = self._hole_stillewache()
            if wache is None:
                return
            jetzt = time.monotonic()
            if not wache.laeuft:
                wache.start(jetzt)
                return
            if self.recorder.paused:
                # Pause heisst ausdruecklich „ich rede gerade woanders" — genau
                # dann darf die Stille das Diktat nicht beenden.
                wache.start(jetzt)
                return
            from ...freihand import VAD_FENSTER_S

            if wache.fertig(self.recorder.tail(VAD_FENSTER_S), jetzt):
                log.info("Anstupsen: %.1f s still — Diktat beendet.", wache.stille_s)
                wache.stop()
                self.controller.stop_if_active()
        except Exception:
            log.exception("Stille-Wache fehlgeschlagen — Aufnahme laeuft weiter.")

    def _starte_stille_wache(self) -> None:
        """Timer, der im Anstupsen-Modus auf das Ende der Rede achtet.

        Laeuft DAUERHAFT und prueft selbst, ob gerade etwas zu tun ist — statt
        beim Aufnahmestart gestartet zu werden. Grund: `_on_record_start` laeuft
        im pynput-Listener-Thread, und ein QTimer darf nur aus dem GUI-Thread
        gestartet werden. Ein Tick, der sofort mit „laeuft nichts" zurueckkommt,
        kostet nichts.
        """
        from PySide6.QtCore import QTimer

        self._stillewache = None
        self._stillewache_laedt = False
        # OHNE Parent: `DesktopApp` ist kein QObject, sondern die einfache Klasse,
        # die alles verdrahtet. `QTimer(self)` wirft deshalb beim Start —
        # genau wie die anderen Timer hier steht er ohne Parent und wird ueber
        # das Attribut am Leben gehalten.
        self._nudge_timer = QTimer()
        self._nudge_timer.setInterval(300)
        self._nudge_timer.timeout.connect(self._nudge_tick)
        self._nudge_timer.start()

    def _hole_stillewache(self):
        """Die Wache, oder None solange das VAD noch laedt.

        Silero kommt aus faster-whisper und braucht beim ersten Zugriff einen
        Moment. Das im GUI-Thread zu tun wuerde die Oberflaeche einfrieren —
        genau in dem Augenblick, in dem der Nutzer gerade zu sprechen anfaengt.
        """
        wache = getattr(self, "_stillewache", None)
        if wache is not None:
            wache.stille_s = self.settings.freihand.stille_s
            return wache
        if self._stillewache_laedt:
            return None
        self._stillewache_laedt = True

        def laden():
            try:
                import numpy as _np

                from ...freihand import SAMPLERATE, baue_vad
                from ...stillewache import Stillewache

                vad = baue_vad()
                # Einmal warmlaufen lassen — HIER, im Hintergrund. Gemessen kostet
                # der erste Aufruf 185 ms, jeder weitere 1,4 ms. Diese 185 ms im
                # GUI-Thread waeren ein sichtbarer Hänger, genau in dem Moment, in
                # dem der Nutzer zu sprechen anfaengt.
                vad(_np.zeros(SAMPLERATE, dtype=_np.float32))
                self._stillewache = Stillewache(
                    vad, stille_s=self.settings.freihand.stille_s,
                    samplerate=self.config.audio.samplerate)
                log.info("Stille-Wache bereit (Anstupsen-Modus).")
            except Exception:
                log.exception("Stille-Wache nicht ladbar — Anstupsen endet nur "
                              "per Tastendruck.")
            finally:
                self._stillewache_laedt = False

        threading.Thread(target=laden, daemon=True).start()
        return None
