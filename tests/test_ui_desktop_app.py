"""DesktopApp-Verdrahtung: Serialisierung, Warmhalten, Undo, Auto-Senden, Pause, Toene.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")

from fleech.usersettings import UserSettings


def test_overlapping_processings_are_serialized():
    """Zwei Diktat-Verarbeitungen duerfen sich nie ueberlappen — sonst schreiben beide
    auf denselben DocumentTracker und der Bezugspunkt fuer Safe-Word-Ersetzungen
    stimmt nicht mehr. Der zweite Lauf wartet, statt parallel zu starten."""
    import threading
    import time as _t
    import types

    from fleech.ui.desktop import DesktopApp

    events = []
    fake = types.SimpleNamespace(
        _process_lock=threading.Lock(),
        _llms_unloaded=False,
        bus=types.SimpleNamespace(
            progress=types.SimpleNamespace(emit=lambda _t: None),
        ),
    )

    def slow(audio, math_mode, force_command=False, math_jobs=None,
             prompt_oneshot=False):
        events.append(("start", audio))
        _t.sleep(0.15)
        events.append(("ende", audio))

    fake._process_locked = slow
    run = lambda tag: DesktopApp._process(fake, tag, False)

    threads = [threading.Thread(target=run, args=(tag,)) for tag in ("A", "B")]
    threads[0].start()
    _t.sleep(0.03)          # B startet, waehrend A noch laeuft
    threads[1].start()
    for th in threads:
        th.join()

    # Streng abwechselnd start/ende — kein verschachteltes start,start,ende,ende.
    assert [e[0] for e in events] == ["start", "ende", "start", "ende"]
    assert events[0][1] == events[1][1]      # A vollstaendig vor B
    assert events[2][1] == events[3][1]

def _keep_warm_fake(monkeypatch, gaming: bool = False):
    """Fake-DesktopApp fuer die Warmhalte-/Entlade-Tests (synchrone Threads)."""
    import time as _t
    import types

    import fleech.ui.desktop as desktop_mod
    from fleech.ui.desktop import DesktopApp

    calls = {"warm": [], "unload": []}

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(desktop_mod.threading, "Thread", SyncThread)

    fake = types.SimpleNamespace(
        settings=UserSettings(),
        _last_dictation=_t.monotonic(),
        _keep_llm_warm=lambda: calls["warm"].append(1),
        _unload_llms_async=lambda reason: calls["unload"].append(reason),
        notifier=types.SimpleNamespace(
            context=object(),
            policy=types.SimpleNamespace(gaming_active=lambda ctx: gaming),
        ),
    )
    fake._idle_unload_window_s = types.MethodType(
        DesktopApp._idle_unload_window_s, fake
    )
    return fake, calls

def test_keep_warm_tick_respects_mode(monkeypatch):
    """Smart-Warmhaltung: Tick haelt nur innerhalb des (einstellbaren) Idle-Fensters
    warm; danach wird AKTIV entladen (RAM frei). "off" nie, "always" immer."""
    import time as _t

    from fleech.ui.desktop import DesktopApp

    fake, calls = _keep_warm_fake(monkeypatch)

    fake.settings.advanced.llm_keep_warm = "off"
    DesktopApp._keep_warm_tick(fake)
    assert calls == {"warm": [], "unload": []}

    fake.settings.advanced.llm_keep_warm = "smart"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]              # frisch aktiv → warmhalten

    window = fake.settings.advanced.llm_idle_unload_minutes * 60
    fake._last_dictation = _t.monotonic() - (window + 60)
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]              # Idle-Fenster abgelaufen → nicht warmhalten
    assert calls["unload"] == ["Leerlauf"]   # … sondern AKTIV entladen

    fake.settings.advanced.llm_keep_warm = "always"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1, 1]           # dauerhaft: unabhaengig vom Fenster

def test_idle_unload_window_reads_setting():
    """Das Idle-Fenster kommt aus der Einstellung (Minuten → Sekunden), 0 erlaubt."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(settings=UserSettings())
    fake.settings.advanced.llm_idle_unload_minutes = 3
    assert DesktopApp._idle_unload_window_s(fake) == 180
    fake.settings.advanced.llm_idle_unload_minutes = 45
    assert DesktopApp._idle_unload_window_s(fake) == 2700

