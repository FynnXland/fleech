"""Was kurz unter oder ueber der Pille erscheint: Transkript, Formeln, Fortschritt.

Mixin auf `OverlayWindow`: Der Zustand bleibt auf EINEM Widget. Ein eigenes
Objekt haette neue Referenzen in den Qt-Objektgraphen gelegt — genau die
Konstellation, aus der in diesem Projekt die wandernden Abstuerze kamen
(CLAUDE.md, Referenzzyklus-Crash).
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from ..state import AppState
from .bausteine import _glyph_icon
from .konstanten import (
    _ACCENT, _FALLBACK_FLASH_MS, _FORMULA_PREVIEW_MS, _IN_ABLAGE_MS, _PROMPT_ACCENT,
)

def _guessed_line(formulas: list) -> str:
    """Eine kurze Zeile fuer geratene Formeln — in LESBARER Form.

    In der Pille ist `\\sqrt{x} - c + \\frac{c}{2}` kaum zu pruefen; genau das muss
    man aber auf einen Blick erfassen koennen. Angezeigt wird deshalb `√x - c + c/2`.
    Eingefuegt wird weiterhin das echte LaTeX. Bewusst nur EINE Zeile ohne
    Erklaerung: Der Hinweis erscheint mitten im Schreiben, dort zaehlt Kuerze."""
    from ...formula import readable

    return "⚠ geraten: " + " · ".join(readable(f) for f in formulas)


def _dropped_line(dropped: str) -> str:
    """Eine Zeile fuer den verworfenen Halluzinations-Schwanz.

    Zeigt den ANFANG des Verworfenen, nicht nur die Wortzahl: Nur so kann man
    erkennen, ob der Guard danebenlag und wirklich Gesagtes getroffen hat.
    Kurz gehalten — der Hinweis erscheint mitten im Schreiben."""
    words = dropped.split()
    preview = " ".join(words[:6])
    if len(words) > 6:
        preview += " …"
    return f"⚠ {len(words)} Wörter verworfen: {preview}"


class EinblendungenMixin:
    def show_formula_preview(self, formulas: list) -> None:
        """Geratene Formeln sichtbar machen — unabhaengig von der Transkript-Anzeige.

        formulas: [(latex, war_geraten)].

        Zwei Wege, je nach Einstellung. Ist die Transkript-Blase an, haengt
        `show_transcript` den Hinweis dort an (zwei Blasen kurz hintereinander
        wuerden sich gegenseitig ueberschreiben). Ist sie AUS, kommt hier eine
        eigene, kurze Blase — denn eine Bestaetigung darf man abschalten, eine
        Warnung nicht: Wer sie ausblendet, will weniger Bestaetigung, nicht
        weniger Sicherheit. Zusaetzlich blinkt der Haken amber; das ist das
        einzige Signal, das auch bei voellig ausgeschaltetem Text ankommt.
        """
        self._pending_formulas = list(formulas or [])
        guessed = [tex for tex, was_guessed in self._pending_formulas if was_guessed]
        if not guessed or self._edit_mode:
            return
        self._flash_check()            # Haken kurz amber = „schau hier nach"
        if self.settings.show_transcript:
            return                     # der Hinweis reist mit der Transkript-Blase
        self._pending_formulas = []
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(
            self.frameGeometry(), _guessed_line(guessed),
            duration_ms=_FORMULA_PREVIEW_MS,
            accent_color=_PROMPT_ACCENT,
        )

    def show_dropped_tail(self, dropped: str) -> None:
        """Melden, dass ein zerfallener Transkript-Schwanz verworfen wurde.

        Gleiche Logik wie bei der Formel-Vorschau, aber mit hoeherem Anspruch: Hier
        wurde etwas GELOESCHT. Wer die Transkript-Blase abschaltet, will weniger
        Bestaetigung — nicht weniger Sicherheit. Deshalb kommt die Meldung in dem
        Fall als eigene Blase, und der Haken blinkt in jedem Fall amber.
        """
        dropped = (dropped or "").strip()
        if not dropped or self._edit_mode:
            return
        self._pending_dropped = dropped
        self._flash_check()
        if self.settings.show_transcript:
            return                     # reist mit der Transkript-Blase mit
        self._pending_dropped = ""
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(
            self.frameGeometry(), _dropped_line(dropped),
            duration_ms=_FORMULA_PREVIEW_MS,
            accent_color=_PROMPT_ACCENT,
        )

    def zeige_in_ablage(self, text: str) -> None:
        """Der Text kam nicht ins Feld, er liegt in der Zwischenablage.

        Diese Blase MUSS ankommen. Die erste Fassung schickte den Hinweis als
        Windows-Benachrichtigung — und die laesst sich abschalten. Am 2026-10-02
        hiess es im Protokoll „Toast unterdrueckt", die Pille verschwand mit dem
        Ende der Verarbeitung, und der Nutzer sah ueberhaupt nichts: kein Text im
        Feld, keine Meldung. Die Blase haengt an keiner Benachrichtigungs-
        Einstellung und zeigt den Anfang des Textes, damit klar ist, WAS dort liegt.
        """
        text = (text or "").strip()
        if self._edit_mode or not text:
            return
        auszug = text if len(text) <= 160 else text[:160].rsplit(" ", 1)[0] + " …"
        self._flash_check()            # Haken kurz amber = „schau hier nach"
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(
            self.frameGeometry(),
            f"{auszug}\n\nNicht eingefügt — du warst inzwischen in einem anderen "
            f"Fenster. Der Text liegt in der Zwischenablage: Strg+V.",
            duration_ms=_IN_ABLAGE_MS,
            accent_color=_PROMPT_ACCENT,
        )

    def zeige_hinweis(self, text: str) -> None:
        """Ein Hinweis, der ankommen muss — als Blase, nicht als Benachrichtigung.

        Aus demselben Grund wie `zeige_in_ablage`: Windows-Benachrichtigungen kann
        man abschalten, und dann hoerte man von einem echten Problem nichts."""
        text = (text or "").strip()
        if self._edit_mode or not text:
            return
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(self.frameGeometry(), text,
                                 duration_ms=_IN_ABLAGE_MS, accent_color=_PROMPT_ACCENT)

    def show_transcript(self, text: str) -> None:
        """Erkannten Text kurz ueber der Pille einblenden (nach dem Diktat)."""
        if self._edit_mode or not self.settings.show_transcript:
            return
        # Endtranskript = KEINE Live-Vorschau mehr → das folgende set_state(IDLE)
        # darf diese Blase nicht als haengengebliebene Vorschau wieder verstecken.
        self._caption_is_live = False
        self._caption_is_status = False   # Endtranskript loest die Fortschritts-Blase ab
        self._roh_vorschau = ""           # ab jetzt gilt die bereinigte Fassung
        clipped = text if len(text) <= 240 else text[:240].rsplit(" ", 1)[0] + " …"
        # Formel-Hinweis anhaengen: Wurde eine Formel GERATEN (die gesprochene
        # Fassung liess mehrere Lesarten zu), steht das direkt unter dem Text —
        # sichtbar, solange die Blase steht, ohne den Diktier-Fluss zu bremsen.
        guessed = [tex for tex, was_guessed in getattr(self, "_pending_formulas", [])
                   if was_guessed]
        self._pending_formulas = []
        if guessed:
            clipped += "\n" + _guessed_line(guessed)
        dropped = getattr(self, "_pending_dropped", "")
        self._pending_dropped = ""
        if dropped:
            clipped += "\n" + _dropped_line(dropped)
        # Nach einem Rohtext-Fallback bekommt die Blase einen amber Rahmen — dieselbe
        # Farbe wie der blinkende Haken, damit beides als ein Signal lesbar ist.
        warned = bool(guessed or dropped)
        self._caption.show_above(
            self.frameGeometry(), clipped,
            duration_ms=_FORMULA_PREVIEW_MS if warned else 4200,
            accent_color=(_PROMPT_ACCENT
                          if (self._fallback_active or warned) else None),
        )

    def show_raw_preview(self, text: str) -> None:
        """Rohtranskript zeigen, sobald die Erkennung durch ist (~0,8 s).

        Die Bereinigung braucht danach noch rund vier Sekunden. Bis dahin stand
        hier nichts — jetzt liest man bereits, waehrend das Modell arbeitet.
        `show_transcript` loest die Blase spaeter durch die fertige Fassung ab.
        """
        if self._edit_mode or not text or not self.settings.show_transcript:
            return
        self._roh_vorschau = (text if len(text) <= self.ROH_MAX
                              else text[:self.ROH_MAX].rsplit(" ", 1)[0] + " …")
        self._caption_is_live = False
        self._caption_is_status = True
        self._zeige_roh_mit_status("Bereinige …")

    def _zeige_roh_mit_status(self, status: str) -> None:
        """Rohtext oben, aktuelle Stufe darunter — eine Blase, zwei Ebenen."""
        text = self._roh_vorschau
        if status:
            text = f"{text}\n\n{status}" if text else status
        self._caption.show_above(self.frameGeometry(), text, sticky=True)

    def show_progress(self, text: str) -> None:
        """Laengeren Zwischenschritt ueber der Pille anzeigen ("Modell wird geladen …").

        Nutzt dieselbe Blase wie Live-Vorschau und Endtranskript — dort schaut man
        beim Diktieren ohnehin hin. Der bisherige Weg (nur Tooltip) war zu versteckt:
        waehrend eines Kaltstarts (~13 s) sah man lediglich "verarbeitet"."""
        if self._edit_mode or not text or self._state is not AppState.PROCESSING:
            return
        self._caption_is_live = False
        self._caption_is_status = True
        # Steht schon ein Rohtext, ERSETZT die Stufe ihn nicht — sie tritt darunter.
        if self._roh_vorschau:
            self._zeige_roh_mit_status(text)
            return
        self._caption.show_above(self.frameGeometry(), text, sticky=True)

    def _clear_status_caption(self) -> None:
        if self._caption_is_status:
            self._caption_is_status = False
            self._roh_vorschau = ""
            self._caption.hide()

    def flash_fallback(self) -> None:
        """Sichtbar machen, dass der Text als ROHTEXT kam (Modell nicht erreichbar
        oder Ausgabe verworfen): der Haken wird kurz amber statt cyan, und die
        Transkript-Blase bekommt denselben amber Rahmen.

        Bewusst kein Toast: Ton und Statuszeile melden den Fallback bereits, und die
        Banner-Politik lautet „so wenig wie moeglich". Was fehlte, war ein Signal
        genau dort, wo der Nutzer beim Diktieren hinschaut."""
        self._fallback_active = True
        self._flash_check()

    def _flash_check(self) -> None:
        """Haken kurz amber faerben = „schau hier bitte nach".

        Getrennt von `flash_fallback`, weil es zwei verschiedene Anlaesse gibt
        (Rohtext-Fallback und geratene Formel) — nur die Optik ist dieselbe. Wuerde
        die Formel-Warnung `_fallback_active` mitsetzen, waere die Transkript-Blase
        faelschlich als Fallback markiert."""
        self._finish_btn.setIcon(_glyph_icon("check", _PROMPT_ACCENT))
        self._fallback_timer.start(_FALLBACK_FLASH_MS)

    def _clear_fallback_flash(self) -> None:
        self._fallback_active = False
        self._finish_btn.setIcon(_glyph_icon("check", _ACCENT))

    def show_live_text(self, text: str) -> None:
        """Grobe Echtzeit-Vorschau WAEHREND der Aufnahme (PreviewStreamer): eine Zeile
        mit fester Breite, in der die zuletzt erkannten Woerter auflaufen — statt
        einer springenden, mehrzeiligen Blase."""
        if self._edit_mode or self._state is not AppState.LISTENING \
                or not getattr(self.settings, "live_preview", False):
            return
        words = (text or "").split()
        if not words:
            return
        self._caption_is_live = True
        self._caption.show_above(
            self.frameGeometry(), " ".join(words[-self.LIVE_WORDS:]),
            sticky=True, single_line=True,
        )

    def _hide_live_caption(self) -> None:
        self._caption_is_live = False
        self._caption.hide()
