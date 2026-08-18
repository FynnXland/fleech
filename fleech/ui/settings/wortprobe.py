"""Einsprech-Probe: hoert Fleech den Begriff so, wie er eingetragen ist?

Einstieg ist ein Woerterbuch-Eintrag auf der Textersetzung-Seite. Geprueft wird
mit dem Erkenner samt Woerterbuch-Priming, also genau dem, was im BETRIEB laeuft:
Ein Test, der besteht, waehrend der Alltag scheitert, ist schlimmer als keiner.

Der zweite Einstieg — die Startwort-Probe der Aufnahme-Seite — ist mit der
Freihand-Oberflaeche in 5.11.0 entfallen. Der Weg dorthin
(`wortprobe(..., zweck="startwort")`) bleibt eingefroren im Code.

Mixin statt Methoden im Panel: Es ist ein eigenes Thema mit eigenem Dialog, und
settings_window.py war mit den Methoden ueber seine Groessengrenze gelaufen.
"""

from __future__ import annotations


class WortprobeMixin:
    def _wortprobe_begriff(self) -> str:
        """Der Begriff aus der Zeile, in der der Cursor steht.

        Bewusst die AKTUELLE Zeile statt eines eigenen Eingabefelds: Man schreibt
        das Wort gerade, der Cursor steht ohnehin darin — ein zweites Feld waere
        dasselbe Wort ein zweites Mal.
        """
        editor = getattr(self, "_dictionary_editor", None)
        if editor is None:
            return ""
        zeile = editor.textCursor().block().text().strip()
        if not zeile:
            # Cursor in einer Leerzeile: die letzte gefuellte Zeile nehmen.
            gefuellt = [z.strip() for z in editor.toPlainText().splitlines() if z.strip()]
            zeile = gefuellt[-1] if gefuellt else ""
        # „falsch => richtig" — geprueft wird, ob die RICHTIGE Schreibweise ankommt.
        if "=>" in zeile:
            zeile = zeile.split("=>", 1)[1]
        return zeile.strip()

    def _wortprobe_starten(self) -> None:
        if self._wortprobe_fn is None:
            return
        begriff = self._wortprobe_begriff()
        if not begriff:
            self._probe_btn.setText("Erst eine Zeile ins Wörterbuch schreiben")
            return
        from ..dialogs import WortprobeDialog

        dlg = WortprobeDialog(begriff, self._wortprobe_fn, self)
        if dlg.exec() and dlg.vorschlag:
            # „gehört => gemeint" ans Wörterbuch anhängen, damit die falsche
            # Schreibweise kuenftig automatisch ersetzt wird.
            editor = self._dictionary_editor
            zeilen = [z for z in editor.toPlainText().splitlines()]
            if dlg.vorschlag not in zeilen:
                zeilen.append(dlg.vorschlag)
                editor.setPlainText("\n".join(zeilen))
        self._probe_btn.setText("Eintrag einsprechen …")
