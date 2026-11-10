"""Technische Zeilen — seit 6.5.0 auf drei Seiten verteilt statt einer Seite „Advanced".

Eine Seite „Advanced" sammelte, was sonst keinen Platz hatte. Jetzt steht jede
Zeile bei ihrem Thema, jeweils unter „Mehr Optionen":

* `updates`   → „Allgemein" (Version, Update-Pruefung, Update-Quelle; Wayland-Hinweis oben)
* `modelle`   → „KI & Text" (Spracherkennung, GPU, Warmhaltung der lokalen KI)
* `protokoll` → „Datenschutz" (Debug-Protokoll, Diktattexte im Protokoll)

Die Widget-Bauer (`panel._combo`, ...) bleiben im Panel.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ...i18n import tr
from .common import hint


def updates(panel, form, mehr) -> None:
    """Version und Updates nach `mehr`; unter Wayland ein Hinweis nach `form`."""
    s = panel.settings
    # Wayland ehrlich benennen, statt Funktionen still ausfallen zu lassen — oben,
    # weil es erklaert, warum etwas fehlt.
    from ...platformpaths import WAYLAND_LIMITS, session_kind

    if session_kind() == "wayland":
        limits = "\n".join(f"• {tr(t)}" for t in WAYLAND_LIMITS)
        warn = hint(
            tr("Wayland erkannt — folgende Funktionen sind hier eingeschränkt:\n"
               "{limits}\nUnter einer X11-Sitzung laufen sie vollständig.",
               limits=limits)
        )
        warn.setStyleSheet("color: #E8A13C; font-size: 8pt;")
        label_w, _ = panel._row_label(
            tr("Sitzung"), tr("Plattform-Einschränkungen der aktuellen Sitzungsart."))
        form.addRow(label_w, warn)

    from ...version import version_string

    version_label = QLabel(f"Fleech {version_string()}")
    version_label.setStyleSheet("font: 600 11pt 'Segoe UI';")
    mehr.addRow(tr("Version"), version_label)

    update_row = QWidget()
    urow = QHBoxLayout(update_row)
    urow.setContentsMargins(0, 0, 0, 0)
    check_btn = QPushButton(tr("Nach Updates suchen"))
    panel._update_status = QLabel("")
    panel._update_status.setStyleSheet("color: #808088; font-size: 8pt;")
    check_btn.clicked.connect(panel._check_updates)
    urow.addWidget(check_btn)
    urow.addWidget(panel._update_status, 1)
    label_w, _ = panel._row_label(tr("Updates"), tr("Manuell nach einer neuen Version suchen."))
    mehr.addRow(label_w, update_row)

    panel._check(mehr, tr("Automatisch nach Updates suchen"), s.advanced.auto_update_check,
                 "advanced", lambda v: setattr(s.advanced, "auto_update_check", v),
                 tr("Beim Start und danach täglich. Gefunden wird nur geprüft und "
                    "gemeldet — installiert wird nie ohne Klick."))
    panel._check(mehr, tr("Updates im Hintergrund laden"),
                 s.advanced.auto_update_download, "advanced",
                 lambda v: setattr(s.advanced, "auto_update_download", v),
                 tr("Lädt die neue Version gleich herunter (mit Prüfsummen-Kontrolle), "
                    "damit die Installation später nur einen Klick braucht."))

    feed = QLineEdit(s.advanced.update_feed_url)
    feed.setPlaceholderText(tr("(leer) GitHub-Releases des Projekts"))
    feed.editingFinished.connect(
        lambda: (setattr(s.advanced, "update_feed_url", feed.text().strip()),
                 panel._changed("advanced"))
    )
    label_w, _ = panel._row_label(
        tr("Update-Quelle"),
        tr("Leer = GitHub-Releases des Projekts. Eine eigene HTTPS-Adresse muss auf "
           "einen JSON-Feed mit „version\", „url\" und „sha256\" zeigen."))
    mehr.addRow(label_w, feed)


def modelle(panel, mehr) -> None:
    """Spracherkennung, GPU und Warmhaltung der lokalen KI nach `mehr`."""
    s = panel.settings
    panel._combo(
        mehr, tr("Spracherkennung"),
        [("standard", tr("Standard")),
         ("deutsch", tr("Deutsch-optimiert"))],
        s.advanced.stt_modell, "stt_modell",
        lambda v: setattr(s.advanced, "stt_modell", v),
        help_map={
            "standard": tr("Whisper turbo — erkennt jede Sprache gleich gut."),
            "deutsch": tr("Dasselbe Modell, auf deutsche Sprache nachtrainiert: im "
                          "Test weniger Fehler und keine erfundenen Schlusssätze. "
                          "Einmaliger Download, 1,6 GB. Für englische Diktate "
                          "„Standard“ wählen."),
        },
    )
    panel._check(mehr, tr("GPU-Beschleunigung bevorzugen (STT)"), s.advanced.prefer_gpu,
                 "stt_device", lambda v: setattr(s.advanced, "prefer_gpu", v),
                 tr("Erkennung auf der Grafikkarte (schneller). Aus = CPU erzwingen."))

    mehr.addRow("", hint(
        tr("Die nächsten beiden Einstellungen gelten nur für die lokale KI (Ollama) — "
           "bei einem Cloud-Anbieter oder „Ohne KI“ wird nichts geladen.")))
    panel._combo(
        mehr, tr("Modell-Warmhaltung"),
        [("smart", tr("Nach Nutzung (empfohlen)")),
         ("always", tr("Dauerhaft")),
         ("off", tr("Aus"))],
        s.advanced.llm_keep_warm, "warmhold",
        lambda v: setattr(s.advanced, "llm_keep_warm", v),
        help_map={
            "smart": tr("KI bleibt nach dem letzten Diktat geladen (Zeit unten "
                        "einstellbar). Danach — oder sobald ein Spiel läuft — wird "
                        "sie sofort entladen (RAM/Grafikspeicher frei)."),
            "always": tr("KI bleibt dauerhaft geladen (rund 3,3 GB Speicher) — "
                         "schnellste Antwort, auch beim Zocken belegt."),
            "off": tr("Kein Warmhalten — maximal freier Speicher, erstes "
                      "Diktat langsamer."),
        },
    )
    panel._combo(
        mehr, tr("Im Leerlauf entladen nach"),
        [(3, tr("3 Minuten (aggressiv)")),
         (10, tr("10 Minuten (empfohlen)")),
         (30, tr("30 Minuten")),
         (45, tr("45 Minuten"))],
        int(s.advanced.llm_idle_unload_minutes), "warmhold",
        lambda v: setattr(s.advanced, "llm_idle_unload_minutes", int(v)),
        help_map={
            3: tr("Gibt RAM schnell frei. Erstes Diktat nach einer Pause um einige "
                  "Sekunden langsamer (teils vom Parallel-Laden verdeckt)."),
            10: tr("Guter Mittelweg: kurze Arbeitspausen bleiben schnell, danach "
                   "wird RAM frei."),
            30: tr("Modelle bleiben lange warm — RAM länger belegt."),
            45: tr("Maximal reaktionsschnell, RAM am längsten belegt."),
        },
    )
    # Der Schalter „Adaptive Geschwindigkeit (Cleanup)" ist in 5.11.0 entfallen
    # (Befund E-4): Er stand bei jedem Nutzer auf „an" und konnte nichts bewirken —
    # `cleanup` und `cleanup_fast` fahren in config.yaml BEWUSST dasselbe Modell.


def protokoll(panel, mehr) -> None:
    """Debug-Protokoll und Diktattexte im Protokoll nach `mehr`."""
    s = panel.settings
    from ...usersettings import SETTINGS_DIR

    panel._check(mehr, tr("Debug-Logging"), s.advanced.debug_logging, "advanced",
                 lambda v: setattr(s.advanced, "debug_logging", v),
                 tr("Ausführliches Protokoll in {pfad} — greift ab dem nächsten "
                    "Start von Fleech.", pfad=SETTINGS_DIR / "fleech.log"))
    panel._check(mehr, tr("Diktattexte ins Protokoll"), s.advanced.protokoll_inhalte,
                 "datenschutz", lambda v: setattr(s.advanced, "protokoll_inhalte", v),
                 tr("Nur zur Fehlersuche: Schreibt erkannten und eingefügten Text "
                    "unverschlüsselt in fleech.log. Normalerweise steht dort nur, wie "
                    "viele Wörter es waren. Danach wieder ausschalten."))
