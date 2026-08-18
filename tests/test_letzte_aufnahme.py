"""Die letzte Aufnahme aufheben — und noch einmal erkennen lassen (V-15/H-8).

198 von 1603 Aufnahmen (12,4 %) lieferten ein leeres Transkript, 24 davon mit
über 5 s Audio, die längste 163 s. Danach war der Ton weg: Die Aufnahme lebte nur
als lokale Variable in `_process_locked`, und bei leerem Transkript entsteht nicht
einmal ein Verlaufseintrag. „Nochmal erkennen" hieß bis 5.10.4 „nochmal sprechen".
"""

import threading
import types
import wave

import numpy as np
import pytest

pytest.importorskip("PySide6")

from fleech.ui.desktop import DesktopApp


def _fake(lock=None):
    """Minimale DesktopApp-Attrappe — die Mixin-Methoden werden ungebunden auf ihr
    aufgerufen, genau wie in den übrigen DesktopApp-Tests."""
    gemeldet: list[str] = []
    fake = types.SimpleNamespace(
        _process_lock=lock or threading.Lock(),
        _llms_unloaded=False,
        _letzte_aufnahme=None,
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        bus=types.SimpleNamespace(
            progress=types.SimpleNamespace(emit=gemeldet.append),
            set_state=lambda *a, **k: None,
        ),
        _flash_status=gemeldet.append,
    )
    fake._letzte_aufnahme_oder_meldung = types.MethodType(
        DesktopApp._letzte_aufnahme_oder_meldung, fake)
    return fake, gemeldet


def _ton(sekunden: float = 0.5) -> np.ndarray:
    t = np.linspace(0, sekunden, int(16000 * sekunden), dtype=np.float32)
    return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


# -- Aufheben ---------------------------------------------------------------------------


def test_das_audio_wird_gehalten_und_beim_naechsten_mal_ersetzt():
    """Genau EINE Aufnahme, sonst waechst der Speicher (163 s sind rund 10 MB)."""
    fake, _ = _fake()
    fake._process_locked = lambda *a, **k: None
    erst, dann = _ton(), _ton(0.25)

    DesktopApp._process(fake, erst, False)
    assert fake._letzte_aufnahme is erst
    DesktopApp._process(fake, dann, False)
    assert fake._letzte_aufnahme is dann


def test_auch_ein_leeres_transkript_laesst_das_audio_stehen():
    """Der eigentliche Fall: `process()` steigt bei leerem Transkript mit "empty"
    aus, ohne Verlaufseintrag. Das Aufheben passiert deshalb VOR der Verarbeitung,
    nicht danach."""
    fake, _ = _fake()

    def leer(audio, *a, **k):
        raise RuntimeError("STT lieferte nichts")   # haerter als 'empty'

    fake._process_locked = leer
    audio = _ton()
    with pytest.raises(RuntimeError):
        DesktopApp._process(fake, audio, False)
    assert fake._letzte_aufnahme is audio


# -- Noch einmal erkennen ---------------------------------------------------------------


def test_erneut_erkennen_schickt_dasselbe_audio_durch_die_pipeline(monkeypatch):
    import fleech.ui.desktopapp.nachbereitung as nach

    class SyncThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(nach.threading, "Thread", SyncThread)
    fake, _ = _fake()
    gesehen: list = []
    fake._process = lambda audio: gesehen.append(audio)
    fake._letzte_aufnahme = audio = _ton()

    DesktopApp._erneut_erkennen(fake)
    assert gesehen == [audio], "die Aufnahme geht unveraendert denselben Weg"


def test_ohne_aufnahme_sagt_es_das_statt_stumm_zu_bleiben():
    fake, gemeldet = _fake()
    DesktopApp._erneut_erkennen(fake)
    assert any("Keine Aufnahme" in m for m in gemeldet)


def test_waehrend_eines_diktats_wird_nicht_dazwischengefunkt():
    lock = threading.Lock()
    lock.acquire()
    fake, gemeldet = _fake(lock)
    fake._letzte_aufnahme = _ton()
    fake._process = lambda audio: pytest.fail("haette nicht laufen duerfen")

    DesktopApp._erneut_erkennen(fake)
    assert any("läuft noch" in m for m in gemeldet)
    lock.release()


# -- Als WAV sichern --------------------------------------------------------------------


def test_wav_datei_entsteht_und_ist_lesbar(tmp_path):
    fake, gemeldet = _fake()
    audio = _ton(0.5)
    ziel = tmp_path / "aufnahme.wav"

    assert DesktopApp._schreibe_wav(fake, ziel, audio) is True
    with wave.open(str(ziel), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == len(audio)
    assert any("gesichert" in m for m in gemeldet)


def test_ein_fehlgeschlagenes_sichern_meldet_sich(tmp_path):
    fake, gemeldet = _fake()
    ziel = tmp_path / "gibtesnicht" / "tief" / "x.wav"
    assert DesktopApp._schreibe_wav(fake, ziel, _ton(0.1)) is False
    assert any("fehlgeschlagen" in m for m in gemeldet)


def test_sichern_ohne_aufnahme_oeffnet_keinen_dialog(monkeypatch):
    """Kein Dateidialog, wenn es nichts zu sichern gibt — sonst waehlt man einen
    Pfad und bekommt hinterher gesagt, dass nichts da war."""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: pytest.fail("Dialog geoeffnet")))
    fake, gemeldet = _fake()
    DesktopApp._letzte_aufnahme_sichern(fake)
    assert any("Keine Aufnahme" in m for m in gemeldet)


# -- Das Tray-Menue ---------------------------------------------------------------------


def test_die_beiden_eintraege_stehen_im_tray_menue(qapp):
    from fleech.ui.tray import TrayController

    gerufen: list[str] = []
    tray = TrayController({
        "toggle_recording": lambda: None, "toggle_overlay": lambda: None,
        "open_settings": lambda: None, "reload": lambda: None, "quit": lambda: None,
        "redo_last": lambda: gerufen.append("redo"),
        "save_last_wav": lambda: gerufen.append("wav"),
    })
    texte = [a.text() for a in tray._menu.actions()]
    assert "Letzte Aufnahme noch einmal erkennen" in texte
    assert "Letzte Aufnahme als WAV sichern …" in texte
    for a in tray._wieder_actions:
        # Datenschutz gehoert an die Stelle, an der man klickt.
        assert "Arbeitsspeicher" in a.toolTip()
        a.trigger()
    assert gerufen == ["redo", "wav"]
    tray.tray.hide()


def test_ohne_aktionen_bleibt_das_menue_wie_es_war(qapp):
    """Die Eintraege sind optional — ein Aufrufer, der sie nicht reicht, bekommt
    kein leeres Menue-Element."""
    from fleech.ui.tray import TrayController

    tray = TrayController({
        "toggle_recording": lambda: None, "toggle_overlay": lambda: None,
        "open_settings": lambda: None, "reload": lambda: None, "quit": lambda: None,
    })
    assert tray._wieder_actions == []
    assert not any("Letzte Aufnahme" in a.text() for a in tray._menu.actions())
    tray.tray.hide()
