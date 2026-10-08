"""Seite 1: Willkommen — und in welcher Sprache diktiert wird.

Die Sprache steht vorn, weil alles Weitere davon abhaengt: die Erkennung, das
Beispiel fuer das Probediktat. Die Oberflaeche selbst ist (noch) deutsch.
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from .bausteine import auswahl, notiz, text, titel

SPRACHEN = (("de", "Deutsch"), ("en", "Englisch"), ("auto", "Automatisch (mehrsprachig)"))


def build(dialog) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setSpacing(12)
    lay.addWidget(titel("Willkommen bei Fleech"))
    lay.addWidget(text(
        "Fleech schreibt, was du sprichst — in das Feld, in dem dein Cursor steht. "
        "Die Spracherkennung läuft immer auf diesem Rechner; welche KI den Text "
        "danach aufräumt, wählst du gleich selbst."
    ))
    lay.addWidget(text(
        "Diese Einführung klärt Sprache, KI, Mikrofon und Taste und lädt "
        "nebenbei, was Fleech braucht. Alles davon findest du später auch in den "
        "Einstellungen wieder."
    ))
    lay.addSpacing(6)
    lay.addWidget(text("In welcher Sprache diktierst du?"))
    box = auswahl()
    for code, name in SPRACHEN:
        box.addItem(name, code)
    box.setCurrentIndex(max(0, box.findData(dialog.settings.general.language)))
    box.currentIndexChanged.connect(dialog._on_sprache_gewaehlt)
    dialog._sprache_box = box
    lay.addWidget(box)
    lay.addWidget(notiz("„Automatisch“ erkennt die Sprache bei jedem Diktat selbst. "
                        "Einzelne Apps können über Profile eine eigene Sprache "
                        "bekommen."))
    lay.addStretch(1)
    return page
