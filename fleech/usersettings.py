"""Persistente Nutzer-Einstellungen der Desktop-App (%APPDATA%/Fleech/settings.json).

Zweischichtiges Modell:
- config.yaml  = technische Basis-Konfiguration (Modelle, Endpoints, Prompts).
- settings.json = alles, was der Nutzer im Settings-UI aendert (Bedienmodus, Overlay-
  Position, Sounds, Eingriffsgrad, ...). Wird beim Start auf die AppConfig gelegt.

Jede Aenderung im UI wird sofort gespeichert; die App kehrt beim Neustart in exakt
denselben Zustand zurueck.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .platformpaths import user_data_dir
from .profiles import ProfilesSettings

log = logging.getLogger(__name__)

SETTINGS_DIR = user_data_dir()
SETTINGS_PATH = SETTINGS_DIR / "settings.json"




def _backup_path(path: Path) -> Path:
    """Die letzte gute Fassung — liegt neben der Datei, nicht in einem Unterordner:
    Wer sie von Hand zurueckholen will, soll sie sehen, ohne zu suchen."""
    return path.with_name(path.name + ".bak")


def _lies_json(path: Path):
    """JSON lesen. None = nicht da, leer oder unbrauchbar (kein Dict).

    Die Leer-Pruefung ist der Kern: Eine auf 0 Byte gekuerzte Datei ist genau das,
    was ein abgebrochener Schreibvorgang hinterlaesst, und `json.loads("")` wirft —
    beides muss denselben Weg gehen, naemlich zur Sicherung.
    """
    try:
        if not path.is_file():
            return None
        roh = path.read_text(encoding="utf-8").strip()
        if not roh:
            return None
        data = json.loads(roh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@dataclass
class GeneralSettings:
    autostart: bool = False
    language: str = "de"
    # Diktat-Historie fuer Home/Insights (lokal, %APPDATA%/Fleech/history.db).
    save_history: bool = True
    # Anzeigename fuer die Begruessung; leer = Windows-Benutzername.
    display_name: str = ""
    # Einfuehrung (Onboarding) schon gezeigt? Bestands-Installationen laden das
    # Feld nicht aus ihrer settings.json → Default False → der Wizard kaeme einmal
    # auch fuer sie. Gewollt: die Einfuehrung ist neu, einmal zeigen schadet nicht,
    # und jeder Weg hinaus (auch X) setzt das Flag dauerhaft.
    onboarding_done: bool = False
    # Signierter Lizenzschluessel dieser Installation (siehe fleech/licensing.py).
    # Leer = Fleech diktiert nicht; alles andere bleibt bedienbar, damit man den
    # Schluessel ueberhaupt eintragen kann.
    license_key: str = ""


@dataclass
class RecordingSettings:
    mode: str = "hold"          # hold | toggle
    hotkey: str = "f9"
    # Die Mathe-Hotkeys (math_hotkey, math_toggle_hotkey) sind nach 5.10.2 auch als
    # Felder entfallen: Seit v3.0.0 band sie niemand mehr, gelesen wurden sie nie.
    # Alte settings.json laden trotzdem weiter — `load()` setzt nur Schluessel,
    # zu denen es ein Feld gibt (`hasattr`), der Rest wird still uebergangen.
    # KI-Prompting-Umschalt: markiert das LAUFENDE Diktat als KI-Prompt (Diktat →
    # strukturierter Prompt). Default: Ctrl+Alt+P.
    prompt_toggle_hotkey: str = "ctrl+alt+p"
    # Letzte Ausgabe durch das ROH-Transkript ersetzen. Fuer den Fall, dass die
    # Bereinigung danebengriff — Wort fuer Wort das, was gesprochen wurde, statt
    # eine Formulierung, die man so nicht gesagt hat.
    undo_hotkey: str = "ctrl+alt+z"
    # Aufnahme anhalten/fortsetzen (z. B. um kurz mit jemandem zu sprechen).
    # Waehrend der Pause laeuft der Stream weiter, es wird aber nichts gesammelt.
    pause_hotkey: str = "ctrl+alt+space"
    # Profil wechseln. TIPPEN = naechstes Profil, HALTEN = Auswahlliste am Zeiger.
    # Leer als Default: die sinnvollste Belegung ist eine Maus-Zusatztaste
    # (mouse4/mouse5), und die ist je nach Maus anders — raten waere hier falsch.
    profile_hotkey: str = ""
    microphone: str | int | None = None  # None = Systemstandard
    # Nutzer-Sperrliste fuer Aufnahmegeraete: Teilstrings von Geraetenamen, die nie
    # als Mikrofon gelten sollen. Ergaenzt die eingebaute Wortliste — unter Windows
    # ist "Stereomix" fuer das Betriebssystem ein regulaeres Capture-Geraet, dort
    # ist eine gepflegte Liste die einzige verlaessliche Handhabe.
    blocked_devices: list = field(default_factory=list)


@dataclass
class FreihandSettings:
    """Diktieren ohne Taste: Startwort sagen, sprechen, aufhoeren.

    Kommt ZUSAETZLICH zum Hotkey, ersetzt ihn nie. Standardmaessig aus — eine App,
    die ungefragt dauerhaft mithoert, waere ein Vertrauensbruch, auch wenn technisch
    nichts gespeichert wird.
    """

    aktiv: bool = False
    # Mehrsilbig und im Deutschen selten: Die Lehre aus „Redax" → „Kimono". Ein
    # kurzes Alltagswort loest im Gespraech staendig versehentlich aus.
    startwort: str = "Kimono"
    abbruchwort: str = "Abbrechen"
    # Welches Modell das Startwort prueft. „diktat" heisst: dasselbe Modell, das
    # ohnehin fuer die Diktate geladen ist.
    #
    # Bis 5.6.0 stand hier „base" — ein eigenes kleines Modell auf der CPU. Das
    # war aus einem Grund falsch, der lange nicht sichtbar war: Die Pruefung lief
    # IM Audio-Callback, und `base` brauchte dafuer 437 ms (Median) bei 200-ms-
    # Bloecken. Gemessen kam dadurch nur noch die HAELFTE des Gesprochenen an;
    # das Modell bekam Fetzen und halluzinierte. Der Callback ist inzwischen frei
    # (siehe freihand.FreihandStream), aber das grosse Modell ist trotzdem die
    # bessere Wahl: 141 ms statt 437, genauer, und kein zusaetzliches VRAM.
    #
    # „tiny"/„base"/„small" bleiben waehlbar fuer Rechner ohne brauchbare GPU.
    modell: str = "diktat"
    # Wie lange Stille ein Diktat beendet (1–4 s, siehe freihand.Einstellungen).
    # Gilt AUCH fuer den Bedienmodus „Anstupsen" (siehe stillewache.py).
    stille_s: float = 2.0
    # Fehlersuche: die geprueften Startwort-Fenster als WAV aufheben. Aus gutem
    # Grund standardmaessig AUS — hier wird Audio gespeichert, und genau das
    # verspricht der Freihand-Modus sonst nicht zu tun.
    diagnose: bool = False
    # Prozessnamen, in denen NICHT gelauscht wird. Spiele und Meeting-Werkzeuge
    # gehoeren hierher: Dort ist Sprache im Raum die Regel.
    ausgeschlossene_apps: list = field(default_factory=list)


@dataclass
class AudioFocusSettings:
    mode: str = "soft_duck"     # pure_mic | soft_duck | hard_focus
    # Restlautstaerke fremder Apps waehrend der Aufnahme (0 = stumm, 1 = unveraendert).
    # Regelbar im UI; ersetzt den fixen config-Default von 0.25 fuer Soft/Hard Duck.
    duck_level: float = 0.25


@dataclass
class MathSettings:
    enabled: bool = True        # Mathe-Funktion global (F10 + gesprochene Delimiter)
    priority: str = "mixed"     # math | natural | mixed
    math_focus: bool = False
    # Automatische Formel-Erkennung: beim Cleanup werden gesprochene mathematische
    # Ausdruecke inline als LaTeX ($…$) geschrieben — ohne Umschalten. Opt-in.
    auto_latex: bool = False


# Die drei Felder oben sind die technische Wahrheit, aber als BEDIENELEMENTE waren
# sie eine Zumutung: Wer Formeln automatisch erkannt haben wollte, musste dreimal
# richtig raten (Prioritaet + Haertung + Automatik). Nach aussen gibt es deshalb
# nur noch eine Stufe; die Felder werden daraus gesetzt. Kein neues Settings-Feld
# und damit keine Migration — bestehende settings.json bleiben gueltig.
MATH_LEVELS = ("off", "auto")


def math_level(m: MathSettings) -> str:
    """Aktuelle Stufe aus den drei technischen Feldern ableiten.

    Befund A-1: Hier zaehlte lange nur `enabled`. Wirksam ist aber `auto_latex`
    (`pipeline_factory`: `enabled and auto_latex`) — und dessen Vorgabe ist False.
    Eine frische Installation zeigte deshalb „Automatisch" und erkannte trotzdem
    keine einzige Formel. Anzeige und Wirkung fragen jetzt dieselben Felder."""
    if not m.enabled or not m.auto_latex:
        return "off"
    return "auto"


def apply_math_level(m: MathSettings, level: str) -> None:
    """Stufe → die drei technischen Felder.

    Seit v3.0.0 gibt es nur noch „an" oder „aus": Der Umschalt-Weg ueber ein
    Cloud-Modell ist entfallen, Formeln entstehen immer im lokalen Parser.
    „off" loescht auch `auto_latex` — sonst bliebe ein Feld auf „an" stehen, das
    die Stufe hinterher wieder als „Automatisch" lesen wuerde (A-1)."""
    if level == "off":
        m.enabled = False
        m.auto_latex = False
        return
    m.enabled = True
    m.priority, m.auto_latex, m.math_focus = "mixed", True, True


