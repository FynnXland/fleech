"""Die zehn Seiten des Einstellungs-Panels — je Seite ein Modul.

Stand 5.4.0 war das EINE Methode mit 674 Zeilen, danach neun Methoden in einer
1379-Zeilen-Datei. Beides liess sich sauber trennen, weil jede Seite mit
`panel._page()` neu anfaengt und keine lokale Variable ueber eine Seitengrenze
hinweg lebt.

Aufteilung wie bei `ui/pages/`: Das Panel (`settings_window.py`) haelt die
Widget-Bauer (`_combo`, `_check`, `_spin`, ...) und den Zustand; die Seitenmodule
rufen sie nur auf. Die Reihenfolge hier ist die Reihenfolge in der Navigation und
muss zu `SettingsPanel.PAGES` passen.
"""

from __future__ import annotations

from . import (
    advanced, allgemein, audiofokus, aufnahme, ausgabe, benachrichtigungen, ki,
    overlay, sounds, textersetzung,
)

# Reihenfolge = Reihenfolge der Eintraege in SettingsPanel.PAGES.
SEITEN = (
    allgemein, ki, aufnahme, audiofokus, overlay, sounds, benachrichtigungen, ausgabe,
    textersetzung, advanced,
)


def build_all(panel) -> None:
    """Baut alle Seiten in der Navigations-Reihenfolge in das Panel."""
    for modul in SEITEN:
        modul.build(panel)
