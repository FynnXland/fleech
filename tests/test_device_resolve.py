"""resolve_input_device: mehrdeutige Mikrofon-Namen (mehrere Host-APIs) → Index.

Realer Bug: Scarlett Solo taucht unter MME/DirectSound/WASAPI/WDM-KS auf; sounddevice
wirft dann "Multiple input devices found" und die Aufnahme startet nie.
"""

import sys
import types


def _install_fake_sounddevice(monkeypatch, devices, default_hostapi=0):
    fake = types.SimpleNamespace()
    fake.query_devices = lambda: devices
    fake.default = types.SimpleNamespace(hostapi=default_hostapi)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


SCARLETT = [
    {"name": "Mikrofon (Scarlett Solo USB)", "max_input_channels": 2, "hostapi": 0},
    {"name": "Mikrofon (Scarlett Solo USB)", "max_input_channels": 2, "hostapi": 1},
    {"name": "Mikrofon (Scarlett Solo USB)", "max_input_channels": 2, "hostapi": 2},
    {"name": "Lautsprecher", "max_input_channels": 0, "hostapi": 0},
]


def test_none_and_int_pass_through(monkeypatch):
    from fleech.audio import resolve_input_device

    _install_fake_sounddevice(monkeypatch, SCARLETT)
    assert resolve_input_device(None) is None
    assert resolve_input_device(7) == 7


def test_ambiguous_name_picks_default_hostapi(monkeypatch):
    from fleech.audio import resolve_input_device

    _install_fake_sounddevice(monkeypatch, SCARLETT, default_hostapi=0)
    assert resolve_input_device("Mikrofon (Scarlett Solo USB)") == 0  # MME
    _install_fake_sounddevice(monkeypatch, SCARLETT, default_hostapi=2)
    assert resolve_input_device("Mikrofon (Scarlett Solo USB)") == 2  # WASAPI


def test_unique_name_returns_its_index(monkeypatch):
    from fleech.audio import resolve_input_device

    devices = [
        {"name": "Webcam Mic", "max_input_channels": 1, "hostapi": 0},
        {"name": "USB Mikro", "max_input_channels": 2, "hostapi": 0},
    ]
    _install_fake_sounddevice(monkeypatch, devices)
    assert resolve_input_device("USB Mikro") == 1


def test_missing_name_falls_back_to_system_default(monkeypatch):
    from fleech.audio import resolve_input_device

    _install_fake_sounddevice(monkeypatch, SCARLETT)
    assert resolve_input_device("Abgezogenes Mikro") is None


def test_ambiguous_without_matching_hostapi_takes_first(monkeypatch):
    from fleech.audio import resolve_input_device

    _install_fake_sounddevice(monkeypatch, SCARLETT, default_hostapi=99)
    assert resolve_input_device("Mikrofon (Scarlett Solo USB)") == 0  # erster Treffer


# -- Der stille Rueckfall wird gemeldet (Befund B-7) --------------------------------


def test_rueckfall_meldet_das_tatsaechlich_benutzte_geraet(monkeypatch):
    """Bis 5.10.3 stand der Rueckfall nur als log.warning im Protokoll (dort
    86-mal). Interface aus, Rechner aus dem Standby, USB-Hub neu enumeriert — ab
    da lief das Diktat ueber die Webcam, ohne ein Wort darueber."""
    from fleech.audio import resolve_input_device

    fake = _install_fake_sounddevice(monkeypatch, SCARLETT)
    fake.query_devices = lambda kind=None: (
        {"name": "Webcam-Mikrofon"} if kind == "input" else SCARLETT
    )
    gemeldet = []
    assert resolve_input_device("Abgezogenes Mikro", gemeldet.append) is None
    assert gemeldet == ["Webcam-Mikrofon"]


def test_ohne_rueckfall_wird_nichts_gemeldet(monkeypatch):
    from fleech.audio import resolve_input_device

    _install_fake_sounddevice(monkeypatch, SCARLETT)
    gemeldet = []
    resolve_input_device("Mikrofon (Scarlett Solo USB)", gemeldet.append)
    assert gemeldet == []


def test_eine_kaputte_meldung_haelt_die_aufnahme_nicht_auf(monkeypatch):
    """Die Rueckmeldung ist Beiwerk — der Aufnahmestart darf daran nie scheitern."""
    from fleech.audio import resolve_input_device

    fake = _install_fake_sounddevice(monkeypatch, SCARLETT)
    fake.query_devices = lambda kind=None: SCARLETT

    def kaputt(_name):
        raise RuntimeError("Pille nicht erreichbar")

    assert resolve_input_device("Abgezogenes Mikro", kaputt) is None
