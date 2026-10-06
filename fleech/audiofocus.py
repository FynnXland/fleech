"""Audio-Fokus-Modus: Playback-Ducking + Capture-Guard, strikt getrennt.

Architektur-Invariante (nicht verhandelbar):
- CAPTURE: ausschliesslich das gewaehlte Mikrofon ueber sounddevice.InputStream
  (fleech/audio.py). Es existiert kein Code-Pfad, der WASAPI-Loopback, Stereo Mix
  oder Systemaudio in die Transkription mischt. Der DeviceGuard verhindert
  zusaetzlich, dass der Nutzer versehentlich ein Loopback-artiges Geraet waehlt.
- PLAYBACK: pycaw steuert die Session-Lautstaerken FREMDER Prozesse (ISimpleAudioVolume)
  fuer weiches Ducking. Das ist reine Ausgabe-Steuerung; es fliesst kein Audio zurueck.

Alles hier ist Best-Effort: Ein Fehler beim Ducken darf das Diktat niemals stoeren.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class FocusMode(Enum):
    PURE_MIC = "pure_mic"      # kein Ducking, nur Mic-only-Garantie
    SOFT_DUCK = "soft_duck"    # andere Apps hoerbar, aber deutlich leiser
    HARD_FOCUS = "hard_focus"  # maximale Transkriptionsqualitaet vor Komfort


# -- Device-Guard -----------------------------------------------------------------------

# Namen, unter denen Treiber Loopback-/Mix-Capture-Geraete anbieten. Solche Geraete
# fuehren Systemaudio in den Input — genau das, was nie passieren darf.
# Linux/PulseAudio: Monitor-Sources ("Monitor of ...", "*.monitor") sind das
# Loopback-Aequivalent und fallen unter denselben Guard.
_LOOPBACK_PATTERNS = re.compile(
    r"stereo\s*mix|stereomix|loopback|what\s*u\s*hear|wave\s*out\s*mix|"
    r"aufnahmesumme|summe\b|mix\s*\(|virtual.*cable|cable\s*output|vb-audio|voicemeeter|"
    r"monitor\s+of|\.monitor\b",
    re.IGNORECASE,
)


@dataclass
class DeviceCheck:
    ok: bool
    name: str
    reason: str = ""
    # Woran es lag: "name" (Wortliste), "monitor" (strukturell erkannt),
    # "blocklist" (Nutzer-Sperrliste), "error" (Geraet nicht abfragbar), "" = ok.
    source: str = ""


def device_blocked_by_user(name: str, blocklist) -> str:
    """Der Eintrag aus der Nutzer-Sperrliste, der auf `name` passt ("" = keiner).

    Bewusst schlichter Teilstring-Vergleich statt Regex: Die Liste pflegt ein
    Mensch, der den Geraetenamen aus dem Dropdown abschreibt — ein halbfertiger
    Regex wuerde hier still gar nichts oder alles sperren."""
    lowered = (name or "").lower()
    for entry in blocklist or []:
        text = str(entry).strip()
        if text and not text.startswith("#") and text.lower() in lowered:
            return text
    return ""


def is_monitor_source(name: str) -> bool | None:
    """Ist das ein PulseAudio/PipeWire-Monitor (= Systemton statt Mikrofon)?

    True/False = strukturell beantwortet, None = auf dieser Plattform nicht
    entscheidbar. Unter Linux liefert `monitor_of_sink` eine harte Aussage, die
    keine Wortliste braucht — Monitor-Sources heissen nicht zwingend „Monitor".

    Unter Windows gibt es bewusst KEIN Gegenstueck: „Stereomix" ist dort ein ganz
    regulaerer Capture-Endpunkt und vom Betriebssystem nicht von einem Mikrofon zu
    unterscheiden. Dort bleiben Wortliste und Sperrliste die einzigen Mittel — das
    ehrlich zu benennen ist besser, als eine Heuristik als Struktur auszugeben.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        import pulsectl

        with pulsectl.Pulse("fleech-monitor-check") as pulse:
            for src in pulse.source_list():
                if name in (src.name, src.description):
                    return getattr(src, "monitor_of_sink", None) not in (None, 0xFFFFFFFF)
    except Exception:
        log.debug("Monitor-Status nicht ermittelbar.", exc_info=True)
        return None
    return None