@dataclass
class InterfaceSettings:
    """Sichtbare Bausteine von Home/Insights — alles ueber die Settings schaltbar."""

    home_show_welcome: bool = True      # Begruessungszeile
    home_show_stats: bool = True        # Kurz-Stats-Karte rechts neben dem Verlauf
    # Gemerkter Zeitraum der Insights (siehe INSIGHT_RANGES in der UI).
    insights_range: str = "all"
    insights_show_wpm: bool = True      # Woerter/Minute + Tacho
    insights_show_corrections: bool = True
    insights_show_words: bool = True    # Woerter diktiert
    insights_show_app_usage: bool = True
    insights_show_top_words: bool = True  # Haeufigste Woerter (Rangliste, ohne Fuellwoerter)
    insights_show_streak: bool = True   # Serie + Aktivitaets-Kalender
    insights_show_patterns: bool = True  # "Deine Muster" (produktivste Tageszeit/Wochentag)
    insights_show_processing: bool = True  # Verarbeitung: Latenzen, Routing, Fallback-Quote
    insights_show_advice: bool = True   # Vorschlaege (Korrektur-Regeln, Fallback-Trend)
    insights_show_commands: bool = True  # Befehlsarten (umformulieren/loeschen/…)
    # Profilseite: erweiterte Felder (Eingriff, Safe-Word, Absenden, App-Zuweisung)
    # zeigen. Aus = nur Name, Ausgabeformat, Schnellwechsel — das reicht fuer den
    # Normalfall, und ein Profil ohne zugewiesene Apps ist voellig in Ordnung:
    # gewaehlt wird es dann von Hand.
    profiles_advanced: bool = False


