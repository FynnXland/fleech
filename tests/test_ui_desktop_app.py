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

def _undo_sofort(monkeypatch):
    """Den Worker-Thread des Rueckgaengig-Wegs synchron machen.

    Befund B-9/D-9: Die Backspaces laufen seit 5.10.4 in einem eigenen Thread —
    im pynput-Listener haetten sie bis zu 23 s lang alle weiteren Fleech-Hotkeys
    blockiert. Die Tests pruefen weiter dasselbe, nur ohne Wettlauf.
    """
    import fleech.ui.desktopapp.nachbereitung as nb

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(nb.threading, "Thread", SyncThread)

def _undo_fake(injected="Bereinigte Fassung.", raw="also die rohe fassung halt",
               alter_s=0.0, scope="dictated", busy=False):
    """Stellvertreter mit genau den Attributen, die _undo_last_output anfasst."""
    import threading
    import time as _t
    import types

    lock = threading.Lock()
    if busy:
        lock.acquire()
    aufrufe = {"replace": [], "record": [], "status": [], "sound": [], "sync": []}
    return types.SimpleNamespace(
        _undo_candidate=(injected, raw, _t.monotonic() - alter_s),
        _process_lock=lock,
        _UNDO_MAX_AGE_S=120,
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(
                replace_tail=lambda n, t: aufrufe["replace"].append((n, t))),
            tracker=types.SimpleNamespace(
                # Befund B-1/D-3: Das Fenster wird jetzt VOR der Wache nachgezogen.
                sync_window=lambda: aufrufe["sync"].append(True),
                resolve_scope=lambda s: scope,
                record_replace=lambda n, t: aufrufe["record"].append((n, t))),
        ),
        notifier=types.SimpleNamespace(sound=lambda k: aufrufe["sound"].append(k)),
        _flash_status=lambda t: aufrufe["status"].append(t),
        _aufrufe=aufrufe,
    )

def test_undo_ersetzt_die_ausgabe_durch_den_rohtext(qapp, monkeypatch):
    from fleech.ui.desktop import DesktopApp

    _undo_sofort(monkeypatch)
    fake = _undo_fake()
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["sync"] == [True]      # Fenster frisch abgeglichen

    assert fake._aufrufe["replace"] == [(len("Bereinigte Fassung."),
                                         "also die rohe fassung halt")]
    assert fake._aufrufe["record"] == fake._aufrufe["replace"]   # Tracker mitgezogen
    assert fake._undo_candidate is None                          # nur EIN Versuch

def test_undo_loescht_nichts_wenn_der_cursor_weg_ist(qapp, monkeypatch):
    """Kernsicherung: Nach einem Fensterwechsel ist unbekannt, wo der Cursor steht.
    Blind Backspaces zu senden hat schon einmal 2701 Zeichen vernichtet."""
    from fleech.ui.desktop import DesktopApp

    _undo_sofort(monkeypatch)
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

def test_undo_wartet_wenn_gerade_verarbeitet_wird(qapp, monkeypatch):
    """Waehrend ein Diktat eingefuegt wird, verschiebt sich die Zielstelle."""
    from fleech.ui.desktop import DesktopApp

    _undo_sofort(monkeypatch)
    fake = _undo_fake(busy=True)
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == []
    assert fake._undo_candidate is not None       # bleibt erhalten, nur verschoben


