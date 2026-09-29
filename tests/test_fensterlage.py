"""Das Hauptfenster öffnet sich mit sichtbarer Titelleiste.

Hintergrund in `fleech/ui/fensterlage.py`: Die Lage wurde als Rahmen-Ecke
gespeichert und als Innenfläche wiederhergestellt — jeder Start rückte das Fenster
um die Titelleistenhöhe nach oben, bis sie außerhalb des Bildschirms lag.
"""

import pytest

from fleech.ui.fensterlage import TITELLEISTE, sichtbare_lage

# Die beiden Monitore des Nutzers (availableGeometry, gemessen am 2026-09-29):
# links ein HP, rechts der primäre Samsung; Taskleiste unten, 48 px.
HP = (-1920, 0, 1920, 1032)
SAMSUNG = (0, 0, 1920, 1032)
BEIDE = [SAMSUNG, HP]


def test_gueltige_lage_bleibt_unveraendert():
    assert sichtbare_lage(300, 200, 1100, 760, BEIDE) == (300, 200)


@pytest.mark.parametrize("y", [11, 3, -14, -45])
def test_titelleiste_ueber_der_kante_wird_heruntergeholt(y):
    """Genau die Werte aus den Sicherungen des Nutzers (y=11, y=3) und die, zu
    denen die alte Drift weitergelaufen wäre (−14, −45)."""
    x, neu_y = sichtbare_lage(415, y, 1100, 760, BEIDE)
    assert neu_y - TITELLEISTE >= 0, "Titelleiste läge oberhalb des Bildschirms"
    assert x == 415


def test_fenster_bleibt_auf_dem_zweitmonitor():
    """Der Bildschirm mit der größten Überlappung zählt, nicht der primäre —
    sonst spränge ein Fenster vom linken HP auf den Samsung."""
    x, y = sichtbare_lage(-1388, 5, 1100, 760, BEIDE)
    assert x == -1388
    assert y >= TITELLEISTE


def test_abgesteckter_monitor_laesst_qt_platzieren():
    """Liegt das Fenster auf keinem vorhandenen Bildschirm, wird es nicht
    irgendwohin geschoben — Qt soll es selbst platzieren."""
    assert sichtbare_lage(-1388, 200, 1100, 760, [SAMSUNG]) is None


def test_zu_weit_rechts_bleibt_greifbar():
    x, _ = sichtbare_lage(1900, 200, 1100, 760, [SAMSUNG])
    assert x <= 1920 - 150


def test_zu_weit_unten_bleibt_greifbar():
    _, y = sichtbare_lage(300, 1020, 1100, 760, [SAMSUNG])
    assert y <= 1032 - 150


def test_schliessen_speichert_die_innenflaeche(qapp, tmp_path, monkeypatch):
    """Der eigentliche Fehler: gespeichert wurde `x()/y()` (Rahmen), wieder-
    hergestellt per `setGeometry` (Innenfläche). Offscreen gibt es keinen Rahmen,
    also werden die beiden hier auseinandergezogen, wie Windows es tut."""
    from PySide6.QtCore import QRect

    from uihelpers import make_main_window

    fenster, _panel, _store, settings, _c = make_main_window(tmp_path, monkeypatch)
    monkeypatch.setattr(fenster, "geometry", lambda: QRect(300, 79, 1100, 760))
    monkeypatch.setattr(fenster, "x", lambda: 300)
    monkeypatch.setattr(fenster, "y", lambda: 79 - 31)   # Rahmen-Ecke

    from PySide6.QtGui import QCloseEvent

    fenster.closeEvent(QCloseEvent())
    assert (settings.window.x, settings.window.y) == (300, 79)