def test_keep_warm_tick_unloads_while_gaming(monkeypatch):
    """Laeuft ein Spiel (Gaming-Erkennung), entlaedt der Smart-Modus die Modelle
    SOFORT — auch mitten im Aktivitaets-Fenster. RAM zaehlt beim Zocken."""
    from fleech.ui.desktop import DesktopApp

    fake, calls = _keep_warm_fake(monkeypatch, gaming=True)
    fake.settings.advanced.llm_keep_warm = "smart"
    DesktopApp._keep_warm_tick(fake)         # letztes Diktat gerade eben — egal: Spiel!
    assert calls["warm"] == []
    assert calls["unload"] == ["Spiel erkannt"]

    # "always" respektiert den ausdruecklichen Nutzerwunsch (kein Auto-Entladen).
    fake.settings.advanced.llm_keep_warm = "always"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]

def test_unload_llms_async_is_idempotent(monkeypatch):
    """Nach einem Entladen feuert der 4-min-Tick nicht weiter Requests gegen ein
    ohnehin leeres Ollama; erst ein Aufwaermen erlaubt das naechste Entladen."""
    import types

    import fleech.ui.desktop as desktop_mod
    from fleech.ui.desktop import DesktopApp

    unloads = []

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(desktop_mod.threading, "Thread", SyncThread)
    import fleech.llm.client as client_mod
    monkeypatch.setattr(client_mod, "ollama_unload", lambda ep: unloads.append(ep))

    fake = types.SimpleNamespace(
        _llms_unloaded=False,
        _llm_endpoints=lambda: ["ep1", "ep2"],
    )
    DesktopApp._unload_llms_async(fake, "Test")
    assert unloads == ["ep1", "ep2"]
    DesktopApp._unload_llms_async(fake, "Test")   # zweiter Aufruf: No-op
    assert unloads == ["ep1", "ep2"]
    assert fake._llms_unloaded is True

def test_sound_synthesis_all_events_and_presets():
    from fleech.ui.sounds import _build_preset

    for preset in ("soft", "click"):
        samples = _build_preset(preset)
        assert set(samples) == {"start", "stop", "commit", "error"}
        for name, arr in samples.items():
            assert 0 < arr.size < 44100  # kurz (<1 s) und nicht leer
            assert abs(float(arr.max())) <= 1.3

def test_sound_player_respects_switches(monkeypatch):
    import sounddevice

    from fleech.ui.sounds import SoundPlayer

    played = []
    monkeypatch.setattr(sounddevice, "play", lambda *a, **k: played.append(a))

    s = UserSettings().sounds
    player = SoundPlayer(s)
    player.play("start")
    assert len(played) == 1  # aktiviert → gespielt

    s.commit = False
    player.play("commit")    # einzeln deaktiviert → still
    assert len(played) == 1

    s.enabled = False
    player.play("start")     # global aus → still
    assert len(played) == 1

    s.enabled = True
    s.volume = 0.0
    player.play("stop")      # Lautstaerke 0 → still
    assert len(played) == 1

def _undo_fake(injected="Bereinigte Fassung.", raw="also die rohe fassung halt",
               alter_s=0.0, scope="dictated", busy=False):
    """Stellvertreter mit genau den Attributen, die _undo_last_output anfasst."""
    import threading
    import time as _t
    import types

    lock = threading.Lock()
    if busy:
        lock.acquire()
    aufrufe = {"replace": [], "record": [], "status": [], "sound": []}
    return types.SimpleNamespace(
        _undo_candidate=(injected, raw, _t.monotonic() - alter_s),
        _process_lock=lock,
        _UNDO_MAX_AGE_S=120,
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(
                replace_tail=lambda n, t: aufrufe["replace"].append((n, t))),
            tracker=types.SimpleNamespace(
                resolve_scope=lambda s: scope,
                record_replace=lambda n, t: aufrufe["record"].append((n, t))),
        ),
        notifier=types.SimpleNamespace(sound=lambda k: aufrufe["sound"].append(k)),
        _flash_status=lambda t: aufrufe["status"].append(t),
        _aufrufe=aufrufe,
    )

