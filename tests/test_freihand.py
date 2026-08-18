"""F1 — Freihand-Modus: Startwort sagen, sprechen, aufhören.

Die Zustandsmaschine kennt kein Audio-Gerät und kein Qt: Audio kommt herein,
Ereignisse kommen heraus. Damit ist der heikle Teil — wann startet, wann endet ein
Diktat — vollständig ohne Mikrofon prüfbar.
"""

import time

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


def speise(strom, audio) -> None:
    """Einen Block durch den Strom schicken — Callback UND Verarbeitung.

    Seit 5.7.0 sind das zwei Stufen: Der Audio-Callback legt nur ab, ein eigener
    Thread rechnet. Im Test wird die zweite Stufe direkt aufgerufen statt über
    den Thread — dieselbe Methode, nur ohne Warten.
    """
    strom._callback(audio, 0, None, None)
    strom.verarbeite_wartende()


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
    # Zwei Sekunden reden, damit die Aufnahme laenger ist als das VAD-Fenster.
    lau._vad = lambda a: True
    for i in range(10):
        lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2)
    # Jetzt Stille: Das 1,0-s-FENSTER gilt als still, die GESAMTE Aufnahme
    # (2 s) enthaelt aber Sprache — sonst wuerde sie als leer verworfen.
    lau._vad = lambda a: len(a) > int(1.5 * SR)
    assert lau.verarbeite(block(0.5), jetzt=102.6) is None    # noch nicht lang genug
    assert lau.verarbeite(block(0.5), jetzt=105.0) is Ereignis.ENDE
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
    # Genug Audio, damit die Anlaufzeit durch ist: Sie gilt, weil das VAD auf
    # weniger als seinem Fenster gar nichts melden KANN (siehe ANLAUF_S).
    assert lau.verarbeite(block(2.0), jetzt=103.5) is Ereignis.ABBRUCH
    assert lau.statistik.verworfen == 1


def test_abbruchwort_startet_nicht_sofort_neu():
    """Sonst machte ein Versprecher daraus eine Endlosschleife."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "Abbrechen"
    lau._vad = lambda a: False
    lau.verarbeite(block(2.0), jetzt=103.5)
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
    speise(strom, block(1.0))
    assert ereignisse == []

    strom.pausiere(False)
    speise(strom, block(1.0))
    assert ereignisse == [Ereignis.START]


def test_pausieren_setzt_den_zustand_zurueck():
    """Ein halb gefüllter Ringpuffer aus der Zeit davor wäre beim Fortsetzen ein
    falscher Bezugspunkt."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    speise(strom, block(1.5))
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
    speise(strom, block(1.0))     # darf nicht werfen


def test_ende_liefert_das_gesammelte_audio():
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    gemeldet = []
    strom = FreihandStream(lau, lambda e, a: gemeldet.append((e, a)), samplerate=SR)
    speise(strom, block(1.0))               # START
    for _ in range(3):
        speise(strom, block(1.0))           # 3 s Diktat sammeln
    lau._erkenner = lambda a: "der Diktattext"
    # Fenster (1 s) gilt als still, die Gesamtaufnahme (3 s) hat Inhalt.
    lau._vad = lambda a: len(a) > int(1.5 * SR)
    lau._letzte_sprache = -99                                 # Stille erzwingen
    speise(strom, block(0.5))               # ENDE
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
    ereignis = lau.verarbeite(block(2.0), jetzt=103.5)
    assert ereignis is Ereignis.ABBRUCH, "stilles Rauschen ging in die Pipeline"


