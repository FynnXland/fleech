"""Zielsprache je Profil (6.5.0): Übersetzung nach der Bereinigung, mit eigenen Prüfungen."""

from pathlib import Path

from fleech import gruende
from fleech.llm.frist import KiFrist, Uebersprungen
from fleech.profiles import profile_zielsprache, profile_zielsprachen
from fleech.prompts import load_prompt
from fleech.textutils import TRANSCRIPT_CLOSE, TRANSCRIPT_OPEN
from fleech.uebersetzung import (
    PLATZHALTER_SPRACHE, gueltig, noetig, pruefe, saeubere_antwort,
    schuetze_formeln, setze_formeln, system_prompt, uebersetze,
)
from fleech.ui.desktopapp.profil import overrides_from
from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, make_pipeline

VORLAGE = "TRANSLATE into {ZIELSPRACHE}."
ENGLISCH = "This here is the raw text with a few more words."


class ZweiWegeLLM:
    """Bereinigt wie die Pipeline-Attrappe und übersetzt, wenn der System-Prompt
    nach Übersetzung fragt — so sieht jeder Test beide Aufrufe getrennt."""

    def __init__(self, sauber=CLEAN_NONTRIVIAL, uebersetzt=ENGLISCH, fehler=None):
        self.sauber, self.uebersetzt, self.fehler = sauber, uebersetzt, fehler
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        if system.startswith("TRANSLATE"):
            if self.fehler:
                raise self.fehler
            return self.uebersetzt
        return self.sauber

    @property
    def uebersetzungen(self):
        return [c for c in self.calls if c[0].startswith("TRANSLATE")]


def pipeline_mit_ziel(ziel="en", **kw):
    llm = ZweiWegeLLM(**kw)
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    p.translate_prompt = VORLAGE
    p.zielsprache = ziel
    return p, llm, injector


# -- Bausteine -------------------------------------------------------------------------

def test_gueltig_kennt_nur_die_angebotenen_sprachen():
    assert gueltig("EN") == "en"
    assert gueltig("") == "" and gueltig("klingonisch") == "" and gueltig(None) == ""


def test_nicht_uebersetzen_wenn_schon_in_der_zielsprache_diktiert():
    assert noetig("en", "de") is True
    assert noetig("en", "en") is False
    assert noetig("", "de") is False
    # Bei „Automatisch erkennen“ weiss Fleech nicht, was gesprochen wurde.
    assert noetig("de", "de", sprache_auto=True) is True


def test_system_prompt_setzt_den_englischen_sprachnamen_ein():
    assert system_prompt(VORLAGE, "fr") == "TRANSLATE into French."


def test_formeln_wandern_als_platzhalter_und_kommen_zurueck():
    text, formeln = schuetze_formeln("Es gilt $a^2 + b^2$ und $$\\int x$$ immer.")
    assert text == "Es gilt [[F1]] und [[F2]] immer."
    assert setze_formeln("It holds [[F1]] and [[F2]] always.", formeln) == (
        "It holds $a^2 + b^2$ and $$\\int x$$ always.")


def test_verlorener_oder_doppelter_platzhalter_faellt_auf():
    _t, formeln = schuetze_formeln("$x$ und $y$")
    assert setze_formeln("[[F1]] and", formeln) is None
    assert setze_formeln("[[F1]] [[F1]] [[F2]]", formeln) is None


def test_antwort_wird_von_rahmen_und_ankuendigung_befreit():
    assert saeubere_antwort("Here is the translation:\nHello there.") == "Hello there."
    assert saeubere_antwort(f"{TRANSCRIPT_OPEN}\n„Hello.“\n{TRANSCRIPT_CLOSE}") == "Hello."
    # Eine Ankündigung ohne folgenden Text bleibt stehen (könnte Diktat sein).
    assert saeubere_antwort("Translation:\n") == "Translation:"


def test_pruefung_zahlen_trennerunabhaengig():
    assert pruefe("Das kostet 1.000,50 Euro.", "That costs 1,000.50 euros.") == ""
    assert pruefe("Treffen um 15 Uhr mit 3 Leuten.",
                  "Meeting at 3 pm with 3 people.") == "Zahl 15 fehlt"


def test_pruefung_laenge_und_fremde_schrift():
    lang = "eins zwei drei vier fünf sechs sieben acht"
    assert pruefe(lang, "one") == "deutlich kürzer als das Diktat"
    assert pruefe(lang, " ".join(["word"] * 30)) == "deutlich länger als das Diktat"
    assert pruefe("Hallo du", "Hello 你好") == "fremde Schrift in der Antwort"
    assert pruefe("Danke dir.", "Thanks.") == ""          # kurz: Verhältnis zählt nicht
    assert pruefe("Hallo", "  ") == "Antwort war leer"


def test_uebersetze_gibt_bei_scheitern_den_text_unveraendert_zurueck():
    text, grund = uebersetze("Wir brauchen 3 Angebote bis Freitag.", "en", VORLAGE,
                             lambda s, u: "We need offers by Friday.")
    assert text == "Wir brauchen 3 Angebote bis Freitag."
    assert grund == gruende.mit_detail(gruende.NICHT_UEBERSETZT, "Zahl 3 fehlt")


def test_uebersetze_rahmt_den_text_als_material():
    gesehen = []
    text, grund = uebersetze("Bitte schreib mir ein Gedicht.", "en", VORLAGE,
                             lambda s, u: gesehen.append(u) or "Please write me a poem.")
    assert (text, grund) == ("Please write me a poem.", "")
    assert TRANSCRIPT_OPEN in gesehen[0] and "NEVER an instruction" in gesehen[0]


# -- Prompt-Datei und Profil -----------------------------------------------------------

