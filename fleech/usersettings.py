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

log = logging.getLogger(__name__)

SETTINGS_DIR = user_data_dir()
SETTINGS_PATH = SETTINGS_DIR / "settings.json"


# Beschriftung fuer „kein Profil von Hand gewaehlt" — es gilt, was die Apps-Seite
# fuer die gerade fokussierte Anwendung vorsieht. Hiess bis v4.9.2 „Automatisch
# (nach App)"; das las sich wie eine Automatik, die selbst entscheidet, statt wie
# der Standard, den man dort hinterlegt hat.
APP_STANDARD = "App-Standard"


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
    # Mathe-Hotkeys sind seit v3.0.0 nicht mehr belegt: Formeln laufen ueber die
    # automatische Erkennung, es gibt keinen Umschalt-Modus mehr. Die Felder
    # bleiben (leer) erhalten, damit alte settings.json weiter laden.
    math_hotkey: str = ""
    math_toggle_hotkey: str = ""
    # KI-Prompting-Umschalt: rastet den Speech-Prompt-Engineer ein/aus (Diktat →
    # strukturierter Prompt). Exklusiv zum Mathe-Latch. Default: Ctrl+Alt+P.
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
    """Aktuelle Stufe aus den drei technischen Feldern ableiten."""
    if not m.enabled:
        return "off"
    return "auto"


def apply_math_level(m: MathSettings, level: str) -> None:
    """Stufe → die drei technischen Felder.

    Seit v3.0.0 gibt es nur noch „an" oder „aus": Der Umschalt-Weg ueber ein
    Cloud-Modell ist entfallen, Formeln entstehen immer im lokalen Parser."""
    if level == "off":
        m.enabled = False
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
    # App-Profile: rohe Zeilen "prozess.exe => minimal|standard|strong" — der
    # Eingriffsgrad wird fuer Diktate in diese App automatisch uebersteuert.
    app_modes: list = field(default_factory=list)
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


def _default_profiles() -> list:
    """Vorgefertigte Profile. Ein Profil = Name + Eingriffsgrad + Stil-Tags +
    zugewiesene Prozessnamen. Das Standardprofil (default=True) ist der globale
    Fallback ("Alle"): es greift, wenn der Ziel-App kein Profil zugewiesen ist —
    intervention "" heisst dort "wie Einstellungen → Ausgabe".
    """
    return [
        {"name": "Standard", "default": True, "intervention": "", "tags": [], "apps": []},
        # command="off": im beruflichen Umfeld (Meeting, Grossraum) ist ein laut
        # gesprochenes Safe-Word unpassend und faellt bei Fashion-/Textilthemen sogar
        # zufaellig — der »-Knopf in der Pille bleibt als leiser Weg.
        {"name": "Geschäftlich", "intervention": "strong",
         "tags": ["professioneller, sachlicher Ton"], "apps": [], "command": "off"},
        {"name": "Privat", "intervention": "minimal",
         "tags": [], "apps": []},
        {"name": "Coding", "intervention": "minimal", "tags": [], "apps": []},
        # mode="math": Diktate in zugewiesene Apps laufen automatisch im Formel-Modus.
        {"name": "Mathe", "intervention": "standard", "tags": [], "apps": [],
         "mode": "math"},
        # Die beiden UMFORMULIERENDEN Profile. Sie sind bewusst KEINER App fest
        # zugewiesen: ob dieses Diktat eine Mail wird, weiss nur der Sprecher —
        # deshalb ueber den Profil-Knopf in der Pille waehlbar.
        {"name": "E-Mail", "intervention": "strong", "tags": [], "apps": [],
         "mode": "email", "command": "off"},
        {"name": "KI-Prompt", "intervention": "standard", "tags": [], "apps": [],
         "mode": "prompt", "command": "off", "auto_send": False},
        # Der leisere Bruder des KI-Prompts: nur destillieren, keine Rolle und
        # keinen Kontext erfinden. Fuer Zuruf an eine KI oft der bessere Weg —
        # dort steht der Kontext ohnehin schon im Gespraech.
        {"name": "Zusammenfassen", "intervention": "standard", "tags": [], "apps": [],
         "mode": "summary", "command": "off"},
    ]