def test_zu_kurze_aufnahme_wird_verworfen():
    """Über die Stille kann eine Aufnahme seit der Anlaufzeit nicht mehr so kurz
    enden — über den Fertig-Knopf der Pille schon. Genau dieser Weg wird hier
    geprüft: Wer sofort nach dem Startwort auf ✓ drückt, hat nichts gesagt."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "ja"
    lau._vad = lambda a: False
    lau.verarbeite(block(0.2), jetzt=100.2)           # nur 0,2 s gesammelt
    lau.beende_vorzeitig()
    lau.verarbeite(block(0.2), jetzt=100.4)
    assert lau.statistik.verworfen == 1


def test_echtes_diktat_geht_weiterhin_durch():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "der eigentliche Diktattext"
    lau._vad = lambda a: True                       # es wird geredet
    for i in range(10):
        lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2)
    # Fenster still, Gesamtaufnahme hat Inhalt → durchlassen
    lau._vad = lambda a: len(a) > int(1.5 * SR)
    ereignis = lau.verarbeite(block(0.5), jetzt=105.0)
    assert ereignis is Ereignis.ENDE
    assert len(lau.aufnahme_audio()) > 0


# -- Die Aufnahme darf nicht nach 2 Sekunden abbrechen ------------------------------------


def test_vad_bekommt_ein_fenster_nicht_nur_einen_block():
    """DER Grund, warum jedes Freihand-Diktat exakt 2,0 s lang war.

    Silero verlangt `min_speech_duration_ms=200` — genau die Blocklaenge des
    Stroms. Gemessen meldete es auf einem einzelnen 0,2-s-Block in 0 % der Faelle
    Sprache, ab 1,0 s in 100 %. Damit lief die Stille-Uhr durch, obwohl geredet
    wurde, und alles nach den ersten zwei Sekunden fehlte.
    """
    gesehen = []

    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)          # START
    lau._vad = lambda a: gesehen.append(len(a)) or True
    for i in range(8):
        lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2)

    assert gesehen, "das VAD wurde waehrend der Aufnahme gar nicht gefragt"
    groesstes = max(gesehen)
    assert groesstes > int(0.2 * SR), (
        f"VAD sieht nur {groesstes/SR:.1f} s — auf so wenig meldet Silero nie Sprache")


def test_langes_diktat_wird_nicht_abgeschnitten():
    """Wer nach dem Startwort zehn Sekunden redet, will zehn Sekunden Text."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "der Diktattext"
    lau._vad = lambda a: True                        # es wird durchgehend geredet

    jetzt = 100.2
    for _ in range(50):                              # 10 Sekunden
        assert lau.verarbeite(block(0.2), jetzt=jetzt) is None, \
            "Aufnahme endete mitten im Reden"
        jetzt += 0.2
    assert len(lau.aufnahme_audio()) / SR > 9.0


# -- Pegel fuer die Pille ------------------------------------------------------------------