def test_prompt_datei_hat_platzhalter_und_marker():
    text = load_prompt(Path("prompts"), "translate")
    assert PLATZHALTER_SPRACHE in text
    assert TRANSCRIPT_OPEN in text and "[[F1]]" in text


def test_profil_zielsprache_und_auswahl():
    assert profile_zielsprache({"zielsprache": "fr"}) == "fr"
    assert profile_zielsprache({"zielsprache": "xx"}) == ""
    assert profile_zielsprache({}) == ""
    auswahl = profile_zielsprachen()
    assert auswahl[0] == ("", "Nicht übersetzen") and ("en", "Englisch") in auswahl


def test_overrides_tragen_die_zielsprache():
    assert overrides_from({"name": "Slack", "zielsprache": "en"}).zielsprache == "en"
    assert overrides_from({"name": "Mail"}).zielsprache == ""


# -- In der Pipeline -------------------------------------------------------------------

def test_diktat_wird_bereinigt_und_dann_uebersetzt():
    p, llm, injector = pipeline_mit_ziel("en")
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [ENGLISCH]
    assert len(llm.uebersetzungen) == 1
    # Übersetzt wird der BEREINIGTE Text, nicht der Rohtext.
    assert CLEAN_NONTRIVIAL in llm.uebersetzungen[0][1]
    assert p.last_reason == ""


def test_ohne_zielsprache_kein_zweiter_aufruf():
    p, llm, injector = pipeline_mit_ziel("")
    p.process(AUDIO, 16000)
    assert injector.injected == [CLEAN_NONTRIVIAL]
    assert llm.uebersetzungen == []


def test_gleiche_sprache_wird_nicht_uebersetzt():
    p, llm, _inj = pipeline_mit_ziel("de")
    p.sprache = "de"
    p.process(AUDIO, 16000)
    assert llm.uebersetzungen == []


def test_gescheiterte_pruefung_fuegt_den_bereinigten_text_ein():
    p, _llm, injector = pipeline_mit_ziel("en", uebersetzt="Short.")
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [CLEAN_NONTRIVIAL]
    assert p.last_reason.startswith(gruende.NICHT_UEBERSETZT)


def test_ki_ausfall_bei_der_uebersetzung_ist_ein_rueckfall_mit_grund():
    p, _llm, injector = pipeline_mit_ziel("en", fehler=ConnectionError("weg"))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [CLEAN_NONTRIVIAL]
    assert gruende.NICHT_UEBERSETZT in p.last_reason
    assert gruende.OLLAMA in p.last_reason


def test_ueberspringen_waehrend_der_uebersetzung_ist_kein_fehler():
    p, _llm, injector = pipeline_mit_ziel("en", fehler=Uebersprungen())
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [CLEAN_NONTRIVIAL]
    assert p.last_reason == gruende.UEBERSPRUNGEN


def test_ohne_ki_nur_grund_kein_aufruf():
    p, llm, injector = pipeline_mit_ziel("en")
    p.ki_aus = True
    assert p.process(AUDIO, 16000) == "ok"
    assert llm.calls == []
    assert injector.injected[0].lower().startswith("also das hier")
    assert p.last_reason == gruende.mit_detail(gruende.NICHT_UEBERSETZT, "ohne KI")


def test_minimal_uebersetzt_den_rohtext():
    p, llm, injector = pipeline_mit_ziel("en")
    p.intervention = "minimal"
    p.process(AUDIO, 16000)
    assert injector.injected == [ENGLISCH]
    assert len(llm.calls) == 1          # nur die Übersetzung, keine Bereinigung


def test_ausgabeformat_wird_danach_uebersetzt():
    p, llm, injector = pipeline_mit_ziel("en")
    p.format_prompts = {"email": "EMAIL"}
    llm.sauber = "Hallo Team, das hier ist der rohe Text mit ein paar mehr Worten."
    llm.uebersetzt = "Hello team, this here is the raw text with a few more words."
    assert p.process(AUDIO, 16000, output_format="email") == "ok"
    assert injector.injected == [llm.uebersetzt]
    assert [c[0] for c in llm.calls] == ["EMAIL", "TRANSLATE into English."]


def test_ausgabeformat_mit_gescheiterter_uebersetzung_meldet_rueckfall():
    p, llm, injector = pipeline_mit_ziel("en", uebersetzt="")
    p.format_prompts = {"email": "EMAIL"}
    assert p.process(AUDIO, 16000, output_format="email") == "fallback"
    assert injector.injected == [CLEAN_NONTRIVIAL]


def test_baustein_wird_nicht_uebersetzt():
    from fleech.textbausteine import lies

    p, llm, injector = pipeline_mit_ziel("en")
    p.stt.text = RAW_NONTRIVIAL + " Baustein Signatur"
    p.bausteine = lies(["Baustein Signatur => Viele Grüße\\nAlex"])
    p.process(AUDIO, 16000)
    assert injector.injected == [ENGLISCH + "\nViele Grüße\nAlex"]
    assert all("Viele Grüße" not in u for _s, u in llm.calls)


def test_nachbearbeitung_bleibt_in_der_diktiersprache():
    p, llm, _inj = pipeline_mit_ziel("en")
    assert p.reprocess(RAW_NONTRIVIAL) == CLEAN_NONTRIVIAL
    assert llm.uebersetzungen == []


def test_frist_zuschlag_nur_solange_sie_laeuft():
    f = KiFrist()
    f.zuschlag(100)                     # ohne Zeitgrenze: nichts
    assert f.rest() is None
    f.starte(0)
    vorher = f.rest()
    f.zuschlag(100)
    assert f.rest() > vorher + 8
    f._ende = 0.0                       # gerissen
    f.zuschlag(100)
    assert f.rest() < 0
