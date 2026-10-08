"""Einstiegspunkt: python -m fleech [--config PFAD] [--list-devices]"""

from __future__ import annotations

import argparse
import logging
import sys


# Wurde stderr gegen fleech-cli.log getauscht? Dann kein zweiter Log-Ausgang.
_STDERR_IST_ERSATZ = False


def _attach_console_if_available() -> None:
    """Windowed EXE (console=False): sys.stdout/sys.stderr sind dann oft None —
    ein blankes print() wuerde crashen (AttributeError), und zwar lautlos, weil
    auch der Traceback nirgendwo hin kann. Zwei Ebenen Absicherung:

    1. An eine vorhandene Elternkonsole andocken (funktioniert z. B. aus einer
       interaktiven PowerShell heraus) — dann sind print()/Logs dort sichtbar.
    2. Klappt das nicht (kein Elternprozess mit Konsole, oder stdout/stderr
       zeigen auf eine Pipe ohne echtes Konsolen-Handle): auf eine Datei
       umleiten, damit --audio-selftest/--pipeline-selftest NIE lautlos
       sterben, sondern immer ein auswertbares Ergebnis hinterlassen.
    """
    global _STDERR_IST_ERSATZ
    # NUR eingreifen, wenn stdout/stderr tatsächlich fehlen (echtes GUI-Subsystem
    # ohne Umleitung). Hat der Elternprozess bereits umgeleitet (`> datei`, Pipe, …),
    # ist sys.stdout schon ein gueltiger Handle — den darf AttachConsole NIEMALS
    # ueberschreiben, sonst geht die Ausgabe an eine falsche, nicht erfasste Konsole.
    if sys.platform == "win32" and (sys.stdout is None or sys.stderr is None):
        try:
            import ctypes

            ATTACH_PARENT_PROCESS = -1
            if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                if sys.stdout is None:
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                if sys.stderr is None:
                    sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except Exception:
            pass

    if sys.stdout is None or sys.stderr is None:
        from .usersettings import SETTINGS_DIR

        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        fallback = open(SETTINGS_DIR / "fleech-cli.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = fallback
        if sys.stderr is None:
            sys.stderr = fallback
            _STDERR_IST_ERSATZ = True


def _debug_logging_gewuenscht() -> bool:
    """Einstellungen → Erweitert → „Debug-Logging": ist der Haken gesetzt?

    Der Schalter wurde bis 5.10.2 gespeichert und von niemandem gelesen (Befund
    B-6) — der Tooltip versprach ein ausfuehrliches Protokoll, das nie entstand.
    Bewusst defensiv: Laesst sich die settings.json hier nicht lesen, startet
    Fleech normal weiter; die Datei wird gleich darauf ohnehin regulaer geladen.
    Bewusst NUR ein Blick in die JSON, kein `UserSettings.load()`: das wuerde die
    Ladezeile („Einstellungen geladen: …") doppelt schreiben und die Heilung aus
    der .bak einen Moment zu frueh anstossen."""
    try:
        from .usersettings import SETTINGS_PATH, AdvancedSettings, _lies_json

        daten = _lies_json(SETTINGS_PATH) or {}
        vorgabe = AdvancedSettings.debug_logging
        return bool((daten.get("advanced") or {}).get("debug_logging", vorgabe))
    except Exception:
        return False


def main() -> int:
    _attach_console_if_available()
    parser = argparse.ArgumentParser(prog="fleech", description="Fleech Diktat-Engine")
    parser.add_argument("--config", help="Pfad zur config.yaml (Standard: ./config.yaml)")
    parser.add_argument(
        "--cli", action="store_true",
        help="Alter Terminal-Modus (Tk-Overlay, Logs in der Konsole) statt Desktop-App",
    )
    parser.add_argument("--gui", action="store_true", help="Desktop-App (Standard)")
    parser.add_argument("--cwd", help="Arbeitsverzeichnis setzen (fuer Autostart)")
    parser.add_argument(
        "--list-devices", action="store_true", help="Verfuegbare Audio-Geraete anzeigen"
    )
    parser.add_argument(
        "--audio-selftest", action="store_true",
        help="Audio-Selbsttest: Testton + Mikrofon-Aufnahme + Transkription",
    )
    parser.add_argument(
        "--pipeline-selftest", metavar="FIXTURES_DIR",
        help="Diagnose: Cleanup/Safe-Word-Befehl/Formel-Modus gegen echte Provider "
             "durchlaufen lassen (erwartet diktat_de.wav/command_safeword.wav/"
             "math_quadratisch.wav im angegebenen Ordner, je optional; "
             "erzeugen mit tests/fixtures/*.ps1).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging")
    args = parser.parse_args()

    if args.cwd:
        import os

        os.chdir(args.cwd)

    # Desktop-Modus: Log in Datei (%APPDATA%/Fleech), da keine Konsole existiert.
    handlers = None
    desktop_modus = not (args.cli or args.list_devices or args.audio_selftest
                         or args.pipeline_selftest)
    if desktop_modus:
        from .usersettings import SETTINGS_DIR

        from logging.handlers import RotatingFileHandler

        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        # Rotation statt endloser Datei: Das Protokoll war zuletzt 11,5 MB /
        # 126.000 Zeilen — durchsuchbar nur noch ueber Zeilennummern. Der Name
        # bleibt `fleech.log` (CLAUDE.md und die Support-Wege zeigen darauf), die
        # aelteren Staende heissen fleech.log.1 … .3. Angehaengt wird wie bisher,
        # rotiert erst beim Ueberlauf — der vorhandene Inhalt bleibt erhalten.
        handlers = [RotatingFileHandler(
            SETTINGS_DIR / "fleech.log", maxBytes=20 * 1024 * 1024, backupCount=3,
            encoding="utf-8")]
        # Nur bei einer echten Konsole mitschreiben. Ist stderr der Ersatz von oben
        # (fleech-cli.log), landete sonst JEDE Zeile ein zweites Mal dort — ohne
        # Rotation: 22 MB, zeilengleich mit fleech.log (gefunden 2026-09-29).
        if sys.stderr is not None and not _STDERR_IST_ERSATZ:
            handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        # MIT Datum: Ohne es liess sich keine Log-Zeile einem Tag zuordnen — jede
        # Fehlersuche musste ueber Start-Zeilen und Zeilennummern datieren (H-2).
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    # Der Haken in den Einstellungen wirkt jetzt wie -v: Wer ihn setzt, will beim
    # naechsten Start ein ausfuehrliches Protokoll sehen (B-6).
    if desktop_modus and not args.verbose and _debug_logging_gewuenscht():
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger(__name__).info(
            "Debug-Logging aus den Einstellungen aktiv — ausfuehrliches Protokoll. "
            "Zum Abschalten: Einstellungen → Erweitert.")

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    from .config import load_config

    if args.audio_selftest:
        from .selftest import run_audio_selftest

        return run_audio_selftest(load_config(args.config))

    if args.pipeline_selftest:
        from .pipelinetest import run_pipeline_selftest

        return run_pipeline_selftest(load_config(args.config), args.pipeline_selftest)

    if args.cli:
        from .app import DictationApp

        app = DictationApp(load_config(args.config))
        try:
            app.run()
        except KeyboardInterrupt:
            logging.getLogger(__name__).info("Beendet.")
        return 0

    from .ui.desktop import run_desktop

    return run_desktop()


if __name__ == "__main__":
    sys.exit(main())