class DeviceGuard:
    """Prueft, dass das gewaehlte Input-Geraet ein echtes Mikrofon ist."""

    @staticmethod
    def resolve_input_name(device) -> str:
        import sounddevice as sd

        from .audio import resolve_input_device

        # Mehrdeutige Namen (dasselbe Mikro unter mehreren Host-APIs) zuerst auf
        # einen eindeutigen Index abbilden — sonst wirft query_devices ValueError.
        try:
            info = sd.query_devices(device=resolve_input_device(device), kind="input")
            name = info["name"]
        except Exception as exc:
            # Beim App-Start ist das Audio-Subsystem gelegentlich noch nicht bereit;
            # dann scheiterte die Abfrage und Fleech meldete faelschlich „Geraet
            # nicht abfragbar" fuer ein voellig normales Mikrofon (real im Log).
            # Fuer die Loopback-Pruefung genuegt aber der NAME — und den kennen wir
            # bereits, wenn der Nutzer eines ausgewaehlt hat.
            if isinstance(device, str) and device.strip():
                log.debug("Geraeteabfrage fehlgeschlagen (%s) — pruefe den Namen.", exc)
                return device
            raise
        # Linux: 'pulse'/'default' sind nur Router — der ECHTE Capture-Endpunkt ist
        # die PipeWire-Default-Source. Deren Namen aufloesen, damit (a) die UI das
        # wirkliche Mikrofon zeigt und (b) der Loopback-Guard eine als Default
        # gesetzte Monitor-Source erkennt.
        if sys.platform.startswith("linux") and name in ("pulse", "pipewire", "default"):
            try:
                import pulsectl

                with pulsectl.Pulse("fleech-device-check") as pulse:
                    # Explizit gewaehlte Source (PULSE_SOURCE, von resolve_input_device
                    # gesetzt) hat Vorrang; sonst die System-Default-Source.
                    wanted = os.environ.get("PULSE_SOURCE") or pulse.server_info().default_source_name
                    for src in pulse.source_list():
                        if src.name == wanted:
                            return src.description or src.name
                    if wanted:
                        return wanted
            except Exception:
                log.debug("Pulse-Source nicht aufloesbar.", exc_info=True)
        return name

    @classmethod
    def check(cls, device, blocklist=None) -> DeviceCheck:
        """Reihenfolge: Sperrliste (Nutzerwille schlaegt alles) → strukturelle
        Monitor-Erkennung → Wortliste. Die Sperrliste zuerst, damit ein Geraet, das
        der Nutzer bewusst ausgeschlossen hat, nie doch durchrutscht, nur weil es
        keiner Heuristik auffaellt."""
        try:
            name = cls.resolve_input_name(device)
        except Exception as exc:
            return DeviceCheck(ok=False, name=str(device),
                               reason=f"Geraet nicht abfragbar: {exc}", source="error")

        entry = device_blocked_by_user(name, blocklist)
        if entry:
            return DeviceCheck(
                ok=False, name=name, source="blocklist",
                reason=f"Steht auf deiner Sperrliste (Eintrag „{entry}“).",
            )

        if is_monitor_source(name):
            return DeviceCheck(
                ok=False, name=name, source="monitor",
                reason="Monitor-Quelle (Systemton) — kein Mikrofon. Systemaudio "
                       "wuerde in die Transkription gelangen.",
            )

        if _LOOPBACK_PATTERNS.search(name):
            return DeviceCheck(
                ok=False,
                name=name,
                source="name",
                reason="Loopback-/Mix-Geraet erkannt — Systemaudio wuerde in die "
                       "Transkription gelangen.",
            )
        return DeviceCheck(ok=True, name=name)


# -- Playback-Ducking --------------------------------------------------------------------


class _PycawSessions:
    """Duenner Adapter um pycaw, damit der Ducker testbar bleibt (austauschbar)."""

    def iter_foreign_sessions(self):
        """Liefert (name, ISimpleAudioVolume) fuer alle fremden, aktiven Audio-Sessions."""
        from pycaw.pycaw import AudioUtilities

        own_pid = os.getpid()
        for session in AudioUtilities.GetAllSessions():
            proc = session.Process
            if proc is None or proc.pid == own_pid:
                continue
            volume = session.SimpleAudioVolume
            if volume is None:
                continue
            yield proc.name(), volume


class _PulseVolume:
    """ISimpleAudioVolume-kompatibler Adapter fuer einen PulseAudio-Sink-Input.

    Gleiche Schnittstelle wie pycaw (GetMasterVolume/SetMasterVolume), damit
    PlaybackDucker/_fade auf beiden Plattformen unveraendert funktionieren.
    """

    def __init__(self, sessions: "_PulseSessions", sink_input):
        self._sessions = sessions
        self._si = sink_input

    def GetMasterVolume(self) -> float:  # noqa: N802 — pycaw-Schnittstelle
        return float(self._sessions.pulse.volume_get_all_chans(self._si))

    def SetMasterVolume(self, value: float, _ctx=None) -> None:  # noqa: N802
        self._sessions.pulse.volume_set_all_chans(self._si, max(0.0, float(value)))


