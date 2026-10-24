"""Seite „Pille & Töne" — die Pille am Bildschirmrand und Fleechs eigene Toene.

Seit 6.5.0 aus zwei Bausteinen: `overlay` (Sichtbarkeit, Groesse, Position oben)
und `sounds` (an/aus und Lautstaerke oben); alles Feinere unter „Mehr Optionen".
"""

from __future__ import annotations

from . import overlay, sounds
from .common import hint
from .mehr import angleichen, bereich


def build(panel) -> None:
    seite, form = panel._page()
    form.addRow("", hint(
        "Die kleine Pille am Bildschirmrand und Fleechs Töne für Start, Stopp und Fehler."
    ))
    mehr = bereich(seite, form)
    overlay.zeilen(panel, form, mehr)
    sounds.zeilen(panel, form, mehr)
    angleichen(form, mehr)
