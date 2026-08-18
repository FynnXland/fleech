"""Der Schwanz ohne Ton — Whisper-Floskeln hinter dem letzten echten Wort.

Gemessen an 22 halluzinierenden Laeufen: 19 wurden sauber, 22 von 22 behielten
ihr letztes echtes Wort. Was hier geprueft wird, sind die drei Sicherungen, die
das teuer erkaufte „22 von 22" tragen — nur vom Ende her, nie das letzte
Segment, und die Schwelle dort, wo der Fehlalarm nachweislich beginnt.
"""

import logging
import threading
import types

import numpy as np
import pytest

from fleech.stt.nachlauf import KEIN_TON_RMS, streiche_tonlosen_schwanz

SAMPLERATE = 16000


def _seg(start, ende, text):
    return types.SimpleNamespace(start=start, end=ende, text=text)


def _audio(sekunden: float = 6.0, sprache_bis: float = 3.0,
           pegel: float = 0.05, teppich: float = 0.0004) -> np.ndarray:
    """Sprache (RMS ~0,05) bis `sprache_bis`, danach Rauschteppich (RMS 0,0004).

    Die Zahlen stammen aus der Messung: echte Segmente lagen bei 0,06–0,11, der
    am Geraet belegte Mikrofon-Rauschteppich bei 0,0004."""
    rng = np.random.default_rng(7)
    n = int(sekunden * SAMPLERATE)
    audio = rng.normal(0.0, teppich, n).astype(np.float32)
    audio[: int(sprache_bis * SAMPLERATE)] = rng.normal(
        0.0, pegel, int(sprache_bis * SAMPLERATE)).astype(np.float32)
    return audio


# -- Die Regel ------------------------------------------------------------------------


def test_tonloser_schwanz_faellt_sprache_bleibt():
    """Der Fall aus dem Log: zwei Floskel-Segmente hinter dem letzten echten Wort."""
    segmente = [
        _seg(0.0, 1.5, "Ich wollte nur sagen, dass das Projekt gut läuft"),
        _seg(1.5, 3.0, "und wir im Zeitplan sind."),
        _seg(3.5, 4.5, "Vielen Dank."),
        _seg(4.5, 5.5, "Bis zum nächsten Mal."),
    ]
    behalten, weg = streiche_tonlosen_schwanz(segmente, _audio(), SAMPLERATE)

    assert [s.text for s in behalten] == [segmente[0].text, segmente[1].text]
    assert [s.text for s in weg] == ["Vielen Dank.", "Bis zum nächsten Mal."]


def test_stille_mitten_im_text_bleibt_stehen():
    """Nur vom Ende her — eine Sprechpause mitten im Diktat ist kein Ausschuss.

    Das tonlose Segment sitzt VOR echtem Ton; der Guard darf es nicht anfassen,
    sonst faellt Text aus der Mitte weg."""
    audio = _audio(sekunden=8.0, sprache_bis=2.0)
    audio[int(5.0 * SAMPLERATE):int(7.0 * SAMPLERATE)] = np.random.default_rng(3).normal(
        0.0, 0.05, int(2.0 * SAMPLERATE)).astype(np.float32)
    segmente = [
        _seg(0.0, 2.0, "erster Teil"),
        _seg(3.0, 4.0, "Vielen Dank."),   # liegt auf Stille, aber nicht am Ende
        _seg(5.0, 7.0, "zweiter Teil"),
    ]
    behalten, weg = streiche_tonlosen_schwanz(segmente, audio, SAMPLERATE)

    assert weg == []
    assert [s.text for s in behalten] == ["erster Teil", "Vielen Dank.", "zweiter Teil"]


