"""packaging/stop_fleech.py — erkennt auch die Quellcode-Instanz und klopft immer an.

Am 2026-10-08 lief Fleech als `pythonw.exe -m fleech --gui`. Das Skript kannte nur
Fleech.exe, meldete „laeuft nicht", und die frisch installierte EXE klopfte danach
nur bei der alten Instanz an — getestet wurde der alte Stand.

Kein Test beendet etwas wirklich: IPC, Prozessliste und Uhr sind ersetzt.
"""

import importlib.util
import os
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def _load_stop_module():
    # Nicht als `packaging.stop_fleech` importierbar — der Name kollidiert mit dem
    # pip-Paket `packaging`.
    spec = importlib.util.spec_from_file_location("fleech_stop", PACKAGING / "stop_fleech.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QUELLCODE = ["E:\\Fleech\\.venv\\Scripts\\pythonw.exe", "-m", "fleech", "--gui",
             "--cwd", "E:\\Fleech"]


# -- Erkennung ----------------------------------------------------------------------

@pytest.mark.parametrize("name, cmdline", [
    ("Fleech.exe", ["C:\\Programs\\Fleech\\Fleech.exe"]),
    ("Fleech", ["/home/u/.local/opt/Fleech/Fleech", "--gui"]),
    ("pythonw.exe", QUELLCODE),
    ("python.exe", ["python", "-mfleech"]),
])
def test_erkennt_fleech(name, cmdline):
    assert _load_stop_module()._ist_fleech(name, cmdline)


@pytest.mark.parametrize("name, cmdline", [
    ("python.exe", ["python", "-m", "pytest", "-q"]),
    ("python.exe", ["python", "packaging/stop_fleech.py"]),
    ("python.exe", ["python", "-m", "fleech_tools"]),
    # Shell mit „-m fleech" mitten in einem Skript-Argument ist kein Fleech:
    ("bash.exe", ["bash", "-c", "cd x && pythonw -m fleech --gui"]),
    ("claude.exe", ["claude", "--project", "E:\\Tools\\Fleech"]),
])
def test_erkennt_anderes_nicht_als_fleech(name, cmdline):
    assert not _load_stop_module()._ist_fleech(name, cmdline)


class _Proc:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


def test_prozessliste_findet_quellcode_instanz_und_laesst_sich_selbst_aus(monkeypatch):
    import psutil

    stop = _load_stop_module()
    prozesse = [
        _Proc(10, "Fleech.exe", ["Fleech.exe"]),
        _Proc(11, "pythonw.exe", QUELLCODE),
        _Proc(12, "python.exe", ["python", "-m", "pytest"]),
        _Proc(13, "System", None),  # Zugriff verweigert → psutil liefert None
        _Proc(os.getpid(), "python.exe", ["python", "-m", "fleech"]),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(prozesse))

    assert [pid for pid, _ in stop.fleech_prozesse()] == [10, 11]


# -- Ablauf -------------------------------------------------------------------------

class _Uhr:
    """Ersetzt das time-Modul im Skript: sleep() rueckt die Uhr vor, wartet nicht."""

    def __init__(self):
        self.jetzt = 0.0

    def monotonic(self):
        return self.jetzt

    def sleep(self, s):
        self.jetzt += s


def _aufbau(monkeypatch, *, ipc, prozesse_nacheinander):
    """`prozesse_nacheinander`: was fleech_prozesse() bei jedem Aufruf liefert;
    der letzte Eintrag gilt fuer alle weiteren Aufrufe."""
    stop = _load_stop_module()
    ablauf = []

    def bitte_beenden():
        ablauf.append("ipc")
        if isinstance(ipc, Exception):
            raise ipc
        return ipc

    folge = list(prozesse_nacheinander)

    def fleech_prozesse():
        ablauf.append("prozesse")
        return folge.pop(0) if len(folge) > 1 else folge[0]

    monkeypatch.setattr(stop, "bitte_beenden", bitte_beenden)
    monkeypatch.setattr(stop, "fleech_prozesse", fleech_prozesse)
    monkeypatch.setattr(stop, "time", _Uhr())
    return stop, ablauf


def test_quellcode_instanz_wird_angeklopft_und_abgewartet(monkeypatch, capsys):
    """Der Fall vom 2026-10-08: keine Fleech.exe, aber `pythonw -m fleech`."""
    instanz = [(4711, " ".join(QUELLCODE))]
    stop, ablauf = _aufbau(monkeypatch, ipc=True,
                           prozesse_nacheinander=[instanz, instanz, []])

    assert stop.main() == 0
    assert ablauf[0] == "ipc"  # erst anklopfen, dann schauen
    assert ablauf.count("prozesse") == 3  # gewartet, bis sie wirklich weg ist
    assert "ordentlich beendet" in capsys.readouterr().out


def test_klopft_auch_an_wenn_kein_prozess_zu_sehen_ist(monkeypatch, capsys):
    """Eine Instanz, die zuhoert, laeuft — egal, ob die Prozessliste sie erkennt."""
    stop, ablauf = _aufbau(monkeypatch, ipc=True, prozesse_nacheinander=[[]])

    assert stop.main() == 0
    assert ablauf[0] == "ipc"
    assert "kein Fleech-Prozess (mehr)" in capsys.readouterr().out


def test_nichts_laeuft(monkeypatch, capsys):
    stop, _ = _aufbau(monkeypatch, ipc=False, prozesse_nacheinander=[[]])

    assert stop.main() == 0
    assert "laeuft nicht" in capsys.readouterr().out


@pytest.mark.parametrize("ipc", [False, OSError("kein Kanal")])
def test_laeuft_ohne_ipc_antwort_meldet_exit_1_mit_pids(monkeypatch, capsys, ipc):
    stop, _ = _aufbau(monkeypatch, ipc=ipc,
                      prozesse_nacheinander=[[(4711, "pythonw.exe -m fleech --gui")]])

    assert stop.main() == 1
    assert "PID 4711" in capsys.readouterr().out


def test_haengt_nach_der_wartezeit_noch_exit_1(monkeypatch, capsys):
    stop, _ = _aufbau(monkeypatch, ipc=True,
                      prozesse_nacheinander=[[(4711, "Fleech.exe")]])

    assert stop.main() == 1
    ausgabe = capsys.readouterr().out
    assert "noch" in ausgabe and "PID 4711" in ausgabe
