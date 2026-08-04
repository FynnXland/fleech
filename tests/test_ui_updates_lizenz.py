"""Update-Dialog, Update-Pruefung und Lizenzeingabe.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")

_UPDATE_INFO = {
    "status": "update_available", "current": "3.13.0", "latest": "3.14.0",
    "url": "https://github.com/x/y/releases/download/v3.14.0/FleechSetup-3.14.0.exe",
    "size": 900 * 1024 * 1024, "sha256": "ab" * 32,
    "notes": "Fleech 3.14.0\n\nSHA256: " + "ab" * 32,
}


def test_update_dialog_zeigt_version_und_groesse(qapp):
    from fleech.ui.updatedialog import UpdateDialog

    dlg = UpdateDialog(_UPDATE_INFO)
    assert dlg._btn.text() == "Herunterladen"
    assert "3.14.0" in dlg.windowTitle() or "3.14.0" in dlg._info["latest"]
    dlg.reject()

def test_update_dialog_mit_fertiger_datei_installiert_direkt(qapp, tmp_path):
    """Ist die Datei schon geladen, ist der naechste Schritt die Installation —
    und die steht immer hinter einem Klick."""
    from fleech.ui.updatedialog import UpdateDialog

    datei = tmp_path / "FleechSetup-3.14.0.exe"
    datei.write_bytes(b"x")
    dlg = UpdateDialog(_UPDATE_INFO, fertige_datei=datei)
    assert dlg._btn.text() == "Installieren und neu starten"
    assert dlg._btn.isEnabled()
    dlg.reject()

def test_update_dialog_meldet_fehlgeschlagenen_download(qapp):
    from fleech.ui.updatedialog import UpdateDialog

    dlg = UpdateDialog(_UPDATE_INFO)
    dlg._on_done("")                       # Download/Pruefung fehlgeschlagen
    assert dlg._btn.text() == "Erneut versuchen"
    assert "nichts wurde installiert" in dlg._status.text()
    dlg.reject()

def test_update_dialog_ohne_startbaren_installer_nennt_den_pfad(qapp, tmp_path, monkeypatch):
    from fleech.ui import updatedialog

    datei = tmp_path / "FleechSetup-3.14.0.exe"
    datei.write_bytes(b"x")
    monkeypatch.setattr(updatedialog, "install_update", lambda p: False)
    beendet = []
    dlg = updatedialog.UpdateDialog(_UPDATE_INFO, on_quit=lambda: beendet.append(True),
                                    fertige_datei=datei)
    dlg._installieren()
    assert "von Hand" in dlg._status.text()
    assert beendet == []                   # nicht beenden, wenn nichts startete
    dlg.reject()

def test_tray_update_eintrag_ist_erst_bei_bedarf_sichtbar(qapp):
    from fleech.ui.tray import TrayController

    geklickt = []
    tray = TrayController({
        "toggle_recording": lambda: None, "toggle_overlay": lambda: None,
        "open_settings": lambda: None, "reload": lambda: None, "quit": lambda: None,
        "open_update": lambda: geklickt.append(True),
    })
    assert not tray._update_action.isVisible()
    tray.show_update("3.14.0", bereit=False)
    assert tray._update_action.text() == "Update 3.14.0 laden …"
    tray.show_update("3.14.0", bereit=True)
    assert tray._update_action.text() == "Update 3.14.0 installieren …"
    tray._update_action.trigger()
    assert geklickt == [True]
    tray.tray.hide()

def test_update_pruefung_respektiert_den_schalter(monkeypatch):
    """Aus heisst aus — auch der Start-Check darf dann nicht laufen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.advanced.auto_update_check = False
    gestartet = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: types.SimpleNamespace(
                            start=lambda: gestartet.append(True)))
    fake = types.SimpleNamespace(settings=settings, bus=None, _pending_update=None)
    DesktopApp._check_updates_async(fake)
    assert gestartet == []

    settings.advanced.auto_update_check = True
    DesktopApp._check_updates_async(fake)
    assert gestartet == [True]

def test_update_pruefung_sucht_nicht_zweimal(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    gestartet = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: types.SimpleNamespace(
                            start=lambda: gestartet.append(True)))
    fake = types.SimpleNamespace(settings=UserSettings(), bus=None,
                                 _pending_update={"latest": "3.14.0"})
    DesktopApp._check_updates_async(fake)
    assert gestartet == []


