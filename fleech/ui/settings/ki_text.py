"""Seite „KI & Text" — wer deinen Text bereinigt und wie stark.

Seit 6.5.0 aus drei Bausteinen: `ki` (Anbieter, Schluessel, Modell), `ausgabe`
(Eingriffsgrad oben; Formeln, Safe-Word, Zeichen, Cursor-Rueckkehr unter
„Mehr Optionen") und `advanced.modelle` (Spracherkennung, GPU, Warmhaltung).
"""

from __future__ import annotations

from . import advanced, ausgabe, ki
from .common import hint
from .mehr import angleichen, bereich


def build(panel) -> None:
    seite, form = panel._page()
    form.addRow("", hint(
        "Wer deinen Text bereinigt und wie stark. Ein Cloud-Anbieter braucht einen "
        "eigenen API-Schlüssel — ein Abo wie ChatGPT Plus oder Claude Pro gilt "
        "dafür nicht."))
    mehr = bereich(seite, form)
    ki.zeilen(panel, form, mehr)
    ausgabe.zeilen(panel, form, mehr)
    advanced.modelle(panel, mehr)
    angleichen(form, mehr)
