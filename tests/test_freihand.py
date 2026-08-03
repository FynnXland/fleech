"""F1 — Freihand-Modus: Startwort sagen, sprechen, aufhören.

Die Zustandsmaschine kennt kein Audio-Gerät und kein Qt: Audio kommt herein,
Ereignisse kommen heraus. Damit ist der heikle Teil — wann startet, wann endet ein
Diktat — vollständig ohne Mikrofon prüfbar.
"""

import numpy as np
import pytest

from fleech.freihand import (
    Einstellungen, Ereignis, Lauscher, Zustand, enthaelt_wort, normalisiere,
)

SR = 16000


def block(sekunden: float = 0.2) -> np.ndarray:
    return np.zeros(int(SR * sekunden), dtype=np.float32)


def _lauscher(text="", sprache=True, **kw):
    """Lauscher mit Attrappen: `text` ist, was die Erkennung liefert."""
    e = Einstellungen(aktiv=True, **kw)
    lau = Lauscher(e, vad=lambda a: sprache, erkenner=lambda a: text, samplerate=SR)
    lau.start_lauschen()
    return lau


# -- Wortvergleich ---------------------------------------------------------------------


@pytest.mark.parametrize("gesprochen", [
    "Kimono", "kimono", "Kimono,", "Also, Kimono!", "kimono.", "  KIMONO  ",
])
def test_startwort_wird_trotz_schreibweise_erkannt(gesprochen):
    """Whisper schreibt dasselbe Wort mal mit Komma, mal groß — ein Startwort,
    das daran scheitert, wäre im Alltag unbrauchbar."""
    assert enthaelt_wort(gesprochen, "Kimono")


@pytest.mark.parametrize("gesprochen", [
    "Kimonos sind schön", "Ich mag Kimonoartiges", "",
])
def test_teiltreffer_loesen_nicht_aus(gesprochen):
    """Wortgrenzen sind Pflicht — sonst aktiviert jedes längere Wort mit.

    „Kimo no" stand hier urspruenglich mit dabei und ist bewusst herausgenommen:
    Die Messung an echter Stimme zeigte, dass das Pruefmodell „Kimono" GENAU SO
    zerreisst. Es als Teiltreffer abzulehnen hiess, den haeufigsten Fall
    abzulehnen — siehe test_reale_verstuemmelungen_aus_dem_protokoll."""
    assert not enthaelt_wort(gesprochen, "Kimono")


def test_normalisierung_entfernt_diakritika():
    assert normalisiere("Männer, Öl!").split() == ["manner", "ol"]


def test_leeres_startwort_loest_nie_aus():
    assert not enthaelt_wort("irgendein Text", "")
    assert not enthaelt_wort("irgendein Text", "   ")


# -- Der Ablauf ------------------------------------------------------------------------


def test_startwort_startet_die_aufnahme():
    lau = _lauscher(text="also Kimono jetzt")
    assert lau.zustand is Zustand.LAUSCHT
    assert lau.verarbeite(block(1.0), jetzt=100.0) is Ereignis.START
    assert lau.zustand is Zustand.AUFNAHME


def test_ohne_startwort_passiert_nichts():
    lau = _lauscher(text="das ist ganz normales Gerede")
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None
    assert lau.zustand is Zustand.LAUSCHT


def test_stille_beendet_das_diktat():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "der eigentliche Diktattext"
    # Der EINGEHENDE Block ist still (beendet das Diktat), die GESAMMELTE
    # Aufnahme enthaelt aber Sprache — sonst wird sie seit 5.5.0 verworfen.
    lau._vad = lambda a: len(a) > 8000
    assert lau.verarbeite(block(0.5), jetzt=101.0) is None    # noch nicht lang genug
    assert lau.verarbeite(block(0.5), jetzt=103.5) is Ereignis.ENDE
    assert lau.zustand is Zustand.LAUSCHT


def test_sprechen_haelt_die_aufnahme_offen():
    """Eine Denkpause unter der Schwelle darf nicht abschneiden."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    for t in (101.0, 102.5, 104.0, 105.5):
        assert lau.verarbeite(block(0.3), jetzt=t) is None
    assert lau.zustand is Zustand.AUFNAHME


def test_abbruchwort_verwirft():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "das war Quatsch, Abbrechen"
    lau._vad = lambda a: False
    assert lau.verarbeite(block(0.5), jetzt=103.5) is Ereignis.ABBRUCH
    assert lau.statistik.verworfen == 1


def test_abbruchwort_startet_nicht_sofort_neu():
    """Sonst machte ein Versprecher daraus eine Endlosschleife."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "Abbrechen"
    lau._vad = lambda a: False
    lau.verarbeite(block(0.5), jetzt=103.5)
    assert lau.zustand is Zustand.LAUSCHT
    lau._erkenner = lambda a: "Kimono"
    lau._vad = lambda a: True
    assert lau.verarbeite(block(1.0), jetzt=103.6) is None


