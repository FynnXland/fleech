"""Audio-Fokus — Ducking und Capture-Guard.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Macht andere Apps (Musik, Videos) während der Aufnahme leiser — für ein "
        "sauberes Mikrofonsignal."
    ))
    panel._combo(
        form, "Fokus-Modus",
        [("pure_mic", "Aus (fremde Apps unverändert)"),
         ("soft_duck", "Leiser stellen (empfohlen)"),
         ("hard_focus", "Stark absenken")],
        s.audio_focus.mode, "audio_focus", lambda v: setattr(s.audio_focus, "mode", v),
        help_map={
            "pure_mic": "Andere Apps bleiben unverändert laut.",
            "soft_duck": "Andere Apps werden beim Aufnehmen leiser gestellt.",
            "hard_focus": "Andere Apps werden beim Aufnehmen stark abgesenkt.",
        },
    )
    panel._slider(form, "Restlautstärke anderer Apps", s.audio_focus.duck_level,
                  "audio_focus", lambda v: setattr(s.audio_focus, "duck_level", v),
                  lo=0, hi=100,
                  hint_text="Wie laut andere Apps beim Aufnehmen bleiben. 0 % = stumm.")