def test_undo_prueft_das_fenster_mit_dem_echten_tracker(qapp, monkeypatch):
    """Befund B-1/D-3: Die Wache hielt nach einem Fensterwechsel faelschlich.

    `resolve_scope` arbeitet auf dem Fenster, das der `DocumentTracker` zuletzt
    gesehen hat — nachgezogen wurde das NUR beim Verarbeiten eines Diktats, nie im
    Rueckgaengig-Weg. Wer nach einem Diktat das Fenster wechselte und den Hotkey
    drueckte, schickte dort so viele Backspaces, wie das Diktat lang war.

    Die uebrigen Undo-Tests reichen `scope` als Attrappe herein und pruefen damit
    nur, was passiert, WENN der Tracker None sagt — nicht, ob er es sagt. Deshalb
    hier der echte Tracker mit gefaelschtem Vordergrundfenster.
    """
    import threading
    import time as _t
    import types

    from fleech.document import DocumentTracker
    from fleech.ui.desktop import DesktopApp

    _undo_sofort(monkeypatch)
    vordergrund = {"hwnd": 1111}
    tracker = DocumentTracker()
    monkeypatch.setattr(tracker, "_foreground_window", lambda: vordergrund["hwnd"])
    monkeypatch.setattr(tracker, "_window_alive", lambda hwnd: True)
    tracker.sync_window()
    tracker.record_append("Bereinigte Fassung.")

    def lauf():
        aufrufe = {"replace": [], "status": []}
        fake = types.SimpleNamespace(
            _undo_candidate=("Bereinigte Fassung.", "also die rohe fassung halt",
                             _t.monotonic()),
            _process_lock=threading.Lock(),
            _UNDO_MAX_AGE_S=120,
            pipeline=types.SimpleNamespace(
                injector=types.SimpleNamespace(
                    replace_tail=lambda n, t: aufrufe["replace"].append((n, t))),
                tracker=tracker,
            ),
            notifier=types.SimpleNamespace(sound=lambda k: None),
            _flash_status=lambda t: aufrufe["status"].append(t),
        )
        DesktopApp._undo_last_output(fake)
        return aufrufe

    # Gleiches Fenster: der bestimmungsgemaesse Gebrauch laeuft.
    assert lauf()["replace"] == [(19, "also die rohe fassung halt")]

    vordergrund["hwnd"] = 2222          # der Nutzer ist woandershin gewechselt
    abgelehnt = lauf()
    assert abgelehnt["replace"] == []
    assert abgelehnt["status"] == ["Cursor nicht mehr an der Stelle"]


# -- Automatisch absenden je Profil (v3.10.0) --------------------------------------

def _diktat_lauf(profil, ergebnis="ok", last_mode="cleanup"):
    """Ein echtes `_process_locked` mit Attrappen ringsum.

    Bewusst der ECHTE Weg Profil → Desktop → Pipeline: Die Befunde E-2 und E-3
    konnten nur deshalb monatelang unbemerkt bleiben, weil die Tests die
    Bedingungen aus `_process_locked` abgeschrieben statt ausgefuehrt haben.
    Rueckgabe: (was die Pipeline an Argumenten sah, wurde Enter gedrueckt?)."""
    import types

    from fleech.ui.desktop import DesktopApp

    gesehen = {}
    gesendet = []

    def process(audio, samplerate, **kwargs):
        gesehen.update(kwargs)
        return ergebnis

    still = types.SimpleNamespace(emit=lambda *a: None)
    fake = types.SimpleNamespace(
        _app_profile_overrides=lambda: profil,
        _setze_sprache=lambda s: None,
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(command_enabled=True),
            general=types.SimpleNamespace(language="de", save_history=False),
        ),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        pipeline=types.SimpleNamespace(
            process=process, last_mode=last_mode, last_injected="Text",
            last_raw="roh", last_formulas=[], last_dropped_tail="",
            last_error_kind="", last_tier="", last_stt_ms=0, last_llm_ms=0,
            injector=types.SimpleNamespace(send_enter=lambda: gesendet.append(True)),
        ),
        bus=types.SimpleNamespace(
            injection_fallback=still, formula_preview=still, tail_dropped=still,
            transcript_ready=still, history_changed=still,
            set_state=lambda *a: None,
        ),
        notifier=types.SimpleNamespace(sound=lambda k: None,
                                       toast=lambda *a: None),
        _record_app="", _record_title="", _undo_candidate=None,
        _check_dictionary_candidates=lambda t: None,
        _count_dictionary_usage=lambda t: None,
        _flash_status=lambda t: None,
    )
    fake._auto_send = lambda: DesktopApp._auto_send(fake)
    DesktopApp._process_locked(fake, b"\x00" * 32)
    return gesehen, bool(gesendet)


