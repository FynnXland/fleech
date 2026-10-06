"""Anstupsen: Tastendruck startet, die Sprechpause beendet.

Der Nachfolger des Freihand-Startworts. Der Wunsch dahinter war nie „mit der
Stimme starten", sondern „am Ende nicht wieder zur Tastatur greifen müssen" —
und nur diese Hälfte lässt sich zuverlässig bauen. Ein dauerhaft offenes
Mikrofon per Sprache zu triggern nicht: Im Protokoll standen Sätze aus einem
laufenden Video, und jeder Fehlstart tippt Text ins gerade fokussierte Fenster.
"""

import numpy as np

from fleech.stillewache import MIN_LAUFZEIT_S, Stillewache

SR = 16000


def audio(sekunden: float = 1.0) -> np.ndarray:
    return np.zeros(int(SR * sekunden), dtype=np.float32)


def _wache(sprache=True, stille_s=2.0):
    return Stillewache(vad=lambda a: sprache, stille_s=stille_s, samplerate=SR)


# -- Der Ablauf ------------------------------------------------------------------------


def test_stille_beendet_die_aufnahme():
    w = _wache(sprache=True)
    w.start(100.0)
    assert w.fertig(audio(), 102.0) is False          # es wird geredet
    w._vad = lambda a: False                          # jetzt still
    assert w.fertig(audio(), 103.0) is False          # noch keine 2 s
    assert w.fertig(audio(), 105.5) is True


def test_reden_haelt_die_aufnahme_offen():
    """Eine Denkpause unter der Schwelle darf nicht abschneiden."""
    w = _wache(sprache=True)
    w.start(100.0)
    for t in (102.0, 104.0, 106.0, 108.0):
        assert w.fertig(audio(), t) is False


def test_kurze_denkpause_setzt_die_uhr_zurueck():
    """Genau der Fall, der das Diktat sonst mitten im Satz abschneidet."""
    w = _wache(sprache=False, stille_s=2.0)
    w.start(100.0)
    assert w.fertig(audio(), 101.5) is False          # erst 1,5 s still
    w._vad = lambda a: True                           # er redet weiter
    assert w.fertig(audio(), 101.9) is False
    w._vad = lambda a: False
    assert w.fertig(audio(), 103.0) is False          # Uhr lief bei 101,9 neu an
    assert w.fertig(audio(), 104.0) is True


def test_mindestlaufzeit_schuetzt_den_start():
    """Wer die Taste drückt und einen Moment überlegt, soll nicht ins Leere laufen."""
    w = _wache(sprache=False, stille_s=1.0)
    w.start(100.0)
    assert w.fertig(audio(), 100.0 + MIN_LAUFZEIT_S - 0.1) is False
    assert w.fertig(audio(), 100.0 + MIN_LAUFZEIT_S + 1.1) is True


def test_ohne_start_passiert_nichts():
    w = _wache(sprache=False)
    assert w.fertig(audio(), 999.0) is False


def test_stop_beendet_die_ueberwachung():
    w = _wache(sprache=False, stille_s=1.0)
    w.start(100.0)
    w.stop()
    assert w.laeuft is False
    assert w.fertig(audio(), 200.0) is False


# -- Robustheit -------------------------------------------------------------------------


def test_ohne_vad_endet_nie_von_selbst():
    """Von zwei Fehlern der harmlosere: Die Taste beendet weiterhin. Andersherum
    (alles gilt als still) würde jedes Diktat sofort abgeschnitten."""
    w = Stillewache(vad=None, stille_s=1.0, samplerate=SR)
    w.start(100.0)
    assert w.fertig(audio(), 200.0) is False


def test_kaputtes_vad_schneidet_nicht_ab():
    def kaputt(a):
        raise RuntimeError("Modell weg")

    w = Stillewache(vad=kaputt, stille_s=1.0, samplerate=SR)
    w.start(100.0)
    assert w.fertig(audio(), 200.0) is False