def test_startwort_landet_nicht_im_diktat():
    """Sonst stünde „Kimono" am Anfang jedes Textes."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    assert len(lau.aufnahme_audio()) == 0
    lau.verarbeite(block(0.5), jetzt=100.5)
    assert len(lau.aufnahme_audio()) == int(0.5 * SR)


# -- Die Sparsamkeit, die den Dauerbetrieb trägt ---------------------------------------


def test_ohne_sprache_laeuft_die_erkennung_gar_nicht():
    """Der Kern der Architektur: Das teure Modell bleibt aus, solange das billige
    VAD keine Sprache meldet."""
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: False,
                   erkenner=lambda a: gerufen.append(1) or "Kimono", samplerate=SR)
    lau.start_lauschen()
    for i in range(10):
        lau.verarbeite(block(1.0), jetzt=100.0 + i * 2)
    assert gerufen == []
    assert lau.statistik.pruefungen == 0


def test_pruefungen_werden_entzerrt():
    """Ohne Mindestabstand liefe tiny bei durchgehendem Sprechen permanent."""
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: gerufen.append(1) or "", samplerate=SR)
    lau.start_lauschen()
    for i in range(20):
        lau.verarbeite(block(0.1), jetzt=100.0 + i * 0.1)
    assert 1 <= len(gerufen) <= 4


def test_zu_wenig_material_wird_nicht_geprueft():
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: gerufen.append(1) or "", samplerate=SR)
    lau.start_lauschen()
    lau.verarbeite(block(0.3), jetzt=100.0)
    assert gerufen == []


def test_ringpuffer_waechst_nicht():
    """Die technische Zusicherung hinter „kein Mitschnitt": Es bleiben immer nur
    wenige Sekunden im Speicher."""
    lau = _lauscher(text="")
    for i in range(50):
        lau.verarbeite(block(1.0), jetzt=100.0 + i)
    assert len(lau._ring) <= int(2.0 * SR) + 1


# -- Schalter und Grenzen ---------------------------------------------------------------


def test_ausgeschaltet_verarbeitet_nichts():
    lau = Lauscher(Einstellungen(aktiv=False), vad=lambda a: True,
                   erkenner=lambda a: "Kimono", samplerate=SR)
    lau.start_lauschen()
    assert lau.zustand is Zustand.AUS
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None


def test_ausgeschlossene_apps():
    """In Spielen und Meetings ist Sprache im Raum die Regel."""
    lau = _lauscher(ausgeschlossene_apps=("game.exe", "Teams.exe"))
    assert lau.app_erlaubt("code.exe")
    assert not lau.app_erlaubt("game.exe")
    assert not lau.app_erlaubt("TEAMS.EXE")
    assert not lau.app_erlaubt("")


@pytest.mark.parametrize("eingabe,erwartet", [
    (0.2, 1.0), (1.0, 1.0), (2.0, 2.0), (4.0, 4.0), (9.0, 4.0), (None, 2.0),
])
def test_stille_dauer_bleibt_im_sinnvollen_bereich(eingabe, erwartet):
    assert Einstellungen(stille_s=eingabe).clamp().stille_s == erwartet


def test_fehler_in_den_stufen_legen_nichts_lahm():
    def kaputt(_a):
        raise RuntimeError("Modell weg")

    lau = Lauscher(Einstellungen(aktiv=True), vad=kaputt, erkenner=kaputt,
                   samplerate=SR)
    lau.start_lauschen()
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None


def test_statistik_zaehlt_mit():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    assert lau.statistik.aktivierungen == 1
    assert lau.statistik.pruefungen == 1
    assert "1 Aktivierungen" in lau.statistik.als_text()


# -- Verdrahtung in der App ------------------------------------------------------------


def test_einstellungen_haben_vernuenftige_vorgaben():
    """Standardmäßig AUS: Eine App, die ungefragt dauerhaft mithört, wäre ein
    Vertrauensbruch — auch wenn technisch nichts gespeichert wird."""
    from fleech.usersettings import UserSettings

    f = UserSettings().freihand
    assert f.aktiv is False
    assert f.startwort and len(f.startwort) >= 5     # mehrsilbig
    assert 1.0 <= f.stille_s <= 4.0


def test_der_strom_pausiert_statt_zu_sammeln():
    """Zwei gleichzeitig sammelnde Wege wären zwei konkurrierende Diktate."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    ereignisse = []
    strom = FreihandStream(lau, lambda e, a: ereignisse.append(e), samplerate=SR)
    strom.pausiere(True)
    strom._callback(block(1.0), 0, None, None)
    assert ereignisse == []

    strom.pausiere(False)
    strom._callback(block(1.0), 0, None, None)
    assert ereignisse == [Ereignis.START]


