"""Advanced — Modelle, Warmhaltung, Diagnose.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Technische Schalter — die Standardwerte passen für die meisten."
    ))
    from ...version import version_string

    version_label = QLabel(f"Fleech {version_string()}")
    version_label.setStyleSheet("font: 600 11pt 'Segoe UI';")
    form.addRow("Version", version_label)

    update_row = QWidget()
    urow = QHBoxLayout(update_row)
    urow.setContentsMargins(0, 0, 0, 0)
    check_btn = QPushButton("Nach Updates suchen")
    panel._update_status = QLabel("")
    panel._update_status.setStyleSheet("color: #808088; font-size: 8pt;")
    check_btn.clicked.connect(panel._check_updates)
    urow.addWidget(check_btn)
    urow.addWidget(panel._update_status, 1)
    label_w, _ = panel._row_label("Updates", "Manuell nach einer neuen Version suchen.")
    form.addRow(label_w, update_row)

    panel._check(form, "Automatisch nach Updates suchen", s.advanced.auto_update_check,
                 "advanced", lambda v: setattr(s.advanced, "auto_update_check", v),
                 "Beim Start und danach täglich. Gefunden wird nur geprüft und "
                 "gemeldet — installiert wird nie ohne Klick.")
    panel._check(form, "Updates im Hintergrund laden",
                 s.advanced.auto_update_download, "advanced",
                 lambda v: setattr(s.advanced, "auto_update_download", v),
                 "Lädt die neue Version gleich herunter (mit Prüfsummen-Kontrolle), "
                 "damit die Installation später nur einen Klick braucht.")

    feed = QLineEdit(s.advanced.update_feed_url)
    feed.setPlaceholderText("(leer) GitHub-Releases des Projekts")
    feed.editingFinished.connect(
        lambda: (setattr(s.advanced, "update_feed_url", feed.text().strip()),
                 panel._changed("advanced"))
    )
    label_w, _ = panel._row_label(
        "Update-Quelle",
        "Leer = GitHub-Releases des Projekts. Eine eigene HTTPS-Adresse muss auf "
        "einen JSON-Feed mit „version\", „url\" und „sha256\" zeigen.")
    form.addRow(label_w, feed)

    token = QLineEdit(s.advanced.update_token)
    token.setEchoMode(QLineEdit.Password)
    token.setPlaceholderText("(nur bei privatem Repository)")
    token.editingFinished.connect(
        lambda: (setattr(s.advanced, "update_token", token.text().strip()),
                 panel._changed("advanced"))
    )
    label_w, _ = panel._row_label(
        "Zugriffstoken",
        "Nur nötig, wenn die Update-Quelle ein privates Repository ist: ein "
        "GitHub-Token mit Leserecht („Contents: Read-only“). Er wird ausschließlich "
        "an GitHub gesendet und nie ins Log geschrieben. Alternativ die "
        "Umgebungsvariable FLEECH_UPDATE_TOKEN setzen.")
    form.addRow(label_w, token)

    # Wayland ehrlich benennen, statt Funktionen still ausfallen zu lassen.
    from ...platformpaths import WAYLAND_LIMITS, session_kind

    if session_kind() == "wayland":
        limits = "\n".join(f"• {t}" for t in WAYLAND_LIMITS)
        warn = hint(
            "Wayland erkannt — folgende Funktionen sind hier eingeschränkt:\n"
            f"{limits}\nUnter einer X11-Sitzung laufen sie vollständig."
        )
        warn.setStyleSheet("color: #E8A13C; font-size: 8pt;")
        label_w, _ = panel._row_label(
            "Sitzung", "Plattform-Einschränkungen der aktuellen Sitzungsart.")
        form.addRow(label_w, warn)

    panel._check(form, "GPU-Beschleunigung bevorzugen (STT)", s.advanced.prefer_gpu,
                 "stt_device", lambda v: setattr(s.advanced, "prefer_gpu", v),
                 "Erkennung auf der Grafikkarte (schneller). Aus = CPU erzwingen.")

    panel._combo(
        form, "Modell-Warmhaltung",
        [("smart", "Nach Nutzung (empfohlen)"),
         ("always", "Dauerhaft"),
         ("off", "Aus")],
        s.advanced.llm_keep_warm, "warmhold",
        lambda v: setattr(s.advanced, "llm_keep_warm", v),
        help_map={
            "smart": "KI bleibt nach dem letzten Diktat geladen (Zeit unten "
                     "einstellbar). Danach — oder sobald ein Spiel läuft — wird "
                     "sie sofort entladen (RAM/Grafikspeicher frei).",
            "always": "KI bleibt dauerhaft geladen (~8 GB Speicher) — "
                      "schnellste Antwort, auch beim Zocken belegt.",
            "off": "Kein Warmhalten — maximal freier Speicher, erstes "
                   "Diktat langsamer.",
        },
    )
    panel._combo(
        form, "Im Leerlauf entladen nach",
        [(3, "3 Minuten (aggressiv)"),
         (10, "10 Minuten (empfohlen)"),
         (30, "30 Minuten"),
         (45, "45 Minuten")],
        int(s.advanced.llm_idle_unload_minutes), "warmhold",
        lambda v: setattr(s.advanced, "llm_idle_unload_minutes", int(v)),
        help_map={
            3: "Gibt RAM schnell frei. Erstes Diktat nach einer Pause ~8 s "
               "langsamer (teils vom Parallel-Laden verdeckt).",
            10: "Guter Mittelweg: kurze Arbeitspausen bleiben schnell, danach "
                "wird RAM frei.",
            30: "Modelle bleiben lange warm — RAM länger belegt.",
            45: "Maximal reaktionsschnell, RAM am längsten belegt.",
        },
    )
    panel._check(form, "Adaptive Geschwindigkeit (Cleanup)", s.advanced.adaptive_cleanup,
                 "adaptive", lambda v: setattr(s.advanced, "adaptive_cleanup", v),
                 "Kurze Diktate laufen über ein kleines, schnelleres Modell.")

    from ...usersettings import SETTINGS_DIR

    panel._check(form, "Debug-Logging", s.advanced.debug_logging, "advanced",
                 lambda v: setattr(s.advanced, "debug_logging", v),
                 f"Ausführliches Protokoll in {SETTINGS_DIR / 'fleech.log'}.")
