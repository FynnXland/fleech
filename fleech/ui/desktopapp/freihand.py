"""Freihand: diktieren ohne Taste — Startwort hoeren, aufnehmen, einfuegen.

Laeuft als eigener Dauerlauscher neben dem normalen Push-to-Talk. Alles
hier ist Best-Effort: Faellt Freihand aus, darf das gedrueckte Diktat
unbeeindruckt weiterlaufen (`_on_freihand_fehler` schaltet ab statt zu
reissen).

Mixin statt eigener Klasse: Der Zustand (settings, overlay, pipeline, recorder)
liegt weiter auf EINEM Objekt. Ein eigenes Controller-Objekt haette neue
Referenzen in den Qt-Objektgraphen gelegt — genau die Konstellation, die in
diesem Projekt schon zu GC-Reihenfolge-Abstuerzen gefuehrt hat.
"""

from __future__ import annotations

import logging
import threading

from ...audio import Recorder
from ..state import AppState, StateBus

log = logging.getLogger(__name__)

class FreihandMixin:
    def _starte_freihand(self) -> None:
        """Dauerlauschen aufbauen — im Hintergrund, weil tiny geladen werden muss.

        Standardmaessig aus: Eine App, die ungefragt dauerhaft mithoert, waere ein
        Vertrauensbruch, auch wenn technisch nichts gespeichert wird.
        """
        if not self.settings.freihand.aktiv:
            return

        def bauen():
            try:
                from ...freihand import (
                    Einstellungen, FreihandStream, Lauscher, baue_erkenner, baue_vad,
                )

                s = self.settings.freihand
                lauscher = Lauscher(
                    Einstellungen(
                        aktiv=True, startwort=s.startwort,
                        abbruchwort=s.abbruchwort, stille_s=s.stille_s,
                        ausgeschlossene_apps=tuple(s.ausgeschlossene_apps or ()),
                    ),
                    vad=baue_vad(),
                    erkenner=baue_erkenner(
                        modell_groesse=getattr(s, "modell", "base") or "base",
                        sprache=self.settings.general.language,
                        startwort=s.startwort,
                    ),
                )
                self._freihand = FreihandStream(
                    lauscher, self._freihand_ereignis,
                    geraet=self.settings.recording.microphone,
                )
                if self._freihand.start():
                    self.bus.freihand_zustand.emit("lauscht")
                else:
                    # SICHTBAR machen. Vorher stand der Fehlschlag nur im Log:
                    # Der Schalter blieb an, der Punkt zeigte „lauscht" nie, und
                    # es gab keinen Hinweis, warum nichts passiert — man haelt
                    # dann das Startwort fuer das Problem und probiert andere aus.
                    self._freihand = None
                    self.bus.freihand_zustand.emit("aus")
                    self.bus.freihand_fehler.emit(
                        "Mikrofon liess sich nicht oeffnen")
            except Exception as fehler:
                log.exception("Freihand-Modus nicht startbar.")
                self._freihand = None
                self.bus.freihand_zustand.emit("aus")
                self.bus.freihand_fehler.emit(str(fehler) or "unbekannter Fehler")

        threading.Thread(target=bauen, daemon=True).start()

    def _stoppe_freihand(self) -> None:
        strom = getattr(self, "_freihand", None)
        if strom is not None:
            strom.stop()
        self._freihand = None
        self.bus.freihand_zustand.emit("aus")

    def toggle_freihand(self) -> None:
        """Schnellschalter (Tray/Hotkey): sofort aufhoeren mitzuhoeren.

        Der Nutzer muss das Lauschen jederzeit mit einem Griff beenden koennen —
        ohne Einstellungen zu oeffnen und ohne zu suchen.
        """
        an = not self.settings.freihand.aktiv
        self.settings.freihand.aktiv = an
        self.settings.save()
        try:
            self.tray.set_freihand(an, self.settings.freihand.startwort)
        except Exception:
            log.debug("Tray-Text nicht aktualisierbar.", exc_info=True)
        if an:
            self._starte_freihand()
            self._flash_status("Freihand an — sag „%s“" % self.settings.freihand.startwort)
        else:
            self._stoppe_freihand()
            self._flash_status("Freihand aus")

    def _freihand_ereignis(self, ereignis, audio) -> None:
        """AUDIO-THREAD! Nur weiterreichen — alles andere gehoert in den UI-Thread."""
        if audio is not None and len(audio):
            self._freihand_audio = audio
        self.bus.freihand_ereignis.emit(ereignis.value)

    def _on_freihand(self, ereignis: str) -> None:
        """UI-Thread: auf ein Freihand-Ereignis reagieren."""
        if ereignis == "start":
            if not self._freihand_erlaubt():
                return
            self.bus.freihand_zustand.emit("aufnahme")
            self.bus.set_state(AppState.LISTENING)
            self.notifier.sound("start")
            prozess, titel = self._freihand_ziel()
            self._record_app, self._record_title = prozess, titel
            # Live-Vorschau auch hier: Sie hing bisher nur am Hotkey-Weg, beim
            # Freihand-Diktat blieb die Pille stumm und man wusste bis zum Ende
            # nicht, ob etwas ankommt.
            if self.settings.overlay.live_preview:
                self._start_preview_async()
            return
        if ereignis == "abbruch":
            self._freihand_audio = None
            self._stop_preview()
            self.bus.freihand_zustand.emit("lauscht")
            self.bus.set_state(AppState.IDLE)
            self._flash_status("Verworfen")
            return
        # ENDE: wie ein normales Diktat weiterverarbeiten.
        audio, self._freihand_audio = getattr(self, "_freihand_audio", None), None
        self._stop_preview()
        self.bus.freihand_zustand.emit("lauscht")
        if audio is None or not len(audio):
            self.bus.set_state(AppState.IDLE)
            return
        self.notifier.sound("stop")
        self.bus.set_state(AppState.PROCESSING)
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _freihand_ziel(self):
        from ..windowsfocus import foreground_now

        return foreground_now()

    def _freihand_erlaubt(self) -> bool:
        """In dieser App lauschen? Spiele und Meetings stehen auf der Sperrliste."""
        strom = getattr(self, "_freihand", None)
        if strom is None:
            return False
        prozess = self._freihand_ziel()[0]
        if not strom.lauscher.app_erlaubt(prozess):
            log.info("Freihand in %s ausgeschlossen — Aktivierung verworfen.", prozess)
            self.bus.freihand_zustand.emit("lauscht")
            return False
        return True

    def _laufendes_audio(self):
        """Bisher aufgenommenes Audio — egal ob per Hotkey oder per Freihand.

        Die Live-Vorschau hing allein am Recorder. Beim Freihand-Diktat laeuft der
        nicht, sie blieb deshalb leer: Man sah beim Sprechen nichts und wusste bis
        zum Ende nicht, ob ueberhaupt etwas ankommt.
        """
        import numpy as _np

        eigenes = self.recorder.snapshot()
        if eigenes is not None and len(eigenes):
            return eigenes
        strom = getattr(self, "_freihand", None)
        lauscher = getattr(strom, "lauscher", None)
        if lauscher is None:
            return eigenes
        try:
            return lauscher.aufnahme_audio()
        except Exception:
            log.debug("Freihand-Audio fuer die Vorschau nicht lesbar.", exc_info=True)
            return _np.zeros(0, dtype=_np.float32)

    def _freihand_level(self) -> float:
        """Eingangspegel des Freihand-Stroms, 0.0 wenn er nicht laeuft.

        Wird aus dem Zeichentakt der Pille aufgerufen (mehrmals je Sekunde) und
        muss deshalb billig und still sein — ein Fehler hier duerfte niemals die
        Anzeige stoppen."""
        strom = getattr(self, "_freihand", None)
        try:
            return float(getattr(strom, "level", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _on_freihand_fehler(self, grund: str) -> None:
        """UI-Thread: Freihand liess sich nicht starten — das muss man SEHEN.

        Der Aufbau laeuft im Hintergrund-Thread, deshalb kommt die Meldung ueber
        den StateBus hier an. Vorher landete so ein Fehlschlag nur im Log: Der
        Schalter stand auf an, der Punkt zeigte nie „lauscht", und nichts sagte
        warum — man sucht den Fehler dann beim Startwort und probiert andere aus,
        obwohl das Mikrofon nie geoeffnet wurde.
        """
        log.warning("Freihand nicht gestartet: %s", grund)
        try:
            self.notifier.toast(
                "background_info", "Freihand konnte nicht starten",
                "Das Mikrofon liess sich nicht öffnen. Prüfe die Mikrofon-Auswahl "
                "in den Einstellungen.",
                bypass_cooldown=True,
            )
        except Exception:
            log.debug("Freihand-Fehlermeldung nicht zeigbar.", exc_info=True)
        try:
            self.tray.set_freihand(False, self.settings.freihand.startwort)
        except Exception:
            log.debug("Tray-Text nicht setzbar.", exc_info=True)