def test_leeres_audio_beendet_nicht():
    w = Stillewache(vad=lambda a: False, stille_s=1.0, samplerate=SR)
    w.start(100.0)
    assert w.fertig(np.zeros(0, dtype=np.float32), 200.0) is False


def test_stille_s_wird_begrenzt():
    """Was ausserhalb liegt, wäre entweder ein Diktat, das nach jedem Wort endet,
    oder eines, das nie endet."""
    assert Stillewache(vad=None, stille_s=0.1).stille_s == 1.0
    assert Stillewache(vad=None, stille_s=99.0).stille_s == 6.0
    assert Stillewache(vad=None, stille_s=None).stille_s == 2.0


# -- Nur das Ende wird geprüft, nicht das ganze Diktat ----------------------------------


def test_nur_das_fenster_geht_ans_vad():
    """Die Wache läuft mehrmals pro Sekunde. Das ganze Diktat zu prüfen würde mit
    jeder Sekunde teurer — für eine Frage, die immer nur das Ende betrifft."""
    from fleech.freihand import VAD_FENSTER_S

    gesehen = []
    w = Stillewache(vad=lambda a: gesehen.append(len(a)) or True,
                    stille_s=2.0, samplerate=SR)
    w.start(100.0)
    w.fertig(audio(30.0), 102.0)
    assert gesehen == [int(VAD_FENSTER_S * SR)]


def test_fenster_stimmt_mit_dem_gemessenen_wert_ueberein():
    """NICHT frei gewählt: Auf 0,2 s meldet Silero nie Sprache (0 %), ab 1,0 s
    zu 100 %. Ein kleineres Fenster schneidet jedes Diktat nach `stille_s` ab —
    real passiert. Zwei Stellen mit demselben Wert würden auseinanderlaufen."""
    import fleech.stillewache as sw
    from fleech.freihand import VAD_FENSTER_S

    assert sw.VAD_FENSTER_S is VAD_FENSTER_S
    assert VAD_FENSTER_S >= 0.8


# -- Der Bedienmodus --------------------------------------------------------------------


def test_anstupsen_startet_per_druck_und_endet_per_druck():
    """Der zweite Druck muss weiterhin beenden — sonst hinge man fest, wenn die
    Stille-Erkennung mal nicht greift."""
    from fleech.recording_control import RecordingController

    ereignisse = []
    c = RecordingController("nudge", lambda k: ereignisse.append(("start", k)),
                            lambda k: ereignisse.append(("stop", k)))
    c.press("dictate")
    assert c.active and ereignisse == [("start", "dictate")]
    c.release("dictate")                      # Loslassen beendet NICHT
    assert c.active
    c.press("dictate")
    assert not c.active
    assert ereignisse[-1] == ("stop", "dictate")


def test_anstupsen_ist_ein_bekannter_modus():
    from fleech.recording_control import MODES, RecordingController

    assert "nudge" in MODES
    c = RecordingController("hold", lambda k: None, lambda k: None)
    c.set_mode("nudge")
    assert c.mode == "nudge"


def test_die_wache_stoppt_ueber_den_controller():
    """Sie ruft `stop_if_active()` — denselben Weg, den auch der Tray-Eintrag und
    das Overlay-Häkchen nehmen. Ein eigener Abkürzungspfad würde die Verarbeitung
    umgehen."""
    import inspect

    from fleech.ui.desktop import DesktopApp

    quelle = inspect.getsource(DesktopApp._nudge_tick)
    assert "stop_if_active()" in quelle
    assert 'mode != "nudge"' in quelle, "Tick muss in anderen Modi sofort aussteigen"


def test_pause_haelt_die_stille_uhr_an():
    """Pause heisst ausdrücklich „ich rede gerade woanders" — genau dann darf die
    Stille das Diktat nicht beenden."""
    import inspect

    from fleech.ui.desktop import DesktopApp

    quelle = inspect.getsource(DesktopApp._nudge_tick)
    assert "recorder.paused" in quelle


# -- Der Recorder liefert nur das Ende --------------------------------------------------