def test_pegel_nur_waehrend_der_aufnahme():
    """Die Pille zeigte beim Freihand-Diktat eine tote Wellenlinie — ihr Pegel
    kommt vom Recorder, und der laeuft hier nicht.

    Beim blossen Lauschen bleibt der Pegel 0: Eine zappelnde Pille wuerde „es
    wird aufgenommen" behaupten, obwohl nur gewartet wird."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    laut = (np.ones(int(0.2 * SR), dtype=np.float32) * 0.3)

    speise(strom, laut)             # nur lauschen
    assert strom.level == 0.0

    lau.zustand = Zustand.AUFNAHME
    speise(strom, laut)
    assert strom.level > 0.2, "kein Pegel waehrend der Aufnahme"


def test_desktop_nimmt_den_hoeheren_pegel():
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(_freihand=types.SimpleNamespace(level=0.42))
    assert DesktopApp._freihand_level(fake) == pytest.approx(0.42)

    fake2 = types.SimpleNamespace(_freihand=None)
    assert DesktopApp._freihand_level(fake2) == 0.0

    kaputt = types.SimpleNamespace(_freihand=types.SimpleNamespace(level="Unsinn"))
    assert DesktopApp._freihand_level(kaputt) == 0.0


# -- Modellwahl ----------------------------------------------------------------------------


def test_pruefung_nimmt_vorgabegemaess_das_diktat_modell():
    """Ein eigenes kleines Modell war zweimal die falsche Wahl.

    Erst „tiny" (verstand „Kimono" als „Kimu"/„Gimo"), dann „base" — und base war
    schlimmer als gedacht: 437 ms Rechenzeit im Audio-Callback, gemessen 49,6 %
    Audioverlust. Das Diktat-Modell liegt ohnehin geladen da, braucht 141 ms und
    hört besser."""
    from fleech.usersettings import UserSettings

    assert UserSettings().freihand.modell == "diktat"


def test_alte_vorgabe_base_wird_beim_laden_umgestellt(tmp_path):
    """„base" war die kaputte VORGABE — wer sie nie angefasst hat, soll den
    reparierten Weg bekommen, ohne etwas einstellen zu müssen."""
    import json

    from fleech.usersettings import UserSettings

    pfad = tmp_path / "settings.json"
    pfad.write_text(json.dumps({"freihand": {"aktiv": True, "modell": "base"}}),
                    encoding="utf-8")
    assert UserSettings.load(pfad).freihand.modell == "diktat"


@pytest.mark.parametrize("gewaehlt", ["tiny", "small"])
def test_bewusste_modellwahl_bleibt_unangetastet(tmp_path, gewaehlt):
    """tiny und small stehen nie durch Vorgabe da — die hat jemand gewählt,
    vermutlich weil die Grafikkarte nichts taugt. Das darf keine Migration
    überschreiben."""
    import json

    from fleech.usersettings import UserSettings

    pfad = tmp_path / "settings.json"
    pfad.write_text(json.dumps({"freihand": {"modell": gewaehlt}}), encoding="utf-8")
    assert UserSettings.load(pfad).freihand.modell == gewaehlt


def test_modellwahl_ueberlebt_das_speichern(tmp_path, monkeypatch):
    import fleech.usersettings as us

    pfad = tmp_path / "settings.json"
    monkeypatch.setattr(us, "SETTINGS_PATH", pfad)
    s = us.UserSettings()
    s.freihand.modell = "small"
    s.save(pfad)
    assert us.UserSettings.load(pfad).freihand.modell == "small"


# -- Der Puffer von sounddevice wird wiederverwendet --------------------------------------


def test_bloecke_werden_kopiert_nicht_referenziert():
    """DER Bug, der Freihand die Diktate gekostet hat.

    sounddevice reicht in jedem Callback DENSELBEN Puffer herein und ueberschreibt
    ihn danach. Wer ihn nur referenziert, sammelt n-mal denselben Block ein. Weil
    die Aufnahme bei Stille endet, war dieser letzte Block still — das Diktat kam
    leer an. Wo doch etwas ankam, ergab derselbe Block aneinandergereiht ein
    periodisches Signal: daher „T-T-T-T-…" und „G-G-G-G-…" im Textfeld.

    Dieser Test bildet die Wiederverwendung nach: EIN Puffer, der zwischen den
    Callbacks seinen Inhalt wechselt.
    """
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)

    puffer = np.zeros(int(0.2 * SR), dtype=np.float32)   # DER wiederverwendete Puffer
    for _ in range(6):                                    # Ringpuffer fuellen (>0,8 s)
        speise(strom, puffer)
    assert lau.zustand is Zustand.AUFNAHME, "Startwort wurde nicht erkannt"

    for wert in (0.1, 0.2, 0.3, 0.4):
        puffer[:] = wert                                  # sounddevice ueberschreibt
        speise(strom, puffer)
    puffer[:] = 0.0                                       # letzter Block: Stille

    audio = lau.aufnahme_audio()
    werte = {round(float(v), 3) for v in np.unique(audio)}
    assert werte >= {0.1, 0.2, 0.3, 0.4}, (
        f"Aufnahme enthaelt nicht alle Bloecke, nur {sorted(werte)} — "
        f"die Bloecke wurden referenziert statt kopiert")


def test_aufnahme_ueberlebt_das_ueberschreiben_des_puffers():
    """Kurzfassung derselben Falle: Nach dem Callback darf das Ueberschreiben des
    Puffers die bereits gesammelten Daten nicht mehr veraendern."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    puffer = np.zeros(int(0.2 * SR), dtype=np.float32)
    for _ in range(6):
        speise(strom, puffer)           # START
    assert lau.zustand is Zustand.AUFNAHME

    puffer[:] = 0.5
    speise(strom, puffer)
    vorher = lau.aufnahme_audio().copy()
    puffer[:] = -0.9                                      # sounddevice schreibt neu
    assert np.array_equal(lau.aufnahme_audio(), vorher), \
        "das Ueberschreiben des Puffers hat die Aufnahme veraendert"


# -- Live-Vorschau beim Freihand-Diktat ----------------------------------------------------


def test_vorschau_findet_auch_das_freihand_audio():
    """Die Live-Vorschau hing allein am Recorder. Beim Freihand-Diktat laeuft der
    nicht — die Pille blieb stumm, und man wusste bis zum Ende nicht, ob
    ueberhaupt etwas ankommt."""
    import types

    from fleech.ui.desktop import DesktopApp

    leer = np.zeros(0, dtype=np.float32)
    diktat = np.ones(1600, dtype=np.float32) * 0.2

    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(snapshot=lambda: leer),
        _freihand=types.SimpleNamespace(
            lauscher=types.SimpleNamespace(aufnahme_audio=lambda: diktat)),
    )
    assert len(DesktopApp._laufendes_audio(fake)) == 1600


