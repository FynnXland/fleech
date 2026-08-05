"""Fehlersuche am Startwort: aufheben, was die Prüfung tatsächlich gehört hat.

Gebaut, weil sich die Frage anders nicht beantworten liess: Die Startwort-Probe
in den Einstellungen trifft zuverlässig, der Freihand-Betrieb nicht. Alles, was
ohne echtes Signal vergleichbar war, zeigte Gleichstand — dieselbe Erkennung,
dasselbe Modell, dieselbe Abtastrate, dieselbe Zustandsmaschine (fünf Szenen,
fünfmal gleich), beide Audioströme unauffällig.
"""

import wave

import numpy as np
import pytest

from fleech.freihand_diagnose import (
    MAX_DATEIEN, _sicherer_name, baue_mitschnitt,
)

SR = 16000


def audio(sekunden: float = 2.0, pegel: float = 0.3) -> np.ndarray:
    t = np.linspace(0, sekunden, int(SR * sekunden), endpoint=False)
    return (pegel * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# -- Was geschrieben wird ----------------------------------------------------------------


def test_schreibt_das_gepruefte_fenster(tmp_path):
    mit = baue_mitschnitt(tmp_path, samplerate=SR, uhr=lambda: "120000")
    mit(audio(2.0), "Kimono.", True)

    dateien = list(tmp_path.glob("*.wav"))
    assert len(dateien) == 1
    with wave.open(str(dateien[0]), "rb") as w:
        assert w.getframerate() == SR
        assert w.getnchannels() == 1
        assert abs(w.getnframes() / SR - 2.0) < 0.01


def test_dateiname_sagt_was_gehoert_wurde(tmp_path):
    """Ohne den Namen müsste man 60 Dateien einzeln anhören, um die eine zu
    finden, bei der es schiefging."""
    mit = baue_mitschnitt(tmp_path, samplerate=SR, uhr=lambda: "120000")
    mit(audio(), "Kimono.", True)
    mit(audio(), "Ich bin hier.", False)

    namen = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert namen[0] == "120000_001_TREFFER_Kimono.wav"
    assert namen[1] == "120000_002_daneben_Ich-bin-hier.wav"


def test_leerer_text_wird_auch_aufgehoben(tmp_path):
    """„Das Modell hat gar nichts gehört" ist als Befund genauso wertvoll wie ein
    falsches Wort — vielleicht sogar wertvoller."""
    mit = baue_mitschnitt(tmp_path, samplerate=SR, uhr=lambda: "120000")
    mit(audio(), "", False)
    assert [p.name for p in tmp_path.glob("*.wav")] == [
        "120000_001_daneben_nichts-gehoert.wav"]


@pytest.mark.parametrize("text,erwartet", [
    ("Kimono.", "Kimono"),
    ("Ja, was denn?!", "Ja-was-denn"),
    ("  ", "nichts-gehoert"),
    ("../../etc/passwd", "etcpasswd"),          # kein Ausbruch aus dem Ordner
    ("x" * 200, "x" * 40),                      # Windows-Pfadlänge
])
def test_dateinamen_sind_sicher(text, erwartet):
    assert _sicherer_name(text) == erwartet


# -- Grenzen -----------------------------------------------------------------------------


def test_alte_aufnahmen_rollen_ab(tmp_path):
    """Eine Diagnose, die man vergisst auszuschalten, darf die Platte nicht füllen."""
    zaehler = {"n": 0}

    def uhr():
        zaehler["n"] += 1
        return f"{zaehler['n']:06d}"

    mit = baue_mitschnitt(tmp_path, samplerate=SR, uhr=uhr)
    for _ in range(MAX_DATEIEN + 15):
        mit(audio(0.2), "x", False)

    dateien = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert len(dateien) == MAX_DATEIEN
    # Die ÄLTESTEN sind weg, die neuesten da.
    assert dateien[-1].startswith(f"{MAX_DATEIEN + 15:06d}")


def test_leeres_audio_schreibt_nichts(tmp_path):
    mit = baue_mitschnitt(tmp_path, samplerate=SR)
    mit(np.zeros(0, dtype=np.float32), "egal", False)
    mit(None, "egal", False)
    assert list(tmp_path.glob("*.wav")) == []


def test_ordner_entsteht_erst_beim_schreiben(tmp_path):
    """Wer die Fehlersuche nie einschaltet, soll den Ordner nie zu sehen bekommen."""
    ziel = tmp_path / "freihand-diagnose"
    baue_mitschnitt(ziel, samplerate=SR)
    assert not ziel.exists()


# -- Verdrahtung -------------------------------------------------------------------------


def test_standardmaessig_aus():
    """Hier wird Audio gespeichert — genau das verspricht Freihand sonst NICHT zu
    tun. Ein versehentlich angelassener Schalter wäre der Vertrauensbruch, den
    der ganze Modus vermeiden soll."""
    from fleech.usersettings import UserSettings

    assert UserSettings().freihand.diagnose is False


def test_ohne_schalter_wird_kein_mitschnitt_gebaut():
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace()
    aus = types.SimpleNamespace(diagnose=False)
    assert DesktopApp._baue_freihand_mitschnitt(fake, aus) is None
    assert DesktopApp._baue_freihand_mitschnitt(fake, types.SimpleNamespace()) is None


def test_lauscher_reicht_das_gepruefte_fenster_durch():
    """Aufgezeichnet wird GENAU das, was die Prüfung gesehen hat — nicht ein
    nachträglich zusammengebautes Stück, das anders klingen könnte."""
    from fleech.freihand import Einstellungen, Lauscher

    gesehen = []
    lau = Lauscher(
        Einstellungen(aktiv=True, startwort="Kimono"),
        vad=lambda a: True, erkenner=lambda a: "Kimono",
        samplerate=SR, mitschnitt=lambda a, t, tr: gesehen.append((len(a), t, tr)))
    lau.start_lauschen()
    lau.verarbeite(audio(1.0), jetzt=100.0)

    assert len(gesehen) == 1
    laenge, text, treffer = gesehen[0]
    assert laenge == SR                 # das Fenster, nicht mehr und nicht weniger
    assert text == "Kimono" and treffer is True


def test_mitschnitt_fehler_reisst_die_erkennung_nicht_mit():
    """Eine volle Platte oder ein gesperrter Ordner darf Freihand nicht lahmlegen."""
    from fleech.freihand import Einstellungen, Ereignis, Lauscher

    def kaputt(a, t, tr):
        raise OSError("Platte voll")

    lau = Lauscher(Einstellungen(aktiv=True, startwort="Kimono"),
                   vad=lambda a: True, erkenner=lambda a: "Kimono",
                   samplerate=SR, mitschnitt=kaputt)
    lau.start_lauschen()
    assert lau.verarbeite(audio(1.0), jetzt=100.0) is Ereignis.START


def test_ohne_mitschnitt_bleibt_alles_wie_vorher():
    from fleech.freihand import Einstellungen, Ereignis, Lauscher

    lau = Lauscher(Einstellungen(aktiv=True, startwort="Kimono"),
                   vad=lambda a: True, erkenner=lambda a: "Kimono", samplerate=SR)
    lau.start_lauschen()
    assert lau.verarbeite(audio(1.0), jetzt=100.0) is Ereignis.START


def test_freihand_modul_bleibt_dateifrei():
    """Die technische Zusicherung hinter „kein Mitschnitt": Das Modul, das das
    Audio hält, kennt keine Dateien. Die Diagnose kommt als Callback von aussen —
    sonst stünde Schreib-Code dauerhaft neben dem Ringpuffer."""
    import inspect

    from fleech import freihand

    quelle = inspect.getsource(freihand)
    for verboten in ("import wave", "open(", "Path("):
        assert verboten not in quelle, f"freihand.py enthält {verboten!r}"
