"""Windowed EXE (console=False): sys.stdout/stderr koennen None sein — print() darf
dann nie lautlos crashen. _attach_console_if_available() muss immer beschreibbare
Streams herstellen (Datei-Fallback, wenn keine Konsole andockbar ist).
"""

import sys

from fleech.__main__ import _attach_console_if_available


def test_none_stdio_gets_file_fallback(tmp_path, monkeypatch):
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    monkeypatch.setattr(sys, "stderr", None, raising=False)
    # AttachConsole selbst nicht simulieren (kein Elternprozess in Tests) —
    # der Datei-Fallback muss trotzdem greifen.
    monkeypatch.setattr(sys, "platform", "linux", raising=False)  # AttachConsole-Pfad ueberspringen

    _attach_console_if_available()

    assert sys.stdout is not None
    assert sys.stderr is not None
    print("dies darf nicht crashen")  # koennte AttributeError werfen, wenn kaputt
    assert (tmp_path / "fleech-cli.log").is_file()


def test_existing_stdio_is_left_alone(monkeypatch):
    import io

    real_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", real_stdout, raising=False)
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    _attach_console_if_available()
    assert sys.stdout is real_stdout


def test_valid_redirected_stdout_survives_successful_attach_console(monkeypatch):
    """Regression: `Fleech.exe --pipeline-selftest ... > out.txt` wurde durch
    AttachConsole kaputt umgeleitet, weil ein bereits gueltiges (umgeleitetes)
    stdout unconditional durch CONOUT$ ersetzt wurde, sobald AttachConsole
    "erfolgreich" an einen fremden Vorgaenger-Prozess andockte. stdout/stderr
    duerfen NUR angefasst werden, wenn sie tatsaechlich None sind.
    """
    import io

    real_stdout = io.StringIO()
    real_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", real_stdout, raising=False)
    monkeypatch.setattr(sys, "stderr", real_stderr, raising=False)
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    import ctypes

    class FakeKernel32:
        @staticmethod
        def AttachConsole(pid):
            return 1  # simuliert erfolgreiches Andocken an eine fremde Konsole

    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": FakeKernel32})(), raising=False)

    _attach_console_if_available()

    assert sys.stdout is real_stdout   # NICHT durch CONOUT$ ersetzt
    assert sys.stderr is real_stderr