def test_hotkey_audio_hat_vorrang():
    """Laeuft eine normale Aufnahme, gilt deren Audio — nie ein Rest aus einem
    frueheren Freihand-Diktat."""
    import types

    from fleech.ui.desktop import DesktopApp

    eigenes = np.ones(800, dtype=np.float32)
    fremdes = np.ones(9999, dtype=np.float32)
    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(snapshot=lambda: eigenes),
        _freihand=types.SimpleNamespace(
            lauscher=types.SimpleNamespace(aufnahme_audio=lambda: fremdes)),
    )
    assert len(DesktopApp._laufendes_audio(fake)) == 800


def test_vorschau_ohne_freihand_bleibt_wie_bisher():
    import types

    from fleech.ui.desktop import DesktopApp

    leer = np.zeros(0, dtype=np.float32)
    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(snapshot=lambda: leer), _freihand=None)
    assert len(DesktopApp._laufendes_audio(fake)) == 0


# -- Der Audio-Thread darf nicht rechnen (der eigentliche Fehler bis 5.6.0) -------------


def test_der_callback_rechnet_nicht_mehr_selbst():
    """DER Fehler, der Freihand so schlecht hören ließ.

    Bis 5.6.0 lief die Zustandsmaschine — und damit Whisper — direkt im
    Audio-Callback. Gemessen an echter Hardware mit 200-ms-Blöcken: bei 440 ms
    Rechenzeit (das war `base` auf der CPU, Median 437 ms) kamen nur noch 49,6 %
    des Audios an. PortAudio wartet nicht; was während der Rechnung hereinkommt,
    fällt weg. Das Prüfmodell bekam Fetzen und halluzinierte „Ich bin hier."
    """
    import time

    from fleech.freihand import FreihandStream

    lau = _lauscher(text="Kimono")
    langsam = []

    def zaeher(audio):
        time.sleep(0.05)          # stellvertretend für 437 ms Whisper
        langsam.append(1)
        return "Kimono"

    lau._erkenner = zaeher
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)

    start = time.perf_counter()
    for _ in range(5):
        strom._callback(block(1.0), 0, None, None)
    dauer = time.perf_counter() - start

    assert langsam == [], "Der Callback hat die Erkennung angestoßen"
    assert dauer < 0.02, f"Callback brauchte {dauer*1000:.0f} ms — er muss frei bleiben"
    # Die Arbeit ist nicht weg, sie wartet nur woanders.
    assert strom.rueckstand() > 0
    strom.verarbeite_wartende()
    assert langsam, "Die Erkennung lief nie"


def test_zeitstempel_kommt_aus_dem_callback_nicht_aus_dem_arbeiter():
    """Sonst schnitte ein Rückstand jedes Diktat mitten im Satz ab.

    Der Arbeiter darf hinterherhängen — aber die Stille-Uhr muss den Moment
    messen, in dem das Audio ANKAM, nicht den, in dem es drankommt.
    """
    from fleech.freihand import FreihandStream

    gesehen = []
    lau = _lauscher(text="")
    lau.verarbeite = lambda b, jetzt=None: gesehen.append(jetzt)
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)

    strom._callback(block(0.2), 0, None, None)
    time.sleep(0.05)
    strom._callback(block(0.2), 0, None, None)
    time.sleep(0.05)                      # so lange hängt der Arbeiter zurück
    spaeter = time.monotonic()
    strom.verarbeite_wartende()

    assert len(gesehen) == 2
    assert all(t is not None for t in gesehen)
    assert gesehen[1] - gesehen[0] >= 0.04, "Der Abstand der Blöcke ging verloren"
    assert gesehen[-1] < spaeter, "Zeitstempel stammt aus dem Arbeiter statt vom Eingang"


def test_ueberlauf_verwirft_den_block_nicht_mehr():
    """`input_overflow` meldet, dass VOR diesem Block etwas verloren ging — der
    Block selbst ist gültig. Ihn wegzuwerfen (so war es) vergrößerte den Verlust."""
    import types

    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    strom._callback(block(0.2), 0, None, types.SimpleNamespace(input_overflow=True))
    assert strom.rueckstand() > 0


