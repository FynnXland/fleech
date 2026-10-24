"""Die sechs Seiten des Einstellungs-Panels — je Seite ein Modul.

Stand 5.4.0 war das EINE Methode mit 674 Zeilen, danach neun Methoden in einer
1379-Zeilen-Datei, ab 5.5.1 zehn Seitenmodule. Seit 6.5.0 sind es sechs Seiten:
Jede zeigt oben nur das Noetige und klappt den Rest unter „Mehr Optionen" auf
(`mehr.py`). Die frueheren Seitenmodule sind Bausteine geblieben (`aufnahme`,
`audiofokus`, `overlay`, `sounds`, `benachrichtigungen`, `ausgabe`, `ki`,
`advanced`) und liefern ihre Zeilen per `zeilen(panel, form, mehr)` an die Seite,
zu der ihr Thema gehoert.

Aufteilung wie bei `ui/pages/`: Das Panel (`settings_window.py`) haelt die
Widget-Bauer (`_combo`, `_check`, `_spin`, ...) und den Zustand; die Module rufen
sie nur auf. Die Reihenfolge hier ist die Reihenfolge in der Navigation und muss
zu `SettingsPanel.PAGES` passen.
"""

from __future__ import annotations

from . import allgemein, datenschutz, ki_text, pille_toene, ruhe, woerterbuch

# Reihenfolge = Reihenfolge der Eintraege in SettingsPanel.PAGES.
SEITEN = (allgemein, ki_text, woerterbuch, pille_toene, ruhe, datenschutz)


def build_all(panel) -> None:
    """Baut alle Seiten in der Navigations-Reihenfolge in das Panel."""
    for modul in SEITEN:
        modul.build(panel)
