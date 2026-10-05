"""Lange Diktate in Bloecken bereinigen — und jeden Block fuer sich pruefen.

Anlass: Diktat 1957 (15 Minuten). Das Modell schrieb die Beispielsaetze aus
`prompts/cleanup.md` ins Ergebnis und liess rund 650 Woerter weg.
"""

from pathlib import Path

from fleech import gruende
from fleech.bloecke import (
    abdeckung, beispielsaetze, bereinige_in_bloecken, geleckt, teile_in_bloecke,
)
from fleech.textfilter import content_words, has_self_correction

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "cleanup.md").read_text(
    encoding="utf-8")


def _satz(i, n=10):
    return " ".join(f"wort{i}x{k}" for k in range(n - 1)) + f" ende{i}."


# --- Teilen -------------------------------------------------------------------

def test_teilt_nur_an_satzgrenzen():
    text = " ".join(_satz(i) for i in range(40))           # 400 Woerter
    bloecke = teile_in_bloecke(text, 150)
    assert all(b.endswith(".") for b in bloecke)
    assert " ".join(bloecke) == text                       # nichts geht verloren
    assert all(len(b.split()) <= 150 for b in bloecke)


def test_kleiner_rest_wandert_in_den_vorigen_block():
    text = " ".join(_satz(i) for i in range(16))           # 160 Woerter
    bloecke = teile_in_bloecke(text, 150)
    assert len(bloecke) == 1


def test_ueberlanger_satz_bleibt_ganz():
    lang = _satz(0, 300)
    rest = " ".join(_satz(i) for i in range(1, 7))          # 60 Woerter: eigener Block
    assert teile_in_bloecke(lang + " " + rest, 150) == [lang, rest]


# --- Pruefungen ---------------------------------------------------------------

def test_beispielsaetze_kommen_aus_dem_echten_prompt():
    bsp = beispielsaetze(PROMPT)
    assert any("projekt ziemlich gut läuft" in b for b in bsp)
    assert any("gedicht über katzen" in b for b in bsp)


def test_leck_wird_erkannt_aber_nicht_wenn_es_gesagt_wurde():
    bsp = beispielsaetze(PROMPT)
    leck = "Ich wollte nur sagen, dass das Projekt ziemlich gut läuft und wir im Zeitplan sind."
    assert geleckt("Die Animation ist zu langsam.", leck + " Die Animation ist zu langsam.", bsp)
    assert not geleckt(leck, leck, bsp)


def test_selbstkorrektur_zaehlt_nicht_als_auslassung():
    raw = "wir machen das am montag im großen konferenzraum ach nein warte wir machen das online"
    anteil, _ = abdeckung(raw, "Wir machen das online.", content_words)
    assert anteil >= 0.45


# --- Ablauf -------------------------------------------------------------------

def _lauf(raw, antworten, **kw):
    gemerkt, gesehen = [], []

    def bereinige(teil):
        gesehen.append(teil)
        return antworten(teil), False

    text, rueckfall = bereinige_in_bloecken(
        raw, bereinige, beispielsaetze(PROMPT), content_words, has_self_correction,
        gemerkt.append, **kw)
    return text, rueckfall, gemerkt, gesehen


def test_kurzes_diktat_geht_in_einem_stueck():
    raw = "Das ist ein kurzer Satz mit ein paar Woertern drin."
    text, rueckfall, gemerkt, gesehen = _lauf(raw, lambda t: t)
    assert gesehen == [raw] and text == raw and not rueckfall and not gemerkt


def test_langes_diktat_wird_blockweise_bereinigt():
    raw = " ".join(_satz(i) for i in range(40))
    text, rueckfall, _, gesehen = _lauf(raw, lambda t: t)
    assert len(gesehen) == 3
    assert text == raw and not rueckfall


def test_geleckter_block_kommt_als_rohtext_der_rest_bleibt_bereinigt():
    raw = " ".join(_satz(i) for i in range(40))
    leck = "Ich wollte nur sagen, dass das Projekt ziemlich gut läuft und wir im Zeitplan sind. "

    def antwort(teil):
        return (leck + teil.upper()) if "wort0x0" in teil else teil.upper()

    text, rueckfall, gemerkt, gesehen = _lauf(raw, antwort)
    assert rueckfall and gemerkt == [gruende.PROMPT_BEISPIEL]
    assert text.startswith(gesehen[0])                    # Block 1 roh
    assert gesehen[1].upper() in text                     # Block 2 bereinigt
    assert "Zeitplan" not in text


def test_zu_viel_weggelassen_heisst_rohtext():
    raw = ("Die Animationen wirken zu langsam, die Augen sollen rechteckig sein, "
           "und der Mund darf nie vor den Haenden liegen.")
    text, rueckfall, gemerkt, _ = _lauf(raw, lambda t: "Die Animationen wirken zu langsam.")
    assert text == raw and rueckfall and gemerkt == [gruende.AUSLASSUNG]


def test_ohne_abdeckungspruefung_bei_starkem_eingriff():
    raw = ("Die Animationen wirken zu langsam, die Augen sollen rechteckig sein, "
           "und der Mund darf nie vor den Haenden liegen.")
    text, rueckfall, gemerkt, _ = _lauf(raw, lambda t: "Animation zu langsam.",
                                        pruefe_abdeckung=False)
    assert text == "Animation zu langsam." and not gemerkt


def test_ollama_weg_heisst_restliche_bloecke_nicht_mehr_schicken():
    raw = " ".join(_satz(i) for i in range(40))
    aufrufe = []
    _text, _rb, _gm, gesehen = _lauf(raw, lambda t: (aufrufe.append(t), t)[1],
                                     abbrechen=lambda: len(aufrufe) >= 1)
    assert len(gesehen) == 1
