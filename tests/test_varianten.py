"""Schreibvarianten statt Grammatik (V-14/H-6, Befunde H-B1 und H-B3).

Die Vorschlagskarte speiste sich aus dem Diff „roh gegen bereinigt" und fand
damit Grammatik („kann → können"). Der Begriff, um den es dem Nutzer wirklich
geht, steht dort nie: „Cloud-Code" kam in 1399 echten Diktaten 18-mal vor,
„Claude Code" 10-mal — und das Projekt-Gedächtnis hatte die falsche Schreibweise
gelernt und primte sie zurück.
"""

import time

import pytest

from fleech import varianten
from fleech.history import DictationRecord, HistoryStore
from fleech.kontext import KontextSpeicher


# -- Die Auswertung ---------------------------------------------------------------------


def _texte(*paare) -> list[str]:
    """[(text, anzahl), …] → Liste von Diktat-Texten."""
    return [text for text, anzahl in paare for _ in range(anzahl)]


def test_der_hauptfall_wird_gefunden():
    """„Cloud-Code" ist EIN Token, „Claude Code" sind ZWEI — ohne Zweiwort-
    Kandidaten und ohne Normalschluessel faellt genau der wichtigste Fall durch."""
    zaehler = varianten.zaehle_kandidaten(_texte(
        ("Der Cloud-Code Agent hat den Test gebaut.", 4),
        ("Der Claude Code Agent hat den Test gebaut.", 3),
    ))
    fragen = varianten.finde_varianten(zaehler)
    assert fragen, "keine Frage gebildet"
    formen = {fragen[0].haeufig, fragen[0].selten}
    assert formen == {"Cloud-Code", "Claude Code"}
    assert fragen[0].haeufig_anzahl == 4 and fragen[0].selten_anzahl == 3


def test_die_haeufigere_form_ist_nicht_die_empfohlene():
    """Die Frage nennt die haeufigere zuerst — als Zahl, nicht als Vorschlag.
    Im echten Fall ist genau die haeufigere die falsche."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Der Cloud-Code baut.", 5),
                                                 ("Der Claude-Code baut.", 2)))
    frage = varianten.finde_varianten(zaehler)[0]
    assert (frage.haeufig, frage.haeufig_anzahl) == ("Cloud-Code", 5)
    assert (frage.selten, frage.selten_anzahl) == ("Claude-Code", 2)


def test_echte_wortpaare_werden_gefragt_nicht_entschieden():
    """„MP3-Datei"/„MP4-Datei" sind zwei richtige Begriffe, liegen aber einen
    Schritt auseinander. Der Cluster zieht sie zusammen — deshalb ist das
    Ergebnis eine Frage mit zwei gleichwertigen Knoepfen und einem „Ignorieren",
    nie eine Ersetzung."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Die MP3-Datei liegt da.", 3),
                                                 ("Die MP4-Datei liegt da.", 3)))
    fragen = varianten.finde_varianten(zaehler)
    assert {fragen[0].haeufig, fragen[0].selten} == {"MP3-Datei", "MP4-Datei"}


def test_zwei_weiche_woerter_werden_nie_gefragt():
    """Gemessen am echten Bestand (1399 Diktate): Ohne die Bedingung „mindestens
    eine harte Form" stehen auf den vorderen Plaetzen „Datei"/„Daten",
    „Pille"/„Rolle", „Sachen"/„Machen" — im Deutschen ist jedes Substantiv gross,
    zwei beliebige davon liegen schnell zwei Schritte auseinander. Der Preis:
    „Fleece"/„Fleech" faellt mit durch. Eine Karte, deren erste Frage Unsinn ist,
    wird nie wieder gelesen — deshalb Genauigkeit vor Vollstaendigkeit."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Die Pille blinkt.", 3),
                                                 ("Die Rolle blinkt.", 3)))
    assert varianten.finde_varianten(zaehler) == []


def test_weit_auseinander_nur_bei_gleichem_anfang():
    """Zwei Schritte Abstand nur bei gleichem Anfangsbuchstaben — sonst kamen am
    echten Bestand „Datei"/„LaTeX" und „E-Mail"/„Detail" durch."""
    weit = varianten.zaehle_kandidaten(_texte(("Die Datei liegt da.", 3),
                                              ("Das LaTeX liegt da.", 3)))
    assert varianten.finde_varianten(weit) == []
    nah = varianten.zaehle_kandidaten(_texte(("Der Kosinus-Satz gilt.", 3),
                                             ("Der Cosinus-Satz gilt.", 3)))
    assert len(varianten.finde_varianten(nah)) == 1


def test_zusammensetzungen_sind_keine_varianten():
    """„KI-Prompt" und „Prompt" sind beide richtig — eine Regel daraus wuerde
    jedes „Prompt" zu „KI-Prompt" machen. Am echten Bestand waren solche Paare
    drei der acht staerksten Fundstellen."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Der Prompt sitzt.", 4),
                                                 ("Der KI-Prompt sitzt.", 3)))
    assert varianten.finde_varianten(zaehler) == []