class _PulseSessions:
    """Sink-Inputs fremder Apps via PulseAudio-API (funktioniert auch mit PipeWire).

    Die Verbindung wird lazy aufgebaut und bei Fehlern (Pulse-Neustart) einmal neu
    versucht. Aufrufe kommen seriell aus dem Ducker (dessen Lock) — trotzdem
    threading_lock=True, weil duck() und restore() aus verschiedenen Threads
    kommen koennen.
    """

    def __init__(self):
        self._pulse = None

    @property
    def pulse(self):
        import pulsectl

        if self._pulse is None:
            self._pulse = pulsectl.Pulse("fleech-ducking", threading_lock=True)
        return self._pulse

    def close(self) -> None:
        if self._pulse is not None:
            try:
                self._pulse.close()
            except Exception:
                pass
            self._pulse = None

    def iter_foreign_sessions(self):
        sink_inputs = None
        for attempt in (1, 2):
            try:
                sink_inputs = self.pulse.sink_input_list()
                break
            except Exception:
                self.close()  # Verbindung stale (Pulse/PipeWire neu gestartet)?
                if attempt == 2:
                    raise
        own_pid = str(os.getpid())
        for si in sink_inputs:
            props = getattr(si, "proplist", {}) or {}
            if props.get("application.process.id") == own_pid:
                continue
            name = (
                props.get("application.name")
                or props.get("application.process.binary")
                or f"sink-input-{si.index}"
            )
            yield name, _PulseVolume(self, si)


def default_playback_sessions():
    """Plattform-Backend fuer den Ducker; None = Plattform ohne Ducking-Support."""
    if sys.platform == "win32":
        return _PycawSessions()
    if sys.platform.startswith("linux"):
        return _PulseSessions()
    return None


class PlaybackDucker:
    """Senkt fremde Playback-Sessions weich ab und stellt sie weich wieder her.

    duck():    fuer jede fremde Session aktuellen Pegel merken, dann per Fade auf
               pegel * duck_level absenken (relativ, damit leise Apps leise bleiben).
    restore(): per Fade auf die gemerkten Pegel zurueck.
    """

    FADE_STEPS = 8

    def __init__(self, duck_level: float = 0.25, fade_ms: int = 250, hard_mute: bool = False,
                 sessions=None):
        self.duck_level = max(0.0, min(1.0, duck_level))
        self.fade_ms = fade_ms
        self.hard_mute = hard_mute
        self._sessions = sessions if sessions is not None else default_playback_sessions()
        self._saved: list[tuple[str, object, float]] = []  # (name, volume, original)
        self._lock = threading.Lock()
        self._ducked = False

    @property
    def ducked(self) -> bool:
        return self._ducked

    def duck(self) -> None:
        with self._lock:
            if self._ducked or self._sessions is None:
                return
            try:
                # Befund D-5: Bereits gemerkte Original-Pegel bleiben stehen. Wurde
                # ein Lauf abgebrochen (Ausnahme mitten im Fade, Prozess weg), stehen
                # die Pegel unten, waehrend `_saved` noch die Originale traegt — sie
                # neu einzulesen wuerde 25 % als „Original" merken und die Lautstaerke
                # bei jedem weiteren Diktat ein Stueck weiter absenken (Sperrklinke).
                bekannt = {id(v): orig for _, v, orig in self._saved}
                gemerkt = []
                for name, volume in self._sessions.iter_foreign_sessions():
                    original = bekannt.get(id(volume))
                    if original is None:
                        original = float(volume.GetMasterVolume())
                    gemerkt.append((name, volume, original))
                self._saved = gemerkt
                if not self._saved:
                    self._ducked = True
                    return
                if self.hard_mute:
                    for name, volume, _ in self._saved:
                        volume.SetMasterVolume(0.0, None)
                else:
                    targets = [(v, orig, orig * self.duck_level) for _, v, orig in self._saved]
                    self._fade(targets)
                self._ducked = True
                log.info(
                    "Ducking AN (%s): %s",
                    "Mute" if self.hard_mute else f"auf {self.duck_level:.0%}",
                    ", ".join(name for name, _, _ in self._saved),
                )
            except Exception:
                log.exception("Ducking fehlgeschlagen — Diktat laeuft unveraendert weiter.")

    def restore(self) -> None:
        with self._lock:
            if not self._ducked:
                return
            try:
                if self._saved:
                    targets = [
                        (v, float(v.GetMasterVolume()), orig) for _, v, orig in self._saved
                    ]
                    self._fade(targets)
                log.info("Ducking AUS — Lautstaerken wiederhergestellt.")
            except Exception:
                log.exception("Wiederherstellen der Lautstaerken fehlgeschlagen.")
            finally:
                self._saved = []
                self._ducked = False

    def _fade(self, targets: list[tuple[object, float, float]]) -> None:
        """Weiche Rampe von 'start' nach 'ziel' fuer alle Sessions gleichzeitig."""
        steps = max(1, self.FADE_STEPS)
        pause = (self.fade_ms / 1000) / steps
        for i in range(1, steps + 1):
            t = i / steps
            for volume, start, goal in targets:
                try:
                    volume.SetMasterVolume(start + (goal - start) * t, None)
                except Exception:
                    pass  # Session kann waehrend des Fades verschwinden (App beendet)
            if pause > 0 and i < steps:
                time.sleep(pause)