def test_warteschlange_hat_einen_deckel():
    """Ein dauerhaft zu langsames Modell darf den Speicher nicht auffressen."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    for _ in range(strom.WARTESCHLANGE_MAX + 40):
        strom._callback(block(0.2), 0, None, None)   # darf nicht werfen
    assert strom.rueckstand() <= strom.WARTESCHLANGE_MAX * strom.BLOCK_S
    assert strom._ueberlauf >= 40


def test_pausieren_wirft_wartende_bloecke_weg():
    """Sie stammen aus der Zeit VOR der Pause — beim Fortsetzen wären sie ein
    falscher Bezugspunkt, genau wie ein halb gefüllter Ringpuffer."""
    from fleech.freihand import FreihandStream

    lau = _lauscher(text="")
    strom = FreihandStream(lau, lambda e, a: None, samplerate=SR)
    for _ in range(3):
        strom._callback(block(0.2), 0, None, None)
    assert strom.rueckstand() > 0
    strom.pausiere(True)
    assert strom.rueckstand() == 0


# -- Welches Modell prüft? --------------------------------------------------------------


def test_erkenner_aus_engine_nutzt_das_geladene_modell():
    """Kein zweites Whisper daneben: Zwei gleichzeitig geladene Modelle waren
    schon einmal der Grund für ständige VRAM-Entladungen (siehe CLAUDE.md)."""
    import types

    from fleech.freihand import baue_erkenner_aus_engine

    gerufen = []
    engine = types.SimpleNamespace(
        transcribe_kurz=lambda audio, language=None, initial_prompt=None:
            gerufen.append((language, initial_prompt)) or "also Kimono jetzt")

    erkenne = baue_erkenner_aus_engine(engine, sprache="de", startwort="Kimono")
    assert erkenne(block(2.0)) == "also Kimono jetzt"
    assert gerufen == [("de", "Kimono.")], "Startwort wurde nicht vorgesagt"


def test_erkenner_aus_engine_reicht_auto_als_none_durch():
    """„auto" heißt: Whisper bestimmt die Sprache selbst. Als String übergeben
    würde faster-whisper danach eine Sprache namens „auto" suchen."""
    import types

    from fleech.freihand import baue_erkenner_aus_engine

    gesehen = []
    engine = types.SimpleNamespace(
        transcribe_kurz=lambda audio, language=None, initial_prompt=None:
            gesehen.append(language) or "")
    baue_erkenner_aus_engine(engine, sprache="auto", startwort="X")(block(1.0))
    assert gesehen == [None]


def test_ohne_startwort_wird_nichts_vorgesagt():
    """Ein leerer initial_prompt ist etwas anderes als keiner — faster-whisper
    würde einen leeren String als Kontext werten."""
    import types

    from fleech.freihand import baue_erkenner_aus_engine

    gesehen = []
    engine = types.SimpleNamespace(
        transcribe_kurz=lambda audio, language=None, initial_prompt=None:
            gesehen.append(initial_prompt) or "")
    baue_erkenner_aus_engine(engine, sprache="de", startwort="  ")(block(1.0))
    assert gesehen == [None]


def test_desktop_waehlt_das_diktat_modell_und_faellt_sauber_zurueck():
    """Fehlt das faster-whisper-Backend, darf Freihand nicht ausfallen — dann
    lieber ein eigenes kleines Modell als gar kein Freihand."""
    import types

    from fleech.ui.desktop import DesktopApp

    s = types.SimpleNamespace(modell="diktat", startwort="Kimono")
    allgemein = types.SimpleNamespace(
        settings=types.SimpleNamespace(general=types.SimpleNamespace(language="de")))

    # a) Engine kann es → Engine-Weg, ohne dass ein Modell geladen wird.
    mit = types.SimpleNamespace(
        **vars(allgemein),
        pipeline=types.SimpleNamespace(stt=types.SimpleNamespace(
            transcribe_kurz=lambda audio, language=None, initial_prompt=None: "Kimono")))
    assert DesktopApp._baue_startwort_erkenner(mit, s)(block(1.0)) == "Kimono"

    # b) Kein passendes Backend → Rückfall, ohne zu werfen.
    ohne = types.SimpleNamespace(**vars(allgemein),
                                 pipeline=types.SimpleNamespace(stt=None))
    gebaut = []
    import fleech.freihand as fh
    echt = fh.baue_erkenner
    fh.baue_erkenner = lambda **kw: gebaut.append(kw) or (lambda a: "")
    try:
        DesktopApp._baue_startwort_erkenner(ohne, s)
    finally:
        fh.baue_erkenner = echt
    assert gebaut and gebaut[0]["modell_groesse"] == "base"


