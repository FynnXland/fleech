"""App-Profile: Regeln, Farben, Schnellwechsel, Vorlagen.

Ein Profil ist ein benannter Satz Abweichungen vom Standardverhalten (Eingriffsgrad,
Stil-Tags, Ausgabeformat, Sprache, Safe-Word) plus die Frage, WANN er gilt — per
Prozessname und optionaler Titel-Bedingung (`app_rule_matches`) oder von Hand ueber
den Schnellwechsel.

Lag bis 5.5.1 mitten in usersettings.py. Dort war es der groesste zusammenhaengende
Block und das einzige Thema mit eigener Logik statt blosser Feldablage — der Rest
der Datei sind Dataclasses mit Vorgabewerten.

Richtung der Abhaengigkeit: usersettings importiert von hier, nie umgekehrt. Dieses
Modul kennt weder Pfade noch das Speichern.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Beschriftung fuer „kein Profil von Hand gewaehlt" — es gilt, was die Apps-Seite
# fuer die gerade fokussierte Anwendung vorsieht. Hiess bis v4.9.2 „Automatisch
# (nach App)"; das las sich wie eine Automatik, die selbst entscheidet, statt wie
# der Standard, den man dort hinterlegt hat.
APP_STANDARD = "App-Standard"


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
        {"name": "Stichpunkte", "intervention": "standard", "tags": [], "apps": [],
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
    # Diktiersprache dieses Profils ("" = wie Einstellungen). Steuert die
    # Erkennung, den sprachgebundenen Teil der Guards und die Zielsprache der
    # umformulierenden Formate.
    sprache: str = ""

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


def profile_sprache(item: dict) -> str:
    """Diktiersprache eines Profils: "" (wie Einstellungen) | "de" | "en" | "auto"."""
    wert = str((item or {}).get("sprache", "") or "").lower()
    return wert if wert in {"de", "en", "auto"} else ""


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
# Diktiersprachen. "" = automatisch erkennen (Whisper kann das) — sinnvoll fuer
# wechselnde Sprachen, kostet aber Genauigkeit bei kurzen Diktaten, weil die
# Erkennung dann selbst raten muss.
PROFILE_SPRACHEN = [
    ("", "Wie Einstellungen"),
    ("de", "Deutsch"),
    ("en", "Englisch"),
    ("auto", "Automatisch erkennen"),
]


PROFILE_FORMATS = [
    ("", "Diktat (Standard)"),
    ("summary", "Stichpunkte"),
    ("email", "E-Mail"),
    ("prompt", "KI-Prompt"),
    ("math", "Formeln"),
]
# Formate, die den Text ueber einen eigenen System-Prompt neu formulieren.
REWRITING_FORMATS = ("summary", "email", "prompt")

# Farbe je Profil — waehlbar, und JEDES Profil hat eine. Vorher trugen nur die
# vier Format-Profile einen Punkt; Profile ohne Format blieben farblos, und in
# der Liste sah es aus, als fehlte dort etwas.
#
# Die Palette ist bewusst kurz und auf den dunklen Grund abgestimmt: Alle Toene
# liegen in aehnlicher Helligkeit, damit keiner heraussticht und keiner
# verschwindet. Ein freier Farbwaehler waere schlechter — auf #16181C sind die
# meisten Farben entweder unsichtbar oder grell.
#
# OHNE die Brand-Akzentfarbe #35C0D8. Die steht im ganzen Programm fuer
# „ausgewaehlt"; als Profilfarbe gelesen wirkte ein Punkt darin wie eine
# Markierung — das wurde bei den Format-Farben schon einmal genau so gemeldet.
# Sie ist ausserdem die Farbe des Freihand-Rings an der Pille: Ein tuerkises
# Profil haette dort zwei fast gleiche Ringe ergeben.
PROFIL_FARBEN = [
    ("#AA78F0", "Violett"),
    ("#E8A13C", "Amber"),
    ("#6E86C8", "Blau"),
    ("#7FD1A6", "Gruen"),
    ("#A8C86E", "Limette"),
    ("#E08585", "Rot"),
    ("#D982C0", "Pink"),
    ("#9AA6B2", "Grau"),
]

# Reserviert und deshalb nicht waehlbar — siehe Kommentar oben.
ACCENT_RESERVIERT = "#35C0D8"

# Welche Farbe ein Format MITBRINGT, solange nichts eigenes gewaehlt wurde. Damit
# sehen bestehende Installationen nach dem Update genau aus wie vorher.
_FORMAT_FARBEN = {"math": "#AA78F0", "prompt": "#E8A13C",
                  "email": "#6E86C8", "summary": "#7FD1A6"}


def profile_color(item: dict) -> str:
    """Die Farbe dieses Profils — immer eine, nie leer.

    Drei Stufen, in dieser Reihenfolge:
      1. selbst gewaehlt (`color`)
      2. die Farbe des Ausgabeformats — so bleibt alles wie vorher, wer nie eine
         Farbe waehlt, merkt vom Umbau nichts
      3. aus dem Namen abgeleitet, stabil

    Stufe 3 ist der Grund, warum kein Profil mehr farblos ist. Sie muss stabil
    sein: Wuerde dieselbe Liste zweimal verschiedene Farben ergeben, waere der
    Punkt keine Wiedererkennung, sondern Rauschen. Deshalb aus dem NAMEN und
    nicht aus der Listenposition — Umsortieren darf nichts umfaerben.
    """
    if not isinstance(item, dict):
        return PROFIL_FARBEN[-1][0]
    gewaehlt = str(item.get("color", "") or "").strip()
    if gewaehlt in {f for f, _ in PROFIL_FARBEN}:
        return gewaehlt
    vom_format = _FORMAT_FARBEN.get(profile_mode(item))
    if vom_format:
        return vom_format
    name = str(item.get("name", "") or "")
    if not name:
        return PROFIL_FARBEN[-1][0]
    # Ohne die Format-Farben, damit ein namensbasiertes Profil nicht zufaellig
    # aussieht wie ein E-Mail- oder Formel-Profil.
    frei = [f for f, _ in PROFIL_FARBEN if f not in _FORMAT_FARBEN.values()]
    return frei[sum(name.encode("utf-8")) % len(frei)]


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
    # Schnellwechsel je App: {"claude.exe": ["KI-Prompt", "Stichpunkte"]}.
    # Fehlt eine App (Normalfall), gelten die global freigegebenen Profile — alte
    # settings.json laufen dadurch unveraendert weiter, keine Migration.
    #
    # Zweck: Beim Durchtippen des Profil-Hotkeys will man in Claude nicht durch
    # „E-Mail" und „Formeln" hindurch, sondern zwischen den zwei Profilen wechseln,
    # die dort ueberhaupt Sinn ergeben. Der Prozessname ist der Schluessel (klein
    # geschrieben) — Titel-Bedingungen bleiben der App-Zuordnung vorbehalten, hier
    # waeren sie eine Genauigkeit, die niemand pflegen will.
    app_quick: dict = field(default_factory=dict)