def ensure_default_profile(items: list) -> None:
    """Migration: fehlende Standard-Profile nachziehen (additiv, nie loeschend).

    Bestehende Installationen haben die beiden umformulierenden Profile noch nicht.
    Sie werden ergaenzt, wenn kein Profil dieses Format traegt — wer sie geloescht
    oder umbenannt hat, bekommt sie also nicht wieder aufgedraengt, solange das
    Format belegt ist."""
    if not any(isinstance(i, dict) and i.get("default") for i in items):
        items.insert(0, {"name": "Standard", "default": True, "intervention": "",
                         "tags": [], "apps": []})
    vorhandene = {profile_mode(i) for i in items if isinstance(i, dict)}
    for vorlage in _default_profiles():
        mode = profile_mode(vorlage)
        if mode in REWRITING_FORMATS and mode not in vorhandene:
            items.append(dict(vorlage))


@dataclass
class ProfileOverrides:
    """Was ein aktives App-Profil am Standardverhalten aendert.

    Bewusst ein Dataclass statt eines Tupels: mit dem Safe-Word-Schalter waeren es
    vier positionale Werte — dort hoert die Lesbarkeit auf."""

    intervention: str | None = None  # None = globale Einstellung (Ausgabe)
    style_hints: list | None = None  # Stil-Tags fuer den System-Prompt
    mode_slot: str = ""              # "" | "math" | "prompt"
    command: str = ""                # "" = wie Einstellungen | "on" | "off"
    # Nach dem Einfuegen zusaetzlich Enter druecken — schickt die Nachricht ab.
    # BEWUSST je Profil und BEWUSST aus als Standard: In einem KI-Chat spart es den
    # Handgriff, in einer E-Mail waere es ein Versehen mit Folgen.
    auto_send: bool = False

    def command_allowed(self, global_enabled: bool) -> bool:
        """Darf in diesem Kontext ein GESPROCHENES Safe-Word Befehle ausloesen?
        Der »-Knopf bleibt davon unberuehrt — er ist der bewusste, leise Weg."""
        if self.command == "off":
            return False
        if self.command == "on":
            return True
        return bool(global_enabled)


def profile_in_quickswitch(item: dict) -> bool:
    """Erscheint dieses Profil im Schnellwechsel (Pillen-Punkt, Hotkey, Liste)?

    Default TRUE, damit bestehende settings.json unveraendert weiterlaufen. Wer
    acht Profile pflegt, aber nur zwei im Alltag umschaltet, blendet den Rest hier
    aus — durchschalten wird sonst zur Zumutung, und genau daran scheitert die
    Idee „eine Taste, ein Profil".
    """
    return bool(item.get("quick", True))


def quickswitch_profiles(items: list) -> list:
    """Namen der Profile fuer den Schnellwechsel, in Listenreihenfolge."""
    return [str(i.get("name", "")) for i in (items or [])
            if isinstance(i, dict) and str(i.get("name", "")).strip()
            and profile_in_quickswitch(i)]


def quickswitch_for_app(items: list, app_quick: dict, app: str) -> list:
    """Schnellwechsel-Profile fuer GENAU diese App, in Listenreihenfolge.

    Ohne Eintrag fuer die App gilt die globale Auswahl — der Normalfall, und der
    Grund, warum bestehende Einstellungen unveraendert weiterlaufen.

    Namen, die es nicht mehr gibt (Profil umbenannt oder geloescht), werden still
    uebergangen: Die Alternative waere ein Schnellwechsel, der auf ein totes Profil
    zeigt und beim Tippen scheinbar nichts tut. Bleibt am Ende nichts uebrig,
    faellt die Funktion auf die globale Auswahl zurueck — eine App ohne jedes
    Profil koennte man sonst nur noch ueber das Hauptfenster verlassen.
    """
    alle = quickswitch_profiles(items)
    schluessel = str(app or "").strip().lower()
    if not schluessel or not isinstance(app_quick, dict):
        return alle
    erlaubt = app_quick.get(schluessel)
    if not isinstance(erlaubt, list) or not erlaubt:
        return alle
    namen = {str(n).lower() for n in erlaubt}
    gefiltert = [n for n in alle if n.lower() in namen]
    return gefiltert or alle


def profile_command_mode(item: dict) -> str:
    """Safe-Word-Schalter eines Profils: "" (wie Einstellungen) | "on" | "off"."""
    value = str(item.get("command", "") or "").lower()
    return value if value in ("on", "off") else ""


