"""Die Pille sagt, wenn die Verarbeitung ungewöhnlich lange dauert.

Anlass: Am 2026-09-24 brauchte ein Diktat 8,5 Minuten (Grafikkarte von fremden
Programmen ausgelastet), und die Pille zeigte nur den Ladekreis.
"""

import types

import numpy as np

from fleech.ui.desktopapp import wachhund
from fleech.ui.desktopapp.wachhund import WachhundMixin, meldung, schwelle_s
from fleech.ui.state import AppState


def test_schwelle_liegt_ueber_dem_alltag():
    """95 % aller Diktate sind nach 9,2 s fertig — kurze melden erst ab 12 s."""
    assert schwelle_s(5) > 9.2


def test_lange_diktate_bekommen_mehr_zeit():
    """645 s Audio brauchten normal 43 s — das ist kein Alarm."""
    assert schwelle_s(645) >= 43


def test_meldung_nennt_die_laufzeit():
    assert meldung(83) == "Dauert länger als üblich … 1:23"


def _fake(audio_s: float):
    gemeldet = []
    uhr = types.SimpleNamespace(start=lambda: None, stop=lambda: None)
    fake = types.SimpleNamespace(
        _wachhund=uhr, _verarbeitung_seit=None, _wachhund_gemeldet=False,
        _letzte_aufnahme=np.zeros(int(audio_s * 16000), np.float32),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        bus=types.SimpleNamespace(progress=types.SimpleNamespace(emit=gemeldet.append)),
    )
    return fake, gemeldet


def test_meldet_erst_nach_der_schwelle(monkeypatch):
    fake, gemeldet = _fake(audio_s=10)
    jetzt = [1000.0]
    monkeypatch.setattr(wachhund.time, "monotonic", lambda: jetzt[0])

    WachhundMixin._wachhund_zustand(fake, AppState.PROCESSING)
    jetzt[0] += 5
    WachhundMixin._wachhund_tick(fake)
    assert gemeldet == []                                   # normal, still

    jetzt[0] += 20
    WachhundMixin._wachhund_tick(fake)
    assert gemeldet and gemeldet[-1].startswith("Dauert länger als üblich")


def test_ende_der_verarbeitung_stoppt_die_meldung(monkeypatch):
    fake, gemeldet = _fake(audio_s=10)
    jetzt = [1000.0]
    monkeypatch.setattr(wachhund.time, "monotonic", lambda: jetzt[0])

    WachhundMixin._wachhund_zustand(fake, AppState.PROCESSING)
    WachhundMixin._wachhund_zustand(fake, AppState.IDLE)
    jetzt[0] += 100
    WachhundMixin._wachhund_tick(fake)
    assert gemeldet == []


def test_wachhund_laesst_sich_ohne_parent_bauen(qapp):
    """`QTimer(self)` mit DesktopApp hat schon einmal den Start verhindert —
    DesktopApp ist kein QObject. Der Aufbau muss ohne Parent gehen."""
    from fleech.ui.state import StateBus

    fake = types.SimpleNamespace(bus=StateBus())
    fake._wachhund_tick = lambda: None
    fake._wachhund_zustand = lambda s: None
    WachhundMixin._baue_wachhund(fake)
    assert fake._wachhund.interval() == 1000