@dataclass
class OverlaySettings:
    """Wispr-Stil-Pille (X · Waveform · Haken) — Groesse ist fix, Position frei."""

    visibility: str = "during_activity"  # always | during_activity | auto_hide | off
    auto_hide_seconds: float = 4.0
    opacity: float = 0.9
    click_through: bool = False
    x: int | None = None        # None = Default (rechts, vertikal ~mittig)
    y: int | None = None
    # Positions-Preset (right_center | left_center | bottom_center | top_center |
    # bottom_right | custom). "" = noch nicht gesetzt: aus x/y ableiten (Migration
    # alter settings.json) bzw. Default right_center fuer Neuinstallationen.
    position: str = ""
    # Erkannten Text kurz ueber der Pille einblenden (Bestaetigung nach dem Diktat).
    show_transcript: bool = True
    # Groesse der Pille: compact | normal | large (skaliert Pille, Buttons, Icons).
    size: str = "normal"
    # Empfindlichkeit der Pegel-Anzeige (0.2–3.0): >1 laesst die Waveform staerker
    # ausschlagen — fuer leise/weiter entfernte Mikrofone.
    level_gain: float = 1.0
    # Pille folgt live dem Monitor, auf dem der Mauszeiger steht.
    follow_mouse_screen: bool = True
    # Grobe Echtzeit-Vorschau ueber der Pille waehrend der Aufnahme (laedt ein
    # zusaetzliches kleines Whisper-Modell, ~0,5 GB VRAM) — bewusst Opt-in.
    live_preview: bool = False
    # Optik der Rand-Buttons: True = eigene, getrennte Hintergruende (drei Inseln);
    # False = alles in einer durchgehenden Pille. Reine Geschmacksfrage.
    separate_islands: bool = True
    # Vier separat einstellbare Raender (px, vor Skalierung) = Padding des Hintergrunds
    # der mittleren Haupt-Pille. Oben/unten machen sie hoeher, links/rechts breiter;
    # der Mathe-Punkt und der Trigger-Button folgen in der Hoehe.
    edge_left: int = 6
    edge_right: int = 6
    edge_top: int = 2
    edge_bottom: int = 2


