import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Muss stehen, bevor irgendein Test die erste QApplication baut — sonst versucht Qt
# ein echtes Fenster zu öffnen. Lag früher in test_ui_smoke.py; alle anderen
# Qt-Tests hingen damit an der Dateireihenfolge.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _kein_echtes_gedaechtnis(tmp_path, monkeypatch):
    """Kein Test fasst das echte Projekt-Gedaechtnis des Nutzers an.

    `KontextSpeicher()` ohne Pfad oeffnet `%APPDATA%\\Fleech\\kontext.db` — die
    Datei mit dem real gelernten Vokabular. Die Einstellungsseite baut so einen
    Speicher beim Aufbau, und seit V-14 kann die Uebernahme eines Vorschlags dort
    auch LOESCHEN. Ein Testlauf darf das nicht koennen, deshalb zeigt der
    Vorgabepfad waehrend der Tests in ein Wegwerf-Verzeichnis.
    """
    import fleech.kontext as kontext

    monkeypatch.setattr(kontext, "DB_PATH", tmp_path / "kontext.db")


@pytest.fixture(autouse=True)
def _keine_echten_einstellungen(tmp_path, monkeypatch):
    """Kein Test fasst die echten Einstellungen des Nutzers an.

    Am 2026-08-20 hat ein Testlauf `%APPDATA%\\Fleech\\settings.json` mit den
    Vorgabewerten ueberschrieben — Hotkeys, App-Zuordnungen und Woerterbuch
    waren weg. Der Weg dorthin ist kurz und unauffaellig: Ein
    Test baut ein `SettingsPanel` mit einem frischen `UserSettings()`, tippt auf
    ein Auswahlfeld, das Panel speichert brav — und speichert eben dorthin, wo
    ohne Pfadangabe gespeichert wird.

    Deshalb wird der Pfad hier fuer JEDEN Test umgebogen, nicht in einzelnen
    Helfern. Ein Schutz, an den man sich erinnern muss, ist keiner: Die eine
    Testdatei, die den Helfer nicht benutzte, hat gereicht.

    `history.db` haengt am selben Verzeichnis und faehrt mit — der Verlauf ist
    genauso wenig Testmaterial.
    """
    import fleech.history as history
    import fleech.usersettings as us

    heim = tmp_path / "appdata"
    heim.mkdir()
    monkeypatch.setattr(us, "SETTINGS_DIR", heim)
    monkeypatch.setattr(us, "SETTINGS_PATH", heim / "settings.json")
    monkeypatch.setattr(history, "DB_PATH", heim / "history.db")


# Wurzel der Autostart-Schluessel waehrend der Tests (unter HKCU) — je Prozess
# eigen, damit zwei parallele Testlaeufe (zwei Worktrees) sich nicht gegenseitig
# die Werte loeschen.
AUTOSTART_TESTWURZEL = rf"Software\Fleech-Tests\{os.getpid()}"


@pytest.fixture(autouse=True)
def _kein_echter_autostart(monkeypatch):
    """Kein Test fasst den echten Autostart-Eintrag des Nutzers an.

    Bis 6.1.0 schrieb test_autostart.py in den echten Wert `Fleech` unter
    HKCU\\...\\CurrentVersion\\Run und raeumte im `finally` mit
    `set_autostart(False)` auf — loeschte also bei JEDEM vollen Testlauf den
    Eintrag des Nutzers. Erst der naechste Start von Fleech stellte ihn wieder her.

    Deshalb zeigen beide Schluessel, die `autostart` kennt (Run und Windows'
    Freigabeliste StartupApproved), waehrend der Tests unter
    `AUTOSTART_TESTWURZEL`. Dort existiert nichts, solange ein Test es nicht
    ausdruecklich anlegt (Fixture `autostart_registry`) — ein Test, der nebenbei
    `set_autostart()` ausloest, schreibt also nirgendwohin.

    Und weil das Umbiegen nur hilft, solange alle ueber die Konstanten gehen,
    scheitert jeder Versuch laut, den echten Schluessel ueberhaupt zu oeffnen —
    auch ueber einen hart verdrahteten Pfad. `pytest.fail` ist kein `Exception`,
    das `except Exception` in `autostart` schluckt es also nicht.

    Linux: Die XDG-Autostart-Tests biegen `XDG_CONFIG_HOME` selbst um.
    """
    if sys.platform != "win32":
        return
    import winreg

    from fleech.ui import autostart

    gesperrt = {autostart._RUN_KEY.lower(), autostart._APPROVED_KEY.lower()}

    def bewacht(original):
        def oeffnen(key, sub_key, *args, **kwargs):
            if key == winreg.HKEY_CURRENT_USER and str(sub_key).strip("\\").lower() in gesperrt:
                pytest.fail(f"Ein Test oeffnet den echten Autostart-Schluessel "
                            f"HKCU\\{sub_key} — der gehoert dem Nutzer.")
            return original(key, sub_key, *args, **kwargs)
        return oeffnen

    for name in ("OpenKey", "OpenKeyEx", "CreateKey", "CreateKeyEx"):
        monkeypatch.setattr(winreg, name, bewacht(getattr(winreg, name)))
    monkeypatch.setattr(autostart, "_RUN_KEY", AUTOSTART_TESTWURZEL + r"\Run")
    monkeypatch.setattr(autostart, "_APPROVED_KEY",
                        AUTOSTART_TESTWURZEL + r"\StartupApproved\Run")


