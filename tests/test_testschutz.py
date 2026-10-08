"""Der Testlauf darf die echten Daten des Nutzers nicht anfassen.

Diese Datei prueft nicht die App, sondern die Testumgebung — und sie steht hier,
weil genau das einmal schiefgegangen ist: Am 2026-08-20 hat ein Lauf der
Testsuite `%APPDATA%\\Fleech\\settings.json` mit den Vorgabewerten ueberschrieben.
Weg waren Hotkeys, App-Zuordnungen und Woerterbuch.

Der Ablauf war unspektakulaer: Eine Testdatei baute ein `SettingsPanel` mit einem
frischen `UserSettings()`, ohne den Pfad umzubiegen. Ein Klick auf ein Auswahlfeld,
das Panel speicherte — und ohne Pfadangabe speichert `save()` dorthin, wo die
echten Einstellungen liegen. Andere Testdateien bogen den Pfad um; diese eine
nicht. Deshalb liegt der Schutz jetzt in `conftest.py` und gilt fuer jeden Test,
und deshalb gibt es diese Datei: damit ein entfernter Schutz auffaellt, bevor er
das zweite Mal etwas kostet.
"""

import os
import sys
from pathlib import Path

import pytest

import fleech.history as history
import fleech.kontext as kontext
import fleech.usersettings as us
from fleech.platformpaths import user_data_dir
from fleech.ui import autostart


def _norm(pfad) -> str:
    """Vergleichbare Schreibweise — bewusst OHNE `resolve()`.

    `resolve()` folgt unter Windows auch der Datei-Umleitung von Store-Apps: Aus
    `%APPDATA%\\Fleech\\settings.json` wurde dabei ein Pfad unter
    `AppData\\Local\\Packages\\…\\LocalCache\\Roaming`, waehrend der Ordner
    daneben unveraendert blieb. Der Vergleich lief dann ins Leere und die
    Zusicherung galt als erfuellt, obwohl der Pfad mitten in den echten Daten lag.
    `abspath` + `normcase` reicht hier und ist ehrlich.
    """
    return os.path.normcase(os.path.abspath(str(pfad)))


def _liegt_im_echten_ordner(pfad) -> bool:
    echt = _norm(user_data_dir())
    return _norm(pfad) == echt or _norm(pfad).startswith(echt + os.sep)


def test_einstellungen_zeigen_waehrend_der_tests_ins_wegwerf_verzeichnis():
    assert not _liegt_im_echten_ordner(us.SETTINGS_PATH), (
        f"SETTINGS_PATH zeigt auf {us.SETTINGS_PATH} — ein Test kann damit die "
        f"echten Einstellungen ueberschreiben."
    )
    assert not _liegt_im_echten_ordner(us.SETTINGS_DIR)


def test_verlauf_und_gedaechtnis_ebenso():
    assert not _liegt_im_echten_ordner(history.DB_PATH)
    assert not _liegt_im_echten_ordner(kontext.DB_PATH)


def test_speichern_ohne_pfad_landet_nicht_beim_nutzer():
    """Der Beweis am echten Aufruf, nicht nur an der Konstanten.

    `save()` ohne Pfad ist der Aufruf, der den Schaden angerichtet hat — also
    genau der, der hier laufen muss."""
    s = us.UserSettings()
    s.save()
    assert Path(us.SETTINGS_PATH).is_file()
    assert not _liegt_im_echten_ordner(us.SETTINGS_PATH)


# -- Der Autostart-Eintrag des Nutzers ebenso nicht -----------------------------------

_ECHTER_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_ECHTE_FREIGABE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_autostart_zeigt_waehrend_der_tests_nicht_in_den_echten_schluessel():
    """Bis 6.1.0 hat jeder volle Testlauf den echten Autostart-Eintrag
    geloescht (test_autostart.py raeumte im `finally` den Wert `Fleech` ab)."""
    assert autostart._RUN_KEY.lower() != _ECHTER_RUN.lower()
    assert autostart._APPROVED_KEY.lower() != _ECHTE_FREIGABE.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
@pytest.mark.parametrize("pfad", [_ECHTER_RUN, _ECHTE_FREIGABE])
def test_echter_autostart_schluessel_ist_gesperrt(pfad):
    """Auch ein hart verdrahteter Pfad kommt nicht durch — weder zum Lesen noch
    zum Schreiben."""
    import winreg

    with pytest.raises(pytest.fail.Exception, match="echten Autostart-Schluessel"):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, pfad, 0, winreg.KEY_SET_VALUE)
    with pytest.raises(pytest.fail.Exception):
        winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, pfad + "\\")


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_set_autostart_nebenbei_schreibt_nirgendwohin():
    """Ein Test, der (etwa ueber einen Einstellungs-Schalter) `set_autostart`
    ausloest, ohne die Test-Schluessel anzulegen, landet im Leeren."""
    assert autostart.set_autostart(True) is False
    assert not autostart.is_autostart_enabled()


# -- Ein Update darf die Einstellungen nicht anfassen -----------------------------------

def test_installer_loescht_die_einstellungen_nicht():
    r"""Der Installer schreibt nach %LOCALAPPDATA%\Programs\Fleech, die
    Einstellungen liegen in %APPDATA%\Fleech — getrennte Orte, damit ein Update
    sie gar nicht erreichen kann.

    Geprueft wird trotzdem, und zwar an der Installer-Beschreibung selbst: Ein
    `[UninstallDelete]`/`[InstallDelete]`-Eintrag auf den Einstellungsordner waere
    eine Zeile Arbeit und wuerde beim naechsten Update alles loeschen. Genau die
    Zeile soll auffallen, bevor sie ausgeliefert wird.
    """
    iss = Path(__file__).resolve().parent.parent / "packaging" / "fleech.iss"
    text = iss.read_text(encoding="utf-8", errors="replace")

    abschnitt = None
    for zeile in text.splitlines():
        nackt = zeile.strip()
        if nackt.startswith("[") and nackt.endswith("]"):
            abschnitt = nackt.lower()
            continue
        if abschnitt not in ("[uninstalldelete]", "[installdelete]"):
            continue
        if not nackt or nackt.startswith(";"):
            continue
        klein = nackt.lower()
        assert "settings" not in klein, f"Installer loescht Einstellungen: {nackt}"
        # Den ganzen Ordner wegzuraeumen trifft settings.json, history.db und den
        # Signierschluessel auf einmal.
        assert not klein.rstrip('"').endswith("{userappdata}\fleech"), (
            f"Installer loescht den ganzen Datenordner: {nackt}")