def test_profilformat_stichpunkte_erreicht_die_pipeline(qapp):
    """Befund E-3: In `_process_locked` stand ein hartes ("email", "prompt").
    „Stichpunkte" kam spaeter dazu und fiel deshalb still auf normales Cleanup
    zurueck — in sechs Wochen Protokoll ist das Format ueber ein Profil kein
    einziges Mal gelaufen, obwohl die Pipeline es kann."""
    from fleech.profiles import PROFILE_FORMATS, ProfileOverrides, REWRITING_FORMATS

    for fmt, _label in PROFILE_FORMATS:
        gesehen, _ = _diktat_lauf(ProfileOverrides(mode_slot=fmt))
        erwartet = fmt if fmt in REWRITING_FORMATS else ""
        assert gesehen["output_format"] == erwartet, fmt

    # Der Fall, an dem es aufgefallen ist — ausdruecklich noch einmal einzeln.
    gesehen, _ = _diktat_lauf(ProfileOverrides(mode_slot="summary"))
    assert gesehen["output_format"] == "summary"


def test_autosend_nur_bei_erlaubtem_profil_und_normalem_diktat(qapp):
    """Enter nach dem Einfügen ist bequem in KI-Chats und fatal in E-Mails.
    Deshalb: nur wo das Profil es erlaubt, und nur nach einem NORMALEN Diktat —
    nach einem Befehl oder einem Rohtext-Rückfall will man erst sehen, was ankam.

    Befund E-2: Die Bedingung fragte nur `last_mode == "cleanup"`. Ausgerechnet
    im Profil „KI-Prompt", für das der Haken gedacht ist, feuerte er nie.
    """
    from fleech.profiles import ProfileOverrides

    def lauf(auto_send, result, mode):
        _, gesendet = _diktat_lauf(ProfileOverrides(auto_send=auto_send),
                                   ergebnis=result, last_mode=mode)
        return gesendet

    assert lauf(True, "ok", "cleanup") is True          # der gewollte Fall
    assert lauf(True, "ok", "prompt") is True           # E-2: der eigentliche Zweck
    assert lauf(True, "ok", "summary") is True
    assert lauf(True, "ok", "email") is False           # eine Mail nie von allein
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
        _freihand=None,   # kein Freihand-Diktat → der Recorder-Weg gilt
        # KEIN `overlay` — greift die Methode es doch an, wirft sie hier.
    )
    fake._freihand_lauscher = types.MethodType(DesktopApp._freihand_lauscher, fake)
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
        # Seit 5.8.3 fragt toggle_pause zuerst, ob ein FREIHAND-Diktat laeuft —
        # dort gibt es keinen Recorder, den man anhalten koennte.
        _freihand=None,
    )
    fake._freihand_lauscher = types.MethodType(DesktopApp._freihand_lauscher, fake)
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


# -- Geraetewechsel im laufenden Betrieb (Befund B-3) --------------------------------


