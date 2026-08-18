"""Was alle Einstellungs-Seiten teilen: die Einordnungszeile und die langen Hilfetexte.

Bewusst ein eigenes Modul und nicht in `settings_window.py`: Die Seiten wuerden sonst
ihr eigenes Panel importieren, das sie gerade baut — ein Zyklus, den Python beim Start
nur zufaellig ueberlebt.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel


def hint(text: str) -> QLabel:
    """Einzeilige Seiten-Einordnung oben — der einzige dauerhaft sichtbare Hinweis."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #808088; font-size: 8pt;")
    return label


INTERVENTION_HELP = {
    "minimal": "Fast Rohtext, keine KI — am schnellsten.",
    "standard": "Füllwörter weg, saubere Zeichensetzung. (Empfohlen)",
    "strong": "Stärkere Glättung mit Absätzen und Aufzählungen. Die Prüfungen "
              "auf Umformulieren und Ausschmücken sind dabei ausgesetzt — Zahlen "
              "und Verneinungen werden weiterhin geprüft.",
}

MATH_LEVEL_HELP = {
    "auto": "Gesprochene Formeln werden im Fließtext erkannt und als LaTeX "
            "geschrieben — vollständig auf diesem Rechner, ohne Umschalten. "
            "Mehrdeutige Ausdrücke werden nach den üblichen Vorrangregeln "
            "übersetzt und in der Vorschau als „geraten“ markiert; sprich "
            "„Klammer auf … Klammer zu“ mit, wenn es eindeutig sein soll.",
    "off": "Keine Formel-Erkennung. Alles wird als normaler Text behandelt.",
}
