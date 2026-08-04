"""Benachrichtigungen — Tray, Toast, Overlay.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from ...usersettings import TOAST_LEVELS, apply_toast_level, toast_level
from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    f = s.focus
    form.addRow("", hint(
        "Windows-Banner (Toasts) und ruhiges Verhalten bei „Nicht stören“ und im Spiel."
    ))
    panel._check(form, "Windows Do Not Disturb respektieren", f.respect_dnd, "focus",
                 lambda v: setattr(f, "respect_dnd", v),
                 "Bei „Nicht stören“: keine unwichtigen Banner.")
    panel._check(form, "Sounds bei DND stummschalten", f.dnd_mute_sounds, "focus",
                 lambda v: setattr(f, "dnd_mute_sounds", v),
                 "Bei „Nicht stören“ zusätzlich alle Fleech-Töne stumm.")
    # Frueher fuenf einzelne Toast-Schalter. Die Entscheidung, die man wirklich
    # trifft, ist "wie viel darf mich unterbrechen" — nicht Banner fuer Banner.
    panel._combo(
        form, "Windows-Banner",
        list(TOAST_LEVELS),
        toast_level(f), "focus",
        lambda v: apply_toast_level(f, v),
        hint_text="„Wichtiges“ meldet nur Probleme (Fehler, Anbieter-Quota); "
                  "„Alles“ zusätzlich Statusmeldungen wie „läuft im Hintergrund“.",
    )
    panel._check(form, "Akzent-Sound bei kritischen Toasts", f.notification_sounds,
                 "focus", lambda v: setattr(f, "notification_sounds", v),
                 "Eigener Ton bei kritischen Bannern.")
    panel._check(form, "Gaming-/Fullscreen-Erkennung", f.gaming_detection, "focus",
                 lambda v: setattr(f, "gaming_detection", v),
                 "Erkennt Spiele und Vollbild-Apps automatisch.")
    panel._combo(
        form, "Overlay im Gaming-Modus",
        [("activity_only", "Nur bei Aufnahme/Verarbeitung (empfohlen)"),
         ("compact", "Compact"), ("hidden", "Versteckt"),
         ("unchanged", "Unverändert")],
        f.gaming_overlay, "focus", lambda v: setattr(f, "gaming_overlay", v),
        hint_text="Verhalten der Pille, während ein Spiel läuft.",
    )
    panel._slider(form, "Fleech-eigene Töne im Spiel", f.gaming_sound_factor,
                  "focus", lambda v: setattr(f, "gaming_sound_factor", v),
                  hint_text="Lautstärke der Fleech-Töne im Spiel. 0 % = stumm.")
    exceptions = QLineEdit(", ".join(f.gaming_exceptions))
    exceptions.editingFinished.connect(lambda: (
        setattr(f, "gaming_exceptions",
                [e.strip() for e in exceptions.text().split(",") if e.strip()]),
        panel._changed("focus"),
    ))
    label_w, _ = panel._row_label(
        "Ausnahmen (Prozesse)",
        "Prozesse, die nicht als Spiel gelten — durch Komma getrennt.",
    )
    form.addRow(label_w, exceptions)
    buttons = QWidget()
    row = QHBoxLayout(buttons)
    row.setContentsMargins(0, 0, 0, 0)
    test_toast = QPushButton("Test-Toast")
    test_toast.clicked.connect(lambda: panel._test_hooks.get("toast", lambda: None)())
    test_sound = QPushButton("Test-Sound")
    test_sound.clicked.connect(lambda: panel._test_hooks.get("sound", lambda: None)())
    row.addWidget(test_toast)
    row.addWidget(test_sound)
    row.addStretch(1)
    label_w, _ = panel._row_label("Testen", "Probe-Banner und Probe-Ton abspielen.")
    form.addRow(label_w, buttons)