def test_beugung_ist_keine_variante():
    """Eine Regel „Diktate => Diktaten" wuerde die Beugung kaputt ersetzen."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Die Diktate sind da.", 3),
                                                 ("Von den Diktaten her.", 3)))
    assert varianten.finde_varianten(zaehler) == []


def test_zwei_weiche_wortpaare_ergeben_keine_frage():
    """Bei Zweiwort-Kandidaten muss eine Seite hart sein (Binnenversal,
    Bindestrich, Ziffer) — sonst waeren „Das Team" und „Dem Team" eine Frage.
    Zwei EINZELWOERTER duerfen weich sein, siehe „Fleece"/„Fleech" oben."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Das Team wartet.", 3),
                                                 ("Dem Team wartet.", 3)))
    assert varianten.finde_varianten(zaehler) == []


def test_fuellwort_paare_verdraengen_den_begriff_nicht():
    """„Die MP3-Datei" kommt genauso oft vor wie „MP3-Datei" — gefragt wird nach
    dem Begriff, nicht nach dem Artikel davor."""
    zaehler = varianten.zaehle_kandidaten(_texte(("Die MP3-Datei liegt da.", 3),
                                                 ("Die MP4-Datei liegt da.", 3)))
    frage = varianten.finde_varianten(zaehler)[0]
    assert {frage.haeufig, frage.selten} == {"MP3-Datei", "MP4-Datei"}


def test_einmal_gesehen_reicht_nicht():
    """Einmal-Treffer sind ueberwiegend Erkennungsfehler, keine Schreibweisen."""
    zaehler = varianten.zaehle_kandidaten(["Der MCP-Server läuft.",
                                           "Der MPC-Server läuft."])
    assert varianten.finde_varianten(zaehler) == []


def test_ein_diktat_zaehlt_je_schreibweise_einmal():
    """Sonst gewinnt ein einzelnes Diktat, das denselben Begriff zwanzigmal
    nennt, gegen zwanzig Diktate mit der anderen Schreibweise."""
    zaehler = varianten.zaehle_kandidaten(["PySide6 PySide6 PySide6 PySide6"])
    assert zaehler["PySide6"] == 1


def test_trennzeichen_sind_dieselbe_schreibweise():
    """„MCP-Server" und „MCP Server" unterscheiden sich nur in der Trennung —
    zusammengezaehlt, nicht als zwei Varianten gefragt."""
    assert varianten.normalschluessel("MCP-Server") == \
        varianten.normalschluessel("MCP Server")
    zaehler = varianten.zaehle_kandidaten(_texte(("Der MCP-Server läuft.", 3),
                                                 ("Der MCP Server läuft.", 3)))
    assert varianten.finde_varianten(zaehler) == []


def test_das_gedaechtnis_ist_die_zweite_quelle(tmp_path):
    """In kontext.db stehen die Varianten samt Trefferzahl bereits fertig —
    dort standen `Cloud-Code` (4 Treffer) und `FLEACH` (3) im Echtbestand."""
    zaehler = varianten.zaehle_gedaechtnis([("Cloud-Code", 4), ("Claude-Code", 3),
                                            ("und", 9)])
    assert zaehler["Cloud-Code"] == 4 and "und" not in zaehler
    frage = varianten.finde_varianten(zaehler)[0]
    assert {frage.haeufig, frage.selten} == {"Cloud-Code", "Claude-Code"}


