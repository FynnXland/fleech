"""Tray-Klick und Zweitstart muessen das Hauptfenster wirklich zeigen.

Gemeldet: „öffnet sich oft nicht". Ursache: Das Fenster war minimiert, und
`open_page` rief nur show()/raise_() — beides holt ein minimiertes Fenster nicht
zurueck. Der Zweitstart kam an (Log: „Zweite Instanz angeklopft"), sichtbar
wurde nichts.
"""

from PySide6.QtCore import Qt

from uihelpers import make_main_window


def _fenster(tmp_path, monkeypatch):
    import fleech.ui.focusrestore as fr

    fenster, *_ = make_main_window(tmp_path, monkeypatch)
    aufrufe = []
    monkeypatch.setattr(fr, "restore_foreground", lambda hwnd: aufrufe.append(hwnd))
    return fenster, aufrufe


def test_minimiertes_fenster_kommt_zurueck(qapp, tmp_path, monkeypatch):
    fenster, aufrufe = _fenster(tmp_path, monkeypatch)
    fenster.setWindowState(Qt.WindowMinimized)
    fenster.open_page("home")
    assert not fenster.isMinimized()
    assert not fenster.isHidden()
    assert aufrufe == [int(fenster.winId())]
    fenster.hide()


def test_maximiertes_bleibt_maximiert(qapp, tmp_path, monkeypatch):
    fenster, _ = _fenster(tmp_path, monkeypatch)
    fenster.setWindowState(Qt.WindowMinimized | Qt.WindowMaximized)
    fenster.open_page("home")
    assert fenster.windowState() == Qt.WindowMaximized
    fenster.hide()


def test_zweitstart_gibt_vordergrund_vor_dem_weckruf_frei(monkeypatch):
    """Erst das Recht weiterreichen, dann wecken — sonst ist die laufende
    Instanz schon am Zug, bevor sie nach vorn darf."""
    import PySide6.QtNetwork as qn

    import fleech.ui.focusrestore as fr
    from fleech.ui import desktop

    ablauf = []

    class Sockel:
        def connectToServer(self, _name):
            pass

        def waitForConnected(self, _ms):
            return True

        def write(self, daten):
            ablauf.append(("write", daten))

        def flush(self):
            pass

        def waitForBytesWritten(self, _ms):
            return True

        def disconnectFromServer(self):
            pass

    monkeypatch.setattr(qn, "QLocalSocket", Sockel)
    monkeypatch.setattr(fr, "erlaube_fremden_vordergrund",
                        lambda: ablauf.append(("erlaube",)))
    assert desktop._wake_running_instance() is True
    assert ablauf == [("erlaube",), ("write", b"show")]


def test_vordergrund_freigabe_ausserhalb_windows_still(monkeypatch):
    import fleech.ui.focusrestore as fr

    monkeypatch.setattr(fr.sys, "platform", "linux")
    assert fr.erlaube_fremden_vordergrund() is None