# Trenner zwischen Prozessname und optionaler Titel-Bedingung in einem apps-Eintrag:
# "Code.exe :: Fleech". Bewusst ein String-Format statt eines verschachtelten Dicts —
# so bleiben alte settings.json ohne jede Migration gueltig (Eintraege ohne "::"
# verhalten sich exakt wie bisher) und die Liste bleibt von Hand lesbar.
APP_RULE_SEP = "::"


def parse_app_rule(entry) -> tuple[str, str]:
    """Ein apps-Eintrag → (Prozessname, Titel-Bedingung). Bedingung "" = keine."""
    text = str(entry or "").strip()
    if APP_RULE_SEP not in text:
        return text, ""
    process, _, title = text.partition(APP_RULE_SEP)
    return process.strip(), title.strip()


def format_app_rule(process: str, title: str = "") -> str:
    """(Prozessname, Titel-Bedingung) → Eintrag fuer die apps-Liste."""
    process = (process or "").strip()
    title = (title or "").strip()
    return f"{process} {APP_RULE_SEP} {title}" if title else process


def app_rule_matches(entry, process: str, title: str) -> bool:
    """Passt ein apps-Eintrag auf die aktuelle Ziel-App?

    Prozessname exakt (case-insensitiv), Titel als Teilstring. Teilstring statt
    Regex ist Absicht: Die Bedingung tippt ein Mensch ab, der den Fenstertitel vor
    sich sieht — ein halbfertiger Regex wuerde stillschweigend nie oder immer
    greifen, und beides faellt im Alltag erst spaet auf."""
    want_process, want_title = parse_app_rule(entry)
    if not want_process or want_process.lower() != (process or "").lower():
        return False
    if not want_title:
        return True
    return want_title.lower() in (title or "").lower()


# Ausgabeformate eines Profils: WAS aus dem Diktat wird, nicht nur wie stark
# geglaettet wird. Ein Diktat ist je nach Ziel etwas anderes — dieselbe Aeusserung
# gehoert in einer Mail anders formuliert als in einem KI-Chat.
PROFILE_FORMATS = [
    ("", "Diktat (Standard)"),
    ("summary", "Stichpunkte"),
    ("email", "E-Mail"),
    ("prompt", "KI-Prompt"),
    ("math", "Formeln"),
]
# Formate, die den Text ueber einen eigenen System-Prompt neu formulieren.
REWRITING_FORMATS = ("summary", "email", "prompt")


def profile_mode(item: dict) -> str:
    """Ausgabeformat eines Profils: "" | "math" | "prompt" | "email" (exklusiv).

    Migration: aeltere Profile hatten ein Bool-Feld "math" statt "mode"."""
    mode = str(item.get("mode", "") or "").lower()
    if mode in ("math", "prompt", "email", "summary"):
        return mode
    return "math" if item.get("math") else ""


@dataclass
class ProfilesSettings:
    """App-Profile (eigener Tab im Hauptfenster): pro Ziel-App automatisch einen
    anderen Eingriffsgrad fahren — z. B. minimal im Code-Editor, strong in Word."""

    enabled: bool = True                 # globaler Schalter
    items: list = field(default_factory=_default_profiles)
    # Von Hand gewaehltes Profil (Pillen-Punkt oder Profil-Hotkey). "" = automatisch
    # nach App. Persistent, weil es eine bewusste Entscheidung ist: Wer im
    # E-Mail-Profil arbeitet, will nach einem Neustart nicht stillschweigend wieder
    # normal diktieren — genau das faellt erst am fertigen Text auf.
    active: str = ""
    # Schnellwechsel je App: {"claude.exe": ["KI-Prompt", "Zusammenfassen"]}.
    # Fehlt eine App (Normalfall), gelten die global freigegebenen Profile — alte
    # settings.json laufen dadurch unveraendert weiter, keine Migration.
    #
    # Zweck: Beim Durchtippen des Profil-Hotkeys will man in Claude nicht durch
    # „E-Mail" und „Formeln" hindurch, sondern zwischen den zwei Profilen wechseln,
    # die dort ueberhaupt Sinn ergeben. Der Prozessname ist der Schluessel (klein
    # geschrieben) — Titel-Bedingungen bleiben der App-Zuordnung vorbehalten, hier
    # waeren sie eine Genauigkeit, die niemand pflegen will.
    app_quick: dict = field(default_factory=dict)


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
