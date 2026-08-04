"""Overlay — Groesse, Position, Verhalten der Pille.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QPushButton, QWidget

from ...usersettings import (
    OVERLAY_COMPACTNESS,
    apply_overlay_compactness,
    overlay_compactness,
)
from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Die kleine Pille am Bildschirmrand: Sichtbarkeit, Größe, Ränder und Position."
    ))
    panel._combo(
        form, "Sichtbarkeit",
        [("during_activity", "Nur während Aufnahme/Verarbeitung (empfohlen)"),
         ("always", "Immer sichtbar"),
         ("auto_hide", "Automatisch ausblenden"),
         ("off", "Deaktiviert")],
        s.overlay.visibility, "overlay", lambda v: setattr(s.overlay, "visibility", v),
        hint_text="Wann die Pille zu sehen ist.",
    )
    hide_seconds = QDoubleSpinBox()
    hide_seconds.setRange(0.5, 60.0)
    hide_seconds.setValue(s.overlay.auto_hide_seconds)
    hide_seconds.setSuffix(" s")
    hide_seconds.valueChanged.connect(
        lambda v: (setattr(s.overlay, "auto_hide_seconds", v), panel._changed("overlay"))
    )
    label_w, _ = panel._row_label(
        "Auto-Hide nach", "Nach dieser Zeit blendet sich die Pille aus.")
    form.addRow(label_w, hide_seconds)
    panel._combo(
        form, "Größe",
        [("compact", "Kompakt"), ("normal", "Standard"), ("large", "Groß")],
        s.overlay.size, "overlay", lambda v: setattr(s.overlay, "size", v),
        hint_text="Gesamtgröße der Pille.",
    )
    # Frueher vier Spinboxen (links/rechts/oben/unten). Die einzelne Einstellbarkeit
    # hat in der Praxis niemand gebraucht — hier steht EINE Stufe, die alle vier
    # Werte setzt. Wer es genauer will, kann sie in der settings.json weiterhin
    # frei setzen; `overlay_compactness` waehlt dann die naechstliegende Stufe.
    panel._combo(
        form, "Pillen-Rand",
        list(OVERLAY_COMPACTNESS),
        overlay_compactness(s.overlay), "overlay",
        lambda v: apply_overlay_compactness(s.overlay, v),
        hint_text="Innenabstand des Pillen-Hintergrunds — enger wirkt kompakter.",
    )
    panel._combo(
        form, "Rand-Buttons",
        [(True, "Eigener Hintergrund (getrennte Inseln)"),
         (False, "In einer durchgehenden Pille")],
        s.overlay.separate_islands, "overlay",
        lambda v: setattr(s.overlay, "separate_islands", v),
        help_map={
            True: "Mathe-Punkt und Trigger-Button als eigene Inseln neben der Pille.",
            False: "Alles in einem durchgehenden Hintergrund.",
        },
    )
    panel._slider(form, "Transparenz", s.overlay.opacity, "overlay",
                  lambda v: setattr(s.overlay, "opacity", v), lo=20, hi=100,
                  hint_text="Deckkraft der Pille.")
    panel._slider(form, "Pegel-Empfindlichkeit", s.overlay.level_gain, "overlay",
                  lambda v: setattr(s.overlay, "level_gain", v), lo=20, hi=300,
                  hint_text="Wie stark die Waveform ausschlägt — rein optisch, hilft "
                           "bei leisen Mikrofonen.")
    panel._check(form, "Click-Through", s.overlay.click_through, "overlay",
                 lambda v: setattr(s.overlay, "click_through", v),
                 "Mausklicks gehen durch die Pille hindurch.")
    panel._check(form, "Folgt dem Maus-Bildschirm", s.overlay.follow_mouse_screen,
                 "overlay", lambda v: setattr(s.overlay, "follow_mouse_screen", v),
                 "Die Pille erscheint auf dem Monitor des Mauszeigers.")
    panel._check(form, "Live-Transkription (experimentell)", s.overlay.live_preview,
                 "overlay", lambda v: setattr(s.overlay, "live_preview", v),
                 "Grobe Echtzeit-Vorschau beim Sprechen (zusätzliches Modell, "
                 "~0,5 GB VRAM).")
    panel._check(form, "Erkannten Text über Overlay zeigen", s.overlay.show_transcript,
                 "overlay", lambda v: setattr(s.overlay, "show_transcript", v),
                 "Zeigt den fertigen Text kurz über der Pille.")

    # Position: Presets + Bearbeiten/Reset
    from ..overlay_qt import OVERLAY_PRESETS

    preset_row = QWidget()
    prow = QHBoxLayout(preset_row)
    prow.setContentsMargins(0, 0, 0, 0)
    prow.setSpacing(6)
    for key, label in OVERLAY_PRESETS:
        b = QPushButton(label)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(
            lambda _=False, k=key: panel._overlay_hooks.get("apply_preset",
                                                            lambda _k: None)(k)
        )
        prow.addWidget(b)
    prow.addStretch(1)
    label_w, _ = panel._row_label("Position", "Pille am Bildschirmrand ausrichten.")
    form.addRow(label_w, preset_row)

    edit_row = QWidget()
    erow = QHBoxLayout(edit_row)
    erow.setContentsMargins(0, 0, 0, 0)
    erow.setSpacing(6)
    panel._overlay_edit_btn = QPushButton("Overlay bearbeiten")
    panel._overlay_edit_btn.setCursor(Qt.PointingHandCursor)
    panel._overlay_edit_btn.clicked.connect(panel._on_overlay_edit_clicked)
    reset_btn = QPushButton("Position zurücksetzen")
    reset_btn.setCursor(Qt.PointingHandCursor)
    reset_btn.clicked.connect(
        lambda: panel._overlay_hooks.get("reset", lambda: None)()
    )
    erow.addWidget(panel._overlay_edit_btn)
    erow.addWidget(reset_btn)
    erow.addStretch(1)
    label_w, _ = panel._row_label(
        "Bearbeiten",
        "Pille dauerhaft anzeigen und mit der Maus an die Wunschposition ziehen.",
    )
    form.addRow(label_w, edit_row)
