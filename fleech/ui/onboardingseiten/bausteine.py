"""Textbausteine der Einfuehrung — Titel, Fliesstext, Randnotiz, Auswahlbox."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel

from ..chevron import apply_chevrons
from ..theme import MUTED, TEXT

TITEL_STIL = f"color: {TEXT}; font-size: 14pt; font-weight: 600;"
TEXT_STIL = f"color: {TEXT}; font-size: 10pt;"
NOTIZ_STIL = f"color: {MUTED}; font-size: 9pt;"
ROT = "color: #E5484D; font-size: 9pt;"
GRUEN = "color: #4CC38A; font-size: 9pt;"
GELB = "color: #E8A13C; font-size: 9pt;"


def titel(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(TITEL_STIL)
    label.setWordWrap(True)
    return label


def text(inhalt: str) -> QLabel:
    label = QLabel(inhalt)
    label.setStyleSheet(TEXT_STIL)
    label.setWordWrap(True)
    return label


def notiz(inhalt: str) -> QLabel:
    label = QLabel(inhalt)
    label.setStyleSheet(NOTIZ_STIL)
    label.setWordWrap(True)
    return label


def auswahl() -> QComboBox:
    box = QComboBox()
    box.setStyleSheet(apply_chevrons(box.styleSheet() or ""))
    return box
