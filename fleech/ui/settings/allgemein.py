"""Seite „Allgemein" — was man zum Diktieren braucht: Sprache, Taste, Mikrofon.

Seit 6.5.0 setzt sie sich aus Bausteinen zusammen: eigene Zeilen (Sprache,
Autostart, Anzeigename, Einfuehrung, Karten), `aufnahme` und `advanced.updates`.
Oben steht nur das Noetige, der Rest unter „Mehr Optionen" (`mehr.py`).
Verlauf und Verschluesselung sind auf die Seite „Datenschutz" gezogen.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QPushButton

from .. import autostart
from ..theme import style_button
from . import advanced, aufnahme
from .common import hint
from .mehr import angleichen, bereich


def build(panel) -> None:
    s = panel.settings
    seite, form = panel._page()
    form.addRow("", hint(
        "Sprache, Taste und Mikrofon — mehr braucht es zum Diktieren nicht."
    ))
    mehr = bereich(seite, form)
    panel._combo(
        form, "Sprache",
        [("de", "Deutsch"), ("en", "Englisch"),
         ("auto", "Automatisch (mehrsprachig)")],
        s.general.language, "general", lambda v: setattr(s.general, "language", v),
        hint_text="Sprache der Erkennung. „Automatisch“ erkennt sie selbst.",
    )
    aufnahme.zeilen(panel, form, mehr)
    panel._autostart_cb = auto = panel._check(
        form, "Autostart mit Windows", autostart.is_autostart_enabled(), "general",
        lambda v: setattr(s.general, "autostart", v),
        "Startet Fleech automatisch beim Windows-Anmelden.",
    )
    panel._autostart_warn = hint("")
    panel._autostart_warn.setStyleSheet("color: #E0574A; font-size: 8pt;")
    panel._autostart_warn.hide()
    form.addRow("", panel._autostart_warn)
    auto.toggled.connect(panel._apply_autostart)

    name = QLineEdit(s.general.display_name)
    name.setPlaceholderText("leer = Windows-Benutzername")
    name.editingFinished.connect(
        lambda: (setattr(s.general, "display_name", name.text().strip()),
                 panel._changed("general"))
    )
    label_w, _ = panel._row_label(
        "Anzeigename",
        "Name in der Begrüßung auf Home — und die Unterschrift unter Diktaten "
        "im Profil „E-Mail“. Leer heißt: die Mail endet mit der Grußformel, "
        "ohne Namen (ein geratener Name unter einer Mail wäre schlimmer).")
    mehr.addRow(label_w, name)
    onboarding_btn = style_button(QPushButton("Einführung erneut zeigen"))
    onboarding_btn.clicked.connect(panel._show_onboarding)
    label_w, _ = panel._row_label(
        "Einführung", "Der Erststart-Rundgang: Mikrofon, Bedienung, Modi.")
    mehr.addRow(label_w, onboarding_btn)

    cards_btn = style_button(QPushButton("Alle Karten wieder einblenden"))
    cards_btn.clicked.connect(panel._restore_cards)
    label_w, _ = panel._row_label(
        "Karten",
        "Karten auf Home und Insights blendest du per Rechtsklick auf die "
        "jeweilige Karte aus. Dieser Knopf holt alle zurück.")
    mehr.addRow(label_w, cards_btn)
    panel._cards_hint = hint("")
    mehr.addRow("", panel._cards_hint)
    advanced.updates(panel, form, mehr)
    angleichen(form, mehr)
