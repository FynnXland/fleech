"""Was nach dem fertigen Diktat passiert: zuruecknehmen, senden, neu machen.

Dazu die selbstlernende Seite des Woerterbuchs — wie oft ein Begriff
wirklich vorkam (steuert das Whisper-Priming) und welche Woerter einem
bekannten Begriff verdaechtig aehnlich sehen (`find_dictionary_candidates`).
Beides braucht den FERTIGEN Text und gehoert deshalb hierher, nicht in die
Pipeline.

Mixin statt eigener Klasse: Der Zustand (settings, overlay, pipeline, recorder)
liegt weiter auf EINEM Objekt. Ein eigenes Controller-Objekt haette neue
Referenzen in den Qt-Objektgraphen gelegt — genau die Konstellation, die in
diesem Projekt schon zu GC-Reihenfolge-Abstuerzen gefuehrt hat.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

class NachbereitungMixin:
    def _count_dictionary_usage(self, text: str) -> None:
        """Zaehlt, welche Woerterbuch-Begriffe tatsaechlich im eingefuegten Text
        vorkamen. Daraus entscheidet sich, welche Begriffe ueber dem 60er-Limit
        ins Whisper-Priming kommen — die genutzten statt der zufaellig obersten."""
        from ...dictionary import find_terms_in_text

        try:
            hits = find_terms_in_text(text, self.pipeline.vocab_terms)
        except Exception:
            log.debug("Woerterbuch-Nutzungszaehlung fehlgeschlagen.", exc_info=True)
            return
        if not hits:
            return
        usage = self.settings.output.dictionary_usage
        for term in hits:
            key = term.lower()
            usage[key] = int(usage.get(key, 0)) + 1
        self.settings.save()

    def _check_dictionary_candidates(self, text: str) -> None:
        """Wahrscheinliche Fehlschreibung eines Woerterbuch-Begriffs erkannt →
        Rueckfrage ausloesen (selbstlernendes Woerterbuch). Nur der erste Treffer
        pro Diktat, abgelehnte Paare werden nie erneut gefragt."""
        import re as _re

        from ...dictionary import find_dictionary_candidates

        try:
            candidates = find_dictionary_candidates(
                text, self.pipeline.vocab_terms,
                self.settings.output.dictionary_ignores,
            )
        except Exception:
            log.debug("Woerterbuch-Kandidaten-Suche fehlgeschlagen.", exc_info=True)
            return
        if not candidates:
            return
        recognized, meant = candidates[0]
        sentence = next(
            (s.strip() for s in _re.split(r"(?<=[.!?])\s+", text)
             if recognized in s),
            text[:160],
        )
        self.bus.dictionary_suggestion.emit(recognized, meant, sentence)

    def _on_dictionary_suggestion(self, recognized: str, meant: str, sentence: str) -> None:
        from ..main_window import DictionarySuggestionDialog

        def learn(rec: str, target: str) -> None:
            self.settings.output.dictionary.append(f"{rec} => {target}")
            self.settings.save()
            self.pipeline.set_dictionary(self.settings.output.dictionary,
                                         self.settings.output.dictionary_usage)
            self.tray.notify("Fleech", f"Gelernt: „{rec}“ → „{target}“.")

        def ignore(rec: str, target: str) -> None:
            self.settings.output.dictionary_ignores.append(
                f"{rec.lower()} => {target.lower()}"
            )
            self.settings.save()

        self._dict_dialog = DictionarySuggestionDialog(
            recognized, meant, sentence, learn, ignore
        )
        self._dict_dialog.show()
        self._dict_dialog.raise_()

    def _undo_last_output(self) -> None:
        """Die letzte Ausgabe durch das ROH-Transkript ersetzen.

        Kein allgemeines "Rueckgaengig", sondern gezielt der Weg fuer den Fall, dass
        die Bereinigung danebengriff: Es kommt Wort fuer Wort das zurueck, was
        gesprochen wurde. Loeschen kann der Nutzer danach mit dem Undo seiner App.

        Drei harte Bedingungen, alle aus einem echten Datenverlust gelernt (ein Befehl
        loeschte einmal 2701 Zeichen ersatzlos): Es muss eine eigene, frische Ausgabe
        geben, der Cursor muss noch dahinter stehen (`resolve_scope` liefert bei
        gewechseltem Fenster None), und jede Ausgabe laesst sich nur EINMAL ersetzen.

        Das eigentliche Ersetzen laeuft im Worker-Thread (Befund B-9/D-9): Die
        Backspaces kosten 4 ms pro Zeichen — bei einem mittleren Diktat 1,3 s, im
        Maximum 23 s. Dieser Aufruf kommt aus dem pynput-Listener; so lange waeren
        dort ALLE weiteren Fleech-Hotkeys blockiert (auch der Diktat-Hotkey).
        """
        kandidat = getattr(self, "_undo_candidate", None)
        if not kandidat:
            self._flash_status("Nichts zum Zurücknehmen")
            return
        injected, raw, ts = kandidat
        if time.monotonic() - ts > self._UNDO_MAX_AGE_S:
            self._undo_candidate = None
            self._flash_status("Letzte Ausgabe ist zu lange her")
            return
        raw = (raw or "").strip()
        if not raw or raw == injected:
            self._flash_status("Rohtext ist identisch")
            return
        # Steht der Cursor noch hinter unserem Text? Nach Fensterwechsel ist die
        # Position unbekannt — dann wird NICHT geloescht.
        # Befund B-1/D-3: `resolve_scope` arbeitet auf dem Fenster, das der Tracker
        # zuletzt gesehen hat, und nachgefuehrt wird das NUR beim Verarbeiten eines
        # Diktats. Ohne diesen Abgleich hielt die Wache nach einem Fensterwechsel
        # faelschlich — die Backspaces gingen in ein fremdes Dokument.
        self.pipeline.tracker.sync_window()
        if self.pipeline.tracker.resolve_scope("dictated") is None:
            self._undo_candidate = None
            self._flash_status("Cursor nicht mehr an der Stelle")
            return

        if self._process_lock.locked():
            # Ein Diktat wird gerade eingefuegt — dazwischenzufunken hiesse, an einer
            # Stelle zu loeschen, die sich im selben Moment verschiebt.
            self._flash_status("Verarbeitung läuft — bitte kurz warten")
            return

        self._undo_candidate = None          # nur ein Versuch je Ausgabe

        def arbeit():
            try:
                with self._process_lock:     # nie parallel zu einem laufenden Diktat
                    self.pipeline.injector.replace_tail(len(injected), raw)
                    self.pipeline.tracker.record_replace(len(injected), raw)
            except Exception:
                log.exception("Rueckgaengig fehlgeschlagen.")
                self._flash_status("Zurücknehmen fehlgeschlagen — Log prüfen")
                return
            log.info("Letzte Ausgabe durch Rohtext ersetzt (%d → %d Zeichen).",
                     len(injected), len(raw))
            self.notifier.sound("commit")
            self._flash_status("Rohtext eingesetzt")

        threading.Thread(target=arbeit, daemon=True).start()

    def _auto_send(self) -> None:
        """Enter nachschicken (Profil-Einstellung „Nachricht absenden").

        Fehler hier duerfen das Diktat nie nachtraeglich zum Fehlschlag machen —
        der Text steht bereits im Feld, nur das Absenden hat nicht geklappt.
        """
        try:
            self.pipeline.injector.send_enter()
            log.info("Automatisch abgeschickt (Profil-Einstellung).")
        except Exception:
            log.exception("Automatisches Absenden fehlgeschlagen — Text steht im Feld.")
            self._flash_status("Absenden fehlgeschlagen")

    # -- Die letzte Aufnahme (V-15) ----------------------------------------------------
    #
    # `_letzte_aufnahme` haelt genau EIN Audio-Array (16 kHz float32), gesetzt in
    # `DesktopApp._process` und dort bei der naechsten Aufnahme ersetzt. Nie auf
    # Platte — ausser der Nutzer sichert ausdruecklich. Der Grund: 198 von 1603
    # Aufnahmen (12,4 %) lieferten ein leeres Transkript, 24 davon mit ueber 5 s
    # Audio, die laengste 163 s. Bis 5.10.4 war die Aufnahme danach weg, und
    # „nochmal erkennen" hiess „nochmal sprechen".

    def _letzte_aufnahme_oder_meldung(self):
        audio = getattr(self, "_letzte_aufnahme", None)
        if audio is None or not len(audio):
            self._flash_status("Keine Aufnahme im Speicher")
            return None
        return audio

    def _erneut_erkennen(self) -> None:
        """Die letzte Aufnahme noch einmal durch dieselbe Verarbeitung schicken.

        Bewusst derselbe Weg wie ein frisches Diktat (`_process`, im Worker, unter
        `_process_lock`) und kein zweiter: Das Ergebnis soll sich in nichts von
        einem Diktat unterscheiden — inklusive Verlaufseintrag, Guards, Pille und
        Einfuegen. Sinnvoll wird das vor allem, wenn zwischendurch etwas anders
        ist: ein anderes Profil, ein ergaenztes Woerterbuch, ein Ollama, das
        wieder laeuft.
        """
        audio = self._letzte_aufnahme_oder_meldung()
        if audio is None:
            return
        if self._process_lock.locked():
            self._flash_status("Ein Diktat läuft noch")
            return
        from ..state import AppState

        log.info("Letzte Aufnahme wird erneut erkannt (%d Samples).", len(audio))
        self.bus.set_state(AppState.PROCESSING)
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _letzte_aufnahme_sichern(self) -> None:
        """Die letzte Aufnahme als WAV-Datei ablegen (Dateidialog, GUI-Thread)."""
        from PySide6.QtWidgets import QFileDialog

        audio = self._letzte_aufnahme_oder_meldung()
        if audio is None:
            return
        vorschlag = f"fleech-aufnahme-{time.strftime('%Y-%m-%d-%H%M%S')}.wav"
        pfad, _filter = QFileDialog.getSaveFileName(
            None, "Letzte Aufnahme sichern", vorschlag, "WAV-Datei (*.wav)")
        if not pfad:
            return
        self._schreibe_wav(pfad, audio)

    def _schreibe_wav(self, pfad, audio) -> bool:
        """Getrennt vom Dateidialog, damit der Inhalt pruefbar ist, ohne eine
        blockierende Qt-Event-Loop zu starten."""
        from pathlib import Path

        from ...audio import audio_to_wav_bytes

        try:
            rate = self.config.audio.samplerate
            Path(pfad).write_bytes(audio_to_wav_bytes(audio, rate))
        except Exception:
            log.exception("Aufnahme konnte nicht gesichert werden: %s", pfad)
            self._flash_status("Sichern fehlgeschlagen — Log prüfen")
            return False
        log.info("Letzte Aufnahme gesichert: %s", pfad)
        self._flash_status("Aufnahme gesichert")
        return True

    def _reprocess_entry(self, roh: str, fmt: str, name: str) -> None:
        """Ein gespeichertes Diktat neu bereinigen lassen. Laeuft im Worker-Thread.

        Das Ergebnis geht in die ZWISCHENABLAGE. Wer im Verlauf rechtsklickt, steht
        im Fleech-Fenster — das urspruengliche Zielfeld ist laengst nicht mehr
        fokussiert. Blind dorthin zu schreiben ist genau die Fehlerklasse, aus der
        die Cursor-Regeln stammen (einmal 2701 Zeichen fremder Text geloescht).
        """
        if self._process_lock.locked():
            self._flash_status("Ein Diktat läuft noch")
            return

        def arbeit():
            with self._process_lock:
                self.bus.progress.emit(f"Neu bereinigen als {name} …")
                try:
                    text = self.pipeline.reprocess(roh, fmt)
                except Exception:
                    log.exception("Nachbearbeitung fehlgeschlagen.")
                    text = ""
                self.bus.reprocessed.emit(text, name)

        threading.Thread(target=arbeit, daemon=True).start()

    def _on_reprocessed(self, text: str, name: str) -> None:
        """UI-Thread: Ergebnis in die Zwischenablage und Rueckmeldung geben."""
        if not text:
            self._flash_status(f"{name} fehlgeschlagen — Text unverändert")
            return
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
        except Exception:
            log.exception("Zwischenablage nicht beschreibbar.")
            self._flash_status("Zwischenablage nicht erreichbar")
            return
        log.info("Neu bereinigt als %s (%d Zeichen) — in der Zwischenablage.",
                 name, len(text))
        self._flash_status(f"{name} kopiert — Strg+V zum Einfügen")