@dataclass
class SoundSettings:
    enabled: bool = True
    volume: float = 0.4
    preset: str = "soft"        # soft | click
    start: bool = True
    stop: bool = True
    commit: bool = True
    error: bool = True


@dataclass
class FocusSettings:
    """Windows Focus & Notifications — ruhiges Verhalten unter Fokusbedingungen."""

    respect_dnd: bool = True            # Windows Do Not Disturb respektieren
    dnd_mute_sounds: bool = False       # UI-Sounds bei DND zusaetzlich stumm
    toasts_enabled: bool = True         # Toasts global (nicht-kritische)
    toast_critical_always: bool = True  # kritische Toasts trotzdem anzeigen
    toast_background_info: bool = True  # "App laeuft im Hintergrund"
    toast_provider_quota: bool = True   # Provider-/Quota-Problem
    toast_long_processing: bool = False # Abschluss langer Verarbeitung
    notification_sounds: bool = False   # eigener Akzent-Sound bei kritischen Toasts
    gaming_detection: bool = True       # Fullscreen/Games automatisch erkennen
    gaming_overlay: str = "activity_only"  # unchanged | activity_only | compact | hidden
    gaming_sound_factor: float = 0.5    # Soundreduktion im Gaming-Modus (0 = stumm)
    gaming_exceptions: list = field(default_factory=list)  # Prozessnamen, z. B. mpv.exe


# --- Abgeleitete Stufen (wie math_level): EIN Regler statt vieler Einzelfelder. ---
# Bewusst KEINE neuen Felder — die technischen Werte bleiben die Quelle der Wahrheit,
# alte settings.json laufen ohne Migration weiter, und wer will, kann sie weiterhin
# von Hand feiner einstellen, als die Oberflaeche es anbietet.

OVERLAY_COMPACTNESS = (("tight", "Eng"), ("normal", "Standard"), ("roomy", "Luftig"))

# Stufe → (links, rechts, oben, unten) in px vor Skalierung.
_COMPACTNESS_EDGES = {
    "tight": (3, 3, 0, 0),
    "normal": (6, 6, 2, 2),
    "roomy": (12, 12, 6, 6),
}


