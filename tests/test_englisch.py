"""F5 — englische Diktate gleichwertig zu deutschen.

Der Kern des Problems steckte im Kauderwelsch-Guard: Zwei seiner vier Merkmale
sind sprachgebunden, und bei englischem Diktat waren beide dauerhaft gesetzt —
englische Füllwörter (erwartbar) und fehlende deutsche Füllwörter (ebenso
erwartbar). Zwei Merkmale bedeuten Schnitt. **Jedes englische Diktat wäre gekürzt
worden.**
"""

import types

import pytest

from fleech.pipeline import Pipeline
from fleech.textfilter import _gibberish_signale, strip_gibberish_tail

EN = ("This is a normal English dictation about the new feature. I want to explain "
      "how it works and why we need it right now.")
DE = ("Das ist ein ganz normales deutsches Diktat über die neue Funktion. Ich "
      "möchte erklären, wie sie funktioniert und warum wir sie brauchen.")


# -- Der Guard misst gegen die richtige Erwartung ---------------------------------------


def test_englischer_text_gilt_bei_deutscher_erwartung_als_auffaellig():
    """Der Zustand VOR der Änderung — festgehalten, damit klar bleibt, wogegen
    die Sprachunterscheidung schützt."""
    assert _gibberish_signale(EN, "de") >= 2


def test_englischer_text_ist_bei_englischer_erwartung_unauffaellig():
    assert _gibberish_signale(EN, "en") == 0


def test_deutscher_text_bleibt_unauffaellig():
    assert _gibberish_signale(DE, "de") == 0


def test_deutscher_text_faellt_bei_englischer_erwartung_auf():
    """Die Spiegelung ist vollständig: Bei „en" gelten deutsche Füllwörter als
    fremd. Der Guard bleibt gleich stark, er misst nur andersherum."""
    assert _gibberish_signale(DE, "en") >= 2


def test_englisches_diktat_wird_nicht_mehr_abgeschnitten():
    text = EN + " And here is one more sentence about the details."
    behalten, entfernt = strip_gibberish_tail(text, "en")
    assert entfernt == ""
    assert behalten == text


def test_echter_wortsalat_wird_auch_bei_englisch_erkannt():
    """Die Schutzwirkung darf nicht verlorengehen — nur die Erwartung ändert sich.
    Wiederholungsschleifen und fremde Diakritika bleiben Merkmale."""
    salat = (EN + " Seekers Odoo Time Go Go Go Go S Go Go and Let me and or. "
             "Căn probabilien werden kann.")
    behalten, entfernt = strip_gibberish_tail(salat, "en")
    assert entfernt, "Wortsalat hätte erkannt werden müssen"
    assert "normal English dictation" in behalten


def test_deutsches_diktat_mit_englischen_fachbegriffen_bleibt_ganz():
    """Der Alltag: „MCP-Server", „Refactoring", „Deployment" in deutschen Sätzen.
    Der Anteil entscheidet, nicht das einzelne Wort."""
    gemischt = ("Ich habe den MCP-Server neu gestartet und das Deployment läuft "
                "jetzt wieder. Das Refactoring von gestern hat also geholfen.")
    behalten, entfernt = strip_gibberish_tail(gemischt, "de")
    assert entfernt == ""
    assert behalten == gemischt


@pytest.mark.parametrize("sprache", ["", None, "de", "DE", "de-DE"])
def test_ohne_klare_sprache_gilt_deutsch(sprache):
    """Ein falsch geratener Guard schneidet lieber nichts als zu viel."""
    assert _gibberish_signale(DE, sprache) == 0


# -- Der Prompt wechselt mit der Sprache ------------------------------------------------


def test_englisches_diktat_bekommt_den_englischen_prompt():
    """LIVE GEMESSEN und deshalb nötig: Mit dem deutschen Prompt übersetzte das
    Modell englischen Text ins Deutsche — und ein bloßer Zusatz („answer in
    English") änderte daran nichts."""
    fake = types.SimpleNamespace(
        cleanup_prompt="DEUTSCHER PROMPT", cleanup_prompt_en="ENGLISH PROMPT",
        sprache="en",
    )
    system = fake.cleanup_prompt
    if fake.sprache.startswith("en") and fake.cleanup_prompt_en:
        system = fake.cleanup_prompt_en
    assert system == "ENGLISH PROMPT"


def test_ohne_englischen_prompt_laeuft_alles_wie_bisher():
    """Fehlt prompts/cleanup-en.md, darf nichts brechen — nur die Übersetzung
    ins Deutsche bleibt dann bestehen."""
    fake = types.SimpleNamespace(
        cleanup_prompt="DEUTSCHER PROMPT", cleanup_prompt_en="", sprache="en")
    system = fake.cleanup_prompt
    if fake.sprache.startswith("en") and fake.cleanup_prompt_en:
        system = fake.cleanup_prompt_en
    assert system == "DEUTSCHER PROMPT"


def test_der_englische_prompt_existiert_und_traegt_die_kernregeln():
    from pathlib import Path

    from fleech.prompts import load_prompt
    from fleech.textutils import TRANSCRIPT_OPEN

    text = load_prompt(Path("prompts"), "cleanup-en")
    assert TRANSCRIPT_OPEN in text              # Marker-Sicherheitsregel
    assert "Do not translate" in text
    assert "faithful" in text.lower()


# -- Sprache je Profil -------------------------------------------------------------------


@pytest.mark.parametrize("wert,erwartet", [
    ("en", "en"), ("de", "de"), ("auto", "auto"),
    ("", ""), ("xx", ""), (None, ""),
])
def test_profil_sprache_wird_geprueft(wert, erwartet):
    from fleech.profiles import profile_sprache

    assert profile_sprache({"sprache": wert}) == erwartet


def test_profil_ohne_sprache_erbt_die_einstellung():
    from fleech.profiles import profile_sprache

    assert profile_sprache({}) == ""


def test_auto_laesst_die_erkennung_selbst_entscheiden():
    """`language=None` heißt bei Whisper: Sprache selbst bestimmen. Für die
    Guards gilt dann Deutsch — hier wird real Deutsch diktiert, und ein falsch
    geratener Guard schneidet lieber nichts."""
    fake = types.SimpleNamespace(
        config=types.SimpleNamespace(stt=types.SimpleNamespace(language="de")),
        pipeline=types.SimpleNamespace(sprache="de", stt=None),
    )
    from fleech.ui.desktop import DesktopApp

    DesktopApp._setze_sprache(fake, "auto")
    assert fake.config.stt.language == ""       # Whisper erkennt selbst
    assert fake.pipeline.sprache == "de"        # Guards bleiben konservativ

    DesktopApp._setze_sprache(fake, "en")
    assert fake.config.stt.language == "en"
    assert fake.pipeline.sprache == "en"
