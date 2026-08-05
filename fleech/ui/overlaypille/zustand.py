"""Was die Pille dauerhaft anzeigt: Aufnahmezustand, Modus, Profil, Pause, Freihand.

Mixin auf `OverlayWindow`: Der Zustand bleibt auf EINEM Widget. Ein eigenes
Objekt haette neue Referenzen in den Qt-Objektgraphen gelegt — genau die
Konstellation, aus der in diesem Projekt die wandernden Abstuerze kamen
(CLAUDE.md, Referenzzyklus-Crash).
"""

from __future__ import annotations

from ..state import AppState
from .bausteine import _GLYPH_COLORS, _glyph_icon


class ZustandMixin:
    def set_command_armed(self, armed: bool) -> None:
        """Signalwort live erkannt → Pille + Waveform in Befehls-Optik schalten."""
        if armed == self._command_armed:
            return
        self._command_armed = armed
        self._wave.set_armed(armed)
        self.update()

    def set_prompt_latched(self, latched: bool) -> None:
        """KI-Prompting-Latch an/aus → amberfarbene Pille + Punkt, dauerhaft sichtbar."""
        if latched == self._prompt_latched:
            return
        self._prompt_latched = latched
        self._apply_latch_visuals()

    def _apply_latch_visuals(self) -> None:
        """Punkt-Farbe + Sichtbarkeit fuer die Modus-Latches nachziehen.

        Solange EIN Latch aktiv ist, bleibt die Pille sichtbar (persistenter
        Indikator), auch bei Sichtbarkeit „nur waehrend Aufnahme". Beim Ausrasten
        wird die normale Sichtbarkeitslogik wiederhergestellt."""
        if self._prompt_latched:
            mode = "prompt"
        else:
            mode = ""
        self._math_dot.set_mode(mode)
        latched = bool(mode)

        if latched and not self._edit_mode and self._effective_visibility() != "off":
            self.show()
        elif not latched and not self._edit_mode:
            if self._effective_visibility() == "during_activity" \
                    and self._state is AppState.IDLE:
                self.hide()
        self.update()

    def set_focus_override(self, override: str | None) -> None:
        if override == self._focus_override:
            return
        self._focus_override = override
        if self._edit_mode:
            return  # Bearbeiten hat Vorrang: Pille bleibt sichtbar
        if override == "hidden":
            self.hide()
        elif self._effective_visibility() != "always" and self._state is AppState.IDLE:
            self.hide()
        elif self._effective_visibility() == "always":
            self.show()

    def _effective_visibility(self) -> str:
        if self._focus_override == "hidden":
            return "off"
        if self._focus_override in ("activity_only", "compact") and \
                self.settings.visibility == "always":
            return "during_activity"
        return self.settings.visibility

    def set_app_state(self, state: AppState) -> None:
        self._state = state
        self._wave.set_state(state)
        busy = state in (AppState.LISTENING, AppState.PROCESSING)
        self._cancel_btn.setEnabled(state is AppState.LISTENING)
        self._finish_btn.setEnabled(state is AppState.LISTENING)
        self._pause_btn.setEnabled(state is AppState.LISTENING)
        if state is not AppState.LISTENING:
            self.set_command_armed(False)  # Befehls-Optik endet mit der Aufnahme
            # Profil-Kapsel gehoert zur Auswahl, nicht zum Ergebnis: spaetestens
            # mit dem Zustandswechsel ist sie weg (zweites Netz neben dem Timer).
            self._profile_caption.hide()
            # Pause endet IMMER mit der Aufnahme. Bliebe die Optik stehen, zeigte
            # die naechste Aufnahme einen Pausenknopf, der nichts pausiert hat.
            self.set_paused(False)
        if state is not AppState.PROCESSING:
            # Fortschritts-Hinweis gehoert zur Verarbeitung — danach nie stehen lassen.
            self._clear_status_caption()
        if state is AppState.LISTENING:
            self._caption.hide()  # alte Transkript-Einblendung wegnehmen
            self.set_command_armed(False)  # neue Aufnahme startet neutral
        elif state is AppState.PROCESSING and self._caption_is_live:
            # Live-Vorschau beenden — das FINALE Transkript kommt (falls aktiviert)
            # gleich per transcript_ready; bei "nichts erkannt" bliebe sie sonst haengen.
            self._hide_live_caption()
        elif state is AppState.IDLE and self._caption_is_live:
            # Abbruch (LISTENING→IDLE ohne PROCESSING/transcript_ready): die sticky
            # Live-Vorschau wuerde sonst haengen bleiben (Nutzer-Bug: X gedrueckt →
            # Blase blieb bis zum Neustart). Ein echtes Endtranskript hat _is_live
            # bereits auf False gesetzt und wird hier NICHT versteckt.
            self._hide_live_caption()
        if self._edit_mode:
            return  # im Bearbeiten-Modus bleibt die Pille sichtbar
        visibility = self._effective_visibility()
        if visibility == "off":
            return
        if busy:
            self._hide_timer.stop()
            self.show()
        elif self._prompt_latched:
            self.show()  # Latch-Indikator bleibt sichtbar, auch wenn gerade nichts laeuft
        elif visibility == "during_activity":
            self.hide()
        elif visibility == "auto_hide":
            self._hide_timer.start(int(max(0.5, self.settings.auto_hide_seconds) * 1000))

    def set_mode_line(self, text: str) -> None:
        """Modus-Zeile („Fokus: soft_duck · Eingriff: Standard · nichts erkannt").

        Bewusst NICHT mehr als Tooltip: Sie erschien beim Hover ueber der ganzen
        Pille — also auch ueber jedem Knopf — und legte sich unter der Pille auf
        dieselbe Stelle wie die Knopf-Erklaerungen und die Profil-Kapsel. Drei
        Einblendungen um einen Platz, von denen eine niemand angefordert hatte.
        Der Text bleibt als Attribut erhalten (Diagnose/Tests), zeigt sich aber
        nur noch, wo er hingehoert: in Fenster und Log.
        """
        self._mode_line = text or ""

    def set_profile_color(self, farbe: str) -> None:
        """Farbe des aktiven Profils an den Punkt links durchreichen.

        Dauerhaft sichtbar, anders als die Namens-Kapsel darunter: Die verschwindet
        nach zwei Sekunden, der Ring bleibt. Genau das war der Wunsch — beim
        Diktieren sehen, welches Profil greift, ohne etwas anzuklicken."""
        self._math_dot.set_profile_color(farbe)

    def show_profile(self, name: str) -> None:
        """Profilnamen kurz neben der Pille zeigen (nach dem Umschalten)."""
        if not name:
            return
        self._profile_caption.show_above(
            self.frameGeometry(), name,
            force_below=True, duration_ms=self.PROFIL_MS,
        )

    def set_freihand(self, zustand: str) -> None:
        """Lauschzustand anzeigen. Der Punkt links traegt es mit.

        Bewusst am vorhandenen Status-Punkt statt an einem neuen Element: Die
        Pille ist klein, und ein zweites Symbol fuer „hoert zu" waere genau die
        Sorte Dauer-Einblendung, die hier schon zweimal entfernt wurde.
        """
        if zustand == self._freihand:
            return
        self._freihand = zustand
        self._math_dot.set_lauscht(zustand == "lauscht")
        self._math_dot.setToolTip(
            "Freihand: hört auf das Startwort" if zustand == "lauscht"
            else self._dot_tooltip_base)
        # Der Punkt ist sonst nur bei aktivem Modus sichtbar — beim Lauschen muss
        # er es auch sein, sonst waere der Zustand unsichtbar.
        if zustand == "lauscht":
            self._math_dot.show()
        self.update()

    def set_paused(self, paused: bool) -> None:
        """Pausenzustand anzeigen: Knopf-Glyphe, ruhende Waveform, matte Pille.

        Die Waveform geht bewusst in den IDLE-Zustand (Punktreihe) statt auf
        flache Balken: eine Reihe stiller Balken saehe aus wie „Mikrofon hoert zu,
        du bist nur leise" — genau die Verwechslung, die hier teuer waere.
        """
        if paused == self._paused:
            return
        self._paused = paused
        self._pause_btn.setIcon(_glyph_icon(
            "resume" if paused else "pause",
            _GLYPH_COLORS["resume" if paused else "pause"],
        ))
        # Kein Tooltip: Die Glyphe sagt es bereits, und die Blase landete unter der
        # Pille — dort, wo auch die Profil-Kapsel steht. Zwei Einblendungen auf
        # einem Platz. Bei ✓/✕ bleibt die Erklaerung, die sind mehrdeutiger
        # (verwerfen vs. einfuegen) und dort ist ein Fehlgriff teuer.
        self._wave.set_state(AppState.IDLE if paused else AppState.LISTENING)
        # Bewusst NICHT ueber show_progress(): das gilt nur waehrend der
        # Verarbeitung. Hier laeuft die Aufnahme (Zustand LISTENING) und steht
        # trotzdem still — der Hinweis muss genau dann erscheinen.
        if paused:
            self._caption_is_live = False
            self._caption_is_status = True
            self._caption.show_above(
                self.frameGeometry(), "Pause — es wird nichts aufgenommen", sticky=True,
            )
        else:
            self._clear_status_caption()
        self.update()

    def set_session_info(self, info) -> None:
        """Session-Punkt: info = (bloecke, minuten[, nur_lesbar]) | None.

        Beantwortet die Frage „warum greift mein Befehl (nicht)?" direkt an der
        Pille — und zwar VORHER. Drei Zustaende:

        * kein Punkt — kein Kontext, ein Bezug wie „der letzte Satz" geht ins Leere.
        * gefuellter Punkt — Kontext da, Ersetzen moeglich.
        * hohler Punkt — Kontext nur LESBAR. Nach einem Fensterwechsel ist die
          Cursor-Position unbekannt, deshalb verweigert Fleech das Ersetzen. Das
          erfuhr man bisher erst, wenn der Befehl schon gesprochen war; genau das
          hat ein externes Gutachten als den fehlenden Handgriff benannt.
        """
        nur_lesbar = bool(info) and len(info) > 2 and info[2]
        self._math_dot.set_session(bool(info), nur_lesbar)
        if not info:
            self._math_dot.setToolTip(self._dot_tooltip_base)
            return
        chunks, minutes = info[0], info[1]
        wann = "gerade eben" if minutes < 1 else f"vor {minutes} min"
        text = (f"{self._dot_tooltip_base}\nErinnert sich an "
                f"{chunks} Diktat{'e' if chunks != 1 else ''} in diesem Fenster "
                f"({wann}).")
        if nur_lesbar:
            text += ("\nNur lesbar: Nach dem Fensterwechsel kann Fleech nicht mehr "
                     "ersetzen — diktiere einmal neu, dann geht es wieder.")
        self._math_dot.setToolTip(text)

    def set_feedback(self, text: str) -> None:
        # Haengte frueher an denselben Pillen-Tooltip an — siehe set_mode_line.
        if text:
            self._mode_line = f"{self._mode_line.splitlines()[0] if self._mode_line else ''}\n{text}".strip()
