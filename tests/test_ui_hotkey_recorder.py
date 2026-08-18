"""Hotkey-Aufnahme: Dialog, Tasten-/Maus-Erkennung, HotkeyField, Kollisionen.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")


def _key_event(key, modifiers=None, vk=0, autorep=False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    mods = modifiers if modifiers is not None else Qt.NoModifier
    if vk:
        return QKeyEvent(QKeyEvent.KeyPress, key, mods, 0, vk, 0, "", autorep, 1)
    return QKeyEvent(QKeyEvent.KeyPress, key, mods, "", autorep, 1)

def test_hotkey_recorder_single_key(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_F10))
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "f10"
    assert not d.cleared

def test_hotkey_recorder_combination(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    # Nur Modifier: noch nicht final
    d.keyPressEvent(_key_event(Qt.Key_Control, Qt.ControlModifier))
    assert d.result_spec is None
    # Haupttaste mit Ctrl+Shift
    d.keyPressEvent(_key_event(Qt.Key_Space, Qt.ControlModifier | Qt.ShiftModifier))
    assert d.result_spec.serialize() == "ctrl+shift+space"

def test_hotkey_recorder_letter_uses_native_vk(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_D, Qt.ControlModifier, vk=0x44))
    assert d.result_spec.serialize() == "ctrl+d"

def test_hotkey_recorder_escape_clears(qapp):
    """Escape LOESCHT die Bindung (vorher: Abbruch ohne Aenderung).

    Nutzererwartung im Alltag: „ich will die Taste nicht mehr" — und genau danach
    hat er gesucht und nichts gefunden. Ein Abbruch ist ohnehin trivial: dieselbe
    Taste nochmal druecken."""
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_Escape))
    assert d.result_spec is None
    assert d.cleared

def test_hotkey_recorder_delete_clears(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_Delete))
    assert d.cleared is True

def test_hotkey_recorder_pynput_fallback_captures_gkeys(qapp):
    """G-/Makrotasten (z. B. Corsair via iCUE als F13–F24) kommen NICHT als
    Qt-Key-Event an — der pynput-Fallback-Slot muss sie finalisieren und dabei
    dieselben Tokens erzeugen, die der globale HotkeyManager matcht."""
    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d._on_global_key("f13", frozenset())
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "f13"

    # Mit Modifiern + exotischem VK-Token; und: nach _done keine Doppel-Finalisierung.
    d2 = HotkeyRecorderDialog()
    d2._on_global_key("vk227", frozenset({"ctrl"}))
    assert d2.result_spec.serialize() == "ctrl+vk227"
    d2._on_global_key("f10", frozenset())
    assert d2.result_spec.serialize() == "ctrl+vk227"  # _done-Guard haelt

    # Esc ueber den Fallback bricht ab statt „esc" zu binden.
    d3 = HotkeyRecorderDialog()
    d3._on_global_key("esc", frozenset())
    assert d3.result_spec is None
    assert not d3.cleared

def test_hotkey_recorder_hat_sichtbaren_abbrechen_knopf(qapp):
    """E-1: Der Recorder greift die Tastatur und hatte keinen sichtbaren Ausgang
    ausser 'Taste druecken' — ein Klick auf 'Abbrechen' muss schliessen, OHNE die
    bestehende Bindung zu loeschen (das bleibt Esc vorbehalten, dokumentiertes
    Verhalten)."""
    from PySide6.QtWidgets import QDialog

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    assert d._cancel_btn.text() == "Abbrechen"
    assert not d._cancel_btn.isHidden()
    d._cancel_btn.click()
    assert d._done is True
    assert d.result_spec is None
    assert not d.cleared          # NICHT geloescht — nur geschlossen


def test_hotkey_recorder_ignores_autorepeat(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_F10, autorep=True))
    assert d.result_spec is None  # Auto-Repeat ignoriert

def _mouse_event(button, modifiers=None):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    mods = modifiers if modifiers is not None else Qt.NoModifier
    return QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
                       button, button, mods)

def test_hotkey_recorder_mouse_button5(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.XButton2))
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "mouse5"
    assert "Maustaste 5" in d._live.text()

def test_hotkey_recorder_mouse_with_modifier(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.MiddleButton, Qt.ControlModifier))
    assert d.result_spec.serialize() == "ctrl+mouse_middle"

def test_hotkey_recorder_left_and_right_click_ignored(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.LeftButton))
    d.mousePressEvent(_mouse_event(Qt.RightButton))
    assert d.result_spec is None  # Dialog laeuft weiter, nichts gebunden

def test_collision_warning():
    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import collision_warning

    spec = HotkeySpec.parse("f10")
    assert collision_warning(spec, {"Mathe": HotkeySpec.parse("f10")})
    assert not collision_warning(spec, {"Mathe": HotkeySpec.parse("f9")})
    # Windows-reservierte Combo
    assert collision_warning(HotkeySpec.parse("alt+f4"), {})

def QDialog_Accepted():
    from PySide6.QtWidgets import QDialog

    return QDialog.Accepted

def test_hotkey_field_pauses_global_hotkeys_during_capture(qapp):
    """Regression: waehrend der Hotkey-Aufnahme muss der globale pynput-Listener
    pausieren — sonst startet der Druck auf den aktuellen Hotkey beim Neubelegen
    eine Diktat-Aufnahme im Hintergrund."""
    from PySide6.QtWidgets import QDialog

    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import HotkeyField, HotkeyRecorderDialog

    calls = []
    field = HotkeyField(
        HotkeySpec.parse("f9"), lambda: {},
        capture_guard=(lambda: calls.append("stop"), lambda: calls.append("start")),
    )
    monkey = HotkeyRecorderDialog.exec
    HotkeyRecorderDialog.exec = lambda self: QDialog.Rejected  # Nutzer bricht ab
    try:
        field._record()
    finally:
        HotkeyRecorderDialog.exec = monkey
    # Guard MUSS auch bei Abbruch wieder freigeben (try/finally):
    assert calls == ["stop", "start"]

def test_hotkey_field_records_and_emits(qapp):
    from PySide6.QtCore import Qt

    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import HotkeyField, HotkeyRecorderDialog

    field = HotkeyField(HotkeySpec.parse("f9"), others_provider=lambda: {})
    assert "F9" in field._display.text()

    emitted = []
    field.changed.connect(emitted.append)
    # Recorder-Ergebnis simulieren, ohne echten Dialog zu oeffnen
    monkey = HotkeyRecorderDialog.exec
    HotkeyRecorderDialog.exec = lambda self: (
        setattr(self, "result_spec", HotkeySpec.parse("ctrl+shift+space")),
        QDialog_Accepted(),
    )[1]
    try:
        field._record()
    finally:
        HotkeyRecorderDialog.exec = monkey
    assert emitted and emitted[0].serialize() == "ctrl+shift+space"
    assert "Ctrl + Shift + Space" in field._display.text()
