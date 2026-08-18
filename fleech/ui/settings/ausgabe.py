"""Ausgabe — wie der Text ins Feld kommt.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from .common import hint, INTERVENTION_HELP, MATH_LEVEL_HELP


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Wie stark die KI dein Diktat glättet — pro App feiner steuerbar im Tab "
        "„Profile“."
    ))

    # Frueher eine eigene Seite „Mathe" fuer diesen EINEN Regler. Er gehoert
    # hierher: Es geht darum, was im Text landet ($…$ statt „x quadrat").
    from ...usersettings import apply_math_level, math_level

    _math_ref = s.math

    def _set_level(value: str) -> None:
        apply_math_level(_math_ref, value)

    panel._combo(
        form, "Formel-Erkennung",
        [("auto", "Automatisch — erkennt Formeln im Fließtext"),
         ("off", "Aus")],
        math_level(s.math), "math", _set_level,
        help_map=MATH_LEVEL_HELP,
    )
    panel._combo(
        form, "Eingriffsgrad",
        [("minimal", "Minimal"), ("standard", "Standard (empfohlen)"), ("strong", "Strong")],
        s.output.intervention, "output", lambda v: setattr(s.output, "intervention", v),
        help_map=INTERVENTION_HELP,
    )
    panel._check(form, "Safe-Word-Befehle aktiv", s.output.command_enabled, "output",
                 lambda v: setattr(s.output, "command_enabled", v),
                 "Befehle per Safe-Word an/aus.")
    panel._check(form, "Gesprochene Zeichen schreiben", s.output.spoken_symbols,
                 "output", lambda v: setattr(s.output, "spoken_symbols", v),
                 "„Slash Hunter“ wird zu „/Hunter“. Ersetzt werden vier Wörter "
                 "(Slash, Backslash, Hashtag, Klammeraffe), sobald ein weiteres "
                 "Wort folgt: an einen Namen gebunden („/Hunter“), vor "
                 "gewöhnlichem Text mit Leerzeichen („# oder“). „Raute“, "
                 "„Unterstrich“, „Schrägstrich“, „Minus“ und „Plus“ bleiben "
                 "Text — das sind gewöhnliche deutsche Wörter.")
    panel._check(form, "Cursor-Rückkehr", s.output.restore_focus, "output",
                 lambda v: setattr(s.output, "restore_focus", v),
                 "Fügt den Text dort ein, wo das Diktat begann — auch wenn du "
                 "zwischendurch woanders hingeklickt hast.")
    trigger = QLineEdit(s.output.trigger_word)
    trigger.setPlaceholderText("leer = Wert aus config.yaml")
    trigger.editingFinished.connect(
        lambda: (setattr(s.output, "trigger_word", trigger.text().strip()),
                 panel._changed("output"))
    )
    label_w, _ = panel._row_label(
        "Safe-Word (Befehle)",
        "Gesprochenes Auslösewort für Befehle, z. B. „Kimono, mach das formeller“.",
    )
    form.addRow(label_w, trigger)
