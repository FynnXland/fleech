"""Pillen-Zeilen der Seite „Pille & Töne": Sichtbarkeit, Groesse, Position.

Seit 6.5.0 ein Baustein: Sichtbarkeit, Groesse und Position oben, Optik und
Verhalten im Detail unter „Mehr Optionen".
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QPushButton, QWidget

from ...i18n import tr
from ...usersettings import (
    OVERLAY_COMPACTNESS,
    apply_overlay_compactness,
    overlay_compactness,
)

def zeilen(panel, form, mehr) -> None:
    s = panel.settings
    # „Auto-Hide nach" wirkt nur bei Sichtbarkeit „auto_hide" (E-15) — dieselbe
    # Verzoegerungs-Liste wie beim Sprechpause-Regler auf der Aufnahme-Seite: Die
    # Zeile entsteht ERST unten, der Setter braucht sie aber schon beim Bau des
    # Combos. Faengt bewusst nur `s`/die Liste, nie `panel` (Referenzzyklus).
    auto_hide_zeilen: list = []

    def sichtbarkeit_gesetzt(v, _ziel=s.overlay, _zeilen=auto_hide_zeilen):
        _ziel.visibility = v
        for layout, row in _zeilen:
            layout.setRowVisible(row, v == "auto_hide")

    panel._sichtbarkeit_box = panel._combo(
        form, tr("Sichtbarkeit"),
        [("during_activity", tr("Nur während Aufnahme/Verarbeitung (empfohlen)")),
         ("always", tr("Immer sichtbar")),
         ("auto_hide", tr("Automatisch ausblenden")),
         ("off", tr("Deaktiviert"))],
        s.overlay.visibility, "overlay", sichtbarkeit_gesetzt,
        hint_text=tr("Wann die Pille zu sehen ist."),
    )
    hide_seconds = QDoubleSpinBox()
    hide_seconds.setRange(0.5, 60.0)
    hide_seconds.setValue(s.overlay.auto_hide_seconds)
    hide_seconds.setSuffix(" s")
    hide_seconds.valueChanged.connect(
        lambda v: (setattr(s.overlay, "auto_hide_seconds", v), panel._changed("overlay"))
    )
    label_w, _ = panel._row_label(
        tr("Auto-Hide nach"), tr("Nach dieser Zeit blendet sich die Pille aus."))
    form.addRow(label_w, hide_seconds)
    panel._auto_hide_box = hide_seconds  # fuer Tests/Nachvollziehbarkeit greifbar
    auto_hide_zeilen.append((form, hide_seconds))
    form.setRowVisible(hide_seconds, s.overlay.visibility == "auto_hide")
    panel._combo(
        form, tr("Größe"),
        [("compact", tr("Kompakt")), ("normal", tr("Standard")), ("large", tr("Groß"))],
        s.overlay.size, "overlay", lambda v: setattr(s.overlay, "size", v),
        hint_text=tr("Gesamtgröße der Pille."),
    )
    # Frueher vier Spinboxen (links/rechts/oben/unten). Die einzelne Einstellbarkeit
    # hat in der Praxis niemand gebraucht — hier steht EINE Stufe, die alle vier
    # Werte setzt. Wer es genauer will, kann sie in der settings.json weiterhin
    # frei setzen; `overlay_compactness` waehlt dann die naechstliegende Stufe.
    panel._combo(
        mehr, tr("Pillen-Rand"),
        [(wert, tr(text)) for wert, text in OVERLAY_COMPACTNESS],
        overlay_compactness(s.overlay), "overlay",
        lambda v: apply_overlay_compactness(s.overlay, v),
        hint_text=tr("Innenabstand des Pillen-Hintergrunds — enger wirkt kompakter."),
    )
    panel._combo(
        mehr, tr("Rand-Buttons"),
        [(True, tr("Eigener Hintergrund (getrennte Inseln)")),
         (False, tr("In einer durchgehenden Pille"))],
        s.overlay.separate_islands, "overlay",
        lambda v: setattr(s.overlay, "separate_islands", v),
        help_map={
            True: tr("Mathe-Punkt und Trigger-Button als eigene Inseln neben der Pille."),
            False: tr("Alles in einem durchgehenden Hintergrund."),
        },
    )
    panel._slider(mehr, tr("Transparenz"), s.overlay.opacity, "overlay",
                  lambda v: setattr(s.overlay, "opacity", v), lo=20, hi=100,
                  hint_text=tr("Deckkraft der Pille."))
    panel._slider(mehr, tr("Pegel-Empfindlichkeit"), s.overlay.level_gain, "overlay",
                  lambda v: setattr(s.overlay, "level_gain", v), lo=20, hi=300,
                  hint_text=tr("Wie stark die Waveform ausschlägt — rein optisch, hilft "
                              "bei leisen Mikrofonen."))
    panel._check(mehr, tr("Click-Through"), s.overlay.click_through, "overlay",
                 lambda v: setattr(s.overlay, "click_through", v),
                 tr("Mausklicks gehen durch die Pille hindurch — auch auf die "
                    "Knöpfe der Pille: ✕, ✓, Pause und Ziehen sind dann nicht mehr "
                    "bedienbar. Rückweg: „Overlay bearbeiten“ weiter oben."))
    panel._check(mehr, tr("Folgt dem Maus-Bildschirm"), s.overlay.follow_mouse_screen,
                 "overlay", lambda v: setattr(s.overlay, "follow_mouse_screen", v),
                 tr("Die Pille erscheint auf dem Monitor des Mauszeigers."))
    panel._check(mehr, tr("Live-Transkription (experimentell)"), s.overlay.live_preview,
                 "overlay", lambda v: setattr(s.overlay, "live_preview", v),
                 tr("Grobe Echtzeit-Vorschau beim Sprechen (zusätzliches Modell, "
                    "~0,5 GB VRAM)."))
    panel._check(mehr, tr("Erkannten Text über Overlay zeigen"), s.overlay.show_transcript,
                 "overlay", lambda v: setattr(s.overlay, "show_transcript", v),
                 tr("Zeigt den fertigen Text kurz über der Pille."))

    # Position: Presets + Bearbeiten/Reset
    from ..overlay_qt import OVERLAY_PRESETS

    preset_row = QWidget()
    prow = QHBoxLayout(preset_row)
    prow.setContentsMargins(0, 0, 0, 0)
    prow.setSpacing(6)
    for key, label in OVERLAY_PRESETS:
        b = QPushButton(tr(label))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(
            lambda _=False, k=key: panel._overlay_hooks.get("apply_preset",
                                                            lambda _k: None)(k)
        )
        prow.addWidget(b)
    prow.addStretch(1)
    label_w, _ = panel._row_label(tr("Position"), tr("Pille am Bildschirmrand ausrichten."))
    form.addRow(label_w, preset_row)

    edit_row = QWidget()
    erow = QHBoxLayout(edit_row)
    erow.setContentsMargins(0, 0, 0, 0)
    erow.setSpacing(6)
    panel._overlay_edit_btn = QPushButton(tr("Overlay bearbeiten"))
    panel._overlay_edit_btn.setCursor(Qt.PointingHandCursor)
    panel._overlay_edit_btn.clicked.connect(panel._on_overlay_edit_clicked)
    reset_btn = QPushButton(tr("Position zurücksetzen"))
    reset_btn.setCursor(Qt.PointingHandCursor)
    reset_btn.clicked.connect(
        lambda: panel._overlay_hooks.get("reset", lambda: None)()
    )
    erow.addWidget(panel._overlay_edit_btn)
    erow.addWidget(reset_btn)
    erow.addStretch(1)
    label_w, _ = panel._row_label(
        tr("Bearbeiten"),
        tr("Pille dauerhaft anzeigen und mit der Maus an die Wunschposition ziehen."),
    )
    form.addRow(label_w, edit_row)
