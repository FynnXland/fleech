"""Projekt-Gedaechtnis: gelerntes Fachvokabular je App und Fenster.

Die Beispiele stammen aus 1189 echten Diktaten — an ihnen wurde die Heuristik
kalibriert, und an ihnen muss sie bleiben.
"""

import time

import pytest

from fleech.kontext import (
    MIN_TREFFER, KontextSpeicher, begriffe_aus_text, titel_segmente,
)


@pytest.fixture
def speicher(tmp_path):
    return KontextSpeicher(tmp_path / "kontext.db")


# -- Was als Fachbegriff gilt ----------------------------------------------------------


@pytest.mark.parametrize("text,erwartet", [
    ("Der MCP-Server läuft", ["MCP-Server"]),
    ("Wir nutzen PySide6 und gemma3", ["PySide6", "gemma3"]),
    ("Siehe share.finland.xyz dazu", ["share.finland.xyz"]),
    ("Die Cauchy-Schwarz-Ungleichung gilt", ["Cauchy-Schwarz-Ungleichung"]),
    ("Das KI-Prompting im Design-System", ["KI-Prompting", "Design-System"]),
])
def test_fachbegriffe_werden_erkannt(text, erwartet):
    assert begriffe_aus_text(text) == erwartet


@pytest.mark.parametrize("text", [
    "Das ist eine ganz normale Aussage über den Abend.",
    "Die Wahrscheinlichkeit dafür ist gering.",
    "Ich habe fünf Würfel und eine Waffe.",
])
def test_gewoehnliche_sprache_wird_nicht_gelernt(text):
    """Getestet und VERWORFEN wurde „kommt nur in dieser App vor" — das lieferte
    genau diese Woerter. Sie zu primen zieht Whisper in ihre Richtung und
    verschlechtert die Erkennung, statt sie zu verbessern."""
    assert begriffe_aus_text(text) == []


def test_doubletten_und_reihenfolge():
    text = "GitHub und GitHub und dann PySide6"
    assert begriffe_aus_text(text) == ["GitHub", "PySide6"]


def test_leeres_und_kaputtes_stoert_nicht():
    for wert in ("", None, "   ", "...", "123 456"):
        assert begriffe_aus_text(wert) == []


# -- Titel-Segmente --------------------------------------------------------------------


def test_titel_wird_in_segmente_zerlegt():
    """Der ganze Titel als Schluessel waere wertlos (jede Datei ein Kontext),
    der Prozessname allein zu grob (alles in einem Topf)."""
    assert titel_segmente("pipeline.py - Fleech - Visual Studio Code") == [
        "pipeline.py", "fleech"]          # der Editor-Name faellt als generisch weg


def test_generische_segmente_fallen_weg():
    assert titel_segmente("Neuer Tab - Google Chrome") == []
    assert "obsidian" not in titel_segmente("Analysis II - Obsidian")


def test_segmentzahl_ist_begrenzt():
    lang = " - ".join(f"Teil{i}" for i in range(12))
    assert len(titel_segmente(lang)) <= 4


# -- Lernen und Abrufen ----------------------------------------------------------------


def test_ein_einzelner_treffer_wird_noch_nicht_geprimt(speicher):
    """Einmal-Treffer sind ueberwiegend Erkennungsfehler. Die wieder einzuspeisen
    wuerde den Fehler verfestigen — real beobachtet als
    „Willkommens-Rueck-Finn-Haar"."""
    speicher.lerne("claude.exe", "", "Der MCP-Server läuft")
    assert speicher.priming_begriffe("claude.exe") == []

    speicher.lerne("claude.exe", "", "Der MCP-Server wieder")
    assert speicher.priming_begriffe("claude.exe") == ["MCP-Server"]


def test_fenster_geht_vor_app_grundstock(speicher):
    """Die zwei Ebenen aus dem Wunsch: ein Haupt-Kontext (app-weit) und der
    spezifische darunter — nur ohne dass jemand sie pflegen muss."""
    for _ in range(MIN_TREFFER):
        speicher.lerne("code.exe", "andere.py - Uni", "Die Fourier-Reihe hier")
        speicher.lerne("code.exe", "pipeline.py - Fleech", "Der MCP-Server dort")

    im_fleech = speicher.priming_begriffe("code.exe", "pipeline.py - Fleech")
    assert im_fleech[0] == "MCP-Server"          # spezifisch zuerst
    assert "Fourier-Reihe" in im_fleech          # Grundstock danach


