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
        """Dauerlauschen aufbauen — im Hintergrund, weil ein Modell geladen wird.

        Standardmaessig aus: Eine App, die ungefragt dauerhaft mithoert, waere ein
        Vertrauensbruch, auch wenn technisch nichts gespeichert wird.

        Seit 5.10.1 ausserdem STILLGELEGT (`freihand.STILLGELEGT`) — der Riegel
        steht hier und nicht in der Oberflaeche, damit auch eine bestehende
        `settings.json` mit `aktiv: true` und der Tray-Schnellschalter davon
        erfasst sind. Ein einziges `False` in `fleech/freihand.py` macht den Modus
        wieder verfuegbar.
        """
        from ...freihand import STILLGELEGT

        if STILLGELEGT:
            if self.settings.freihand.aktiv:
                log.info("Freihand ist vorerst stillgelegt — Einstellung wird "
                         "ignoriert (siehe freihand.STILLGELEGT).")
            self.bus.freihand_zustand.emit("aus")
            return
        if not self.settings.freihand.aktiv:
            return

        def bauen():
            try:
                from ...freihand import (
                    Einstellungen, FreihandStream, Lauscher, baue_erkenner,
                    baue_erkenner_aus_engine, baue_vad,
                )

                s = self.settings.freihand
                lauscher = Lauscher(
                    Einstellungen(
                        aktiv=True, startwort=s.startwort,
                        abbruchwort=s.abbruchwort, stille_s=s.stille_s,
                        ausgeschlossene_apps=tuple(s.ausgeschlossene_apps or ()),
                    ),
                    vad=baue_vad(),
                    erkenner=self._baue_startwort_erkenner(s),
                    mitschnitt=self._baue_freihand_mitschnitt(s),
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

    # `toggle_freihand` (Tray-Schnellschalter) ist mit der Freihand-Oberflaeche in
    # 5.11.0 entfallen: Der Eintrag meldete einen Zustand, den der stillgelegte
    # Modus nicht mehr einnehmen kann (Befund E-8). Es gibt seither keinen Weg
    # mehr, `freihand.aktiv` zur Laufzeit umzustellen — genau das ist der Zweck.

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

    def _baue_freihand_mitschnitt(self, s):
        """Diagnose-Aufzeichnung, oder None (der Normalfall).

        Getrennt vom Erkenner, damit im ausgeschalteten Zustand wirklich NICHTS
        an Datei-Code in der Nähe des Audios steht.
        """
        if not getattr(s, "diagnose", False):
            return None
        from ...freihand_diagnose import ORDNER_NAME, baue_mitschnitt
        from ...platformpaths import user_data_dir

        ordner = user_data_dir() / ORDNER_NAME
        log.warning("Freihand-DIAGNOSE ist an — geprüfte Fenster landen als WAV "
                    "in %s. Nach der Fehlersuche wieder ausschalten.", ordner)
        return baue_mitschnitt(ordner, samplerate=self.config.audio.samplerate)

    def _baue_startwort_erkenner(self, s):
        """Wer prueft auf das Startwort — das Diktat-Modell oder ein eigenes?

        „diktat" ist seit 5.7.0 die Vorgabe: dasselbe Modell, das ohnehin geladen
        ist. Ein eigenes kleines Modell bleibt waehlbar fuer Rechner ohne
        brauchbare GPU. Faellt der Weg ueber die Engine aus (kein
        faster-whisper-Backend), wird auf `base` zurueckgefallen statt Freihand
        ganz abzuschalten.
        """
        from ...freihand import baue_erkenner, baue_erkenner_aus_engine

        gewuenscht = (getattr(s, "modell", "diktat") or "diktat").strip().lower()
        sprache = self.settings.general.language
        if gewuenscht == "diktat":
            engine = getattr(self.pipeline, "stt", None)
            if engine is not None and hasattr(engine, "transcribe_kurz"):
                log.info("Freihand prueft mit dem Diktat-Modell.")
                return baue_erkenner_aus_engine(
                    engine, sprache=sprache, startwort=s.startwort)
            log.warning("Freihand: Diktat-Modell nicht nutzbar — nehme 'base'.")
            gewuenscht = "base"
        log.info("Freihand prueft mit eigenem Modell %r (CPU).", gewuenscht)
        return baue_erkenner(modell_groesse=gewuenscht, sprache=sprache,
                             startwort=s.startwort)

    def _erkenne_probe(self, audio):
        """Erkennung für die Wortprobe — mit demselben Priming wie im Diktat.

        Der `initial_prompt` ist der Punkt: Er ist genau das, was das Wörterbuch
        bewirkt. Ohne ihn würde der Test messen, wie gut Whisper das Wort OHNE
        Wörterbuch versteht — also das Gegenteil der Frage."""
        p = self.pipeline
        with p._stt_lock:
            return p.stt.transcribe(
                audio, self.config.audio.samplerate,
                initial_prompt=getattr(p, "_vocab_prompt", None),
            ) or ""

    def _erkenne_startwort(self, audio):
        """Erkennung für die Startwort-Probe — exakt der Freihand-Weg.

        Nicht der Diktat-Weg: Freihand prüft mit `beam_size=1`, abgeschnittener
        Stille und dem Startwort als `initial_prompt`. Mit dem Diktat-Weg zu
        messen hiesse, eine Frage zu beantworten, die niemand gestellt hat.

        Läuft Freihand gerade, wird DESSEN Erkenner genommen — dieselbe Instanz,
        die im Betrieb entscheidet. Sonst wird einer gebaut; bei einem eigenen
        kleinen Modell kostet das beim ersten Mal ein paar Sekunden Ladezeit.
        """
        lauscher = getattr(getattr(self, "_freihand", None), "lauscher", None)
        laufender = getattr(lauscher, "erkenner", None)
        if laufender is not None:
            return laufender(audio) or ""
        return self._baue_startwort_erkenner(self.settings.freihand)(audio) or ""

    def _freihand_lauscher(self):
        """Der Lauscher, wenn Freihand gerade AUFNIMMT — sonst None.

        Die Pille kennt nur einen Zustand „Aufnahme laeuft" und weiss nicht, auf
        welchem Weg sie zustande kam. Bis 5.8.2 wirkten alle drei Knoepfe
        ausschliesslich auf den `RecordingController` — beim Freihand-Diktat
        laeuft der aber gar nicht, also tat kein einziger Knopf etwas.
        """
        from ...freihand import Zustand

        lauscher = getattr(getattr(self, "_freihand", None), "lauscher", None)
        if lauscher is not None and lauscher.zustand is Zustand.AUFNAHME:
            return lauscher
        return None

    def wortprobe(self, begriff: str, sekunden: float = 3.0,
                  zweck: str = "woerterbuch"):
        """Ein Wort einsprechen lassen und prüfen, ob es ankommt.

        Läuft über DIESELBE Erkennung wie im Alltag — beim Wörterbuch mit dem
        Wörterbuch-Priming, beim Startwort über den Weg, den Freihand geht. Ein
        Test, der anders erkennt als der Betrieb, misst die falsche Frage.

        Blockiert bewusst, solange aufgenommen wird: Der Dialog wartet auf das
        Ergebnis, und zwei parallele Aufnahmen auf demselben Mikrofon wären ein
        Gerätekonflikt.
        """
        import time as _time

        from ...wortprobe import Ergebnis, Probe, pruefe_audio

        if self.controller.active:
            # Ein laufendes Diktat hat Vorrang — das Mikrofon gehoert ihm.
            return Probe(Ergebnis.NICHTS, "", begriff, zweck)
        # Freihand hoert am selben Mikrofon mit. Ohne Pause liefe die Probe
        # Gefahr, das eigene Startwort auszuloesen — mitten im Test.
        freihand = getattr(self, "_freihand", None)
        if freihand is not None:
            freihand.pausiere(True)
        self.recorder.start()
        try:
            _time.sleep(max(0.5, min(10.0, float(sekunden))))
        finally:
            audio = self.recorder.stop()
            if freihand is not None:
                freihand.pausiere(False)
        erkenne = (self._erkenne_startwort if zweck == "startwort"
                   else self._erkenne_probe)
        return pruefe_audio(
            audio, begriff, erkenne,
            samplerate=self.config.audio.samplerate, zweck=zweck,
        )
