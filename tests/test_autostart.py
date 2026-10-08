import sys

import pytest

from fleech.ui import autostart


def test_command_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = autostart._command()
    assert "-m" in cmd and "fleech" in cmd and "--gui" in cmd


def test_command_frozen_mode(monkeypatch, tmp_path):
    exe = tmp_path / "Fleech.exe"
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    cmd = autostart._command()
    assert str(exe) in cmd and "--gui" in cmd
    assert "-m" not in cmd  # kein Python-Modul-Aufruf in der installierten App


# Die Registry-Tests laufen auf umgebogenen Schluesseln (conftest:
# `_kein_echter_autostart`, `autostart_registry`) — nie auf dem echten Eintrag.
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")


@windows_only
def test_enable_disable_roundtrip(autostart_registry):
    assert autostart.set_autostart(True)
    assert autostart.is_autostart_enabled()
    assert autostart.current_autostart_command() == autostart._command()
    assert autostart.set_autostart(False)
    assert not autostart.is_autostart_enabled()


@windows_only
def test_refresh_updates_stale_path(autostart_registry):
    import winreg

    # veralteten Eintrag setzen
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart._RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, autostart._VALUE_NAME, 0, winreg.REG_SZ,
                          '"C:\\Alt\\Pfad\\Fleech.exe" --gui')
    autostart.reconcile_autostart(True)
    assert autostart.current_autostart_command() == autostart._command()


@windows_only
def test_freigabeliste_ungerades_erstes_byte_heisst_deaktiviert(autostart_registry):
    """Die echte Lesestelle von StartupApproved — moeglich, seit auch dieser
    Schluessel in den Tests umgebogen ist."""
    import winreg

    assert autostart.set_autostart(True)
    assert not autostart.blocked_by_system()  # kein Eintrag = nie deaktiviert
    for erstes_byte, blockiert in ((3, True), (2, False)):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart._APPROVED_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, autostart._VALUE_NAME, 0, winreg.REG_BINARY,
                              bytes([erstes_byte]) + bytes(11))
        assert autostart.blocked_by_system() is blockiert


# -- Wunsch bewahren + Windows-Deaktivierung (v2.1.0) ------------------------------

def test_blocked_by_system_liest_das_erste_byte(monkeypatch):
    """Ungerades erstes Byte = im Task-Manager deaktiviert."""
    import sys as _sys

    from fleech.ui import autostart as a

    if _sys.platform != "win32":
        return
    monkeypatch.setattr(a, "is_autostart_enabled", lambda: True)
    monkeypatch.setattr(a, "_blocked_by_windows", lambda: True)
    assert a.blocked_by_system() is True
    monkeypatch.setattr(a, "_blocked_by_windows", lambda: False)
    assert a.blocked_by_system() is False