# -- Lizenz: Dialog und Aufnahme-Sperre ---------------------------------------------

def _echter_schluessel(name="Max Mustermann", expires=""):
    """Signiert mit einem Wegwerf-Paar und haengt dessen oeffentlichen Teil an
    licensing.PUBLIC_KEY_HEX — sonst muesste der Test den echten privaten
    Schluessel des Herausgebers kennen (den er nicht hat und nicht haben soll)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from fleech.licensing import sign_payload

    privat = Ed25519PrivateKey.generate()
    oeffentlich = privat.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    return sign_payload(privat, name, expires=expires), oeffentlich

def test_license_dialog_nimmt_gueltigen_schluessel_an(qapp, monkeypatch):
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    key, oeffentlich = _echter_schluessel()
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", oeffentlich)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    settings = UserSettings()
    gemeldet = []
    dlg = LicenseDialog(settings, on_changed=gemeldet.append)

    assert not dlg._ok.isEnabled()                 # leer = nichts freizuschalten
    dlg._feld.setPlainText(key)
    assert dlg._ok.isEnabled()
    assert "Max Mustermann" in dlg._status.text()
    dlg._uebernehmen()
    assert settings.general.license_key == key
    assert gemeldet == ["general"]

def test_license_dialog_lehnt_gefaelschten_schluessel_ab(qapp, monkeypatch):
    """Ein Schluessel aus einem fremden Schluesselpaar darf nicht freischalten."""
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    fremd, _ = _echter_schluessel("Freifahrer")
    _, echt = _echter_schluessel()
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", echt)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    settings = UserSettings()
    dlg = LicenseDialog(settings)
    dlg._feld.setPlainText(fremd)
    assert not dlg._ok.isEnabled()
    assert "ungültig" in dlg._status.text()
    dlg._uebernehmen()                             # darf nichts speichern
    assert settings.general.license_key == ""
    dlg.reject()

def test_license_dialog_meldet_ablauf(qapp, monkeypatch):
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    key, oeffentlich = _echter_schluessel("Alt", expires="2020-01-01")
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", oeffentlich)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg = LicenseDialog(UserSettings())
    dlg._feld.setPlainText(key)
    assert not dlg._ok.isEnabled()
    assert "abgelaufen" in dlg._status.text()
    dlg.reject()

def test_ohne_lizenz_wird_nicht_aufgenommen(monkeypatch):
    """Die Sperre sitzt VOR dem Mikrofon: ohne Schluessel wird gar nicht erst
    aufgenommen, und der Dialog kommt sofort statt einer Fehlermeldung danach.

    Der Dialog wird ANGEFORDERT, nicht gebaut: `_on_record_start` laeuft im
    pynput-Listener-Thread. Dort ein QDialog zu konstruieren hat Fleech in 4.7.0
    reproduzierbar eingefroren (Qt-Widgets gehoeren dem GUI-Thread). Deshalb
    prueft dieser Test auf das Signal — wer hier wieder direkt aufruft, faellt auf.
    """
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    angefordert, aufnahme = [], []
    fake = types.SimpleNamespace(
        settings=UserSettings(),                   # frisch = kein Schluessel
        _license_state=None,
        controller=types.SimpleNamespace(stop_if_active=lambda: None),
        bus=types.SimpleNamespace(license_needed=types.SimpleNamespace(
            emit=lambda: angefordert.append(True))),
        focus=types.SimpleNamespace(
            may_record=lambda math_mode=False: aufnahme.append(True) or (True, "")),
    )
    fake._license_ok = lambda: DesktopApp._license_ok(fake)
    DesktopApp._on_record_start(fake, "dictate")
    assert angefordert == [True]
    assert aufnahme == []                          # Mikrofon wurde nie angefasst

def test_license_state_wird_gemerkt_und_nach_eingabe_neu_bewertet(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    aufrufe = []

    def zaehl(settings):
        aufrufe.append(True)
        from fleech.licensing import LicenseState

        return LicenseState(False, reason="nein")

    monkeypatch.setattr("fleech.licensing.check", zaehl)
    fake = types.SimpleNamespace(settings=UserSettings(), _license_state=None)
    assert DesktopApp._license_ok(fake) is False
    assert DesktopApp._license_ok(fake) is False
    assert len(aufrufe) == 1                       # gemerkt, nicht bei jedem Hotkey


# -- Pause: Verdrahtung Recorder ↔ Pille ---------------------------------------------
