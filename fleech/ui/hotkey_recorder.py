"""Hotkey-Recorder fuer das Settings-UI: Taste(n) druecken statt Namen eintippen.

- HotkeyRecorderDialog: greift die Tastatur, zeigt live die gedrueckte Kombination,
  finalisiert bei der ersten Nicht-Modifier-Taste. Esc bricht ab, Backspace/Entf
  loescht die Bindung. Auto-Repeat wird entprellt.
- HotkeyField: Zeile im Settings-Formular (Anzeige + Button + Kollisionswarnung).
- collision_warning(): interne Doppelbelegung + Hinweis auf Windows-problematische Combos.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..hotkey import HotkeySpec

log = logging.getLogger(__name__)

_QT_NAMED = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Tab: "tab", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down", Qt.Key_Insert: "insert",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_ScrollLock: "scroll_lock", Qt.Key_Pause: "pause",
    Qt.Key_Print: "print_screen", Qt.Key_Menu: "menu",
}
_QT_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                     Qt.Key_AltGr, Qt.Key_Super_L, Qt.Key_Super_R}

# Bindbare Maustasten: Mitte + Daumentasten. Links/rechts wuerden die normale
# Mausnutzung zerstoeren und sind bewusst ausgeschlossen.
_QT_MOUSE_TOKENS = {
    Qt.MiddleButton: "mouse_middle",
    Qt.XButton1: "mouse4",
    Qt.XButton2: "mouse5",
}

# Windows faengt diese Kombinationen selbst ab bzw. sie sind heikel als globaler Hotkey.
_WINDOWS_RESERVED = {
    "ctrl+alt+delete", "ctrl+shift+esc", "win+l", "win+d", "alt+tab", "alt+f4",
    "ctrl+esc", "win+tab",
}


def qt_modifiers(event) -> frozenset:
    mods = event.modifiers()
    out = set()
    if mods & Qt.ControlModifier:
        out.add("ctrl")
    if mods & Qt.AltModifier:
        out.add("alt")
    if mods & Qt.ShiftModifier:
        out.add("shift")
    if mods & Qt.MetaModifier:
        out.add("win")
    return frozenset(out)


def qt_main_token(event) -> str | None:
    """Kanonisches Token der Haupttaste, oder None wenn (noch) nur Modifier gedrueckt."""
    qk = event.key()
    if qk in _QT_MODIFIER_KEYS:
        return None
    if Qt.Key_F1 <= qk <= Qt.Key_F35:
        return f"f{qk - Qt.Key_F1 + 1}"
    if qk in _QT_NAMED:
        return _QT_NAMED[qk]
    vk = event.nativeVirtualKey()
    if vk:
        if 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        if 0x30 <= vk <= 0x39:
            return chr(vk)
        if 0x60 <= vk <= 0x69:
            return f"num{vk - 0x60}"
    text = event.text()
    if text and text.strip():
        return text.lower()
    return None


_MOD_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


def _modifier_display(mods: frozenset) -> str:
    parts = [_MOD_LABELS[m] for m in ("ctrl", "alt", "shift", "win") if m in mods]
    return " + ".join(parts + ["…"]) if parts else "…"


def collision_warning(spec: HotkeySpec, others: dict) -> str:
    """others: {anderer_name: HotkeySpec}. Gibt Warntext zurueck oder ""."""
    serial = spec.serialize()
    for name, other in others.items():
        if other is not None and other.serialize() == serial:
            return f"⚠ Bereits belegt für „{name}“."
    if serial in _WINDOWS_RESERVED:
        return "⚠ Von Windows reserviert — funktioniert evtl. nicht zuverlässig."
    return ""


class HotkeyRecorderDialog(QDialog):
    # Vom pynput-Fallback-Listener (Thread!) gemeldete Taste: (token, modifiers).
    _global_key = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hotkey aufnehmen")
        self.setModal(True)
        self.result_spec: HotkeySpec | None = None
        self.cleared = False
        self._done = False
        self._pynput_listener = None
        self._pynput_mods: set[str] = set()

        layout = QVBoxLayout(self)
        self._title = QLabel("Drücke jetzt die gewünschte Tastenkombination")
        self._title.setStyleSheet("font: 600 11pt 'Segoe UI';")
        self._live = QLabel("…")
        self._live.setAlignment(Qt.AlignCenter)
        self._live.setStyleSheet("font: 14pt 'Segoe UI'; color: #4a90d9; padding: 12px;")
        hint = QLabel("Auch Maustaste 4/5 oder Mitte: einfach hier im Dialog klicken.\n"
                      "G-/Makrotasten (Corsair, Logitech …) funktionieren, wenn sie in\n"
                      "iCUE/G HUB eine Taste senden (z. B. F13–F24).\n"
                      "Esc = abbrechen · Entf/Backspace = Bindung löschen")
        hint.setStyleSheet("color: #808088; font-size: 8pt;")
        layout.addWidget(self._title)
        layout.addWidget(self._live)
        layout.addWidget(hint)
        self.resize(360, 160)
        self._global_key.connect(self._on_global_key)

    def showEvent(self, event) -> None:
        """Keyboard-Grab erst hier: grabKeyboard() auf einem noch UNSICHTBAREN Widget
        verschluckt die Events ins Leere (real reproduziert) — der Dialog bekam am
        Bildschirm keinen einzigen Tastendruck. Im showEvent ist das Fenster sichtbar
        und der Grab funktioniert."""
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()
        self._start_pynput_fallback()

    # -- pynput-Fallback: faengt Tasten, die Qt nicht als Key-Event liefert -----------
    #
    # Gaming-Zusatztasten (Corsair G-Tasten, Logitech G-Keys) senden je nach
    # iCUE-/G-HUB-Belegung F13–F24 oder exotische VK-Codes. Der Low-Level-Hook
    # sieht sie IMMER — und normalisiert mit demselben pynput_token() wie der
    # globale HotkeyManager. Damit stimmen Aufnahme und spaeteres Matching
    # garantiert ueberein. Fuer normale Tasten gewinnt der Qt-Pfad (kommt zuerst);
    # der _done-Guard verhindert Doppel-Finalisierung.

    def _start_pynput_fallback(self) -> None:
        if self._pynput_listener is not None:
            return
        from pynput import keyboard as pk

        from ..hotkey import is_modifier_token, pynput_token

        def on_press(key):
            token = pynput_token(key)
            if is_modifier_token(token):
                self._pynput_mods.add(token)
                return
            self._global_key.emit(token, frozenset(self._pynput_mods))

        def on_release(key):
            token = pynput_token(key)
            self._pynput_mods.discard(token)

        try:
            self._pynput_listener = pk.Listener(on_press=on_press, on_release=on_release)
            self._pynput_listener.start()
        except Exception:
            log.exception("Hotkey-Recorder: pynput-Fallback nicht verfügbar.")
            self._pynput_listener = None

    def _stop_pynput_fallback(self) -> None:
        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None

    def _on_global_key(self, token: str, mods) -> None:
        if self._done or not token or token == "unknown":
            return
        if token == "esc":
            self._finish(cancel=True)
            return
        if token in ("backspace", "delete"):
            self.cleared = True
            self._finish()
            return
        self.result_spec = HotkeySpec(key=token, modifiers=frozenset(mods))
        self._live.setText(self.result_spec.display())
        self._finish()

    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        qk = event.key()
        if qk == Qt.Key_Escape:
            self._finish(cancel=True)
            return
        if qk in (Qt.Key_Backspace, Qt.Key_Delete):
            self.cleared = True
            self._finish()
            return
        token = qt_main_token(event)
        mods = qt_modifiers(event)
        if token is None:
            # Nur Modifier: live anzeigen, noch nicht finalisieren.
            self._live.setText(_modifier_display(mods))
            return
        self.result_spec = HotkeySpec(key=token, modifiers=mods)
        self._live.setText(self.result_spec.display())
        self._finish()

    def mousePressEvent(self, event) -> None:
        token = _QT_MOUSE_TOKENS.get(event.button())
        if token is None:
            return  # links/rechts: nicht bindbar
        self.result_spec = HotkeySpec(key=token, modifiers=qt_modifiers(event))
        self._live.setText(self.result_spec.display())
        self._finish()

    def _finish(self, cancel: bool = False) -> None:
        if self._done:
            return
        self._done = True
        self._stop_pynput_fallback()
        self.releaseKeyboard()
        self.reject() if cancel else self.accept()

    def closeEvent(self, event) -> None:
        self._stop_pynput_fallback()
        self.releaseKeyboard()
        super().closeEvent(event)


class HotkeyField(QWidget):
    """Formularzeile: Anzeige der Bindung + Aufnehmen-Button + Kollisionswarnung."""

    changed = Signal(object)  # HotkeySpec | None (None = geloescht)

    def __init__(self, spec: HotkeySpec | None, others_provider, parent=None,
                 capture_guard=None):
        super().__init__(parent)
        self._spec = spec
        self._others_provider = others_provider  # callable → {name: HotkeySpec}
        # (before, after): globale Hotkeys waehrend der Aufnahme pausieren — sonst
        # startet der Druck auf den AKTUELLEN Hotkey beim Neubelegen eine Diktat-
        # Aufnahme im Hintergrund.
        self._capture_guard = capture_guard
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._display = QLabel()
        # Design-System: Karten-Feld mit Hairline, 8px Radius (wie Combos).
        self._display.setStyleSheet(
            "padding: 5px 10px; background: #22262E; font-weight: 500;"
            " border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;"
            " min-width: 140px;"
        )
        self._button = QPushButton("Aufnehmen")
        self._button.clicked.connect(self._record)
        row.addWidget(self._display, 1)
        row.addWidget(self._button)
        outer.addLayout(row)
        self._warning = QLabel("")
        self._warning.setStyleSheet("color: #d08030; font-size: 8pt;")
        self._warning.setVisible(False)
        outer.addWidget(self._warning)
        self._refresh()

    def spec(self) -> HotkeySpec | None:
        return self._spec

    def _refresh(self) -> None:
        self._display.setText(self._spec.display() if self._spec else "— keine —")
        warn = collision_warning(self._spec, self._others_provider()) if self._spec else ""
        self._warning.setText(warn)
        self._warning.setVisible(bool(warn))

    def _record(self) -> None:
        before, after = self._capture_guard or (lambda: None, lambda: None)
        before()
        try:
            dialog = HotkeyRecorderDialog(self)
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            after()
        if not accepted:
            return  # abgebrochen (Esc)
        self._spec = None if dialog.cleared else dialog.result_spec
        self._refresh()
        self.changed.emit(self._spec)
