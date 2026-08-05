"""Einsprech-Probe: hoert Fleech den Begriff so, wie er eingetragen ist?

Zwei Einstiege in dieselbe Sache — das Startwort auf der Aufnahme-Seite und ein
Woerterbuch-Eintrag auf der Textersetzung-Seite. Beide oeffnen den
`WortprobeDialog`; geprueft wird jeweils mit dem Erkenner, der im BETRIEB
laeuft, nicht mit dem genaueren Diktat-Weg: Ein Test, der besteht, waehrend der
Alltag scheitert, ist schlimmer als keiner.

Mixin statt Methoden im Panel: Es ist ein eigenes Thema mit eigenem Dialog, und
settings_window.py war mit den drei Methoden ueber seine Groessengrenze gelaufen.
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

    def _startwort_probe_starten(self) -> None:
        """Das Startwort einsprechen und sehen, ob Freihand darauf anspringen würde.

        Geprüft wird mit dem Erkenner, der im Betrieb LÄUFT — nicht mit dem
        Diktat-Weg. Der hört ungleich besser, und ein Test, der besteht, während
        der Alltag scheitert, ist schlimmer als keiner.
        """
        if self._wortprobe_fn is None:
            return
        liste = getattr(self, "_startwort_liste", None)
        woerter = liste.woerter() if liste is not None else []
        if not woerter:
            self._startwort_probe_btn.setText("Erst ein Startwort eintragen")
            return
        # Bei mehreren wird das ERSTE geprüft: Es ist das, das man im Alltag sagt
        # — die anderen stehen als Rückfalloption da. Alle nacheinander abzufragen
        # wäre ein Testlauf statt einer Probe.
        wort = woerter[0]
        from ..dialogs import WortprobeDialog

        WortprobeDialog(wort, self._wortprobe_fn, self, zweck="startwort").exec()
        self._startwort_probe_btn.setText("Startwort einsprechen …")

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