def overlay_compactness(o: OverlaySettings) -> str:
    """Aktuelle Stufe aus den vier Randwerten ableiten.

    Passt nichts exakt (aeltere settings.json oder von Hand gesetzte Werte), gewinnt
    die naechstliegende Stufe — die Oberflaeche zeigt so nie einen leeren Regler.
    """
    edges = (o.edge_left, o.edge_right, o.edge_top, o.edge_bottom)
    best, best_dist = "normal", None
    for level, preset in _COMPACTNESS_EDGES.items():
        dist = sum(abs(a - b) for a, b in zip(edges, preset))
        if best_dist is None or dist < best_dist:
            best, best_dist = level, dist
    return best


def apply_overlay_compactness(o: OverlaySettings, level: str) -> None:
    """Stufe → die vier Randwerte."""
    preset = _COMPACTNESS_EDGES.get(level)
    if preset is None:
        return
    o.edge_left, o.edge_right, o.edge_top, o.edge_bottom = preset


TOAST_LEVELS = (("none", "Nichts"), ("important", "Wichtiges"), ("all", "Alles"))

_TOAST_FIELDS = ("toasts_enabled", "toast_critical_always", "toast_background_info",
                 "toast_provider_quota", "toast_long_processing")

# "Wichtiges" = nur was auf ein PROBLEM hinweist (kritische Fehler, Anbieter-Quota).
# Reine Statusmeldungen ("laeuft im Hintergrund", "Verarbeitung fertig") sind Komfort
# und gehoeren zu "Alles".
_TOAST_PRESETS = {
    "none": (False, False, False, False, False),
    "important": (True, True, False, True, False),
    "all": (True, True, True, True, True),
}


def toast_level(f: FocusSettings) -> str:
    """Aktuelle Stufe aus den fuenf Toast-Feldern ableiten.

    Ein EINZELNER aktiver Status-Toast genuegt fuer "Alles": Der Regler muss sagen,
    was wirklich passiert. Zeigte er "Wichtiges", waehrend noch Statusbanner kommen,
    waere die Anzeige eine Luege — und genau darauf verlaesst man sich bei so einer
    Zusammenfassung. (Der Auslieferungszustand hat `toast_background_info` an.)
    """
    if not f.toasts_enabled and not f.toast_critical_always:
        return "none"
    if f.toast_background_info or f.toast_long_processing:
        return "all"
    return "important"


def apply_toast_level(f: FocusSettings, level: str) -> None:
    """Stufe → die fuenf Toast-Felder."""
    preset = _TOAST_PRESETS.get(level)
    if preset is None:
        return
    for name, value in zip(_TOAST_FIELDS, preset):
        setattr(f, name, value)


