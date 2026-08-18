import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Muss stehen, bevor irgendein Test die erste QApplication baut — sonst versucht Qt
# ein echtes Fenster zu öffnen. Lag früher in test_ui_smoke.py; alle anderen
# Qt-Tests hingen damit an der Dateireihenfolge.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _kein_echtes_gedaechtnis(tmp_path, monkeypatch):
    """Kein Test fasst das echte Projekt-Gedaechtnis des Nutzers an.

    `KontextSpeicher()` ohne Pfad oeffnet `%APPDATA%\\Fleech\\kontext.db` — die
    Datei mit dem real gelernten Vokabular. Die Einstellungsseite baut so einen
    Speicher beim Aufbau, und seit V-14 kann die Uebernahme eines Vorschlags dort
    auch LOESCHEN. Ein Testlauf darf das nicht koennen, deshalb zeigt der
    Vorgabepfad waehrend der Tests in ein Wegwerf-Verzeichnis.
    """
    import fleech.kontext as kontext

    monkeypatch.setattr(kontext, "DB_PATH", tmp_path / "kontext.db")


@pytest.fixture
def qapp():
    """Eine QApplication für alle Qt-Tests.

    Lag bisher nur in test_ui_smoke.py — jede weitere Testdatei mit Widgets hätte
    sie kopieren müssen. Qt verträgt genau eine Instanz je Prozess, deshalb wird
    eine bestehende weiterverwendet statt eine zweite zu bauen.
    """
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])
