"""Allgemein — Autostart, Sprache, Name, Verlauf.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QPushButton

from .. import autostart
from ..theme import style_button
from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Grundlegendes: Start mit Windows, Sprache, dein Name und der lokale Verlauf."
    ))
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
    panel._combo(
        form, "Sprache",
        [("de", "Deutsch"), ("en", "Englisch"),
         ("auto", "Automatisch (mehrsprachig)")],
        s.general.language, "general", lambda v: setattr(s.general, "language", v),
        hint_text="Sprache der Erkennung. „Automatisch“ erkennt sie selbst.",
    )
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
    form.addRow(label_w, name)
    panel._check(form, "Diktat-Verlauf speichern", s.general.save_history, "general",
                 lambda v: setattr(s.general, "save_history", v),
                 "Speichert Diktate lokal für Home und Insights — keine Cloud.")
    clear_btn = style_button(QPushButton("Verlauf löschen …"), "danger")
    clear_btn.clicked.connect(lambda: (panel._on_clear_history or (lambda: None))())
    label_w, _ = panel._row_label(
        "Verlauf", "Löscht alle Diktate endgültig — dazu „Delete“ eintippen.")
    form.addRow(label_w, clear_btn)
    onboarding_btn = style_button(QPushButton("Einführung erneut zeigen"))
    onboarding_btn.clicked.connect(panel._show_onboarding)
    label_w, _ = panel._row_label(
        "Einführung", "Der Erststart-Rundgang: Mikrofon, Bedienung, Modi.")
    form.addRow(label_w, onboarding_btn)

    cards_btn = style_button(QPushButton("Alle Karten wieder einblenden"))
    cards_btn.clicked.connect(panel._restore_cards)
    label_w, _ = panel._row_label(
        "Karten",
        "Karten auf Home und Insights blendest du per Rechtsklick auf die "
        "jeweilige Karte aus. Dieser Knopf holt alle zurück.")
    form.addRow(label_w, cards_btn)
    panel._cards_hint = hint("")
    form.addRow("", panel._cards_hint)