def test_recorder_tail_liefert_nur_die_letzten_sekunden():
    from fleech.audio import Recorder

    r = Recorder(samplerate=SR)
    r._capture_rate = SR
    r._frames = [np.full((SR // 5, 1), i, dtype=np.float32) for i in range(50)]
    ende = r.tail(1.0)
    assert len(ende) == SR
    # Die letzten 5 Blöcke à 0,2 s = Werte 45..49
    assert set(np.unique(ende)) == {45.0, 46.0, 47.0, 48.0, 49.0}


def test_recorder_tail_ohne_aufnahme():
    from fleech.audio import Recorder

    r = Recorder(samplerate=SR)
    assert len(r.tail(1.0)) == 0
    assert len(r.tail(0.0)) == 0


def test_recorder_tail_kopiert():
    """Dieselbe Falle wie bei Freihand: Ohne Kopie zeigt das Ergebnis auf den
    Puffer, den der Audio-Thread gleich überschreibt."""
    from fleech.audio import Recorder

    r = Recorder(samplerate=SR)
    r._capture_rate = SR
    block = np.ones((SR, 1), dtype=np.float32)
    r._frames = [block]
    ende = r.tail(1.0)
    block[:] = 0.0
    assert float(ende.max()) == 1.0


# -- Der Timer selbst (real abgestuerzt) -------------------------------------------------


def test_die_wache_laesst_sich_wirklich_aufbauen(qapp):
    """DER Fehler, der 5.8.0 beim Start zerlegt hat.

    `QTimer(self)` — aber `DesktopApp` ist kein QObject, sondern die schlichte
    Klasse, die alles verdrahtet. Der TypeError flog in `__init__`, also VOR dem
    ersten Fenster: Fleech startete gar nicht mehr.

    Die anderen Tests hier prüfen die Logik mit Attrappen und liefen deshalb alle
    grün. Was fehlte, war ein Test, der den Aufbau tatsächlich AUSFÜHRT.
    """
    import types

    from fleech.ui.desktop import DesktopApp

    getickt = []
    fake = types.SimpleNamespace(_nudge_tick=lambda: getickt.append(1))
    DesktopApp._starte_stille_wache(fake)
    try:
        assert fake._nudge_timer.isActive()
        assert fake._stillewache is None          # das VAD lädt erst bei Bedarf
        assert fake._stillewache_laedt is False
    finally:
        fake._nudge_timer.stop()


def test_kein_qtimer_mit_desktopapp_als_parent():
    """Wächter für dieselbe Falle an anderer Stelle: `DesktopApp` ist kein QObject,
    ein QTimer darf es also nie als Parent bekommen.

    Kommentare werden ausgeblendet — sonst schlägt der Wächter an der Stelle an,
    die den Fehler ERKLÄRT."""
    import inspect

    from fleech.ui import desktop

    code = [z for z in inspect.getsource(desktop).splitlines()
            if not z.strip().startswith("#")]
    treffer = [z.strip() for z in code if "QTimer(self)" in z]
    assert not treffer, f"QTimer(self) wirft — DesktopApp ist kein QObject: {treffer}"


# -- Ein Startfehler darf nicht unsichtbar sein ------------------------------------------


def test_startfehler_landet_im_protokoll_und_raeumt_die_hotkeys_ab():
    """Die Lehre aus dem 5.8.0-Absturz — es waren ZWEI Fehler.

    Der Traceback flog nur auf stderr; bei der gepackten EXE sieht dort niemand
    zu. Im Protokoll stand bloss, wie weit der Start gekommen war, und „Prozess
    läuft + keine ERROR-Zeile" sahen nach einem sauberen Lauf aus, während die
    App längst tot war.

    Und der Tastatur-Hook lief da schon: `HotkeyManager.start()` kommt früh in
    `__init__`. Bricht es danach ab, hängt ein Low-Level-Hook in einem halbtoten
    Prozess — beim Nutzer als „komische Tastatureingaben beim Starten".
    """
    import inspect

    from fleech.ui import desktop

    quelle = inspect.getsource(desktop.run_desktop)
    assert "log.exception" in quelle, "Startfehler geht nicht ins Protokoll"
    assert "HotkeyManager.stop_all()" in quelle, "Tastatur-Hook bleibt hängen"
    assert "bereit" in quelle, "Kein positiver Startmarker im Protokoll"


def test_stop_all_raeumt_jeden_laufenden_listener():
    from fleech.hotkey import HotkeyManager

    gestoppt = []

    class Attrappe(HotkeyManager):
        def stop(self):
            gestoppt.append(self)
            super().stop()

    a, b = (Attrappe(lambda n: None, lambda n: None) for _ in range(2))
    HotkeyManager._lebende[:] = [a, b]
    assert HotkeyManager.stop_all() == 2
    assert gestoppt == [a, b]
    assert HotkeyManager._lebende == []


def test_stop_all_ohne_listener_ist_harmlos():
    from fleech.hotkey import HotkeyManager

    HotkeyManager._lebende.clear()
    assert HotkeyManager.stop_all() == 0


# -- Nebenläufigkeit: GUI-Timer liest, während der Audio-Thread schreibt -----------------


def test_tail_liest_sauber_waehrend_der_audio_thread_schreibt():
    """Aus dem externen Gutachten (2026-08-05) als möglicher Torn Read gemeldet.

    Die Lage ist real: `_nudge_tick` läuft alle 300 ms im GUI-Thread und ruft
    `recorder.tail()`, während der PortAudio-Callback aus dem Audio-Thread neue
    Blöcke anhängt. Beide fassen `_frames` an.

    Der Befund selbst trifft nicht zu — `tail()` und `_callback` teilen sich
    `Recorder._lock`. Dieser Test hält das fest, statt es nur zu behaupten: Er
    lässt beide Seiten gegeneinander laufen und prüft, dass jedes gelesene
    Stück in sich stimmig ist (jeder Block trägt seine Nummer als Wert).
    """
    import threading

    from fleech.audio import Recorder

    r = Recorder(samplerate=SR)
    r._capture_rate = SR
    blockgroesse = SR // 5                      # 0,2 s wie im Betrieb
    fehler, laeuft = [], threading.Event()
    laeuft.set()

    def schreiber():
        n = 0
        while laeuft.is_set() and n < 400:
            n += 1
            with r._lock:
                r._frames.append(np.full((blockgroesse, 1), float(n), dtype=np.float32))
                r._samples += blockgroesse

    def leser():
        while laeuft.is_set():
            stueck = r.tail(1.0)
            if not len(stueck):
                continue
            # Jeder Wert muss eine ganze Blocknummer sein. Ein Torn Read (halb
            # geschriebener Block) oder eine Race auf der Liste zeigte sich hier
            # als Bruchzahl, als 0 mitten drin oder als Absturz.
            werte = np.unique(stueck)
            if not np.all(werte == np.floor(werte)) or np.any(werte <= 0):
                fehler.append(f"unstimmiges Stück: {werte[:5]}")

    faeden = [threading.Thread(target=schreiber), threading.Thread(target=leser)]
    for f in faeden:
        f.start()
    faeden[0].join(timeout=10)
    laeuft.clear()
    for f in faeden:
        f.join(timeout=5)

    assert not fehler, f"{len(fehler)} unstimmige Lesevorgänge: {fehler[:3]}"


def test_tail_und_callback_teilen_sich_dasselbe_schloss():
    """Wächter gegen den Rückfall: Würde `tail()` das Schloss verlieren, wäre der
    Test darüber je nach Zeitverhalten still — dieser hier nicht."""
    import inspect

    from fleech.audio import Recorder

    for name in ("tail", "_callback", "snapshot", "stop"):
        quelle = inspect.getsource(getattr(Recorder, name))
        assert "self._lock" in quelle, f"Recorder.{name} fasst _frames ohne Schloss an"
