"""System-Tray: Status-Icon (idle/listening/processing/error), Tooltip, Menue."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .state import AppState

log = logging.getLogger(__name__)

_STATE_COLOR = {
    AppState.IDLE: "#8a8a92",
    AppState.LISTENING: "#e04848",
    AppState.PROCESSING: "#e0a030",
    AppState.ERROR: "#b03060",
}
_STATE_TOOLTIP = {
    AppState.IDLE: "Fleech — bereit",
    AppState.LISTENING: "Fleech — Aufnahme läuft",
    AppState.PROCESSING: "Fleech — verarbeite Diktat",
    AppState.ERROR: "Fleech — Fehler (Log prüfen)",
}


def _make_icon(color: str) -> QIcon:
    """Brand-Waveform (5 Balken) in Status-Farbe, zur Laufzeit gemalt (keine Assets)."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    heights = (0.40, 0.66, 1.00, 0.66, 0.40)
    n = len(heights)
    bar_w = size * 0.11
    gap = size * 0.065
    total = n * bar_w + (n - 1) * gap
    x0 = (size - total) / 2
    cy = size / 2
    max_h = size * 0.62
    for i, h in enumerate(heights):
        bx = x0 + i * (bar_w + gap)
        bh = max_h * h
        p.drawRoundedRect(bx, cy - bh / 2, bar_w, bh, bar_w / 2, bar_w / 2)
    p.end()
    return QIcon(pm)


class TrayController:
    """Kapselt QSystemTrayIcon; Aktionen werden als Callbacks injiziert."""

    def __init__(self, actions: dict):
        """actions: toggle_recording, toggle_overlay, open_settings, reload, quit;
        optional: open_home, open_update, redo_last, save_last_wav (die beiden
        letzten = die letzte Aufnahme, V-15)."""
        self._icons = {state: _make_icon(color) for state, color in _STATE_COLOR.items()}
        self.tray = QSystemTrayIcon(self._icons[AppState.IDLE])
        self.tray.setToolTip(_STATE_TOOLTIP[AppState.IDLE])
        # Brand-Tile als Kontextmenue-/Fallback-Icon (Tray selbst zeigt Status-Farbe).
        try:
            from ..resources import app_icon_path

            brand = QIcon(str(app_icon_path()))
            if not brand.isNull():
                self._brand_icon = brand
        except Exception:
            pass

        menu = QMenu()
        # Update-Eintrag: erst sichtbar, wenn wirklich eine neue Version bereitliegt.
        # Er ist der Weg, der auch dann funktioniert, wenn der Nutzer alle Toasts
        # abgeschaltet hat — sonst waere ein Update unsichtbar.
        self._update_action = QAction("Update installieren …")
        self._update_action.setVisible(False)
        if actions.get("open_update"):
            self._update_action.triggered.connect(actions["open_update"])
        self._record_action = QAction("Aufnahme starten")
        self._record_action.triggered.connect(actions["toggle_recording"])
        self._overlay_action = QAction("Overlay ein/aus")
        self._overlay_action.triggered.connect(actions["toggle_overlay"])
        # Der Freihand-Schnellschalter ist mit der Freihand-Oberflaeche in 5.11.0
        # entfallen: Er meldete einen Zustand („Freihand: an"), den der stillgelegte
        # Modus gar nicht mehr einnehmen kann (Befund E-8).
        # Die letzte Aufnahme (V-15): Rund jede achte Aufnahme lieferte ein leeres
        # Transkript, und danach war der Ton weg — „nochmal erkennen" hiess
        # „nochmal sprechen". Beide Eintraege bleiben immer anklickbar; ob etwas
        # im Speicher liegt, meldet die Pille beim Klick. Grund: Der Zustand
        # aendert sich im Worker-Thread, und ein QAction von dort umzuschalten
        # waere ein Griff an ein Qt-Objekt aus dem falschen Thread.
        self._wieder_actions = []
        for schluessel, text, tipp in (
            ("redo_last", "Letzte Aufnahme noch einmal erkennen",
             "Schickt den zuletzt aufgenommenen Ton noch einmal durch die "
             "Erkennung — nützlich nach einem leeren oder falschen Ergebnis."),
            ("save_last_wav", "Letzte Aufnahme als WAV sichern …",
             "Speichert den zuletzt aufgenommenen Ton als Datei."),
        ):
            if not actions.get(schluessel):
                continue
            a = QAction(text)
            a.setToolTip(
                tipp + " Hinweis: Die letzte Aufnahme liegt bis zur nächsten "
                "im Arbeitsspeicher — auf die Festplatte kommt sie nur, wenn du "
                "sie hier ausdrücklich sicherst."
            )
            a.triggered.connect(actions[schluessel])
            self._wieder_actions.append(a)
        settings_action = QAction("Einstellungen …")
        settings_action.triggered.connect(actions["open_settings"])
        reload_action = QAction("Neu laden")
        reload_action.triggered.connect(actions["reload"])
        quit_action = QAction("Beenden")
        quit_action.triggered.connect(actions["quit"])
        for a in (self._record_action, self._overlay_action):
            menu.addAction(a)
        if self._wieder_actions:
            menu.addSeparator()
            for a in self._wieder_actions:
                menu.addAction(a)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(self._update_action)
        menu.addAction(reload_action)
        menu.addAction(quit_action)
        self._menu = menu
        self._actions = [self._record_action, self._overlay_action, settings_action,
                         self._update_action, reload_action,
                         quit_action, *self._wieder_actions]  # Referenzen halten (GC!)
        self.tray.setContextMenu(menu)

        # Linksklick: Hauptfenster (Home); Rechtsklick macht Qt selbst (Menue).
        open_main = actions.get("open_home", actions["open_settings"])
        self.tray.activated.connect(
            lambda reason: open_main() if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    def set_state(self, state: AppState) -> None:
        self.tray.setIcon(self._icons[state])
        self.tray.setToolTip(_STATE_TOOLTIP[state])
        self._record_action.setText(
            "Aufnahme stoppen" if state is AppState.LISTENING else "Aufnahme starten"
        )

    def show_update(self, version: str, bereit: bool) -> None:
        """Update-Eintrag im Menue ein-/ausblenden. bereit = schon geladen."""
        self._update_action.setText(
            f"Update {version} installieren …" if bereit
            else f"Update {version} laden …"
        )
        self._update_action.setVisible(bool(version))

    def notify(self, title: str, message: str) -> None:
        self.tray.showMessage(title, message, QSystemTrayIcon.Information, 4000)
