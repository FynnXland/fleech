"""Probediktat — direkt im Dialog statt „klick nachher irgendwo hin".

Das Feld ist ein ganz normales Textfeld: Fleech fuegt hier genauso ein wie in
jedes andere Programm (Zwischenablage + Strg+V an das Fenster, das beim
Aufnahmestart vorn war). Kommt Text an, ist die ganze Kette bewiesen —
Mikrofon, Taste, Erkennung, KI, Einfuegen.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ... import i18n
from ...i18n import tr
from ..theme import BORDER_HAIRLINE, TEXT
from .bausteine import GRUEN, NOTIZ_STIL, notiz, text, titel
from .taste import tasten_name

FUELLWORT = {"de": "äh", "en": "uh"}   # das Füllwort im Beispiel
BEISPIEL = {
    "de": "„Das ist mein erstes Diktat mit Fleech, äh, mal sehen, was die "
          "Bereinigung daraus macht.“",
    "en": "“This is my first dictation with Fleech, uh, let's see what the "
          "cleanup makes of it.”",
}


def build(dialog) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setSpacing(10)
    lay.addWidget(titel(tr("Probediktat")))
    dialog._probe_anleitung = text("")
    lay.addWidget(dialog._probe_anleitung)
    beispiel = QLabel("")
    beispiel.setWordWrap(True)
    beispiel.setStyleSheet(
        f"color: {TEXT}; font-size: 10.5pt; font-style: italic;"
        f" background: rgba(255,255,255,0.05); border-radius: 8px; padding: 10px;"
    )
    dialog._probe_beispiel = beispiel
    lay.addWidget(beispiel)
    feld = QPlainTextEdit()
    feld.setPlaceholderText(tr("Hier hineinklicken, dann diktieren …"))
    feld.setFixedHeight(90)
    feld.setStyleSheet(
        f"QPlainTextEdit {{ background: rgba(255,255,255,0.04); color: {TEXT};"
        f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px; padding: 6px;"
        f"  font-size: 10.5pt; }}"
    )
    feld.textChanged.connect(dialog._on_probe_text)
    dialog._probe_feld = feld
    lay.addWidget(feld)
    dialog._probe_status = notiz("")
    lay.addWidget(dialog._probe_status)
    lay.addStretch(1)
    lay.addWidget(notiz(tr("Diese Einführung findest du jederzeit wieder unter "
                           "Einstellungen → Allgemein → Mehr Optionen.")))
    return page


def aktualisiere(dialog, downloads_laufen: bool = False) -> None:
    """Beim Betreten: Taste, Bedienart und Sprache koennen sich geaendert haben."""
    settings = dialog.settings
    taste = tasten_name(settings)
    if settings.recording.mode == "toggle":
        wie = tr("drück {taste} einmal, sprich, und drück sie erneut", taste=taste)
    elif settings.recording.mode == "nudge":
        wie = tr("drück {taste} einmal und sprich — hörst du auf, endet die Aufnahme",
                 taste=taste)
    else:
        wie = tr("halte {taste} gedrückt, während du sprichst", taste=taste)
    dialog._probe_anleitung.setText(
        tr("Klick in das Feld unten und {wie}. Zum Beispiel:", wie=wie))
    # „Automatisch“: das Beispiel in der Sprache der Oberfläche.
    sprache = settings.general.language
    if sprache not in BEISPIEL:
        sprache = i18n.aktuell() if i18n.aktuell() in BEISPIEL else "de"
    dialog._probe_beispiel.setText(BEISPIEL[sprache])
    if dialog._probe_feld.toPlainText().strip():
        return
    if downloads_laufen:
        dialog._probe_status.setText(tr("Die Modelle laden noch (Zeile unten) — das "
                                        "Probediktat klappt, sobald sie fertig sind."))
    else:
        dialog._probe_status.setText(tr("Das „{fuellwort}“ sollte im Ergebnis fehlen — "
                                        "der Rest bleibt wortgetreu.",
                                        fuellwort=FUELLWORT[sprache]))
    dialog._probe_status.setStyleSheet(NOTIZ_STIL)


def angekommen(dialog) -> None:
    if dialog._probe_feld.toPlainText().strip():
        dialog._probe_status.setText(tr("✓ Angekommen. Genauso landet Text in jedem "
                                        "anderen Programm, in dem dein Cursor steht."))
        dialog._probe_status.setStyleSheet(GRUEN)
