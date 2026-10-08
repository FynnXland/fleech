"""Taste & Bedienung: welche Taste — und wie sie sich verhaelt.

Die Taste ist frei waehlbar (derselbe Aufnehmen-Knopf wie unter Einstellungen →
Aufnahme). F9 ist eine Vorgabe, keine Antwort: Auf Laptops liegt sie oft hinter
Fn, in manchen Programmen ist sie belegt.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QRadioButton, QVBoxLayout, QWidget

from ...hotkey import HotkeySpec
from ..hotkey_recorder import HotkeyField
from ..theme import style_button
from .bausteine import notiz, text, titel

log = logging.getLogger(__name__)

# Die anderen Bindungen — fuer den Hinweis auf Doppelbelegung.
_ANDERE = (("prompt_toggle_hotkey", "KI-Prompting"), ("undo_hotkey", "Rohtext einsetzen"),
           ("pause_hotkey", "Pause"), ("profile_hotkey", "Profil wechseln"))


def tasten_name(settings) -> str:
    """Die Diktat-Taste zum Vorlesen („F9", „Strg+Alt+D")."""
    roh = settings.recording.hotkey or "f9"
    try:
        return HotkeySpec.parse(roh).display()
    except ValueError:
        return roh.upper()


def _andere_bindungen(settings):
    """Nur das Dataclass fangen, nie den Dialog (Referenzzyklus-Falle)."""
    recording = settings.recording

    def liefern() -> dict:
        raus = {}
        for attr, name in _ANDERE:
            roh = getattr(recording, attr, "")
            if not roh:
                continue
            try:
                raus[name] = HotkeySpec.parse(roh)
            except ValueError:
                log.debug("Bindung %s unlesbar: %r", attr, roh)
        return raus

    return liefern


def build(dialog, capture_guard=None) -> QWidget:
    settings = dialog.settings
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setSpacing(10)
    lay.addWidget(titel("Taste und Bedienung"))
    lay.addWidget(text("Mit welcher Taste willst du diktieren? Klick auf „Aufnehmen“ "
                       "und drück die Taste oder Kombination — auch eine "
                       "Maus-Daumentaste geht."))
    try:
        spec = HotkeySpec.parse(settings.recording.hotkey or "f9")
    except ValueError:
        spec = HotkeySpec.parse("f9")
    feld = HotkeyField(spec, _andere_bindungen(settings), capture_guard=capture_guard)
    style_button(feld._button)
    feld.changed.connect(dialog._on_taste_gewaehlt)
    dialog._taste_feld = feld
    lay.addWidget(feld)
    lay.addSpacing(6)
    dialog._taste_satz = text("")
    lay.addWidget(dialog._taste_satz)
    dialog._hold_radio = QRadioButton()
    dialog._toggle_radio = QRadioButton()
    dialog._nudge_radio = QRadioButton()
    mode = settings.recording.mode
    if mode == "toggle":
        dialog._toggle_radio.setChecked(True)
    elif mode == "nudge":
        dialog._nudge_radio.setChecked(True)
    else:
        dialog._hold_radio.setChecked(True)
    # Jedes Radio meldet nur sein eigenes „checked=True" — die transiente
    # Abwahl-Meldung des vorherigen schriebe sonst kurz den falschen Modus.
    for radio in (dialog._hold_radio, dialog._toggle_radio, dialog._nudge_radio):
        radio.toggled.connect(dialog._on_mode_toggled)
        lay.addWidget(radio)
    beschrifte(dialog)
    lay.addSpacing(6)
    lay.addWidget(notiz(
        "Während der Aufnahme erscheint eine kleine Pille am Bildschirmrand: x bricht "
        "ab, der Haken fügt ein. Weitere Tasten (Pause, Rohtext, Profile) findest du "
        "unter Einstellungen → Aufnahme."
    ))
    lay.addStretch(1)
    return page


def beschrifte(dialog) -> None:
    """Texte an die gewaehlte Taste anpassen."""
    taste = tasten_name(dialog.settings)
    dialog._taste_satz.setText(f"Aufgenommen wird über {taste} — auf drei Arten:")
    dialog._hold_radio.setText(
        f"Halten:  {taste} gedrückt halten = aufnehmen, loslassen = fertig")
    dialog._toggle_radio.setText(
        f"Umschalten:  {taste} einmal drücken = Start, nochmal = fertig")
    dialog._nudge_radio.setText(
        f"Anstupsen:  {taste} einmal drücken, reden — endet von selbst, sobald du "
        f"aufhörst")
