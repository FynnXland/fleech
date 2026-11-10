"""Die vier Modi — Diktat, Befehle, Formeln, KI-Prompting — auf einer Seite."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import ACCENT, TEXT
from ...i18n import tr
from .bausteine import notiz, titel


def build(dialog) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setSpacing(10)
    lay.addWidget(titel(tr("Die vier Modi")))
    trigger = dialog._trigger_word()
    rows = [
        (tr("Diktat"), tr("einfach sprechen — Füllwörter und Versprecher räumt die "
                          "KI weg, deine Worte bleiben deine Worte.")),
        (tr("Befehle"), tr("sprich „{trigger}“ mitten im Diktat, dann die Anweisung — "
                           "z. B. „{trigger}, mach den letzten Satz formeller.“",
                           trigger=trigger)),
        (tr("Formeln"), tr("Werden automatisch im Fließtext erkannt und als LaTeX "
                           "geschrieben — abschaltbar unter Einstellungen → KI & Text.")),
        (tr("KI-Prompting"), tr("Strg+Alt+P: dein Diktat wird zu einem strukturierten "
                                "Prompt für eine KI ausformuliert.")),
    ]
    for name, beschreibung in rows:
        row = QLabel(f"<b style='color:{ACCENT};'>{name}</b>"
                     f"<span style='color:{TEXT};'> — {beschreibung}</span>")
        row.setWordWrap(True)
        row.setTextFormat(Qt.RichText)
        row.setStyleSheet("font-size: 10pt;")
        lay.addWidget(row)
    lay.addSpacing(6)
    lay.addWidget(notiz(tr(
        "Befehle und KI-Prompting brauchen eine KI — „Ohne KI“ ruhen sie. Für "
        "einzelne Apps lässt sich das Verhalten über Profile anpassen (Tab „Profile“)."
    )))
    lay.addStretch(1)
    return page