def test_undo_ersetzt_die_ausgabe_durch_den_rohtext(qapp):
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake()
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == [(len("Bereinigte Fassung."),
                                         "also die rohe fassung halt")]
    assert fake._aufrufe["record"] == fake._aufrufe["replace"]   # Tracker mitgezogen
    assert fake._undo_candidate is None                          # nur EIN Versuch

def test_undo_loescht_nichts_wenn_der_cursor_weg_ist(qapp):
    """Kernsicherung: Nach einem Fensterwechsel ist unbekannt, wo der Cursor steht.
    Blind Backspaces zu senden hat schon einmal 2701 Zeichen vernichtet."""
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(scope=None)
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == []
    assert fake._undo_candidate is None          # verfaellt, statt es spaeter zu wagen

def test_undo_verfaellt_nach_zwei_minuten(qapp):
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(alter_s=200)
    DesktopApp._undo_last_output(fake)
    assert fake._aufrufe["replace"] == []

def test_undo_ohne_kandidat_und_bei_gleichem_text(qapp):
    """Nichts zu tun ist kein Fehler — aber es darf auch nichts passieren."""
    from fleech.ui.desktop import DesktopApp

    leer = _undo_fake()
    leer._undo_candidate = None
    DesktopApp._undo_last_output(leer)
    assert leer._aufrufe["replace"] == []

    gleich = _undo_fake(injected="Gleicher Text.", raw="Gleicher Text.")
    DesktopApp._undo_last_output(gleich)
    assert gleich._aufrufe["replace"] == []

def test_undo_wartet_wenn_gerade_verarbeitet_wird(qapp):
    """Waehrend ein Diktat eingefuegt wird, verschiebt sich die Zielstelle."""
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(busy=True)
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == []
    assert fake._undo_candidate is not None       # bleibt erhalten, nur verschoben


# -- Automatisch absenden je Profil (v3.10.0) --------------------------------------

def test_autosend_nur_bei_erlaubtem_profil_und_normalem_diktat(qapp):
    """Enter nach dem Einfügen ist bequem in KI-Chats und fatal in E-Mails.
    Deshalb: nur wo das Profil es erlaubt, und nur nach einem NORMALEN Diktat —
    nach einem Befehl oder einem Rohtext-Rückfall will man erst sehen, was ankam.
    """
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.profiles import ProfileOverrides

    def lauf(auto_send, result, mode):
        gesendet = []
        fake = types.SimpleNamespace(
            pipeline=types.SimpleNamespace(
                injector=types.SimpleNamespace(
                    send_enter=lambda: gesendet.append(True)),
                last_mode=mode),
            _flash_status=lambda t: None,
        )
        prof = ProfileOverrides(auto_send=auto_send)
        # Dieselbe Bedingung wie in _process_locked.
        if prof.auto_send and result == "ok" and fake.pipeline.last_mode == "cleanup":
            DesktopApp._auto_send(fake)
        return bool(gesendet)

    assert lauf(True, "ok", "cleanup") is True          # der gewollte Fall
    assert lauf(False, "ok", "cleanup") is False        # Profil erlaubt es nicht
    assert lauf(True, "fallback", "cleanup") is False   # Rohtext-Rückfall
    assert lauf(True, "ok", "command") is False         # war ein Befehl

def test_autosend_fehler_macht_das_diktat_nicht_kaputt(qapp):
    """Der Text steht bereits im Feld — scheitert nur das Enter, ist das Diktat
    trotzdem geglückt und darf nicht als Fehler enden."""
    import types

    from fleech.ui.desktop import DesktopApp

    meldungen = []
    fake = types.SimpleNamespace(
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(
                send_enter=lambda: (_ for _ in ()).throw(RuntimeError("kein Zugriff"))),
            last_mode="cleanup"),
        _flash_status=meldungen.append,
    )
    DesktopApp._auto_send(fake)                 # darf NICHT werfen
    assert meldungen and "Absenden" in meldungen[0]

def test_autosend_standardmaessig_aus():
    """Ein neues Profil sendet nie von allein — die Einstellung ist bewusst opt-in."""
    from fleech.profiles import ProfileOverrides

    assert ProfileOverrides().auto_send is False


# -- Kaltstart-Einrichtung (Seite in der Einfuehrung) --------------------------------