def test_kurze_pruefung_und_diktat_teilen_sich_ein_schloss():
    """ctranslate2 ist nicht reentrant. Ohne Schloss liefen die Freihand-Prüfung
    (eigener Thread) und das Diktat gleichzeitig in dieselbe Modellinstanz."""
    import inspect

    from fleech.stt.faster_whisper_stt import FasterWhisperSTT

    for name in ("_run", "transcribe_kurz"):
        quelle = inspect.getsource(getattr(FasterWhisperSTT, name))
        assert "self._lock" in quelle, f"{name} läuft ohne Schloss"


def test_kurze_pruefung_schneidet_die_stille_weg():
    """Das Prüffenster ist 2 s lang, das Wort darin oft 0,4 s. Aus der Stille
    halluziniert Whisper („Vielen Dank.", „Ich bin hier.") und überdeckt damit,
    was wirklich gesagt wurde — echt aus dem Protokoll."""
    import inspect

    from fleech.stt.faster_whisper_stt import FasterWhisperSTT

    quelle = inspect.getsource(FasterWhisperSTT.transcribe_kurz)
    assert "vad_filter=True" in quelle
    assert "beam_size=1" in quelle


# -- Vorerst stillgelegt (5.10.1) --------------------------------------------------------


def test_freihand_ist_stillgelegt():
    """Auf ausdrückliche Anweisung abgeschaltet — der Riegel steht an EINER Stelle."""
    from fleech.freihand import STILLGELEGT

    assert STILLGELEGT is True


def test_der_riegel_greift_auch_bei_aktiv_true():
    """Eine bestehende settings.json mit `aktiv: true` darf ihn nicht umgehen —
    deshalb sitzt die Prüfung im Startpfad und nicht in der Oberfläche."""
    import inspect

    from fleech.ui.desktopapp.freihand import FreihandMixin

    quelle = inspect.getsource(FreihandMixin._starte_freihand)
    assert "STILLGELEGT" in quelle
    # Der Riegel muss VOR der aktiv-Abfrage stehen, sonst greift er nicht.
    assert quelle.index("STILLGELEGT") < quelle.index("freihand.aktiv")


def test_der_tray_schalter_meldet_sich_statt_stumm_zu_bleiben():
    """Der Eintrag steht im Tray; ein Klick ohne jede Rückmeldung liesse den
    Nutzer den Fehler beim Mikrofon suchen."""
    import inspect

    from fleech.ui.desktopapp.freihand import FreihandMixin

    quelle = inspect.getsource(FreihandMixin.toggle_freihand)
    assert "STILLGELEGT" in quelle and "_flash_status" in quelle


def test_der_riegel_laesst_sich_an_einer_stelle_loesen():
    """„Vorerst" heisst umkehrbar: Ein einziges False muss reichen, der Code
    bleibt vollständig erhalten."""
    from pathlib import Path

    quelle = Path("fleech/freihand.py").read_text(encoding="utf-8")
    # Genau eine Zuweisung, und die Zustandsmaschine kennt das Flag gar nicht —
    # sie ist weiterhin ohne Riegel testbar.
    assert quelle.count("STILLGELEGT = ") == 1
    assert "STILLGELEGT" not in quelle.split("class Lauscher")[1]


def test_das_tray_meldet_freihand_nicht_als_an_solange_es_stillgelegt_ist():
    """Befund E-8: Beim Start ging die gespeicherte Einstellung ungeprüft an das
    Tray — wer vor 5.10.1 `aktiv: true` stehen hatte, las dort „Freihand: an
    (Kimono)", während in Wirklichkeit nichts lauschte. Bei einer Funktion,
    deren ganzer Sinn Vertrauen ist, ist genau diese Richtung die schlimmere."""
    from pathlib import Path

    quelle = Path("fleech/ui/desktop.py").read_text(encoding="utf-8")
    assert "set_freihand(self.settings.freihand.aktiv and not STILLGELEGT" in quelle
