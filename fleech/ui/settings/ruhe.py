"""Seite „Ruhe" — was Fleech beim Diktieren leiser macht und wann es selbst still ist.

Seit 6.5.0 aus zwei Bausteinen: `audiofokus` (andere Apps leiser stellen) und
`benachrichtigungen` (Banner, „Nicht stören", Spiele). Oben die vier
Entscheidungen, die Feineinstellungen unter „Mehr Optionen".
"""

from __future__ import annotations

from . import audiofokus, benachrichtigungen
from .common import hint
from .mehr import angleichen, bereich


def build(panel) -> None:
    seite, form = panel._page()
    form.addRow("", hint(
        "Musik und Videos leiser beim Diktieren — und wann Fleech selbst still bleibt."
    ))
    mehr = bereich(seite, form)
    audiofokus.zeilen(panel, form, mehr)
    benachrichtigungen.zeilen(panel, form, mehr)
    angleichen(form, mehr)