def test_geraetewechsel_erneuert_den_guard_der_ihn_auch_liest(monkeypatch):
    """Befund B-3: Das frische Urteil landete auf `self.controller` — dem
    RecordingController, einer Klasse ohne dieses Feld. Es legte dort still ein
    Attribut an, das niemand liest; gewarnt wird ueber `AudioFocusController`.
    Folge: Wer im Betrieb auf „Stereomix" umstellte, bekam keine Warnung, und
    eine alte Warnung blieb bis zum Neustart stehen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.audiofocus import DeviceCheck, DeviceGuard

    # Kein echtes Audiogeraet befragen — hier zaehlt, WOHIN das Urteil geht.
    monkeypatch.setattr(DeviceGuard, "check", staticmethod(
        lambda device, blocklist: DeviceCheck(
            ok=False, name=str(device), reason="Loopback-/Mix-Geraet")))

    focus = types.SimpleNamespace(device_check=DeviceCheck(ok=True, name="alt"))
    fake = types.SimpleNamespace(
        focus=focus,
        controller=types.SimpleNamespace(),      # hat kein device_check — mit Absicht
        settings=types.SimpleNamespace(recording=types.SimpleNamespace(
            microphone="Stereomix", blocked_devices=["Stereomix"])),
        config=types.SimpleNamespace(audio_focus=types.SimpleNamespace(
            blocked_devices=[])),
        tray=types.SimpleNamespace(notify=lambda *a: None),
    )
    DesktopApp._recheck_input_device(fake)

    assert focus.device_check.ok is False        # die Warnung kommt dort an, wo sie zaehlt
    assert not hasattr(fake.controller, "device_check")
    assert fake.config.audio_focus.blocked_devices == ["Stereomix"]
    # Und der Guard, der das Urteil wirklich liest, meldet es auch.
    from fleech.audiofocus import AudioFocusController, FocusMode

    ctrl = AudioFocusController(FocusMode.PURE_MIC, None, focus.device_check)
    erlaubt, hinweis = ctrl.may_record()
    assert erlaubt is True and "WARNUNG" in hinweis


# -- Was aus dem pynput-Thread kommt, fasst keine Widgets an ------------------------


def test_ki_prompting_faerbt_die_pille_ueber_den_bus(qapp):
    """Befund D-6: `_toggle_prompt_oneshot` rief `overlay.set_prompt_latched`
    direkt — aus dem pynput-Listener-Thread. Das endet in `show()`, `hide()` und
    `update()` auf einem Qt-Widget; ein Thread-Verstoss wirft dort keine Ausnahme,
    er crasht spaeter irgendwo anders („wandernde access violation").

    Wie beim Pause-Hotkey laesst dieser Test das Overlay ganz weg — greift die
    Methode es doch an, wirft sie hier.
    """
    import types

    from fleech.ui.desktop import DesktopApp

    gemeldet, toene = [], []
    fake = types.SimpleNamespace(
        _prompt_oneshot=False,
        bus=types.SimpleNamespace(prompt_latch_changed=types.SimpleNamespace(
            emit=gemeldet.append)),
        notifier=types.SimpleNamespace(sound=toene.append),
        # KEIN `overlay`
    )
    DesktopApp._toggle_prompt_oneshot(fake)
    assert gemeldet == [True] and toene == ["start"]
    DesktopApp._toggle_prompt_oneshot(fake)
    assert gemeldet == [True, False] and toene == ["start", "stop"]


def test_aufnahmeende_meldet_den_prompt_latch_ueber_den_bus(qapp, monkeypatch):
    """Dieselbe Stelle ein zweites Mal: Im Hold-Modus kommt auch `_on_record_stop`
    aus dem pynput-Thread (Befund D-6)."""
    import types

    import fleech.ui.desktop as desktop_mod
    from fleech.ui.desktop import DesktopApp

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=(), kwargs=None):
            self._target, self._args, self._kwargs = target, args, kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(desktop_mod.threading, "Thread", SyncThread)
    gemeldet = []
    fake = types.SimpleNamespace(
        _last_dictation=0.0,
        _freihand=None,
        _stop_preview=lambda: None,
        focus=types.SimpleNamespace(on_recording_stop=lambda: None),
        recorder=types.SimpleNamespace(stop=lambda: b""),
        _prompt_oneshot=True,
        notifier=types.SimpleNamespace(sound=lambda n: None),
        bus=types.SimpleNamespace(
            prompt_latch_changed=types.SimpleNamespace(emit=gemeldet.append),
            set_state=lambda *a: None),
        _process=lambda audio, force_command=False, prompt_oneshot=False,
        abschnitte=None: None,
        # KEIN `overlay`
    )
    DesktopApp._on_record_stop(fake, "dictate")
    assert gemeldet == [False]


def test_verschwundenes_profil_wird_im_gui_thread_aufgeraeumt(qapp):
    """Befund D-7: `_app_profile_overrides` laeuft im VERARBEITUNGS-Thread und rief
    dort `_set_profile("")` — das schreibt die settings.json (ungeschuetzt aus dem
    Worker) und faerbt zwei Mal die Pille. Beides gehoert in den GUI-Thread."""
    import types

    from fleech.profiles import ProfileOverrides
    from fleech.ui.desktopapp.profil import ProfilMixin

    gemeldet = []
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="Geloeschtes Profil", items=[
                {"name": "E-Mail", "apps": ["outlook.exe"]},
            ])),
        bus=types.SimpleNamespace(profil_zuruecksetzen=types.SimpleNamespace(
            emit=lambda: gemeldet.append(True))),
        _record_app="outlook.exe", _record_title="",
        # KEIN `_set_profile`, KEIN `overlay` — ein direkter Zugriff wuerde werfen.
    )
    ergebnis = ProfilMixin._app_profile_overrides(fake)
    assert gemeldet == [True]
    assert ergebnis == ProfileOverrides()      # dieses eine Diktat laeuft neutral


def test_das_aufraeumen_selbst_setzt_auf_automatisch(qapp):
    """Gegenstueck im GUI-Thread — dort darf gespeichert und gefaerbt werden."""
    import types

    from fleech.ui.desktopapp.profil import ProfilMixin

    gesetzt = []
    fake = types.SimpleNamespace(_set_profile=gesetzt.append)
    ProfilMixin._on_profil_zuruecksetzen(fake)
    assert gesetzt == [""]


# -- Fehlgeschlagener Aufnahmestart (Befund D-10) ----------------------------------


def test_mikrofon_fehlstart_erzeugt_kein_geister_diktat(qapp):
    """Befund D-10: In den Abbruchzweigen stand `stop_if_active()`. Das laeuft den
    vollen Stopp-Weg — Stoppton, Zustand PROCESSING, Worker-Thread mit dem leeren
    Array aus `recorder.stop()`. Die Pipeline verwirft es („Aufnahme zu kurz
    (0.00 s)") und setzt IDLE „nichts erkannt" — und ueberschreibt damit die
    Fehlermeldung von drei Zeilen vorher. Im Protokoll 12-mal genau so.
    """
    import types

    from fleech.ui.desktop import DesktopApp

    ereignisse = []

    def start_geht_nicht():
        raise OSError("Geraet belegt")

    fake = types.SimpleNamespace(
        _license_ok=lambda: True,
        focus=types.SimpleNamespace(may_record=lambda math_mode=False: (True, "")),
        _freihand=None,
        recorder=types.SimpleNamespace(start=start_geht_nicht),
        controller=types.SimpleNamespace(
            cancel=lambda: ereignisse.append("cancel"),
            stop_if_active=lambda: ereignisse.append("stop_if_active")),
        bus=types.SimpleNamespace(
            set_state=lambda zustand, text="": ereignisse.append(("state", text))),
        sounds=types.SimpleNamespace(play=lambda n: None),
    )
    DesktopApp._on_record_start(fake, "dictate")
    assert ereignisse == [("state", "Mikrofon-Start fehlgeschlagen"), "cancel"]


# -- Beenden mitten in der Aufnahme (Befund D-5) -----------------------------------


def test_beenden_macht_fremde_apps_wieder_laut(qapp, monkeypatch):
    """Befund D-5: `_quit` rief `stop_if_active()` und direkt danach
    `QApplication.quit()`. Die Wiederherstellung laeuft aber nur als Daemon-Thread
    (Fade ~250 ms) — der Prozess war vorher weg. Nach dem ueblichen Deploy-Ablauf
    (beenden, kopieren, starten) blieben Discord und Spotify auf einem Viertel."""
    import types

    import fleech.ui.desktopapp.lebenszyklus as lz
    from fleech.ui.desktopapp.lebenszyklus import LebenszyklusMixin

    ablauf = []
    fake = types.SimpleNamespace(
        _stoppe_freihand=lambda: ablauf.append("freihand"),
        controller=types.SimpleNamespace(
            stop_if_active=lambda: ablauf.append("stop")),
        focus=types.SimpleNamespace(
            on_recording_stop=lambda: ablauf.append("lautstaerken")),
        settings=types.SimpleNamespace(save=lambda: ablauf.append("save")),
        hotkeys=types.SimpleNamespace(stop=lambda: ablauf.append("hotkeys")),
    )
    fake._stelle_lautstaerken_her = types.MethodType(
        LebenszyklusMixin._stelle_lautstaerken_her, fake)

    class FakeApp:
        @staticmethod
        def instance():
            return types.SimpleNamespace(quit=lambda: ablauf.append("quit"))

    monkeypatch.setattr(lz, "QApplication", FakeApp)
    LebenszyklusMixin._quit(fake)
    # Die Lautstaerken sind zurueck, BEVOR der Prozess geht.
    assert ablauf.index("lautstaerken") < ablauf.index("quit")
    assert ablauf == ["freihand", "stop", "lautstaerken", "save", "hotkeys", "quit"]


# -- Weggefallenes Mikrofon (Befund B-7) --------------------------------------------


def test_geraete_rueckfall_wird_einmal_gemeldet(qapp):
    """Befund B-7: Der Rueckfall auf den Systemstandard stand nur im Protokoll.
    Einmal je Geraet melden — bei jedem Diktat waere die Meldung selbst eine
    Stoerung — und die Statuszeile auf das Geraet setzen, das WIRKLICH aufnimmt."""
    import types

    from fleech.audiofocus import DeviceCheck
    from fleech.ui.desktopapp.lebenszyklus import LebenszyklusMixin

    meldungen = []
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(recording=types.SimpleNamespace(
            microphone="Mikrofon (Scarlett Solo USB)")),
        focus=types.SimpleNamespace(
            device_check=DeviceCheck(ok=True, name="Mikrofon (Scarlett Solo USB)")),
        _flash_status=meldungen.append,
    )
    melde = types.MethodType(LebenszyklusMixin._melde_mikrofon_rueckfall, fake)
    melde("Webcam-Mikrofon")
    assert len(meldungen) == 1
    assert "Scarlett" in meldungen[0] and "Webcam-Mikrofon" in meldungen[0]
    assert "Webcam-Mikrofon" in fake.focus.device_check.name   # Statuszeile
    melde("Webcam-Mikrofon")                    # dasselbe Geraet: nicht noch einmal
    assert len(meldungen) == 1


# -- Rueckgaengig blockiert den Hotkey-Thread nicht (Befund B-9/D-9) ----------------


def test_rueckgaengig_laeuft_im_worker_thread(qapp, monkeypatch):
    """Die Backspaces kosten 4 ms pro Zeichen — Median 1,3 s, im Maximum 23 s. So
    lange blockierte der pynput-Listener und damit JEDER weitere Fleech-Hotkey;
    wer in dieser Zeit den Diktat-Hotkey drueckte, verlor den Satzanfang."""
    import fleech.ui.desktopapp.nachbereitung as nb
    from fleech.ui.desktop import DesktopApp

    gestartet = []

    class ZaehlThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target, self._args = target, args
            gestartet.append(daemon)

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(nb.threading, "Thread", ZaehlThread)
    fake = _undo_fake()
    DesktopApp._undo_last_output(fake)
    assert gestartet == [True]                  # genau ein Daemon-Worker
    assert fake._aufrufe["replace"]             # und der macht die Arbeit


# -- Fehlende lokale KI (Befund E-13) ----------------------------------------------


def test_hinweis_auf_die_fehlende_lokale_ki_kommt_einmal(qapp):
    """Wer die Einfuehrung ueberspringt, hat keinen Ollama-Dienst — jedes Diktat
    kommt als Roh-Transkript an, sichtbar nur als „eingefügt (Fallback — Log
    prüfen)". Der Rueckweg stand nirgends. Einmal je Sitzung, nicht bei jedem
    Diktat: Wer den Hinweis kennt, will ihn nicht zwanzig Mal lesen."""
    import types

    from fleech.ui.desktopapp.modelle import ModelleMixin

    gemeldet = []
    fake = types.SimpleNamespace(
        bus=types.SimpleNamespace(progress=types.SimpleNamespace(emit=gemeldet.append)))
    melde = types.MethodType(ModelleMixin._melde_ki_offline, fake)
    melde()
    melde()
    assert len(gemeldet) == 1
    assert "Einführung erneut zeigen" in gemeldet[0]


def test_der_fallback_weg_fragt_nach_dem_grund(qapp):
    """Die Verdrahtung selbst: Nur bei „llm_offline" kommt der Einfuehrungs-Hinweis
    — ein abgeschnittener Cleanup oder eine leere Modellantwort ist etwas anderes."""
    import types

    from fleech.profiles import ProfileOverrides
    from fleech.ui.desktop import DesktopApp

    def lauf(grund):
        hinweise = []
        still = types.SimpleNamespace(emit=lambda *a: None)
        fake = types.SimpleNamespace(
            _app_profile_overrides=ProfileOverrides,
            _setze_sprache=lambda s: None,
            settings=types.SimpleNamespace(
                output=types.SimpleNamespace(command_enabled=True),
                general=types.SimpleNamespace(language="de", save_history=False)),
            config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
            pipeline=types.SimpleNamespace(
                process=lambda *a, **k: "fallback", last_mode="cleanup",
                last_injected="Text", last_raw="roh", last_formulas=[],
                last_dropped_tail="", last_error_kind=grund, last_tier="",
                last_stt_ms=0, last_llm_ms=0),
            bus=types.SimpleNamespace(
                injection_fallback=still, formula_preview=still, tail_dropped=still,
                transcript_ready=still, history_changed=still,
                set_state=lambda *a: None),
            notifier=types.SimpleNamespace(sound=lambda k: None,
                                           toast=lambda *a: None),
            _record_app="", _record_title="", _undo_candidate=None,
            _check_dictionary_candidates=lambda t: None,
            _count_dictionary_usage=lambda t: None,
            _melde_ki_offline=lambda: hinweise.append(True),
        )
        DesktopApp._process_locked(fake, b"\x00" * 32)
        return hinweise

    assert lauf("llm_offline") == [True]
    assert lauf("") == []


def test_nach_spielende_wird_nicht_sofort_nachgeladen(monkeypatch):
    """Alt-Tab aus dem Spiel ist kein Arbeitsbeginn.

    Im Log von 42 Tagen: 729 Neuladevorgaenge direkt nach einem Spiel-Entladen,
    im Median 40 s spaeter — jedes Mal rund 4 GB in die Grafikkarte, waehrend das
    Spiel noch offen war. Nur 249 von 849 Ladevorgaengen folgte ein Diktat."""
    import time as _t

    from fleech.ui.desktop import DesktopApp
    from fleech.ui.desktopapp.modelle import SPIELPAUSE_S

    fake, calls = _keep_warm_fake(monkeypatch)
    fake.settings.advanced.llm_keep_warm = "smart"
    fake._llms_unloaded = True
    fake._spiel_ende = _t.monotonic() - 40          # vor 40 s aus dem Spiel
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == []

    fake._spiel_ende = _t.monotonic() - (SPIELPAUSE_S + 1)   # laengere Pause
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]


def test_ohne_spiel_bleibt_das_warmhalten_wie_bisher(monkeypatch):
    """Die Sperre gilt NUR nach einem Spiel-Entladen — warm ist warm."""
    from fleech.ui.desktop import DesktopApp

    fake, calls = _keep_warm_fake(monkeypatch)
    fake.settings.advanced.llm_keep_warm = "smart"
    fake._llms_unloaded = False
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]


def test_vorschau_nimmt_modell_und_takt_aus_der_konfiguration(monkeypatch):
    """Bis 5.12.3 stand „small" fest im Code, und `interval_ms` aus config.yaml
    erreichte die Desktop-App nie — sie dekodierte mit 0,5 s statt dem
    konfigurierten Takt (20 818 Vorschau-Laeufe bei 454 Diktaten im Log)."""
    import types

    import fleech.overlay as overlay_mod
    from fleech.config import AppConfig
    from fleech.ui.desktop import DesktopApp

    gebaut = {}

    class FakeModell:
        def __init__(self, model_size, language, samplerate):
            gebaut["modell"] = model_size

        def load(self):
            pass

        def transcribe_segments(self, w):
            return []

    monkeypatch.setattr(overlay_mod, "PreviewModel", FakeModell)
    cfg = AppConfig()
    cfg.overlay.model_size = "tiny"
    fake = types.SimpleNamespace(settings=UserSettings(), config=cfg, _preview_model=None)
    DesktopApp._ensure_preview_model(fake)
    assert gebaut["modell"] == "tiny"


def test_waehrend_eines_diktats_wird_nicht_entladen(monkeypatch):
    """Im Log lag das Entladen siebenmal zwischen Spracherkennung und Bereinigung;
    die Bereinigung musste das Modell dann neu laden. Aufgeschoben heisst: Der
    naechste Takt darf es wieder versuchen."""
    import threading
    import types

    import fleech.ui.desktopapp.modelle as modelle_mod
    from fleech.ui.desktop import DesktopApp
    from fleech.ui.state import AppState

    entladen = []
    monkeypatch.setattr("fleech.llm.client.ollama_unload", entladen.append)

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr(modelle_mod.threading, "Thread", SyncThread)
    sperre = threading.Lock()
    fake = types.SimpleNamespace(_llms_unloaded=False, _process_lock=sperre,
                                 bus=types.SimpleNamespace(state=AppState.IDLE),
                                 _llm_endpoints=lambda: ["gemma"])
    sperre.acquire()
    DesktopApp._unload_llms_async(fake, "Spiel gestartet")
    assert entladen == [] and fake._llms_unloaded is False      # aufgeschoben

    sperre.release()
    DesktopApp._unload_llms_async(fake, "Spiel gestartet")
    assert entladen == ["gemma"] and fake._llms_unloaded is True


_GEMMA = __import__('types').SimpleNamespace(model='gemma3:4b')


def _ki_fake(monkeypatch, auf_cpu, stt_auf_cpu=False):
    import types

    import fleech.llm.client as client

    hinweise = []
    monkeypatch.setattr(client, "ollama_auf_cpu", lambda ep: auf_cpu())
    return types.SimpleNamespace(
        pipeline=types.SimpleNamespace(stt=types.SimpleNamespace(_on_cpu=stt_auf_cpu)),
        bus=types.SimpleNamespace(hinweis=types.SimpleNamespace(emit=hinweise.append)),
    ), hinweise


def test_ki_auf_dem_prozessor_wird_einmal_gemeldet(monkeypatch):
    """Ollama fand am 2026-10-02 nach einem Update die Grafikkarte nicht — jedes
    Diktat dauerte 13–27 s, und niemand sagte warum."""
    from fleech.ui.desktop import DesktopApp

    zustand = {"cpu": True}
    fake, hinweise = _ki_fake(monkeypatch, lambda: zustand["cpu"])
    DesktopApp._pruefe_ki_auf_grafikkarte(fake, _GEMMA)
    DesktopApp._pruefe_ki_auf_grafikkarte(fake, _GEMMA)
    assert len(hinweise) == 1 and "Prozessor" in hinweise[0]

    zustand["cpu"] = False                    # Ollama neu gestartet → wieder GPU
    DesktopApp._pruefe_ki_auf_grafikkarte(fake, _GEMMA)
    zustand["cpu"] = True                     # spaeterer Rueckfall
    DesktopApp._pruefe_ki_auf_grafikkarte(fake, _GEMMA)
    assert len(hinweise) == 2


def test_ohne_grafikkarte_kein_hinweis(monkeypatch):
    """Laeuft schon Whisper auf der CPU, gibt es keine Grafikkarte zu finden."""
    from fleech.ui.desktop import DesktopApp

    fake, hinweise = _ki_fake(monkeypatch, lambda: True, stt_auf_cpu=True)
    DesktopApp._pruefe_ki_auf_grafikkarte(fake, _GEMMA)
    assert hinweise == []