def test_app_trennung(speicher):
    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der MCP-Server")
        speicher.lerne("obsidian.exe", "", "Die Cauchy-Schwarz-Ungleichung")
    assert speicher.priming_begriffe("claude.exe") == ["MCP-Server"]
    assert speicher.priming_begriffe("obsidian.exe") == ["Cauchy-Schwarz-Ungleichung"]
    assert speicher.priming_begriffe("unbekannt.exe") == []


def test_haeufigeres_steht_vorn(speicher):
    for _ in range(6):
        speicher.lerne("claude.exe", "", "Das Design-System")
    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der USB-Stick")
    b = speicher.priming_begriffe("claude.exe")
    assert b.index("Design-System") < b.index("USB-Stick")


def test_spaetere_schreibweise_gewinnt(speicher):
    """Woerterbuch und Sprachmodell korrigieren mit der Zeit — geprimt werden
    soll die richtige Fassung, nicht die erste."""
    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der MCP-server")
    speicher.lerne("claude.exe", "", "Der MCP-Server")
    assert speicher.priming_begriffe("claude.exe") == ["MCP-Server"]


def test_limit_wird_eingehalten(speicher):
    for i in range(60):
        for _ in range(MIN_TREFFER):
            speicher.lerne("claude.exe", "", f"Begriff-Nummer{i} hier")
    assert len(speicher.priming_begriffe("claude.exe", limit=25)) == 25


def test_alte_begriffe_verfallen(speicher):
    """Projekte enden. Ein Vokabular, das nie vergisst, primt auf Vergangenes."""
    import sqlite3

    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Das Alt-Projekt hier")
    with sqlite3.connect(speicher.path) as con:
        con.execute("UPDATE begriffe SET zuletzt = ?", (time.time() - 200 * 86400,))
    assert speicher.priming_begriffe("claude.exe") == []
    assert speicher.aufraeumen() > 0


def test_uebersicht_und_vergessen(speicher):
    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "pipeline.py - Fleech", "Der MCP-Server")
    assert speicher.kontexte("claude.exe")
    assert speicher.vergiss("claude.exe") > 0
    assert speicher.priming_begriffe("claude.exe") == []
    assert speicher.kontexte() == []


def test_ohne_app_wird_nichts_gelernt(speicher):
    """Ohne Ziel-App gibt es keinen Kontext, dem der Begriff gehoert."""
    assert speicher.lerne("", "titel", "Der MCP-Server") == 0
    assert speicher.priming_begriffe("") == []


def test_daten_ueberleben_den_neustart(speicher, tmp_path):
    """Der Kern des Wunsches: „auch wenn wir das Modell neu starten"."""
    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der MCP-Server")
    neu = KontextSpeicher(tmp_path / "kontext.db")     # zweiter Start
    assert neu.priming_begriffe("claude.exe") == ["MCP-Server"]


# -- Verdrahtung in der Pipeline -------------------------------------------------------


def test_pipeline_gibt_gelernte_begriffe_ins_priming(speicher):
    """Das Gelernte muss auch ankommen — als Whisper-Hinweis, denselben Weg wie
    das handgepflegte Woerterbuch."""
    import types

    from fleech.pipeline import Pipeline

    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der MCP-Server im Design-System")

    fake = types.SimpleNamespace(kontext=speicher, kontext_lernen=True,
                                 _vocab_prompt="")
    begriffe = Pipeline._kontext_begriffe(fake, "claude.exe", "")
    assert "MCP-Server" in begriffe and "Design-System" in begriffe

    # Ohne App (unbekannter Fokus) darf nichts kommen — sonst primte Fleech
    # fremdes Vokabular in ein Fenster, das nichts damit zu tun hat.
    assert Pipeline._kontext_begriffe(fake, "", "") == []