@dataclass
class OutputSettings:
    intervention: str = "standard"  # minimal | standard | strong
    # Gesprochene Zeichen als Zeichen schreiben („Slash Hunter" → „/Hunter").
    # Bewusst nur eindeutige Woerter (Slash, Hashtag, Unterstrich, Klammeraffe) —
    # „Minus"/„Plus" bleiben Text, das sind gewoehnliche deutsche Woerter.
    spoken_symbols: bool = True
    # Safe-Word-Befehle komplett an/aus ("aktiv beenden", nicht nur Wort wechseln).
    command_enabled: bool = True
    # Safe-Word fuer Befehle im Redefluss. Leer = Wert aus config.yaml verwenden.
    # Als Settings-Feld, damit Trigger-Kandidaten ohne App-Neustart durchprobiert
    # werden koennen (ASR-Robustheit ist stimmabhaengig).
    trigger_word: str = ""
    # Persoenliches Woerterbuch: rohe Zeilen ("Begriff" = Vokabular-Priming fuer
    # Whisper; "falsch => richtig" = zusaetzlich deterministische Ersetzung).
    dictionary: list = field(default_factory=list)
    # `app_modes` (rohe Zeilen "prozess.exe => minimal|standard|strong") ist nach
    # 5.10.2 entfallen: Das koennen die App-Profile (fleech/profiles.py) seit
    # v3.7.2, gelesen hat das Feld projektweit niemand mehr. Alte settings.json
    # laden weiter, der Schluessel wird beim Laden still uebergangen.
    # DIE eine Ignorier-Liste ("falsch => richtig"): abgelehnte Woerterbuch-
    # Rueckfragen UND weggeklickte Insights-Vorschlaege. Dauerhaft, weil sichtbar:
    # Die Liste steht als Editor auf der Woerterbuch-Seite — Zeile loeschen holt
    # den Vorschlag zurueck. (Bis v1.10.1 waren Insights-Ignores ein eigenes,
    # unsichtbares Feld advice_dismissed mit 30-Tage-Frist; die Frist war nur der
    # Ersatz fuer die fehlende Oberflaeche.)
    dictionary_ignores: list = field(default_factory=list)
    # Text-Bausteine: rohe Zeilen "Kuerzel => Text" ("\n" im Text = Zeilenumbruch).
    # Gesprochen als "<Signalwort> <Kuerzel>" — der Text wird deterministisch
    # eingefuegt, ohne dass ein Modell ihn zu sehen bekommt.
    snippets: list = field(default_factory=list)
    # Signalwort fuer Bausteine. Leer = "Baustein". Bewusst getrennt vom Safe-Word:
    # Bausteine sind stumpfes Einfuegen, Befehle veraendern vorhandenen Text.
    snippet_keyword: str = ""
    # Wie oft kam ein Woerterbuch-Begriff zuletzt in eingefuegtem Text vor?
    # {begriff_klein: treffer}. Entscheidet, welche Begriffe ueber dem 60er-
    # Priming-Limit Vorrang haben — sonst verlieren Power-User das Priming
    # stillschweigend fuer alles am Listenende.
    dictionary_usage: dict = field(default_factory=dict)
    # Cursor-Rueckkehr: beim Aufnahme-Start Fenster + Text-Cursor-Position merken und
    # den Text dort einfuegen — auch wenn waehrend des Sprechens weggeklickt wurde
    # (anderes Fenster ODER anderes Feld derselben App). Fallback: existiert das Ziel
    # nicht mehr, geht der Text an den aktuellen Fokus.
    restore_focus: bool = True


@dataclass
class AdvancedSettings:
    debug_logging: bool = False
    # Projekt-Gedaechtnis (fleech/kontext.py): Fachbegriffe je App/Fenster lernen
    # und beim naechsten Diktat als Erkennungs-Hinweis mitgeben. Kostet keine
    # spuerbare Zeit (0,6 ms Abruf) und beeinflusst nur die Schreibweise erkannter
    # Woerter, nie den Inhalt — deshalb standardmaessig an.
    kontext_lernen: bool = True
    # Leer = GitHub-Releases des Projekts (Standardweg). Eine eigene URL zeigt auf
    # einen JSON-Feed {"version", "url", "sha256"} — siehe fleech/ui/updates.py.
    update_feed_url: str = ""
    # Beim Start und danach taeglich pruefen. Aus = nur der Knopf in den Einstellungen.
    auto_update_check: bool = True
    # Gefundene Updates gleich im Hintergrund laden (Installation bleibt ein Klick —
    # die App muss dafuer neu starten, das entscheidet niemand ausser dem Nutzer).
    auto_update_download: bool = True
    # Zugriffstoken, wenn die Update-Quelle ein PRIVATES Repository ist. Nur lesend
    # noetig (fein granuliert: "Contents: Read-only" fuer genau dieses Repository).
    # Wird ausschliesslich an GitHub gesendet und nie ins Log geschrieben.
    # Alternative ohne Eintrag in der Datei: Umgebungsvariable FLEECH_UPDATE_TOKEN.
    update_token: str = ""
    # True (Default) = stt.device "auto" (nutzt GPU, faellt automatisch auf CPU
    # zurueck). False = "cpu" erzwingen (z. B. um GPU/VRAM fuer Spiele freizuhalten).
    # Persistiert in settings.json — uebersteht Neustart und Autostart, kein
    # Env-Var-/setx-Umweg noetig.
    prefer_gpu: bool = True
    # True (Default) = adaptives Routing: kurze, einfache Diktate → kleines schnelles
    # Modell (~2x schneller), komplexe → grosses Modell. False = immer grosses Modell.
    adaptive_cleanup: bool = True
    # LLM-Warmhaltung (RAM/VRAM vs. Latenz):
    # "always" = Modelle dauerhaft geladen (schnellste Antwort, ~8 GB belegt),
    # "smart"  = nur bis `llm_idle_unload_minutes` nach dem letzten Diktat warmhalten
    #            (Default) — danach oder bei erkanntem SPIEL werden die Modelle SOFORT
    #            entladen (keep_alive=0, RAM frei); beim naechsten Aufnahmestart wird
    #            parallel zum Sprechen vorgeladen,
    # "off"    = nie aktiv warmhalten (Speicher maximal frei, erste Antwort langsamer).
    llm_keep_warm: str = "smart"
    # Nur im Smart-Modus: Minuten ohne Diktat, nach denen die Modelle aus dem RAM
    # entladen werden (kleiner = schneller RAM frei, dafuer oefter ~8 s Kaltstart).
    llm_idle_unload_minutes: int = 10




