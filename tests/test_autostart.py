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


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_enable_disable_roundtrip():
    try:
        assert autostart.set_autostart(True)
        assert autostart.is_autostart_enabled()
        assert autostart.current_autostart_command() == autostart._command()
    finally:
        autostart.set_autostart(False)
    assert not autostart.is_autostart_enabled()


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_refresh_updates_stale_path(monkeypatch):
    import winreg

    # veralteten Eintrag setzen
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart._RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, autostart._VALUE_NAME, 0, winreg.REG_SZ,
                          '"C:\\Alt\\Pfad\\Fleech.exe" --gui')
    try:
        autostart.reconcile_autostart(True)
        assert autostart.current_autostart_command() == autostart._command()
    finally:
        autostart.set_autostart(False)


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
