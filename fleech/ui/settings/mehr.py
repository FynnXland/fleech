"""„Mehr Optionen" — der zugeklappte zweite Teil jeder Einstellungsseite.

Seit 6.5.0 hat das Panel sechs Seiten statt zehn. Jede zeigt oben nur, was man
zum Diktieren wirklich entscheidet (rund 28 Zeilen statt 80 insgesamt); alles
Weitere steht darunter in einem eigenen Formular, das erst ein Klick aufklappt.

Bewusst ein eigenes Formular statt ausgeblendeter Zeilen im selben: Mehrere Zeilen
blenden sich schon heute je nach Wahl ein und aus (Sprechpause, Auto-Hide,
API-Schluessel). Zwei Gruende fuer „unsichtbar" in derselben Zeile liessen sich
beim Aufklappen nicht mehr auseinanderhalten.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QPushButton, QVBoxLayout, QWidget

from ..theme import MUTED, TEXT

ZU = "Mehr Optionen ▸"
AUF = "Weniger Optionen ▾"


def bereich(seite, form: QFormLayout) -> QFormLayout:
    """Unter dem Formular `form` der Seite einen zugeklappten Bereich anlegen und
    dessen eigenes Formular zurueckgeben. `seite` ist die QScrollArea aus
    `panel._page()`."""
    aussen: QVBoxLayout = seite.widget().layout()
    knopf = QPushButton(ZU)
    knopf.setObjectName("mehrOptionen")
    knopf.setCursor(Qt.PointingHandCursor)
    knopf.setFlat(True)
    rand = form.contentsMargins()
    knopf.setStyleSheet(
        f"QPushButton#mehrOptionen {{ color: {MUTED}; background: transparent; "
        f"border: none; padding: 4px 0; margin-left: {rand.left()}px; "
        f"text-align: left; font-size: 9pt; }}"
        f"QPushButton#mehrOptionen:hover {{ color: {TEXT}; }}")
    behaelter = QWidget()
    behaelter.setObjectName("mehrBereich")
    mehr = QFormLayout(behaelter)
    # Dieselben Seitenraender wie oben, sonst steht die Spalte versetzt.
    mehr.setContentsMargins(rand.left(), 6, rand.right(), rand.bottom())
    mehr.setLabelAlignment(form.labelAlignment())
    mehr.setHorizontalSpacing(form.horizontalSpacing())
    mehr.setVerticalSpacing(form.verticalSpacing())
    behaelter.setHidden(True)

    # Faengt nur die beiden Kind-Widgets, nie das Panel (Referenzzyklus-Falle).
    def umschalten(_=False, _b=behaelter, _k=knopf):
        auf = _b.isHidden()
        _b.setHidden(not auf)
        _k.setText(AUF if auf else ZU)

    knopf.clicked.connect(umschalten)
    # Vor dem Stretch am Ende einfuegen, damit alles oben buendig bleibt.
    stelle = max(0, aussen.count() - 1)
    aussen.insertWidget(stelle, knopf, 0, Qt.AlignLeft)
    aussen.insertWidget(stelle + 1, behaelter)
    return mehr


def angleichen(*formulare: QFormLayout) -> None:
    """Die Bezeichnungen aller Formulare einer Seite gleich breit machen — sonst
    springt die Steuerelement-Spalte zwischen oberem Teil und „Mehr Optionen"."""
    labels = []
    for form in formulare:
        for zeile in range(form.rowCount()):
            item = form.itemAt(zeile, QFormLayout.LabelRole)
            w = item.widget() if item is not None else None
            if w is not None:
                labels.append(w)
    if not labels:
        return
    breite = max(w.sizeHint().width() for w in labels)
    for w in labels:
        w.setMinimumWidth(breite)


def ist_zugeklappt(form: QFormLayout) -> bool:
    """Fuer Tests: Liegt dieses Formular im (noch) zugeklappten Bereich?"""
    eltern = form.parentWidget()
    return eltern is not None and eltern.objectName() == "mehrBereich" and eltern.isHidden()

