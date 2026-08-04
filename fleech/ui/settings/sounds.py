"""Sounds — Quittungstoene und Lautstaerke.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Fleechs eigene Töne für Start, Stopp, eingefügten Text und Fehler."
    ))
    panel._check(form, "UI-Sounds", s.sounds.enabled, "sounds",
                 lambda v: setattr(s.sounds, "enabled", v),
                 "Alle Töne an/aus.")
    panel._slider(form, "Lautstärke", s.sounds.volume, "sounds",
                  lambda v: setattr(s.sounds, "volume", v),
                  hint_text="Lautstärke der Fleech-Töne.")
    panel._combo(form, "Preset", [("soft", "Soft (Chimes)"), ("click", "Click (Ticks)")],
                 s.sounds.preset, "sounds", lambda v: setattr(s.sounds, "preset", v),
                 hint_text="Klangstil der Töne.")
    for key, label, tip in (
        ("start", "Start der Aufnahme", "Ton beim Aufnahmestart."),
        ("stop", "Stopp der Aufnahme", "Ton beim Aufnahmestopp."),
        ("commit", "Text eingefügt", "Ton, wenn der Text eingefügt wurde."),
        ("error", "Fehler/Fallback", "Ton bei Fehlern oder Ersatz-Verarbeitung."),
    ):
        panel._check(form, label, getattr(s.sounds, key), "sounds",
                     lambda v, k=key: setattr(s.sounds, k, v), tip)
