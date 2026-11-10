"""Wird der Wortlaut aufgehoben? — eine bewusste Entscheidung, kein Schalter.

Der Verlauf war immer schon abschaltbar, aber standardmaessig AN und nur unter
Einstellungen → Allgemein zu finden. Ein externes Gutachten hat das als Opt-out
bei sensiblen Inhalten benannt, und der Punkt traegt: Der vollstaendige Wortlaut
jedes Diktats bleibt auf der Platte stehen. Seit 6.3.0 verschluesselt (`tresor/`),
aber wer Gesundheitliches, Finanzielles oder versehentlich ein Passwort diktiert,
sollte trotzdem entschieden haben, ob es aufgehoben wird, und es nicht entdecken.
Bis 6.5.0 stand hier noch „unverschlüsselt" — eine falsche Angabe seit dem Tresor.

Der Standardwert bleibt AN — Home und Insights leben davon. Also: die Frage.
Sie steht VOR dem Probediktat: Wer gleich etwas diktiert, soll vorher entschieden
haben, ob es aufgehoben wird.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

from ..theme import TEXT
from ...i18n import tr
from .bausteine import notiz, text, titel


def build(dialog) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setSpacing(12)
    lay.addWidget(titel(tr("Was Fleech sich merkt")))
    lay.addWidget(text(tr(
        "Fleech kann jedes Diktat aufheben — den gesprochenen Rohtext und den "
        "fertigen Text. Daraus entstehen die Startseite, die Auswertungen und die "
        "Wörterbuch-Vorschläge."
    )))
    lay.addWidget(text(tr(
        "Gespeichert wird nur auf diesem Rechner, verschlüsselt und an deine "
        "Anmeldung gebunden. Nichts davon wird gesendet — aber es steht danach "
        "dort, standardmäßig 90 Tage lang."
    )))
    box = QCheckBox(tr("Diktate im Verlauf aufheben"))
    box.setChecked(bool(dialog.settings.general.save_history))
    box.setStyleSheet(f"color: {TEXT}; font-size: 10pt;")
    box.toggled.connect(dialog._on_verlauf_toggled)
    dialog._verlauf_cb = box
    lay.addWidget(box)
    lay.addSpacing(4)
    lay.addWidget(notiz(tr(
        "Ohne Verlauf funktioniert das Diktieren genau gleich — nur Startseite und "
        "Auswertungen bleiben leer. Jederzeit änderbar unter Einstellungen → "
        "Datenschutz, samt Knopf zum Löschen des bisherigen Verlaufs."
    )))
    lay.addStretch(1)
    return page
