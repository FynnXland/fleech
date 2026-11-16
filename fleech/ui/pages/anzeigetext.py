"""Zahlen und Datumsangaben im Format der Oberflächensprache (6.6.0).

Home, Insights und die Bestandszeile zeigen Stückzahlen und Kalendertage. Deutsch
schreibt 74.245 und 03.11.2026, Englisch 74,245 und Nov 3, 2026. Profilnamen und
Gründe übersetzen ihre eigenen Module (`profiles.anzeigename`, `gruende.anzeige`).

Kein Qt: reine Formatierung, ohne Fenster prüfbar.
"""

from __future__ import annotations

import datetime as _dt

from ... import i18n

# Englische Monatskürzel. Deutsch bleibt beim gewohnten 03.11.2026.
_MONATE_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ganzzahl(n: int) -> str:
    """Stückzahl mit Tausendertrenner der Oberfläche: 74.245 / 74,245."""
    text = f"{int(n):,}"
    return text.replace(",", ".") if i18n.aktuell() == "de" else text


def datum(tag: _dt.date) -> str:
    """Kalendertag: „03.11.2026“ / „Nov 3, 2026“."""
    if i18n.aktuell() == "de":
        return tag.strftime("%d.%m.%Y")
    return f"{_MONATE_EN[tag.month - 1]} {tag.day}, {tag.year}"