def test_alles_tonlos_das_erste_segment_bleibt():
    """Fluester-Diktat: lieber ein fragwuerdiger Satz als gar nichts."""
    leise = np.full(6 * SAMPLERATE, 1e-5, dtype=np.float32)
    segmente = [_seg(0.0, 1.0, "kaum zu hören"), _seg(1.0, 2.0, "Vielen Dank."),
                _seg(2.0, 3.0, "Tschüss.")]
    behalten, weg = streiche_tonlosen_schwanz(segmente, leise, SAMPLERATE)

    assert [s.text for s in behalten] == ["kaum zu hören"]
    assert len(weg) == 2


def test_segment_jenseits_der_audiodauer_faellt():
    """343 solcher Segmente in der Messung: Whisper schreibt ueber das Material
    hinaus weiter (Segment bei 111 s in einem 95-s-Audio). Physikalisch
    unmoeglicher Text — faellt unabhaengig vom RMS."""
    segmente = [_seg(0.0, 3.0, "echter Satz"), _seg(9.0, 10.5, "Untertitelung des ZDF")]
    behalten, weg = streiche_tonlosen_schwanz(segmente, _audio(sekunden=6.0), SAMPLERATE)

    assert [s.text for s in behalten] == ["echter Satz"]
    assert [s.text for s in weg] == ["Untertitelung des ZDF"]


@pytest.mark.parametrize("pegel, faellt", [(0.0035, False), (0.0009, True)])
def test_die_schwelle_trennt_knapp_darueber_von_knapp_darunter(pegel, faellt):
    """Der Fehlalarm beginnt gemessen erst unterhalb von RMS 0,002: ein auf
    0,00186 heruntergerechneter echter Satz fiel, alles ab 0,00278 blieb heil."""
    rng = np.random.default_rng(11)
    audio = _audio(sekunden=6.0, sprache_bis=3.0)
    audio[int(4.0 * SAMPLERATE):int(5.0 * SAMPLERATE)] = rng.normal(
        0.0, pegel, SAMPLERATE).astype(np.float32)
    segmente = [_seg(0.0, 3.0, "echter Satz"), _seg(4.0, 5.0, "leise gesprochen")]

    behalten, weg = streiche_tonlosen_schwanz(segmente, audio, SAMPLERATE)
    assert (len(weg) == 1) is faellt
    assert (len(behalten) == 1) is faellt


def test_leere_liste_und_fehlende_zeiten():
    """Robustheit an den Raendern: nichts da, ein einziges Segment, keine Zeiten.

    Segmente ohne `.start`/`.end` gelten als MIT Ton — was nicht geprueft werden
    kann, wird nicht verworfen."""
    audio = _audio()
    assert streiche_tonlosen_schwanz([], audio, SAMPLERATE) == ([], [])

    eins = [_seg(4.0, 5.0, "Vielen Dank.")]           # tonlos, aber das letzte
    assert streiche_tonlosen_schwanz(eins, audio, SAMPLERATE) == (eins, [])

    ohne_zeit = [_seg(0.0, 3.0, "echt"), _seg(None, None, "ohne Zeiten")]
    behalten, weg = streiche_tonlosen_schwanz(ohne_zeit, audio, SAMPLERATE)
    assert weg == [] and len(behalten) == 2


def test_die_schwelle_ist_dieselbe_wie_die_der_pille():
    """Zwei Orte, eine Zahl. Der Kern darf die Oberflaeche nicht importieren
    (`tests/test_kernstruktur.py`), also steht 0,002 zweimal — dieser Test ist
    der Preis dafuer. Ein Test DARF beides sehen."""
    from fleech.ui.overlaypille.konstanten import KEIN_TON_SCHWELLE

    assert KEIN_TON_RMS == KEIN_TON_SCHWELLE


# -- Der Einbau im Backend -------------------------------------------------------------


class _FakeModell:
    def __init__(self, segmente):
        self.segmente = segmente

    def transcribe(self, audio, **kwargs):
        return iter(self.segmente), types.SimpleNamespace(language="de")