def test_pausieren_setzt_den_zustand_zurueck():
    """Ein halb gefüllter Ringpuffer aus der Zeit davor wäre beim Fortsetzen ein
    falscher Bezugspunkt."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    strom._callback(block(1.5), 0, None, None)
    assert len(lau._ring) > 0
    strom.pausiere(True)
    assert len(lau._ring) == 0


def test_fehler_im_audio_thread_reisst_nichts_mit():
    """Der Callback läuft im Audio-Thread — eine Ausnahme dort würde den Strom
    stilllegen und wäre nirgends sichtbar."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    def kaputt(e, a):
        raise RuntimeError("UI weg")

    strom = FreihandStream(lau, kaputt, samplerate=SR)
    strom._callback(block(1.0), 0, None, None)     # darf nicht werfen


def test_ende_liefert_das_gesammelte_audio():
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    gemeldet = []
    strom = FreihandStream(lau, lambda e, a: gemeldet.append((e, a)), samplerate=SR)
    strom._callback(block(1.0), 0, None, None)               # START
    strom._callback(block(1.0), 0, None, None)               # Diktat sammeln
    lau._erkenner = lambda a: "der Diktattext"
    # Gesammeltes Audio enthaelt Sprache, der letzte Block nicht mehr.
    lau._vad = lambda a: len(a) > 8000
    lau._letzte_sprache = -99                                 # Stille erzwingen
    strom._callback(block(0.5), 0, None, None)               # ENDE
    ereignis, audio = gemeldet[-1]
    assert ereignis is Ereignis.ENDE
    assert audio is not None and len(audio) > 0


# -- Mehrdeutige Geraetenamen (real aufgetreten) -----------------------------------------


def test_geraetename_wird_aufgeloest_statt_durchgereicht(monkeypatch):
    """DER Grund, warum Freihand beim Nutzer nie lief.

    Unter Windows meldet sich dasselbe Mikrofon einmal je Host-API. Ein Scarlett
    Solo taucht viermal auf (MME, DirectSound, WASAPI, WDM-KS). Gibt man den
    NAMEN an sounddevice, wirft es „Multiple input devices found" — der Strom
    startet nie, und Freihand bleibt stumm aus, unabhaengig vom Startwort.

    Der Hotkey-Weg loeste das laengst ueber `resolve_input_device`; hier fehlte es.
    """
    import types

    from fleech import freihand as fh

    geoeffnet = []

    class FakeStream:
        def __init__(self, **kw):
            geoeffnet.append(kw.get("device"))
            if isinstance(kw.get("device"), str):
                raise ValueError(
                    "Multiple input devices found for 'Mikrofon (Scarlett Solo USB)'")

        def start(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules, "sounddevice",
        types.SimpleNamespace(InputStream=FakeStream),
    )
    # Der Name loest auf Index 18 auf (WASAPI) — wie es audio.py tut.
    monkeypatch.setattr(fh_audio(), "resolve_input_device", lambda d: 18)

    lau = _lauscher(text="")
    strom = fh.FreihandStream(lau, lambda e, a: None,
                              geraet="Mikrofon (Scarlett Solo USB)", samplerate=SR)
    assert strom.start() is True
    assert geoeffnet == [18], f"nicht aufgeloest — an sounddevice ging {geoeffnet}"


def fh_audio():
    from fleech import audio

    return audio


def test_defektes_wunschmikrofon_faellt_auf_den_standard_zurueck(monkeypatch):
    """Ein abgezogenes Mikrofon soll Freihand nicht abschalten — der Hotkey-Weg
    wuerde in derselben Lage ebenfalls weiterlaufen."""
    import types

    from fleech import freihand as fh

    versuche = []

    class FakeStream:
        def __init__(self, **kw):
            versuche.append(kw.get("device"))
            if kw.get("device") is not None:
                raise OSError("Geraet weg")

        def start(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules, "sounddevice",
        types.SimpleNamespace(InputStream=FakeStream),
    )
    monkeypatch.setattr(fh_audio(), "resolve_input_device", lambda d: 7)

    lau = _lauscher(text="")
    strom = fh.FreihandStream(lau, lambda e, a: None, geraet="Weg.exe", samplerate=SR)
    assert strom.start() is True
    assert versuche == [7, None], "kein Rueckfall auf das Standardgeraet"