def test_hotkey_pfade_fassen_keine_widgets_an():
    """Alles, was der pynput-Thread ausloest, laeuft ueber den StateBus.

    Grund ist ein echter Aufhaenger: der Lizenz-Dialog wurde direkt im
    Listener-Thread gebaut und die App stand. Derselbe Fehler steckte leiser im
    Pause-Hotkey (`overlay.set_paused` direkt). Beide Wege sind jetzt Signale —
    dieser Test haelt das fest, indem er das Overlay ganz weglaesst."""
    import types

    from fleech.ui.desktop import DesktopApp

    geschaltet, toene = [], []
    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(
            recording=True, paused=False,
            pause=lambda: setattr(fake.recorder, "paused", True),
            resume=lambda: setattr(fake.recorder, "paused", False)),
        bus=types.SimpleNamespace(paused_changed=types.SimpleNamespace(
            emit=lambda wert: geschaltet.append(wert))),
        notifier=types.SimpleNamespace(sound=lambda n: toene.append(n)),
        # KEIN `overlay` — greift die Methode es doch an, wirft sie hier.
    )
    DesktopApp.toggle_pause(fake)
    assert geschaltet == [True] and toene == ["stop"]
    DesktopApp.toggle_pause(fake)
    assert geschaltet == [True, False] and toene == ["stop", "start"]

def _pause_fake(recording=True, paused=False):
    import types

    from fleech.ui.desktop import DesktopApp

    zustand = {"paused": paused}
    protokoll = []

    class FakeRecorder:
        """`paused` muss LIVE gelesen werden — toggle_pause fragt es zweimal ab
        (vor der Entscheidung und danach fuer die Anzeige)."""

        def __init__(self):
            self.recording = recording

        @property
        def paused(self):
            return zustand["paused"]

        def pause(self):
            zustand["paused"] = True
            protokoll.append("pause")

        def resume(self):
            zustand["paused"] = False
            protokoll.append("resume")

    recorder = FakeRecorder()
    fake = types.SimpleNamespace(
        recorder=recorder,
        # Ueber den Bus, nicht direkt ans Overlay: der Pause-Hotkey feuert im
        # pynput-Thread (siehe test_hotkey_pfade_fassen_keine_widgets_an).
        bus=types.SimpleNamespace(paused_changed=types.SimpleNamespace(
            emit=lambda p: protokoll.append(f"overlay:{p}"))),
        notifier=types.SimpleNamespace(sound=lambda n: protokoll.append(f"sound:{n}")),
    )
    return DesktopApp.toggle_pause, fake, protokoll

def test_toggle_pause_haelt_an_und_setzt_fort():
    toggle, fake, protokoll = _pause_fake()
    toggle(fake)
    assert protokoll == ["pause", "overlay:True", "sound:stop"]
    protokoll.clear()
    toggle(fake)
    assert protokoll == ["resume", "overlay:False", "sound:start"]

def test_toggle_pause_ohne_aufnahme_tut_nichts():
    """Ein „Pause" im Leerlauf haette keinen Zustand zum Fortsetzen."""
    toggle, fake, protokoll = _pause_fake(recording=False)
    toggle(fake)
    assert protokoll == []

def test_pause_hotkey_nur_waehrend_der_aufnahme(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp

    gerufen = []
    fake = types.SimpleNamespace(
        controller=types.SimpleNamespace(active=True, press=lambda n: None),
        recorder=types.SimpleNamespace(recording=True),
        toggle_pause=lambda: gerufen.append(True),
    )
    DesktopApp._on_hotkey_activate(fake, "pause")
    assert gerufen == [True]

    fake.recorder = types.SimpleNamespace(recording=False)
    DesktopApp._on_hotkey_activate(fake, "pause")
    assert gerufen == [True]                     # ausserhalb bleibt die Taste frei

def test_pause_hotkey_ist_belegt_und_konfigurierbar():
    from fleech.usersettings import RecordingSettings

    s = RecordingSettings()
    assert s.pause_hotkey == "ctrl+alt+space"
    s.pause_hotkey = ""                          # loeschbar wie die anderen
    assert s.pause_hotkey == ""


# -- Pause in der Pille -------------------------------------------------------------
