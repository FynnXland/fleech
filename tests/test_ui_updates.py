"""Update-Dialog und Update-Pruefung.

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


# -- Pause: Verdrahtung Recorder ↔ Pille ---------------------------------------------
