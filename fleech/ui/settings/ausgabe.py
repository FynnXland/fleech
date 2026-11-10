"""Text-Zeilen der Seite „KI & Text": wie stark geglaettet wird und was im Feld landet.

Seit 6.5.0 ein Baustein: der Eingriffsgrad oben, Formeln, Safe-Word, gesprochene
Zeichen und Cursor-Rueckkehr unter „Mehr Optionen".
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from ...i18n import tr
from .common import INTERVENTION_HELP, MATH_LEVEL_HELP, uebersetzt


def zeilen(panel, form, mehr) -> None:
    s = panel.settings

    # Frueher eine eigene Seite „Mathe" fuer diesen EINEN Regler. Er gehoert
    # hierher: Es geht darum, was im Text landet ($…$ statt „x quadrat").
    from ...usersettings import apply_math_level, math_level

    _math_ref = s.math

    def _set_level(value: str) -> None:
        apply_math_level(_math_ref, value)

    panel._combo(
        mehr, tr("Formel-Erkennung"),
        [("auto", tr("Automatisch — erkennt Formeln im Fließtext")),
         ("off", tr("Aus"))],
        math_level(s.math), "math", _set_level,
        help_map=uebersetzt(MATH_LEVEL_HELP),
    )
    panel._combo(
        form, tr("Eingriffsgrad"),
        [("minimal", tr("Minimal")), ("standard", tr("Standard (empfohlen)")),
         ("strong", tr("Strong"))],
        s.output.intervention, "output", lambda v: setattr(s.output, "intervention", v),
        help_map=uebersetzt(INTERVENTION_HELP),
    )
    panel._check(mehr, tr("Safe-Word-Befehle aktiv"), s.output.command_enabled, "output",
                 lambda v: setattr(s.output, "command_enabled", v),
                 tr("Befehle per Safe-Word an/aus."))
    panel._trigger_field = trigger = QLineEdit(s.output.trigger_word)
    # E-17: Der Platzhalter nannte nur die Herkunft ("Wert aus config.yaml"), nie
    # den WERT selbst — genau die Frage ("auf welches Wort reagiert Fleech?") blieb
    # unbeantwortet. Best-Effort: schlaegt das Lesen fehl, bleibt wenigstens der
    # alte Hinweis auf die Herkunft stehen.
    try:
        from ...config import load_config

        _effektiv = load_config().command.trigger_word or "Kimono"
        trigger.setPlaceholderText(tr("leer = {wort} (aus config.yaml)", wort=_effektiv))
    except Exception:
        trigger.setPlaceholderText(tr("leer = Wert aus config.yaml"))
    trigger.editingFinished.connect(
        lambda: (setattr(s.output, "trigger_word", trigger.text().strip()),
                 panel._changed("output"))
    )
    label_w, _ = panel._row_label(
        tr("Safe-Word (Befehle)"),
        tr("Gesprochenes Auslösewort für Befehle, z. B. „Kimono, mach das formeller“."),
    )
    mehr.addRow(label_w, trigger)
    panel._check(mehr, tr("Gesprochene Zeichen schreiben"), s.output.spoken_symbols,
                 "output", lambda v: setattr(s.output, "spoken_symbols", v),
                 tr("„Slash Hunter“ wird zu „/Hunter“. Ersetzt werden vier Wörter "
                    "(Slash, Backslash, Hashtag, Klammeraffe), sobald ein weiteres "
                    "Wort folgt: an einen Namen gebunden („/Hunter“), vor "
                    "gewöhnlichem Text mit Leerzeichen („# oder“). „Raute“, "
                    "„Unterstrich“, „Schrägstrich“, „Minus“ und „Plus“ bleiben "
                    "Text — das sind gewöhnliche deutsche Wörter."))
    panel._check(mehr, tr("Cursor-Rückkehr"), s.output.restore_focus, "output",
                 lambda v: setattr(s.output, "restore_focus", v),
                 tr("Fügt den Text dort ein, wo das Diktat begann — auch wenn du "
                    "zwischendurch woanders hingeklickt hast."))
