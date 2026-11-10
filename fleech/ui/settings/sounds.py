"""Ton-Zeilen der Seite „Pille & Töne": Quittungstoene und Lautstaerke.

Seit 6.5.0 ein Baustein: an/aus und Lautstaerke oben, Klangstil und die
einzelnen Toene unter „Mehr Optionen".
"""

from __future__ import annotations

from ...i18n import N_, tr


def zeilen(panel, form, mehr) -> None:
    s = panel.settings
    panel._check(form, tr("UI-Sounds"), s.sounds.enabled, "sounds",
                 lambda v: setattr(s.sounds, "enabled", v),
                 tr("Alle Töne an/aus."))
    panel._slider(form, tr("Lautstärke"), s.sounds.volume, "sounds",
                  lambda v: setattr(s.sounds, "volume", v),
                  hint_text=tr("Lautstärke der Fleech-Töne."))
    panel._combo(mehr, tr("Klangstil"), [("warm", tr("Warm (Standard)")),
                                         ("chimes", tr("Klassisch (Chimes)")),
                                         ("click", tr("Click (Ticks)"))],
                 s.sounds.preset, "sounds", lambda v: setattr(s.sounds, "preset", v),
                 hint_text=tr("Klangstil der Töne."))
    for key, label, tip in (
        ("start", N_("Start der Aufnahme"), N_("Ton beim Aufnahmestart.")),
        ("stop", N_("Stopp der Aufnahme"), N_("Ton beim Aufnahmestopp.")),
        ("commit", N_("Text eingefügt"), N_("Ton, wenn der Text eingefügt wurde.")),
        ("error", N_("Fehler/Fallback"), N_("Ton bei Fehlern oder Ersatz-Verarbeitung.")),
    ):
        panel._check(mehr, tr(label), getattr(s.sounds, key), "sounds",
                     lambda v, k=key: setattr(s.sounds, k, v), tr(tip))