def _loesche_schluesselbaum(winreg, pfad):
    """`winreg` kennt kein DeleteTree — Kinder zuerst, dann der Schluessel selbst."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, pfad, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    kind = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _loesche_schluesselbaum(winreg, pfad + "\\" + kind)
    except FileNotFoundError:
        return
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, pfad)


@pytest.fixture
def autostart_registry():
    """Legt die umgebogenen Autostart-Schluessel an und raeumt sie restlos ab.

    Angelegt statt vorausgesetzt: Auf dem GitHub-Runner (windows-latest) gibt es
    nicht einmal den echten Run-Schluessel — ein Test, der nur oeffnet, scheitert
    dort an `FileNotFoundError`.
    """
    import winreg

    from fleech.ui import autostart

    for pfad in (autostart._RUN_KEY, autostart._APPROVED_KEY):
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, pfad).Close()
    yield
    _loesche_schluesselbaum(winreg, AUTOSTART_TESTWURZEL)
    try:  # leer = kein anderer Testlauf mehr darunter
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Fleech-Tests")
    except OSError:
        pass


class SchluesselbundImSpeicher:
    """Ersatz fuer `keyring`: dieselben drei Aufrufe, nur ein Dict."""

    def __init__(self):
        self.daten = {}

    def get_password(self, dienst, konto):
        return self.daten.get((dienst, konto))

    def set_password(self, dienst, konto, wert):
        self.daten[(dienst, konto)] = wert

    def delete_password(self, dienst, konto):
        del self.daten[(dienst, konto)]


@pytest.fixture(autouse=True)
def schluesselbund(monkeypatch):
    """Kein Test liest oder schreibt den echten Schluesselbund des Systems — dort
    liegen echte API-Schluessel. Umgebungsvariablen der Anbieter werden ebenfalls
    ausgeblendet, damit ein lokal gesetzter OPENAI_API_KEY kein Ergebnis faerbt."""
    import fleech.llm.apikeys as apikeys
    from fleech.llm.providers import ANBIETER

    bund = SchluesselbundImSpeicher()
    monkeypatch.setattr(apikeys, "_bund", lambda: bund)
    for eintrag in ANBIETER:
        if eintrag.umgebung:
            monkeypatch.delenv(eintrag.umgebung, raising=False)
        monkeypatch.delenv(f"FLEECH_{eintrag.id.upper()}_API_KEY", raising=False)
    return bund


@pytest.fixture
def qapp():
    """Eine QApplication für alle Qt-Tests.

    Lag bisher nur in test_ui_smoke.py — jede weitere Testdatei mit Widgets hätte
    sie kopieren müssen. Qt verträgt genau eine Instanz je Prozess, deshalb wird
    eine bestehende weiterverwendet statt eine zweite zu bauen.
    """
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


class TresorAblageImSpeicher:
    """Ersatz fuer DPAPI/Secret Service: der Datenschluessel lebt nur im Test."""

    def __init__(self):
        self.wert = None

    def beschreibung(self) -> str:
        return "im Test-Speicher abgelegt"

    def lies(self):
        return self.wert

    def speichere(self, schluessel: bytes) -> None:
        self.wert = schluessel


@pytest.fixture(autouse=True)
def tresor_ablage(tmp_path, monkeypatch):
    r"""Kein Test fasst den echten Datenschluessel an (`fleech/tresor`).

    Ohne das legte der erste Test, der Einstellungen speichert, einen
    DPAPI-Block in `%APPDATA%\Fleech` an — oder schlimmer: ersetzte dort einen
    vorhandenen, und die echten Daten waeren mit dem Test-Schluessel nicht mehr
    zu oeffnen. Ablage und Datenordner zeigen deshalb fuer JEDEN Test ins
    Wegwerf-Verzeichnis; der Zwischenspeicher des Schluessels wird geleert.
    """
    from fleech.tresor import schluessel

    ablage = TresorAblageImSpeicher()
    monkeypatch.setattr(schluessel, "ablage", lambda: ablage)
    monkeypatch.setattr(schluessel, "DATENORDNER", tmp_path / "appdata")
    schluessel.vergiss()
    yield ablage
    schluessel.vergiss()


@pytest.fixture(autouse=True)
def zwischenablage(monkeypatch):
    """Kein Test schreibt in die echte Zwischenablage des Nutzers.

    Seit 6.3.0 schreibt Fleech unter Windows selbst in die Ablage (ohne Verlauf
    und Cloud, `clipboard._kopiere_privat`). Hier landet stattdessen jeder
    kopierte Text in einer Liste, die Tests pruefen koennen."""
    from fleech import clipboard

    kopiert: list = []
    monkeypatch.setattr(clipboard, "_kopiere_privat", kopiert.append)
    return kopiert