class MicLevelController:
    """Senkt den Pegel des STANDARD-Aufnahmegeraets waehrend der Aufnahme (Math Focus).

    Zweck: aggressive Treiber-Boosts uebersteuern bei lauter Sprache — ein moderater
    Pegel (z. B. 0.7) verbessert die Whisper-Qualitaet. Wird nach der Aufnahme exakt
    wiederhergestellt. Grenze: wirkt auf das System-Standardgeraet, nicht zwingend
    auf ein per Config abweichend gewaehltes Mikrofon.
    """

    def __init__(self, level: float):
        self.level = max(0.0, min(1.0, level))
        self._saved: float | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _endpoint():
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        mic = AudioUtilities.GetMicrophone()
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)

    @staticmethod
    def _pulse_default_source(pulse):
        name = pulse.server_info().default_source_name
        for src in pulse.source_list():
            if src.name == name:
                return src
        raise RuntimeError(f"Default-Source {name!r} nicht in der Source-Liste.")

    def _get_level(self) -> float:
        if sys.platform == "win32":
            return float(self._endpoint().GetMasterVolumeLevelScalar())
        import pulsectl

        with pulsectl.Pulse("fleech-mic-level") as pulse:
            return float(pulse.volume_get_all_chans(self._pulse_default_source(pulse)))

    def _set_level(self, value: float) -> None:
        if sys.platform == "win32":
            self._endpoint().SetMasterVolumeLevelScalar(value, None)
            return
        import pulsectl

        with pulsectl.Pulse("fleech-mic-level") as pulse:
            pulse.volume_set_all_chans(self._pulse_default_source(pulse), max(0.0, value))

    def apply(self) -> None:
        with self._lock:
            if self._saved is not None:
                return
            try:
                self._saved = self._get_level()
                self._set_level(self.level)
                log.info("Math Focus: Mic-Pegel %.0f%% → %.0f%%.", self._saved * 100, self.level * 100)
            except Exception:
                log.exception("Mic-Pegel-Steuerung fehlgeschlagen — Aufnahme unveraendert.")
                self._saved = None

    def restore(self) -> None:
        with self._lock:
            if self._saved is None:
                return
            try:
                self._set_level(self._saved)
                log.info("Math Focus: Mic-Pegel wiederhergestellt (%.0f%%).", self._saved * 100)
            except Exception:
                log.exception("Mic-Pegel-Wiederherstellung fehlgeschlagen.")
            finally:
                self._saved = None


# -- Fokus-Controller ---------------------------------------------------------------------


@dataclass
class FocusState:
    mode: FocusMode
    mic_name: str
    ducking_active: bool = False


class AudioFocusController:
    """Buendelt Modus, Guard und Ducker; wird von der App bei Start/Stopp gerufen."""

    def __init__(self, mode: FocusMode, ducker: PlaybackDucker | None,
                 device_check: DeviceCheck,
                 mic_level: MicLevelController | None = None):
        self.mode = mode
        self.ducker = ducker
        self.device_check = device_check
        self.mic_level = mic_level

    def may_record(self) -> tuple[bool, str]:
        """Loopback-Geraet: warnen, aber nicht blockieren.

        Frueher wurde im Formel-Modus hart blockiert, weil dort Audio an einen
        kostenpflichtigen Cloud-Dienst ging. Diesen Pfad gibt es seit v3.0.0 nicht
        mehr — es bleibt die Warnung, damit ein falsch gewaehltes Geraet auffaellt,
        ohne dass jemand vor einem verschlossenen Mikrofon steht."""
        if self.device_check.ok:
            return True, ""
        return True, (
            f"WARNUNG: Input-Geraet '{self.device_check.name}' — {self.device_check.reason}"
        )

    def on_recording_start(self) -> None:
        if self.mode is not FocusMode.PURE_MIC and self.ducker is not None:
            self.ducker.duck()
        if self.mic_level is not None:
            self.mic_level.apply()

    def on_recording_stop(self) -> None:
        if self.ducker is not None:
            self.ducker.restore()
        if self.mic_level is not None:
            self.mic_level.restore()

    def state(self) -> FocusState:
        return FocusState(
            mode=self.mode,
            mic_name=self.device_check.name,
            ducking_active=bool(self.ducker and self.ducker.ducked),
        )

    def status_line(self) -> str:
        s = self.state()
        return (
            f"Mic: {s.mic_name} | Capture: nur Mikrofon | Fokus: {s.mode.value}"
            + (" | Apps geduckt" if s.ducking_active else "")
        )