def test_pipeline_uebersteht_einen_kaputten_speicher():
    """Ohne Priming wird schlechter erkannt — ohne Diktat gar nicht. Ein Fehler
    im Gedaechtnis darf die Aufnahme nie aufhalten."""
    import types

    from fleech.pipeline import Pipeline

    class Kaputt:
        def priming_begriffe(self, *a, **k):
            raise OSError("Datenbank gesperrt")

        def lerne(self, *a, **k):
            raise OSError("Datenbank gesperrt")

    fake = types.SimpleNamespace(kontext=Kaputt(), kontext_lernen=True,
                                 _vocab_prompt="")
    assert Pipeline._kontext_begriffe(fake, "claude.exe", "") == []
    Pipeline._kontext_lernen(fake, "claude.exe", "", "Text")   # darf nicht werfen

    ohne = types.SimpleNamespace(kontext=None, kontext_lernen=True,
                                 _vocab_prompt="")
    assert Pipeline._kontext_begriffe(ohne, "claude.exe", "") == []
    Pipeline._kontext_lernen(ohne, "claude.exe", "", "Text")


def test_gelernt_wird_erst_nach_dem_einfuegen(speicher):
    """Was nie beim Nutzer ankam (verworfen, abgebrochen, Fehler), soll das
    Vokabular nicht praegen."""
    import types

    from fleech.pipeline import Pipeline

    fake = types.SimpleNamespace(
        kontext=speicher, kontext_lernen=True,
        _ziel_app="claude.exe", _ziel_fenster="",
        tracker=types.SimpleNamespace(separator=lambda: "",
                                      record_append=lambda t: None),
        injector=types.SimpleNamespace(inject=lambda t: None),
        last_injected="",
    )
    fake._kontext_lernen = lambda a, ti, tx: Pipeline._kontext_lernen(fake, a, ti, tx)
    for _ in range(MIN_TREFFER):
        Pipeline._inject_append(fake, "Der MCP-Server läuft")
    assert speicher.priming_begriffe("claude.exe") == ["MCP-Server"]


def test_schalter_haelt_das_gedaechtnis_komplett_an(speicher):
    """Aus heisst aus — weder primen noch lernen. Sonst waechst im Hintergrund
    weiter etwas, das man abgeschaltet zu haben glaubt."""
    import types

    from fleech.pipeline import Pipeline

    for _ in range(MIN_TREFFER):
        speicher.lerne("claude.exe", "", "Der MCP-Server")

    aus = types.SimpleNamespace(kontext=speicher, kontext_lernen=False,
                                _vocab_prompt="")
    assert Pipeline._kontext_begriffe(aus, "claude.exe", "") == []

    Pipeline._kontext_lernen(aus, "claude.exe", "", "Das Design-System hier")
    Pipeline._kontext_lernen(aus, "claude.exe", "", "Das Design-System nochmal")
    assert "Design-System" not in speicher.priming_begriffe("claude.exe")


def test_gelernte_begriffe_weichen_dem_handgepflegten_woerterbuch(speicher):
    """Der Whisper-initial_prompt hat ein hartes Limit (~224 Token). Wer viel
    Vokabular pflegt, darf es nicht an das Gelernte verlieren — von Hand
    eingetragene Begriffe sind praeziser."""
    import types

    from fleech.pipeline import Pipeline

    for i in range(40):
        for _ in range(MIN_TREFFER):
            speicher.lerne("claude.exe", "", f"Der Begriff-Nr{i} hier")

    leer = types.SimpleNamespace(kontext=speicher, kontext_lernen=True,
                                 _vocab_prompt="")
    voll = types.SimpleNamespace(kontext=speicher, kontext_lernen=True,
                                 _vocab_prompt="Vokabular: " + ", ".join(
                                     f"Fachwort{i}" for i in range(60)) + ".")
    ohne_woerterbuch = len(Pipeline._kontext_begriffe(leer, "claude.exe", ""))
    mit_woerterbuch = len(Pipeline._kontext_begriffe(voll, "claude.exe", ""))
    assert ohne_woerterbuch > mit_woerterbuch
    assert mit_woerterbuch >= 8          # nie ganz verdraengt
