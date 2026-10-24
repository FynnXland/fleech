"""Ton-Zeilen der Seite „Pille & Töne": Quittungstoene und Lautstaerke.

Seit 6.5.0 ein Baustein: an/aus und Lautstaerke oben, Klangstil und die
einzelnen Toene unter „Mehr Optionen".
"""

from __future__ import annotations


def zeilen(panel, form, mehr) -> None:
    s = panel.settings
    panel._check(form, "UI-Sounds", s.sounds.enabled, "sounds",
                 lambda v: setattr(s.sounds, "enabled", v),
                 "Alle Töne an/aus.")
    panel._slider(form, "Lautstärke", s.sounds.volume, "sounds",
                  lambda v: setattr(s.sounds, "volume", v),
                  hint_text="Lautstärke der Fleech-Töne.")
    panel._combo(mehr, "Preset", [("soft", "Soft (Chimes)"), ("click", "Click (Ticks)")],
                 s.sounds.preset, "sounds", lambda v: setattr(s.sounds, "preset", v),
                 hint_text="Klangstil der Töne.")
    for key, label, tip in (
        ("start", "Start der Aufnahme", "Ton beim Aufnahmestart."),
        ("stop", "Stopp der Aufnahme", "Ton beim Aufnahmestopp."),
        ("commit", "Text eingefügt", "Ton, wenn der Text eingefügt wurde."),
        ("error", "Fehler/Fallback", "Ton bei Fehlern oder Ersatz-Verarbeitung."),
    ):
        panel._check(mehr, label, getattr(s.sounds, key), "sounds",
                     lambda v, k=key: setattr(s.sounds, k, v), tip)