def test_wenn_gar_nichts_geht_meldet_start_ehrlich_fehl(monkeypatch):
    import types

    from fleech import freihand as fh

    class FakeStream:
        def __init__(self, **kw):
            raise OSError("kein Audio")

        def start(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules, "sounddevice",
        types.SimpleNamespace(InputStream=FakeStream),
    )
    monkeypatch.setattr(fh_audio(), "resolve_input_device", lambda d: None)

    lau = _lauscher(text="")
    strom = fh.FreihandStream(lau, lambda e, a: None, samplerate=SR)
    assert strom.start() is False
    assert strom.laeuft is False


def test_fehlschlag_wird_dem_nutzer_gemeldet():
    """Vorher stand der Fehlschlag NUR im Log — der Schalter blieb an, nichts
    passierte, und man sucht den Fehler beim Startwort."""
    import types

    from fleech.ui.desktop import DesktopApp

    getoastet = []
    tray_stand = []
    fake = types.SimpleNamespace(
        notifier=types.SimpleNamespace(
            toast=lambda *a, **kw: getoastet.append(a)),
        tray=types.SimpleNamespace(
            set_freihand=lambda an, wort: tray_stand.append(an)),
        settings=types.SimpleNamespace(
            freihand=types.SimpleNamespace(startwort="Kimono")),
    )
    DesktopApp._on_freihand_fehler(fake, "Mikrofon liess sich nicht oeffnen")

    assert getoastet, "keine sichtbare Meldung"
    assert any("Freihand" in str(a) for a in getoastet[0])
    assert tray_stand == [False], "Tray zeigt Freihand weiter als aktiv"


# -- Hoerfehler des kleinen Modells (gemessen) -------------------------------------------


@pytest.mark.parametrize("gehoert", [
    "Kimunno",                      # REAL vom Modell geliefert, im Satz gesprochen
    "Kimunno, schreibt das bitte auf.",
    "Kimano", "Kimon", "kimunno",
])
def test_verunglueckte_startwoerter_loesen_trotzdem_aus(gehoert):
    """Der Grund, warum Freihand im Alltag nicht ansprang.

    Gemessen: Sagt man „Kimono" allein, versteht das kleine Modell „Kimono".
    Sagt man „Kimono, schreib das bitte auf", wird daraus „Kimunno" — und der
    exakte Wortvergleich schlug fehl. Freihand loeste nie aus, obwohl alles
    richtig eingestellt war.
    """
    assert enthaelt_wort(gehoert, "Kimono")


@pytest.mark.parametrize("gehoert", [
    "Kimonos sind schön", "Ich mag Kimonoartiges",
])
def test_die_wortgrenzen_regel_bleibt(gehoert):
    """Diese Faelle durften noch nie ausloesen, und daran aendert die Unschaerfe
    nichts: Woerter, die mit dem GANZEN Startwort beginnen, sind eigene Woerter —
    keine Hoerfehler. Genau diese Trennung macht die Toleranz vertretbar."""
    assert not enthaelt_wort(gehoert, "Kimono")


@pytest.mark.parametrize("gehoert", [
    "Wir gehen ins Kino", "Das läuft in Mono", "Simon kommt später",
    "Simone hat angerufen", "Domino spielen", "ein Kilo Mehl",
    "die Kimme des Gewehrs", "Kimchi essen", "Kim ruft an",
])
def test_aehnliche_woerter_loesen_nicht_aus(gehoert):
    """An echten Woertern kalibriert: „Kino", „Mono", „Simon" und „Simone" liegen
    bei derselben Distanz wie der echte Hoerfehler „Kimunno". Die Distanz allein
    reicht deshalb NICHT — erst zusammen mit gleichem Wortanfang trennt es."""
    assert not enthaelt_wort(gehoert, "Kimono")


def test_kurze_startwoerter_bekommen_keine_unschaerfe():
    """Unter vier Zeichen laege jede Toleranz neben zu vielen echten Woertern."""
    assert enthaelt_wort("Kim ruft an", "Kim")          # exakt weiterhin ja
    assert not enthaelt_wort("Kind ruft", "Kim")
    assert not enthaelt_wort("Kiel ist schön", "Kim")