def _engine(segmente):
    from fleech.config import STTConfig
    from fleech.stt.faster_whisper_stt import FasterWhisperSTT

    engine = FasterWhisperSTT(STTConfig())
    engine._model = _FakeModell(segmente)
    engine._lock = threading.Lock()
    return engine


def _mit_no_speech(seg):
    seg.no_speech_prob = 0.0      # in der Messung bei ALLEN 2367 Segmenten 0,0000
    return seg


def test_run_gibt_den_text_ohne_schwanz_zurueck_und_meldet_ihn(caplog):
    """Der ganze Weg durch `_run`: Text ohne Floskel, Attribut gesetzt, Log-Zeile da."""
    segmente = [_mit_no_speech(s) for s in (
        _seg(0.0, 3.0, " Wir sind im Zeitplan."),
        _seg(3.5, 4.5, " Vielen Dank."),
    )]
    engine = _engine(segmente)

    with caplog.at_level(logging.INFO, logger="fleech.stt.faster_whisper_stt"):
        text = engine._run(_audio(), initial_prompt="Signalwort: Kimono.")

    assert text == "Wir sind im Zeitplan."
    assert engine.letzter_schwanz_ohne_ton == "Vielen Dank."
    assert "Schwanz ohne Ton verworfen" in caplog.text
    assert "Vielen Dank." in caplog.text


def test_run_setzt_das_attribut_vor_jedem_lauf_zurueck():
    """Sonst schleppte ein sauberes Diktat die Meldung des vorigen mit sich."""
    engine = _engine([_mit_no_speech(_seg(0.0, 3.0, " Alles gut."))])
    engine.letzter_schwanz_ohne_ton = "Vielen Dank."

    assert engine._run(_audio()) == "Alles gut."
    assert engine.letzter_schwanz_ohne_ton == ""


# -- Die Pipeline holt den Schwanz ab --------------------------------------------------


def test_pipeline_nennt_den_grund_und_zeigt_den_verworfenen_text():
    """Der Text faellt im Backend, bevor die Pipeline ihn sieht — trotzdem darf er
    nicht still verschwinden: Grund in `last_reason` (Verlauf, Insights),
    Wortlaut in `last_dropped_tail` (Pille, Verlaufs-Detail)."""
    from fleech import gruende
    from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, make_pipeline

    p, _llm, _injector = make_pipeline(
        RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.stt.letzter_schwanz_ohne_ton = "Vielen Dank. Bis zum nächsten Mal."
    p.process(AUDIO, 16000)

    assert gruende.SCHWANZ_OHNE_TON in p.last_reason
    assert "Vielen Dank." in p.last_dropped_tail


def test_pipeline_stellt_den_schwanz_vor_die_textguards():
    """Zwei Guards in einem Diktat: der STT-Schwanz lag im Audio VOR allem, was
    die Textguards danach schneiden — also steht er auch vorn."""
    from pipelinehelpers import AUDIO, FakeLLM, make_pipeline

    raw = ("Kannst du das in meiner Datei einmal korrigieren? Am besten in perfekter "
           "Klausulnotation zu dem Punkt, wo wir jetzt gerade sind. Klausulnotation "
           "Am besten! Mit einer F1-B-5 2019 Polski Der Konflikt L conflicts des "
           "Klausulnotation Kurv für das Klausulnotation Klausulnotation Dr "
           "Klausulnotation Klausulnotation Vergnügen")
    p, _llm, _injector = make_pipeline(raw)
    p.stt.letzter_schwanz_ohne_ton = "Untertitelung des ZDF"
    p.process(AUDIO, 16000)

    assert p.last_dropped_tail.startswith("Untertitelung des ZDF")
    assert "Polski" in p.last_dropped_tail


def test_pipeline_ohne_schwanz_meldet_nichts():
    """Kein Fehlalarm-Kanal: Ohne verworfene Segmente bleibt beides leer."""
    from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, make_pipeline

    p, _llm, _injector = make_pipeline(
        RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000)

    assert p.last_dropped_tail == ""
    assert p.last_reason == ""
