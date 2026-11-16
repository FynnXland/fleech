"""Audio-Fokus-Zeilen der Seite „Ruhe": andere Apps beim Diktieren leiser stellen.

Seit 6.5.0 ein Baustein: der Modus oben, die Restlautstaerke unter „Mehr Optionen".
"""

from __future__ import annotations

from ...i18n import tr


def zeilen(panel, form, mehr) -> None:
    s = panel.settings
    panel._combo(
        form, tr("Fokus-Modus"),
        [("pure_mic", tr("Aus (fremde Apps unverändert)")),
         ("soft_duck", tr("Leiser stellen (empfohlen)")),
         ("hard_focus", tr("Stark absenken"))],
        s.audio_focus.mode, "audio_focus", lambda v: setattr(s.audio_focus, "mode", v),
        help_map={
            "pure_mic": tr("Andere Apps bleiben unverändert laut."),
            "soft_duck": tr("Andere Apps werden beim Aufnehmen leiser gestellt."),
            "hard_focus": tr("Andere Apps werden beim Aufnehmen auf ein Drittel der "
                             "Restlautstärke unten abgesenkt."),
        },
    )
    panel._slider(mehr, tr("Restlautstärke anderer Apps"), s.audio_focus.duck_level,
                  "audio_focus", lambda v: setattr(s.audio_focus, "duck_level", v),
                  lo=0, hi=100,
                  hint_text=tr("Wie laut andere Apps beim Aufnehmen bleiben. 0 % = stumm."))