def test_vorschlaege_verbinden_verlauf_und_gedaechtnis(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    for i in range(3):
        store.add(DictationRecord(ts=time.time() - i, raw="x",
                                  cleaned="Der Cloud-Code Agent.", audio_seconds=1.0))
    speicher = KontextSpeicher(tmp_path / "k.db")
    for _ in range(2):
        speicher.lerne("claude.exe", "", "Der Claude-Code Agent.")
    fragen = varianten.vorschlaege(store, speicher)
    assert fragen and {fragen[0].haeufig, fragen[0].selten} == {"Cloud-Code",
                                                                "Claude-Code"}


def test_kaputte_quellen_kosten_nur_den_vorschlag():
    class Kaputt:
        def recent_cleaned(self, limit=300):
            raise RuntimeError("db weg")

    assert varianten.vorschlaege(Kaputt()) == []


# -- Das Gedaechtnis: einzeln lesen und einzeln vergessen -------------------------------


def test_alle_begriffe_zaehlt_jeden_begriff_einmal(tmp_path):
    """`lerne` legt jeden Begriff app-weit UND unter jedem Titel-Segment ab. Ueber
    alles summiert waere jeder Begriff mehrfach gezaehlt — und zwar unterschiedlich
    oft, je nachdem wie viele Fenstertitel er gesehen hat."""
    speicher = KontextSpeicher(tmp_path / "k.db")
    speicher.lerne("code.exe", "pipeline.py - Fleech-Projekt", "Der MCP-Server läuft.")
    speicher.lerne("code.exe", "home.py - Fleech-Projekt", "Der MCP-Server läuft.")
    assert speicher.alle_begriffe() == [("MCP-Server", 2)]


def test_ein_einzelner_begriff_laesst_sich_vergessen(tmp_path):
    """Bisher gab es nur „alles vergessen" — wer den einen Hoerfehler loswerden
    wollte, verlor das ganze gelernte Vokabular mit (Befund H-B3)."""
    speicher = KontextSpeicher(tmp_path / "k.db")
    speicher.lerne("claude.exe", "Fleech-Projekt", "Der Cloud-Code und der MCP-Server.")
    assert speicher.vergiss(begriff="Cloud-Code") == 2      # beide Segmente
    verbleibend = dict(speicher.alle_begriffe())
    assert "Cloud-Code" not in verbleibend and "MCP-Server" in verbleibend
    # Auch das Titel-Segment ist frei — sonst primt es den Fehler weiter.
    assert "Cloud-Code" not in speicher.priming_begriffe("claude.exe",
                                                         "Fleech-Projekt")


# -- Die Oberflaeche --------------------------------------------------------------------

pytest.importorskip("PySide6")


def _insights(tmp_path, settings, speicher=None):
    from fleech.ui.pages.insights import InsightsPage

    store = HistoryStore(tmp_path / "advice.db")
    jetzt = time.time()
    for i in range(4):
        store.add(DictationRecord(ts=jetzt - i, raw="x",
                                  cleaned="Der Cloud-Code Agent baut.",
                                  audio_seconds=1.0, app="claude.exe"))
    for i in range(3):
        store.add(DictationRecord(ts=jetzt - 10 - i, raw="x",
                                  cleaned="Der Claude Code Agent baut.",
                                  audio_seconds=1.0, app="claude.exe"))
    genommen: list = []
    seite = InsightsPage(
        store, on_add_rule=lambda w, r: genommen.append((w, r)), settings=settings,
        kontext_fn=(lambda: speicher) if speicher is not None else None,
    )
    seite.refresh()
    return seite, genommen


def _knopftexte(seite) -> list[str]:
    from PySide6.QtWidgets import QPushButton

    return [b.text() for row in seite._advice_rows
            for b in row.findChildren(QPushButton)]


def test_die_karte_stellt_die_frage_mit_beiden_seiten(qapp, tmp_path):
    from fleech.usersettings import UserSettings

    seite, _ = _insights(tmp_path, UserSettings())
    texte = _knopftexte(seite)
    assert any("Cloud-Code" in t and "ist richtig" in t for t in texte)
    assert any("Claude Code" in t and "ist richtig" in t for t in texte)
    assert "Ignorieren" in texte


def test_jede_seite_kann_die_richtige_sein(qapp, tmp_path):
    """Beide Knoepfe legen `falsch => richtig` an — je nachdem, welchen man
    drueckt. Keine Vorauswahl, auch nicht ueber die Haeufigkeit."""
    from PySide6.QtWidgets import QPushButton

    from fleech.usersettings import UserSettings

    seite, genommen = _insights(tmp_path, UserSettings())
    knoepfe = [b for row in seite._advice_rows for b in row.findChildren(QPushButton)
               if "Claude Code" in b.text() and "ist richtig" in b.text()]
    assert knoepfe
    knoepfe[0].click()
    assert genommen == [("Cloud-Code", "Claude Code")]


def test_der_knopf_sagt_was_er_tut(qapp, tmp_path):
    """B-1: Jede uebernommene Regel ist eine GLOBALE Ersetzung — das muss am
    Knopf stehen, nicht erst hinterher auffallen."""
    from PySide6.QtWidgets import QPushButton

    from fleech.usersettings import UserSettings

    seite, _ = _insights(tmp_path, UserSettings())
    hinweise = [b.toolTip() for row in seite._advice_rows
                for b in row.findChildren(QPushButton) if "ist richtig" in b.text()]
    assert hinweise and all("überall" in h for h in hinweise)


def test_ignorieren_wirkt_in_beide_richtungen(qapp, tmp_path):
    """Bei einer Variantenfrage steht nicht fest, welche Seite die falsche ist —
    ein „Ignorieren" darf die Frage in keiner Richtung wiederbringen."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    seite, _ = _insights(tmp_path, settings)
    assert seite._advice_rows
    settings.output.dictionary_ignores.append("claude code => cloud-code")
    seite.refresh()
    assert not any("ist richtig" in t for t in _knopftexte(seite))


def test_eine_uebernommene_regel_beendet_die_frage(qapp, tmp_path):
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    seite, _ = _insights(tmp_path, settings)
    settings.output.dictionary.append("Cloud-Code => Claude Code")
    seite.refresh()
    assert not any("ist richtig" in t for t in _knopftexte(seite))


def test_die_vorschlagskarte_rendert(qapp, tmp_path):
    from fleech.usersettings import UserSettings

    seite, _ = _insights(tmp_path, UserSettings())
    seite.resize(1000, 700)
    bild = seite._advice_frame.grab()
    assert not bild.isNull()


def test_uebernahme_legt_die_regel_an_und_vergisst_die_falsche_form(
        qapp, tmp_path, monkeypatch):
    """Der Kern von V-14: Ohne das Vergessen bliebe der Fehler im Priming —
    `kontext.db` gibt gelernte Begriffe als initial_prompt an Whisper zurueck."""
    from uihelpers import make_main_window

    fenster, panel, _store, settings, _changed = make_main_window(tmp_path, monkeypatch)
    speicher = KontextSpeicher()          # zeigt per conftest in tmp_path
    speicher.lerne("claude.exe", "", "Der Cloud-Code Agent baut den Test.")
    assert "Cloud-Code" in dict(speicher.alle_begriffe())

    fenster._add_dictionary_rule("Cloud-Code", "Claude Code")

    assert "Cloud-Code => Claude Code" in settings.output.dictionary
    assert "Cloud-Code" not in dict(speicher.alle_begriffe())
    # Der Editor in den Einstellungen zieht mit (sonst erst nach Neustart sichtbar).
    assert "Cloud-Code => Claude Code" in panel._dictionary_editor.toPlainText()


def test_gelerntes_einzeln_vergessen_in_den_einstellungen(qapp, tmp_path, monkeypatch):
    """Die kleine Auswahlliste neben „Gelerntes vergessen": genau EINEN Begriff
    loeschen, statt das ganze Vokabular."""
    from uihelpers import make_main_window

    speicher = KontextSpeicher()          # zeigt per conftest in tmp_path
    speicher.lerne("claude.exe", "", "Der Cloud-Code und der MCP-Server.")
    _fenster, panel, _store, _settings, _changed = make_main_window(tmp_path, monkeypatch)

    combo = panel._kontext_begriffe
    assert combo.count() == 2 and combo.isEnabled()
    combo.setCurrentIndex([combo.itemData(i) for i in range(combo.count())]
                          .index("Cloud-Code"))
    panel._kontext_begriff_vergessen()

    verbleibend = dict(speicher.alle_begriffe())
    assert "Cloud-Code" not in verbleibend and "MCP-Server" in verbleibend
    assert [panel._kontext_begriffe.itemData(i)
            for i in range(panel._kontext_begriffe.count())] == ["MCP-Server"]