def test_unschaerfe_laesst_sich_abschalten():
    assert enthaelt_wort("Kimunno", "Kimono") is True
    assert enthaelt_wort("Kimunno", "Kimono", unscharf=False) is False


def test_erkanntes_wird_protokolliert(caplog):
    """Ohne diese Spur ist im Alltag nicht feststellbar, warum nichts passiert —
    man sieht nur Stille und verdaechtigt das Startwort."""
    import logging

    lau = _lauscher(text="also Kimono jetzt")
    with caplog.at_level(logging.INFO, logger="fleech.freihand"):
        lau.verarbeite(block(1.0), jetzt=100.0)

    zeilen = [r.getMessage() for r in caplog.records]
    assert any("Kimono jetzt" in z for z in zeilen), \
        f"das Gehoerte steht nicht im Protokoll: {zeilen}"
    assert any("TREFFER" in z for z in zeilen)


def test_auch_ein_nicht_treffer_wird_protokolliert(caplog):
    import logging

    lau = _lauscher(text="irgendein anderer Satz")
    with caplog.at_level(logging.INFO, logger="fleech.freihand"):
        lau.verarbeite(block(1.0), jetzt=100.0)

    zeilen = [r.getMessage() for r in caplog.records]
    assert any("kein Treffer" in z for z in zeilen), \
        f"Fehlversuche bleiben unsichtbar: {zeilen}"


# -- Was an der ECHTEN Stimme gemessen wurde ---------------------------------------------


@pytest.mark.parametrize("gehoert", [
    "Kimu", "Kimun.", "Kimu...", "Kimo no", "Kimo no.",
])
def test_reale_verstuemmelungen_aus_dem_protokoll(gehoert):
    """Nicht ausgedacht — so stand es im Protokoll, als „Kimono" ins Mikrofon
    gesprochen wurde. Das Modell SCHNEIDET ab („Kimu") und ZERREISST („Kimo no").

    Die erste Kalibrierung lief gegen TTS-Stimmen, wo das Wort viel sauberer
    ankam; sie war deshalb zu eng."""
    assert enthaelt_wort(gehoert, "Kimono")


@pytest.mark.parametrize("satz", [
    "Ich schreibe gerade an dem neuen Bericht.",
    "Wir waren im Kino und danach essen.",
    "Simone kommt später dazu.",
    "Mono oder Stereo ist mir egal.",
    "Die Kommode steht im Flur.",
    "Kim hat gestern angerufen.",
    "Komm mal bitte her.",
])
def test_normale_saetze_loesen_weiterhin_nicht_aus(satz):
    """Die erweiterte Toleranz darf nicht dazu fuehren, dass Freihand mitten im
    Gespraech anspringt."""
    assert not enthaelt_wort(satz, "Kimono")


# -- Aufnahme ohne Sprache (real: „G-G-G-G-…") -------------------------------------------


def test_aufnahme_ohne_sprache_wird_verworfen():
    """Real passiert: Startwort gesagt, auf eine Reaktion gewartet — die Aufnahme
    lief in die Stille. Aus zwei Sekunden Mikrofonrauschen halluzinierte Whisper
    „G-G-G-G-G-…" und das landete im Textfeld."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)          # START
    lau._erkenner = lambda a: ""                      # nichts gesprochen
    lau._vad = lambda a: False                        # VAD: keine Sprache
    ereignis = lau.verarbeite(block(0.5), jetzt=103.5)
    assert ereignis is Ereignis.ABBRUCH, "stilles Rauschen ging in die Pipeline"


def test_zu_kurze_aufnahme_wird_verworfen():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "ja"
    lau._vad = lambda a: False
    lau.verarbeite(block(0.2), jetzt=103.5)           # nur 0,2 s gesammelt
    assert lau.statistik.verworfen == 1


def test_echtes_diktat_geht_weiterhin_durch():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "der eigentliche Diktattext"
    # VAD meldet Sprache im gesammelten Audio → durchlassen
    lau._vad = lambda a: len(a) > 8000
    for t in (100.5, 101.0, 101.5):
        lau.verarbeite(block(0.5), jetzt=t)
    lau._vad = lambda a: len(a) > 8000
    ereignis = lau.verarbeite(block(0.5), jetzt=104.5)
    assert ereignis is Ereignis.ENDE
    assert len(lau.aufnahme_audio()) > 0