@dataclass
class WindowSettings:
    x: int | None = None
    y: int | None = None
    # Startgroesse: Bei 780x560 wurden Insights-Karten und die dreispaltige
    # Profilseite rechts abgeschnitten — man musste das Fenster jedes Mal von Hand
    # aufziehen. Der Wert passt auf jeden Full-HD-Bildschirm; wer kleiner will,
    # zieht es zusammen (die Groesse wird ohnehin gespeichert).
    width: int = 1120
    height: int = 780
    tray_hint_shown: bool = False  # Hinweis "laeuft im Hintergrund" nur einmal


@dataclass
class UserSettings:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    interface: InterfaceSettings = field(default_factory=InterfaceSettings)
    recording: RecordingSettings = field(default_factory=RecordingSettings)
    audio_focus: AudioFocusSettings = field(default_factory=AudioFocusSettings)
    freihand: FreihandSettings = field(default_factory=FreihandSettings)
    math: MathSettings = field(default_factory=MathSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    sounds: SoundSettings = field(default_factory=SoundSettings)
    focus: FocusSettings = field(default_factory=FocusSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    profiles: ProfilesSettings = field(default_factory=ProfilesSettings)
    advanced: AdvancedSettings = field(default_factory=AdvancedSettings)
    window: WindowSettings = field(default_factory=WindowSettings)

    # -- Persistenz ---------------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Atomar speichern, mit Sicherung der letzten guten Fassung.

        Frueher: `path.write_text(...)`. Das kuerzt die Datei auf 0 und schreibt neu
        — wird der Prozess in genau diesem Moment beendet (hartes Kill beim Update,
        Absturz, Stromausfall), bleibt eine leere oder halbe Datei zurueck. Beim
        naechsten Start hiess das: alles auf Vorgaben, Lizenzschluessel weg. Genau
        das ist mehrfach passiert, weil `settings.save()` an ueber einem Dutzend
        Stellen laeuft (Fensterposition, Profilwechsel, Hotkeys …) — die Chance,
        ausgerechnet dabei getroffen zu werden, ist ueber den Tag nicht klein.

        Jetzt: erst vollstaendig in eine Nebendatei schreiben, auf die Platte
        zwingen (`fsync` — ohne das steht der Inhalt nur im Cache und ein
        Stromausfall liefert eine Datei voller Nullen), dann `os.replace`. Das ist
        auf NTFS wie auf ext4 atomar: Es gibt nur die alte ODER die neue Fassung,
        nie etwas dazwischen.
        """
        path = path or SETTINGS_PATH
        try:
            inhalt = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        except Exception:
            log.exception("Einstellungen liessen sich nicht serialisieren — nichts geschrieben.")
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Sicherung der bisherigen Fassung, BEVOR sie ersetzt wird. Sie ist die
            # Rettung fuer den Fall, dass die neue Datei kaputt geht — und der
            # Grund, warum ein Reset nicht mehr endgueltig ist.
            if path.is_file() and path.stat().st_size > 0:
                try:
                    _backup_path(path).write_bytes(path.read_bytes())
                except Exception:
                    log.debug("Sicherung der Einstellungen fehlgeschlagen.", exc_info=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(inhalt)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            log.exception("Einstellungen konnten nicht gespeichert werden: %s", path)

    @classmethod
    def load(cls, path: Path | None = None) -> "UserSettings":
        path = path or SETTINGS_PATH
        settings = cls()
        data = _lies_json(path)
        if data is None and path.is_file():
            # Kaputte Datei NICHT stillschweigend durch Vorgaben ersetzen: Der
            # naechste `save()` wuerde die Vorgaben zementieren und alles waere
            # endgueltig weg. Stattdessen die Sicherung ziehen und die kaputte
            # Fassung zur Ansicht aufheben.
            sicherung = _lies_json(_backup_path(path))
            if sicherung is not None:
                log.warning("settings.json war unbrauchbar — Sicherung von %s "
                            "wiederhergestellt.", _backup_path(path).name)
                data = sicherung
            else:
                try:
                    path.replace(path.with_name(path.name + ".kaputt"))
                    log.error("settings.json unbrauchbar und keine Sicherung da — "
                              "als settings.json.kaputt beiseitegelegt, starte mit "
                              "Vorgaben.")
                except Exception:
                    log.debug("Kaputte settings.json nicht verschiebbar.", exc_info=True)
        if data is None:
            return settings
        for section_name, section_data in (data or {}).items():
            section = getattr(settings, section_name, None)
            if section is None or not isinstance(section_data, dict):
                continue
            for key, value in section_data.items():
                if hasattr(section, key):
                    setattr(section, key, value)
        # Migration v1.10.1 → v1.10.2: Insights-Ignores lagen kurz in einem eigenen
        # Feld advice_dismissed ({"falsch => richtig": ts}); jetzt gibt es nur noch
        # die eine sichtbare Liste dictionary_ignores.
        legacy = (data or {}).get("output", {})
        if isinstance(legacy, dict):
            dismissed = legacy.get("advice_dismissed")
            if isinstance(dismissed, dict):
                known = {str(i).strip().lower() for i in settings.output.dictionary_ignores}
                for pair in dismissed:
                    if str(pair).strip().lower() not in known:
                        settings.output.dictionary_ignores.append(str(pair))
        # Migration 5.6.0 → 5.7.0: „base" war die alte VORGABE fuer die
        # Startwort-Pruefung und nachweislich kaputt — sie brauchte 437 ms im
        # Audio-Callback und liess dabei die halbe Aufnahme fallen. Wer den Wert
        # nie angefasst hat, bekommt den reparierten Weg; „tiny" und „small"
        # bleiben unangetastet, denn die hat man bewusst gewaehlt.
        if (data or {}).get("freihand", {}).get("modell") == "base":
            settings.freihand.modell = "diktat"
            log.info("Freihand-Pruefmodell von 'base' auf 'diktat' umgestellt "
                     "(alte Vorgabe, siehe FreihandSettings).")
        return settings

    # -- Anwendung auf die technische Config ---------------------------------------

    def apply_to(self, config) -> None:
        """Legt die UI-Einstellungen auf die geladene AppConfig."""
        config.hotkey.dictate = self.recording.hotkey
        if self.recording.microphone is not None:
            config.audio.device = self.recording.microphone
        config.audio_focus.blocked_devices = list(self.recording.blocked_devices or [])
        config.stt.language = self.general.language
        config.stt.device = "auto" if self.advanced.prefer_gpu else "cpu"
        config.audio_focus.mode = self.audio_focus.mode
        # Regelbare Restlautstaerke: greift fuer Soft- UND Hard-Duck (der Nutzer
        # steuert genau einen Wert, statt zwei getrennte config-Konstanten).
        level = max(0.0, min(1.0, float(self.audio_focus.duck_level)))
        config.audio_focus.duck_level = level
        config.audio_focus.hard_duck_level = level
        if self.output.trigger_word.strip():
            config.command.trigger_word = self.output.trigger_word.strip()
