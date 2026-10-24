"""Textbausteine (6.5.0): gesprochenes Kuerzel → fester Text, an der KI vorbei."""

from fleech.textbausteine import lies, mit_bausteinen, zerlege
from pipelinehelpers import AUDIO, FakeLLM, make_pipeline

SIGNATUR = "Viele Grüße\nAlex"
BAUSTEINE = lies([
    "Baustein Signatur => Viele Grüße\\nAlex",
    "Baustein Adresse => Musterstraße 1, 12345 Musterstadt",
    "Baustein Adresse Büro => Hafenweg 7, 20457 Hamburg",
])


# -- Einlesen ----------------------------------------------------------------------

def test_lies_versteht_zeilenumbruch_und_sortiert_laengste_zuerst():
    assert BAUSTEINE[0] == ("Baustein Adresse Büro", "Hafenweg 7, 20457 Hamburg")
    assert ("Baustein Signatur", SIGNATUR) in BAUSTEINE


def test_lies_uebergeht_kaputtes_und_doppeltes():
    gelesen = lies(["", "# Kommentar", "ohne Pfeil", "=> nur Text", "Kürzel =>",
                    "Gruß => Hallo", "gruß => doppelt"])
    assert gelesen == [("Gruß", "Hallo")]


# -- Zerlegen ----------------------------------------------------------------------

def test_ohne_kuerzel_bleibt_alles_ein_textstueck():
    assert zerlege("Das ist ein ganz normales Diktat.", BAUSTEINE) == [
        ("text", "Das ist ein ganz normales Diktat.")]


def test_kuerzel_mitten_im_diktat_mit_whisper_satzzeichen():
    teile = zerlege("Danke für die Unterlagen, Baustein, Signatur. Bis bald", BAUSTEINE)
    assert teile == [("text", "Danke für die Unterlagen"), ("baustein", SIGNATUR),
                     ("text", "Bis bald")]


def test_laengeres_kuerzel_gewinnt():
    teile = zerlege("Bitte an Baustein Adresse Büro schicken.", BAUSTEINE)
    assert ("baustein", "Hafenweg 7, 20457 Hamburg") in teile
    assert ("baustein", "Musterstraße 1, 12345 Musterstadt") not in teile


def test_nur_ganze_woerter_loesen_aus():
    assert zerlege("Bausteinsignatur ist kein Kürzel", BAUSTEINE) == [
        ("text", "Bausteinsignatur ist kein Kürzel")]


# -- Zusammensetzen ----------------------------------------------------------------

def test_baustein_bleibt_unveraendert_und_nur_text_wird_bereinigt():
    gesehen = []

    def bereinige(text):
        gesehen.append(text)
        return text.upper(), False

    text, rueckfall = mit_bausteinen("danke, Baustein Signatur", BAUSTEINE,
                                     lambda t: t, bereinige)
    assert gesehen == ["danke"]                      # die KI sieht den Baustein nie
    assert text == "DANKE\n" + SIGNATUR              # mehrzeilig → eigene Zeile
    assert rueckfall is False


def test_nur_das_kuerzel_braucht_kein_modell():
    def bereinige(text):
        raise AssertionError("darf nicht aufgerufen werden")

    text, _ = mit_bausteinen("Baustein Adresse.", BAUSTEINE, lambda t: t, bereinige)
    assert text == "Musterstraße 1, 12345 Musterstadt"


def test_woerterbuch_stufe_laeuft_nicht_ueber_den_baustein():
    text, _ = mit_bausteinen("Meine Adresse lautet Baustein Adresse", BAUSTEINE,
                             lambda t: t.replace("1", "EINS"), lambda t: (t, False))
    assert text == "Meine Adresse lautet Musterstraße 1, 12345 Musterstadt"


def test_rueckfall_eines_textstuecks_wird_gemeldet():
    def bereinige(text):
        return text, text == "zweitens"

    _, rueckfall = mit_bausteinen("erstens Baustein Adresse zweitens", BAUSTEINE,
                                  lambda t: t, bereinige)
    assert rueckfall is True


# -- In der echten Pipeline ----------------------------------------------------------

def test_pipeline_setzt_den_baustein_ein_ohne_ihn_dem_modell_zu_zeigen():
    llm = FakeLLM(reply="Vielen Dank für die schnelle Antwort.")
    p, llm, injector = make_pipeline(
        "vielen dank für die schnelle antwort. Baustein Signatur.", llm=llm)
    p.bausteine = BAUSTEINE
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Vielen Dank für die schnelle Antwort.\n" + SIGNATUR]
    assert all("Signatur" not in user for _sys, user in llm.calls)


def test_pipeline_ohne_bausteine_unveraendert():
    p, llm, injector = make_pipeline("das hier ist ein ganz normales diktat ohne kürzel")
    llm.reply = "Das hier ist ein ganz normales Diktat ohne Kürzel."
    p.process(AUDIO, 16000)
    assert injector.injected == ["Das hier ist ein ganz normales Diktat ohne Kürzel."]
