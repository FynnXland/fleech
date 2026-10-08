"""README-Medien für Fleech: GIFs, Screenshots und Social Preview — reproduzierbar.

Das Skript rendert die ECHTEN Qt-Widgets von Fleech (Pille, Hauptfenster,
Einstellungen) Bild für Bild in doppelter Auflösung und setzt daraus mit ffmpeg
GIFs zusammen. Die Beispieltexte sind echte Ausgaben von Fleechs Pipeline mit dem
lokalen Modell (gemma3:4b über Ollama); sie liegen in `examples.json` neben diesem
Skript, damit jeder Neubau nachprüfbar dieselben Texte zeigt.

Aufruf aus dem Projektordner, mit dem Python der Fleech-Umgebung:

    python docs/media/make_media.py                 # alle Szenen aus examples.json
    python docs/media/make_media.py hero tour       # nur diese Szenen
    python docs/media/make_media.py --beispiele     # examples.json neu erzeugen
    python docs/media/make_media.py --liste         # verfügbare Szenen

`--beispiele` braucht ein laufendes Ollama mit gemma3:4b (Adresse aus config.yaml).
ffmpeg kommt aus dem PATH oder aus der Umgebungsvariable FFMPEG.

Sicherheit — alles hier landet in einem öffentlichen Repository:

* APPDATA/LOCALAPPDATA (bzw. XDG_*) zeigen VOR dem ersten fleech-Import auf einen
  frischen Temp-Ordner; das Skript bricht ab, wenn Fleechs Datenordner nicht darin
  liegt. Echte Einstellungen, Verläufe oder Logs werden nie gelesen.
* Prozessliste, Vordergrundfenster und Schlüsselbund sind durch Attrappen ersetzt
  (die Apps-Seite listet sonst die laufenden Programme dieses Rechners, die
  KI-Seite zeigt einen gespeicherten API-Schlüssel maskiert an).
* Anzeigename ist „Alex“ — ohne ihn nähme die Startseite den Kontonamen.
* Kein Fenster erscheint auf dem Bildschirm (WA_DontShowOnScreen), alle Timer
  werden angehalten und von Hand weitergeschaltet.
"""

from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parents[1]
BEISPIELE = HIER / "examples.json"
ASSETS = ROOT / "assets"
SKALIERUNG = 2          # alles in doppelter Auflösung; das README zeigt halbe Breite
FPS = 20

# -- Sandbox: MUSS vor jedem fleech-Import stehen ------------------------------------
# Die Datenpfade werden beim Laden der Module festgelegt (config, history, kontext,
# prompts, usersettings) — später umgebogen wäre es zu spät.
_SANDBOX = Path(tempfile.mkdtemp(prefix="fleech-media-")).resolve()


def _aufraeumen() -> None:
    """Sandbox wieder löschen. Offene SQLite-Verbindungen (Verlauf, Gedächtnis)
    hängen an Objekten in Referenzzyklen — erst einsammeln, sonst bleibt die Datei
    unter Windows gesperrt und der Ordner liegen."""
    import gc

    for _ in range(5):
        gc.collect()
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        if not _SANDBOX.exists():
            return
        time.sleep(0.3)
    print(f"Hinweis: Temp-Ordner blieb liegen: {_SANDBOX}")


atexit.register(_aufraeumen)
for _var in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
             "XDG_CACHE_HOME"):
    os.environ[_var] = str(_SANDBOX)
# getpass.getuser() liest diese Variablen zuerst — zweites Netz neben dem Anzeigenamen.
for _var in ("LOGNAME", "USER", "LNAME", "USERNAME"):
    os.environ[_var] = "alex"
# Feste 2x-Skalierung, unabhängig vom Monitor dieses Rechners.
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = str(SKALIERUNG)
sys.path.insert(0, str(ROOT))


def _pruefe_sandbox() -> None:
    """Abbrechen, falls irgendein Datenpfad von Fleech außerhalb der Sandbox liegt."""
    from fleech import config, history
    from fleech.platformpaths import user_data_dir

    for pfad in (user_data_dir(), config.USER_DIR, history.DB_PATH):
        pfad = Path(pfad).resolve()
        if _SANDBOX not in pfad.parents:
            raise SystemExit(f"Abbruch: Datenpfad außerhalb der Sandbox: {pfad.name}")


_pruefe_sandbox()


# =====================================================================================
# Beispielsätze. Hier stehen nur die ROHTEXTE (das „Gesprochene“); was Fleech daraus
# macht, erzeugt ausschließlich `--beispiele` und speichert es in examples.json.
# =====================================================================================

HERO_ROH = {
    "de": "Hallo zusammen, ähm, ich schicke euch die Präsentation bis Donnerstag, äh, "
          "nein, bis Freitagmittag, dann können wir sie am Montag durchgehen.",
    "en": "Hey team, um, I'll send the slides by Thursday, uh, actually by Friday noon, "
          "and we can go through them on Monday.",
}

# Ein Diktat, vier Profile. Nur Deutsch: Die umformulierenden Formate (prompts/email.md,
# summary.md, prompt_engineer.md) antworten auf Deutsch — englisches Diktat käme dort
# als deutsche Mail heraus (mit --beispiele geprüft, siehe examples.json „profiles._en“).
PROFIL_ROH = ("Also, ähm, die neue Website soll nächste Woche online gehen, vorher "
              "müssen wir aber noch die Texte prüfen und, äh, die Bilder komprimieren.")
PROFIL_ROH_EN = ("Um, so the new website should go live next week, but before that we "
                 "still need to check the copy and, uh, compress the images.")
PROFILE_IM_FILM = ("Standard", "E-Mail", "Stichpunkte", "KI-Prompt")

# Safe-Word-Befehl: erst ein Diktat, dann „Kimono, …“ in einer zweiten Aufnahme.
BEFEHL_ROH = {
    "de": ("Hey Leute, das wird morgen nix mit dem Meeting, ich bin krank.",
           "Kimono, mach den letzten Satz höflicher."),
    "en": ("Hey guys, I can't make it to the meeting tomorrow, I'm sick.",
           "Kimono, make the last sentence more polite."),
}

# Formeln: deterministischer Parser (fleech/formula.py), kein Modell. Der zweite Satz
# ist absichtlich mehrdeutig — Fleech rät und sagt es (amber Blase).
MATHE_ROH = (
    "Nach Pythagoras gilt a Quadrat plus b Quadrat gleich c Quadrat.",
    "Und das Ergebnis ist Wurzel aus x Quadrat plus c.",
)

# Erfundener Verlauf für Hauptfenster/Insights: (Tage zurück, Uhrzeit, App, Profil,
# Sprache, Rohtext). Zwei Lücken (Tag 5 und 11) für eine glaubhafte Serie.
# „kubernetis“ ist die eingepflanzte, wiederkehrende Fehlerkennung — daraus macht
# Insights den Vorschlag „kubernetis → Kubernetes“ als Wörterbuch-Regel.
VERLAUF_ROH = [
    (16, "09:05", "notepad.exe", "Standard", "de",
     "Einkaufsliste für morgen: Milch, Eier, Haferflocken und, äh, Kaffee."),
    (16, "11:20", "thunderbird.exe", "E-Mail", "de",
     "hallo frau berger, danke für die unterlagen, ich schaue sie mir bis freitag an und "
     "melde mich dann."),
    (16, "15:40", "code.exe", "Coding", "de",
     "TODO: Fehlerbehandlung für leere Eingaben ergänzen."),
    (15, "08:50", "obsidian.exe", "Standard", "de",
     "Idee fürs Wochenende: ähm, Fahrradtour an der Elbe und danach Picknick am Wasser."),
    (15, "10:15", "winword.exe", "Geschäftlich", "de",
     "Im dritten Quartal ist der Umsatz um, äh, rund acht Prozent gestiegen, vor allem "
     "durch das Online-Geschäft."),
    (15, "14:30", "firefox.exe", "Standard", "en",
     "What's the difference between a process and a thread? Explain it with a simple "
     "example."),
    (15, "16:45", "notepad.exe", "Standard", "de",
     "Der Cluster läuft auf kubernetis, die Pods starten aber noch ziemlich langsam."),
    (14, "09:30", "thunderbird.exe", "E-Mail", "de",
     "kurze info an alle, das meeting morgen verschiebt sich auf elf uhr, der raum bleibt "
     "gleich."),
    (14, "13:10", "obsidian.exe", "Stichpunkte", "de",
     "Für den Umzug brauchen wir noch Kartons, einen Transporter fürs Wochenende und, "
     "ähm, jemanden, der beim Tragen hilft."),
    (14, "17:20", "code.exe", "Coding", "de",
     "Der Test schlägt fehl, weil die Zeitzone nicht gesetzt ist."),
    (13, "08:40", "notepad.exe", "Standard", "de",
     "Termin beim Zahnarzt am Dienstag um, äh, halb neun, vorher noch die "
     "Versichertenkarte suchen."),
    (13, "11:55", "firefox.exe", "KI-Prompt", "de",
     "Erklär mir, wie Indizes in SQLite funktionieren, am besten mit einem kurzen "
     "Beispiel."),
    (13, "15:05", "winword.exe", "Geschäftlich", "de",
     "Wir empfehlen, das Projekt in zwei Phasen umzusetzen, ähm, zuerst die "
     "Schnittstellen und danach die Oberfläche."),
    (13, "19:30", "obsidian.exe", "Standard", "de",
     "Kapitel drei war, ähm, deutlich spannender als erwartet."),
    (12, "09:10", "thunderbird.exe", "E-Mail", "de",
     "hallo sam, danke für die schnelle antwort, dienstag passt mir gut, sagen wir "
     "vierzehn uhr."),
    (12, "10:40", "code.exe", "Coding", "de",
     "Die Funktion sollte lieber eine leere Liste zurückgeben statt None."),
    (12, "14:20", "notepad.exe", "Standard", "de",
     "Für den Release brauchen wir noch Screenshots, ähm, das Changelog und die neuen "
     "Übersetzungen."),
    (12, "16:50", "obsidian.exe", "Standard", "de",
     "Wir migrieren die Datenbank nächste Woche auf kubernetis, das Backup läuft vorher "
     "noch einmal komplett durch."),
    (10, "08:30", "notepad.exe", "Standard", "de",
     "Ähm, heute erledigen: Steuererklärung abschicken, Reifenwechsel buchen, Paket zur "
     "Post bringen."),
    (10, "12:15", "firefox.exe", "Standard", "en",
     "Quick question: does the store close at six or at eight on Saturdays?"),
    (10, "15:35", "winword.exe", "Geschäftlich", "de",
     "Die Ergebnisse der Umfrage zeigen, dass, ähm, zwei Drittel der Befragten die neue "
     "Funktion täglich nutzen."),
    (10, "18:05", "thunderbird.exe", "E-Mail", "de",
     "hallo zusammen, ich bin ab montag wieder im büro und bringe kuchen mit."),
    (9, "09:45", "obsidian.exe", "Stichpunkte", "de",
     "Beim Gespräch heute ging es um das Budget, die neue Stelle im Support und, äh, den "
     "Termin für die Weihnachtsfeier."),
    (9, "11:30", "code.exe", "Coding", "de",
     "Refactoring: die Konfiguration aus der Klasse herausziehen und als eigenes Modul "
     "anlegen."),
    (9, "14:50", "notepad.exe", "Standard", "de",
     "Rezept für Sonntag: Kürbissuppe mit Ingwer, ähm, Kokosmilch und ein bisschen Chili."),
    (9, "16:10", "firefox.exe", "KI-Prompt", "de",
     "Schreib mir eine kurze Zusammenfassung der wichtigsten Unterschiede zwischen REST "
     "und GraphQL."),
    (8, "10:05", "thunderbird.exe", "E-Mail", "de",
     "hallo herr klein, anbei wie besprochen das angebot, bei fragen melden sie sich gern."),
    (8, "13:40", "winword.exe", "Geschäftlich", "de",
     "Die Kosten für die Wartung liegen bei, äh, etwa zwölftausend Euro im Jahr."),
    (8, "17:15", "obsidian.exe", "Standard", "de",
     "Für das Deployment auf kubernetis brauchen wir noch einen eigenen Namespace und die "
     "Freigabe vom Team."),
    (7, "08:55", "notepad.exe", "Standard", "en",
     "Note to self: call the landlord about the heating before Thursday."),
    (7, "11:25", "code.exe", "Coding", "de",
     "Kommentar: Hier wird der Cache nur geleert, wenn sich die Version geändert hat."),
    (7, "15:00", "obsidian.exe", "Standard", "de",
     "Für den Vortrag lieber mit einer Frage an das Publikum anfangen, ähm, statt mit der "
     "Agenda."),
    (7, "18:40", "firefox.exe", "Standard", "de",
     "Wie lange braucht man mit dem Zug von Hamburg nach Kopenhagen?"),
    (6, "09:20", "thunderbird.exe", "E-Mail", "de",
     "hallo zusammen, die folien für donnerstag liegen jetzt im gemeinsamen ordner, bitte "
     "schaut sie euch vorher an."),
    (6, "12:45", "winword.exe", "Geschäftlich", "de",
     "Als nächsten Schritt schlagen wir einen gemeinsamen Workshop im November vor."),
    (6, "16:30", "notepad.exe", "Standard", "de",
     "Geschenkideen für Mama: ein gutes Kochbuch, Konzertkarten oder, äh, ein Wochenende "
     "an der Ostsee."),
    (4, "08:45", "obsidian.exe", "Standard", "de",
     "Heute zuerst die Präsentation fertig machen, ähm, und danach zum Sport."),
    (4, "10:30", "code.exe", "Coding", "de",
     "Bug: Der Export bricht ab, wenn der Dateiname ein Leerzeichen enthält."),
    (4, "13:55", "thunderbird.exe", "E-Mail", "de",
     "hallo frau öztürk, vielen dank für die einladung, ich komme gern und bringe eine "
     "kollegin mit."),
    (4, "17:05", "firefox.exe", "KI-Prompt", "de",
     "Hilf mir, eine freundliche Absage für ein Vorstellungsgespräch zu formulieren."),
    (3, "09:00", "notepad.exe", "Standard", "en",
     "Packing list: passport, charger, rain jacket and the hiking boots."),
    (3, "11:40", "winword.exe", "Geschäftlich", "de",
     "Zusammenfassend lässt sich sagen, dass die Pilotphase alle Erwartungen erfüllt hat."),
    (3, "14:15", "obsidian.exe", "Stichpunkte", "de",
     "Für die neue Website fehlen noch das Impressum, die Datenschutzerklärung und, ähm, "
     "ein paar Fotos vom Team."),
    (3, "16:55", "code.exe", "Coding", "de",
     "Die Abfrage dauert zu lange, wir sollten einen Index auf die Spalte created_at "
     "legen."),
    (3, "20:10", "notepad.exe", "Standard", "de",
     "Filmabend am Samstag, ähm, Popcorn nicht vergessen."),
    (2, "08:35", "thunderbird.exe", "E-Mail", "de",
     "hallo team, ich bin heute nachmittag beim kunden und ab vier wieder erreichbar."),
    (2, "10:50", "obsidian.exe", "Standard", "de",
     "Leseliste: Atomic Habits zu Ende lesen, danach, ähm, endlich mal Der Schwarm."),
    (2, "13:20", "firefox.exe", "Standard", "en",
     "Can you recommend a good beginner book about photography?"),
    (2, "15:45", "winword.exe", "Geschäftlich", "de",
     "Bitte beachten Sie, dass sich die Lieferzeiten im Dezember um etwa eine Woche "
     "verlängern."),
    (2, "18:30", "notepad.exe", "Standard", "de",
     "Ähm, Erinnerung: Blumen gießen und die Pflanzen auf dem Balkon reinholen, bevor es "
     "friert."),
    (1, "09:15", "code.exe", "Coding", "de",
     "Neue Option hinzufügen, mit der man die Sprache pro Projekt festlegen kann."),
    (1, "11:05", "thunderbird.exe", "E-Mail", "de",
     "liebe lena, danke für dein feedback zum entwurf, ich baue die punkte bis morgen ein."),
    (1, "14:40", "obsidian.exe", "Standard", "de",
     "Mit einem guten Mikrofon steigt die Erkennungsrate deutlich, ähm, vor allem bei "
     "Fachbegriffen."),
    (1, "16:20", "firefox.exe", "KI-Prompt", "de",
     "Schlag mir drei Namen für ein kleines Café am Hafen vor."),
    (1, "19:00", "notepad.exe", "Standard", "de",
     "Abendessen: Pasta mit Tomaten, Basilikum und, äh, Parmesan."),
    (0, "08:40", "obsidian.exe", "Standard", "de",
     "Ähm, Notizen zum Standup: Das Release ist fertig, die Tests laufen und morgen gehen "
     "die Release Notes raus."),
    (0, "10:20", "thunderbird.exe", "E-Mail", "de",
     "hallo zusammen, kurze erinnerung an das teamessen am freitag um neunzehn uhr."),
    (0, "13:05", "code.exe", "Coding", "de",
     "Die Validierung prüft jetzt auch, ob das Datum in der Zukunft liegt."),
    (0, "15:30", "notepad.exe", "Standard", "de",
     "Ähm, also bis Freitag noch die Präsentation fertig machen, äh, nein, bis "
     "Donnerstag, weil Freitag frei ist."),
    (0, "16:45", "obsidian.exe", "Standard", "en",
     "Idea for the blog: a short post about how dictation changed my writing workflow."),
]
# Ein einziger Rückfall im Verlauf (Ollama war kurz weg): zeigt den amber Punkt und
# die Zeile „Rückfälle“ in Insights. Der Text ist dann — wie in der App — der Rohtext.
VERLAUF_RUECKFALL = (7, "18:40")
# App-Zuordnungen, wie man sie auf der Apps-Seite anlegen würde.
APP_ZUORDNUNG = {"E-Mail": ["thunderbird.exe"], "Coding": ["code.exe"],
                 "Geschäftlich": ["winword.exe"]}


# =====================================================================================
# Teil 1: --beispiele — echte Ausgaben über Fleechs Pipeline
# =====================================================================================

class _AttrappeSTT:
    """Steht für faster-whisper: liefert das nächste vorbereitete Transkript."""

    def __init__(self, sprache: str):
        from types import SimpleNamespace

        self.cfg = SimpleNamespace(language=sprache)
        self.warteschlange: list[str] = []
        self.letzter_schwanz_ohne_ton = ""

    def transcribe(self, audio, samplerate, initial_prompt=None):
        return self.warteschlange.pop(0)


class _Mitschrift:
    """Injector-Ersatz: merkt sich, was Fleech einfügen bzw. ersetzen würde."""

    def __init__(self):
        self.log: list = []

    def inject(self, text):
        self.log.append(["inject", text])

    def replace_tail(self, delete_chars, text):
        self.log.append(["replace_tail", delete_chars, text])


def _profil(name: str) -> dict:
    from fleech.profiles import _default_profiles

    return next(p for p in _default_profiles() if p["name"] == name)


def _pipeline(sprache: str = "de", auto_latex: bool = False):
    from fleech.config import load_config
    from fleech.pipeline_factory import build_pipeline
    from fleech.usersettings import UserSettings

    s = UserSettings()                       # Vorgaben, nie .load()
    s.general.display_name = "Alex"
    s.general.language = sprache
    s.math.enabled = s.math.auto_latex = auto_latex
    s.advanced.kontext_lernen = False        # kein Hintergrund-Thread, kein Lernen
    mit = _Mitschrift()
    pipe = build_pipeline(load_config(), s, injector=mit)
    pipe.stt = _AttrappeSTT(sprache)
    # Ein festes „Zielfenster“: Der Kontext-Puffer (für „der letzte Satz“) hängt am
    # Vordergrundfenster — das echte darf hier keine Rolle spielen.
    pipe.tracker._foreground_window = lambda: 1
    return pipe, mit


def _diktiere(pipe, roh: str, profil: str = "Standard", app: str = "notepad.exe") -> dict:
    """Ein Diktat komplett durch `process()` schicken — derselbe Weg wie in der App."""
    import numpy as np

    from fleech.profiles import profile_mode

    item = _profil(profil)
    status_zeilen: list[str] = []
    pipe.status_callback = status_zeilen.append
    pipe.stt.warteschlange = [roh]
    t0 = time.perf_counter()
    status = pipe.process(
        np.zeros(16000 * 3, dtype=np.float32), 16000,
        intervention_override=item.get("intervention") or None,
        style_hints=item.get("tags") or None,
        output_format=profile_mode(item),
        suppress_command=item.get("command") == "off",
        app=app,
    )
    return {"status": status, "mode": pipe.last_mode, "tier": pipe.last_tier,
            "llm_ms": pipe.last_llm_ms or int((time.perf_counter() - t0) * 1000),
            "statuszeilen": status_zeilen}


def _pruefe_ollama() -> str:
    from fleech.config import load_config

    cfg = load_config().llm_cleanup
    if cfg.model != "gemma3:4b":
        raise SystemExit(f"config.yaml nennt {cfg.model!r} — die Medien zeigen gemma3:4b.")
    try:
        with urllib.request.urlopen(cfg.base_url.rstrip("/") + "/api/tags", timeout=5) as r:
            namen = [m["name"] for m in json.load(r).get("models", [])]
    except Exception as exc:
        raise SystemExit(f"Ollama unter {cfg.base_url} nicht erreichbar ({exc}).") from exc
    if cfg.model not in namen:
        raise SystemExit(f"Ollama läuft, aber {cfg.model} ist nicht geladen "
                         f"(ollama pull {cfg.model}).")
    return cfg.model


def erzeuge_beispiele() -> None:
    from fleech.version import APP_VERSION

    modell = _pruefe_ollama()
    daten: dict = {
        "_hinweis": "Erzeugt von make_media.py --beispiele: Rohtext = was gesprochen "
                    "wurde (erfunden), Ausgabe = was Fleechs Pipeline mit dem lokalen "
                    "Modell daraus gemacht hat (temperature 0). Nicht von Hand ändern.",
        "_modell": modell,
        "_fleech": APP_VERSION,
        "_erzeugt": dt.date.today().isoformat(),
    }

    # 1) Hero: ein Diktat je Sprache
    daten["hero"] = {}
    for sprache, roh in HERO_ROH.items():
        pipe, mit = _pipeline(sprache)
        info = _diktiere(pipe, roh)
        daten["hero"][sprache] = {"raw": roh, "text": mit.log[-1][1], **info}
        print(f"hero.{sprache}: {mit.log[-1][1]}")

    # 2) Profile: dasselbe Diktat, vier Profile
    ergebnisse = {}
    for name in PROFILE_IM_FILM:
        pipe, mit = _pipeline("de")
        info = _diktiere(pipe, PROFIL_ROH, name)
        ergebnisse[name] = {"text": mit.log[-1][1], **info}
        print(f"profiles.{name}: {mit.log[-1][1][:70]!r}")
    pipe, _ = _pipeline("en")
    en_mail = pipe.reprocess(PROFIL_ROH_EN, "email")
    daten["profiles"] = {
        "de": {"raw": PROFIL_ROH, "ergebnisse": ergebnisse},
        "_en": {"raw": PROFIL_ROH_EN, "email": en_mail,
                "hinweis": "Die Format-Prompts antworten auf Deutsch — deshalb gibt es "
                           "diese Szene nur auf Deutsch."},
    }

    # 3) Safe-Word-Befehl: zwei Aufnahmen im selben Fenster
    daten["command"] = {}
    for sprache, (diktat, befehl) in BEFEHL_ROH.items():
        pipe, mit = _pipeline(sprache)
        a = _diktiere(pipe, diktat)
        b = _diktiere(pipe, befehl)
        daten["command"][sprache] = {"diktat_raw": diktat, "befehl_raw": befehl,
                                     "status": [a["status"], b["status"]],
                                     "log": mit.log}
        print(f"command.{sprache}: {mit.log}")

    # 4) Formeln (auto_latex an — in der App ein Opt-in unter Einstellungen → Ausgabe)
    daten["math"] = {"de": []}
    for roh in MATHE_ROH:
        pipe, mit = _pipeline("de", auto_latex=True)
        info = _diktiere(pipe, roh, app="obsidian.exe")
        daten["math"]["de"].append({"raw": roh, "text": mit.log[-1][1],
                                    "formeln": [list(f) for f in pipe.last_formulas],
                                    "status": info["status"]})
        print(f"math: {mit.log[-1][1]}  {pipe.last_formulas}")

    # 5) Verlauf für Hauptfenster und Insights
    verlauf = []
    for tag, zeit, app, profil, sprache, roh in VERLAUF_ROH:
        pipe, mit = _pipeline(sprache)
        rueckfall = (tag, zeit) == VERLAUF_RUECKFALL
        if rueckfall:
            info = {"status": "fallback", "mode": "cleanup", "tier": "complex",
                    "llm_ms": 0, "statuszeilen": []}
            text = roh
        else:
            info = _diktiere(pipe, roh, profil, app)
            text = mit.log[-1][1] if mit.log else roh
        verlauf.append({"tag": tag, "zeit": zeit, "app": app, "profil": profil,
                        "sprache": sprache, "raw": roh, "text": text,
                        "mode": info["mode"], "tier": info["tier"],
                        "status": info["status"], "llm_ms": info["llm_ms"]})
        print(f"verlauf {tag:2d} {zeit} {profil:12s} {text[:60]!r}")
    daten["verlauf"] = verlauf

    BEISPIELE.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"→ {BEISPIELE.relative_to(ROOT)}")


# =====================================================================================
# Teil 2: Rendern (Qt)
# =====================================================================================

_APP = None


def _qt():
    """QApplication + Fleechs dunkles Theme + Attrappen für alles Maschinenspezifische."""
    global _APP
    if _APP is not None:
        return _APP
    from PySide6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication(sys.argv[:1])
    dpr = _APP.primaryScreen().devicePixelRatio()
    if abs(dpr - SKALIERUNG) > 0.01:
        print(f"Hinweis: Bildschirm-DPR {dpr} statt {SKALIERUNG} — Bilder werden "
              f"umgerechnet.")

    import getpass

    getpass.getuser = lambda: "alex"
    from fleech.llm import apikeys

    apikeys.lies = lambda *a, **k: ""
    apikeys.speichere = lambda *a, **k: False
    from fleech.ui import windowsfocus

    # Beide werden innerhalb von Funktionen importiert → Modulattribut tauschen reicht.
    windowsfocus.list_visible_window_processes = lambda: ["thunderbird.exe",
                                                          "notepad.exe"]
    windowsfocus.foreground_now = lambda: ("thunderbird.exe", "Posteingang")

    from fleech.ui.desktop import _apply_dark_theme

    _apply_dark_theme(_APP)
    return _APP


def _settings():
    """Vorgabe-Einstellungen wie nach einer frischen Installation (+ Anzeigename)."""
    from fleech.usersettings import UserSettings

    s = UserSettings()
    s.general.display_name = "Alex"
    s.general.onboarding_done = True
    s.overlay.follow_mouse_screen = False
    return s


def _farbe(hexwert: str, alpha: int = 255):
    from PySide6.QtGui import QColor

    c = QColor(hexwert)
    c.setAlpha(alpha)
    return c


def schrift(px: float, gewicht: str = "normal"):
    from PySide6.QtGui import QFont

    f = QFont()
    f.setFamilies(["Segoe UI", "Noto Sans", "DejaVu Sans", "Arial"])
    f.setPixelSize(max(1, round(px)))
    f.setWeight({"normal": QFont.Normal, "halbfett": QFont.DemiBold,
                 "fett": QFont.Bold}[gewicht])
    return f


def _bild(breite: int, hoehe: int, dpr: int = SKALIERUNG, transparent: bool = False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    img = QImage(breite * dpr, hoehe * dpr, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.transparent if transparent else _farbe("#16181C"))
    return img


def _maler(img):
    from PySide6.QtGui import QPainter

    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                     | QPainter.SmoothPixmapTransform)
    return p


# -- Film: Einzelbilder sammeln, mit ffmpeg zum GIF -----------------------------------

def _ffmpeg() -> str:
    pfad = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not pfad:
        raise SystemExit("ffmpeg nicht gefunden — in den PATH legen oder FFMPEG setzen.")
    return pfad


class Film:
    def __init__(self, name: str, fps: int = FPS):
        self.name = name
        self.fps = fps
        self.ordner = _SANDBOX / f"film-{name}"
        shutil.rmtree(self.ordner, ignore_errors=True)
        self.ordner.mkdir(parents=True)
        self.n = 0

    def bild(self, img, mal: int = 1) -> None:
        """Ein Bild anhängen; `mal` > 1 hält es (Duplikate kosten im GIF fast nichts)."""
        erstes = self.ordner / f"f_{self.n:05d}.png"
        img.save(str(erstes))
        self.n += 1
        for _ in range(mal - 1):
            shutil.copyfile(erstes, self.ordner / f"f_{self.n:05d}.png")
            self.n += 1

    def gif(self, ziel: Path, farben: int = 256) -> None:
        vf = (f"split[a][b];[a]palettegen=max_colors={farben}:stats_mode=diff[p];"
              "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
        subprocess.run([_ffmpeg(), "-v", "error", "-y", "-framerate", str(self.fps),
                        "-i", str(self.ordner / "f_%05d.png"), "-vf", vf,
                        "-loop", "0", str(ziel)], check=True)
        print(f"  {ziel.relative_to(ROOT)}: {self.n} Bilder, {self.n / self.fps:.1f} s, "
              f"{ziel.stat().st_size // 1024} KB")


# -- Die echte Pille ------------------------------------------------------------------

def _sprechpegel(t: float, rnd: random.Random) -> float:
    """Künstliche RMS-Hüllkurve: Wortgruppen mit Silbenrhythmus und kurzen Pausen."""
    phase = t % 2.3
    if phase < 0.18 or 1.25 < phase < 1.4:
        return 0.003 + rnd.random() * 0.002
    silbe = 0.5 + 0.5 * math.sin(2 * math.pi * 4.3 * t + rnd.random() * 0.8)
    return 0.02 + 0.10 * silbe * rnd.uniform(0.55, 1.0)


class Pille:
    """Fleechs OverlayWindow samt seiner drei Blasen — nie auf dem Bildschirm."""

    def __init__(self, settings, seed: int = 7):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from fleech.ui.overlay_qt import OverlayWindow

        self.settings = settings
        self.pegel = 0.0
        self.rnd = random.Random(seed)
        self.t = 0.0
        self.ov = OverlayWindow(settings.overlay, level_provider=lambda: self.pegel)
        ov = self.ov
        self.blasen = (ov._caption, ov._profile_caption, ov._tip_caption)
        for w in (ov, *self.blasen):
            w.setAttribute(Qt.WA_DontShowOnScreen, True)
        # Mitten auf den Bildschirm: so schiebt die Blasen-Logik nie etwas an einen Rand.
        geo = QApplication.primaryScreen().availableGeometry()
        ov.move(geo.center().x() - ov.width() // 2, geo.center().y())
        self.ruhe()

    @property
    def breite(self) -> int:
        return self.ov.width()

    @property
    def hoehe(self) -> int:
        return self.ov.height()

    def ruhe(self) -> None:
        """Alle Timer anhalten — die Zeit im Film bestimmt dieses Skript."""
        ov = self.ov
        for t in (ov._wave._timer, ov._hide_timer, ov._fallback_timer, ov._follow_timer,
                  *(b._timer for b in self.blasen)):
            t.stop()
        _qt().processEvents()

    def zustand(self, name: str) -> None:
        from fleech.ui.overlay_qt import AppState

        self.ov.set_app_state(getattr(AppState, name))
        self.ruhe()

    def sprich(self, schritte: int = 1, stumm: bool = False) -> None:
        """Waveform um `schritte` Ticks (je 50 ms) weiterschalten."""
        for _ in range(schritte):
            self.pegel = 0.0 if stumm else _sprechpegel(self.t, self.rnd)
            self.t += 0.05
            self.ov._wave._tick()
        self.ruhe()

    def blase_weg(self) -> None:
        self.ov._caption.hide()

    def zeichne(self, p, pos, deckkraft: float = 1.0, nur_pille: bool = False,
                fenster_transparenz: bool = True) -> None:
        """Pille (mit ihrer Fenster-Transparenz) und sichtbare Blasen an `pos` malen.

        `grab()` kennt die Fenster-Transparenz (Vorgabe 0,9) nicht — sie wird hier
        nachgebildet. Für das freigestellte pill.png bleibt sie aus: Ohne Hintergrund
        dahinter sähe die Pille sonst je nach Seitenfarbe grau oder milchig aus."""
        from PySide6.QtCore import QPointF

        ov = self.ov
        if not ov.isHidden():
            fenster = self.settings.overlay.opacity if fenster_transparenz else 1.0
            p.setOpacity(deckkraft * max(0.2, min(1.0, fenster)))
            p.drawPixmap(pos, ov.grab())
        if not nur_pille:
            for b in self.blasen:
                if not b.isHidden():
                    p.setOpacity(deckkraft)
                    off = b.pos() - ov.pos()
                    p.drawPixmap(pos + QPointF(off.x(), off.y()), b.grab())
        p.setOpacity(1.0)

    def umriss(self):
        """Begrenzungsrechteck von Pille + sichtbaren Blasen, relativ zur Pille."""
        from PySide6.QtCore import QRectF

        r = QRectF(0, 0, self.breite, self.hoehe) if not self.ov.isHidden() else QRectF()
        for b in self.blasen:
            if not b.isHidden():
                off = b.pos() - self.ov.pos()
                r = r.united(QRectF(off.x(), off.y(), b.width(), b.height()))
        return r


def _profilfarbe(name: str) -> str:
    from fleech.profiles import profile_color

    return profile_color(_profil(name))


# -- Kulissen: neutraler Editor, Mail-Fenster, KI-Chat, Taste, Mauszeiger ------------

def _hintergrund(p, breite: float, hoehe: float) -> None:
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QLinearGradient, QRadialGradient

    g = QLinearGradient(0, 0, breite, hoehe)
    g.setColorAt(0, _farbe("#1C2430"))
    g.setColorAt(1, _farbe("#2A323E"))
    p.fillRect(QRectF(0, 0, breite, hoehe), g)
    glanz = QRadialGradient(QPointF(breite * 0.3, 0), breite * 0.8)
    glanz.setColorAt(0, _farbe("#35C0D8", 22))
    glanz.setColorAt(1, _farbe("#35C0D8", 0))
    p.fillRect(QRectF(0, 0, breite, hoehe), glanz)


def _dokument(bloecke: list, breite: float, px: float, zeilenhoehe: int = 130):
    """QTextDocument aus Blöcken [(text, format), …]; Format: None|fett|neu|formel|grau.

    Leerzeilen zwischen Absätzen werden halb so hoch gesetzt — eine Mail mit vier
    Leerzeilen sähe in der kleinen Attrappe sonst luftiger aus als im echten Programm.
    """
    from PySide6.QtGui import QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(schrift(px))
    cur = QTextCursor(doc)
    bf = QTextBlockFormat()
    bf.setLineHeight(zeilenhoehe, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    leer = QTextBlockFormat()
    leer.setLineHeight(px * 0.65, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    for i, block in enumerate(bloecke):
        ist_leer = not "".join(t for t, _ in block) and i < len(bloecke) - 1
        if i:
            cur.insertBlock(leer if ist_leer else bf)
        else:
            cur.setBlockFormat(leer if ist_leer else bf)
        for text, fmt in block:
            cf = QTextCharFormat()
            cf.setFont(schrift(px, "halbfett" if fmt == "fett" else "normal"))
            cf.setForeground(_farbe({"grau": "#8A9099", "formel": "#1F6FB2"}.get(fmt, "#1F2328")))
            if fmt == "neu":
                cf.setBackground(_farbe("#35C0D8", 60))
            if fmt == "formel":
                cf.setBackground(_farbe("#E8F1FA"))
            cur.insertText(text, cf)
    doc.setTextWidth(breite)
    doc.documentLayout()
    return doc, cur


def _bloecke(text: str, fmt=None) -> list:
    """Klartext → Blöcke. In Formelzeilen werden $…$-Stellen hervorgehoben."""
    bloecke = []
    for zeile in text.split("\n"):
        if fmt == "formel":
            teile = [(t, "formel" if t.startswith("$") else None)
                     for t in re.split(r"(\$[^$]+\$)", zeile) if t]
            bloecke.append(teile or [("", None)])
        else:
            bloecke.append([(zeile, fmt)])
    return bloecke


def _caret(p, doc, cur, ursprung, an: bool) -> None:
    """Schreibmarke am Ende des Dokuments — echte Textlage, kein Ersatzzeichen."""
    from PySide6.QtCore import QRectF

    if not an:
        return
    block = cur.block()
    layout = block.layout()
    pos = cur.positionInBlock()
    zeile = layout.lineForTextPosition(pos)
    if not zeile.isValid():
        return
    x = zeile.cursorToX(pos)
    x = x[0] if isinstance(x, tuple) else x
    lp = layout.position()
    h = zeile.height() * 0.78
    y = lp.y() + zeile.y() + (zeile.height() - h) / 2
    p.fillRect(QRectF(ursprung.x() + lp.x() + x, ursprung.y() + y, 1.6, h),
               _farbe("#1F2328"))


def zeichne_fenster(p, r, titel: str, bloecke: list, *, art: str = "notiz",
                    kopf: list | None = None, px: float = 15, caret: bool = True,
                    platzhalter: str = "") -> None:
    """Ein neutrales, helles App-Fenster (keine echte Marke)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    # Schatten
    for i, a in ((10, 18), (6, 26), (3, 40)):
        schatten = QPainterPath()
        schatten.addRoundedRect(r.adjusted(-i / 2, -i / 4, i / 2, i), 12 + i / 2, 12 + i / 2)
        p.fillPath(schatten, _farbe("#000000", a))
    rahmen = QPainterPath()
    rahmen.addRoundedRect(r, 10, 10)
    p.fillPath(rahmen, _farbe("#FFFFFF"))
    p.save()
    p.setClipPath(rahmen)
    # Titelleiste
    leiste = QRectF(r.x(), r.y(), r.width(), 34)
    p.fillRect(leiste, _farbe("#F1F2F4"))
    p.fillRect(QRectF(r.x(), leiste.bottom() - 1, r.width(), 1), _farbe("#DADDE2"))
    p.setPen(_farbe("#555B65"))
    p.setFont(schrift(12.5))
    p.drawText(leiste.adjusted(16, 0, -120, 0), Qt.AlignVCenter | Qt.AlignLeft, titel)
    stift = QPen(_farbe("#6B7280"), 1.2)
    p.setPen(stift)
    p.setBrush(Qt.NoBrush)
    cx, cy = r.right() - 22, leiste.center().y()
    p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))          # ✕
    p.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))
    p.drawRect(QRectF(cx - 40, cy - 5, 10, 10))                           # □
    p.drawLine(QPointF(cx - 75, cy), QPointF(cx - 65, cy))                # —
    y = leiste.bottom()
    # Kopfzeilen (Mail)
    for feld, wert in kopf or []:
        zeile = QRectF(r.x() + 18, y, r.width() - 36, 32)
        p.setFont(schrift(13))
        p.setPen(_farbe("#8A9099"))
        p.drawText(zeile, Qt.AlignVCenter | Qt.AlignLeft, feld)
        p.setPen(_farbe("#1F2328"))
        p.drawText(zeile.adjusted(70, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, wert)
        p.fillRect(QRectF(r.x() + 18, zeile.bottom() - 1, r.width() - 36, 1),
                   _farbe("#E6E8EB"))
        y = zeile.bottom()
    if art == "chat":
        # KI-Chat: Eingabefeld mit Senden-Knopf, darüber leerer Verlauf
        p.fillRect(QRectF(r.x(), y, r.width(), r.bottom() - y), _farbe("#F7F7F8"))
        feld = QRectF(r.x() + 22, y + 18, r.width() - 44, r.bottom() - y - 36)
        pfad = QPainterPath()
        pfad.addRoundedRect(feld, 14, 14)
        p.fillPath(pfad, _farbe("#FFFFFF"))
        p.setPen(QPen(_farbe("#D5D9DF"), 1))
        p.drawPath(pfad)
        knopf = QRectF(feld.right() - 44, feld.bottom() - 44, 32, 32)
        p.setPen(Qt.NoPen)
        p.setBrush(_farbe("#35C0D8" if bloecke else "#C9CED6"))
        p.drawEllipse(knopf)
        p.setPen(QPen(_farbe("#FFFFFF"), 2.2, Qt.SolidLine, Qt.RoundCap))
        c = knopf.center()
        p.drawLine(QPointF(c.x(), c.y() + 7), QPointF(c.x(), c.y() - 7))
        p.drawLine(QPointF(c.x() - 6, c.y() - 1), QPointF(c.x(), c.y() - 7))
        p.drawLine(QPointF(c.x() + 6, c.y() - 1), QPointF(c.x(), c.y() - 7))
        inhalt = feld.adjusted(16, 14, -56, -12)
    else:
        inhalt = QRectF(r.x() + 22, y + 16, r.width() - 44, r.bottom() - y - 24)
    if not bloecke and platzhalter:
        p.setFont(schrift(px))
        p.setPen(_farbe("#9AA0A8"))
        p.drawText(inhalt.adjusted(4, 0, 0, 0), Qt.AlignLeft | Qt.AlignTop, platzhalter)
    doc, cur = _dokument(bloecke or [[("", None)]], inhalt.width(), px)
    p.save()
    p.translate(inhalt.topLeft())
    doc.drawContents(p, QRectF(0, 0, inhalt.width(), inhalt.height()))
    p.restore()
    _caret(p, doc, cur, inhalt.topLeft(), caret)
    p.restore()
    p.setPen(QPen(_farbe("#000000", 40), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(rahmen)


def zeichne_taste(p, mitte, beschriftung: str, gedrueckt: bool, deckkraft: float = 1.0) -> None:
    """Demo-Element: Tastenkappe „F9“ mit Beschriftung daneben (nicht Teil der App)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QLinearGradient, QPainterPath, QPen

    if deckkraft <= 0:
        return
    p.save()
    p.setOpacity(deckkraft)
    w, h = 54.0, 46.0
    versatz = 2.5 if gedrueckt else 0.0
    sockel = QRectF(mitte.x() - w / 2, mitte.y() - h / 2 + 3, w, h)
    pfad = QPainterPath()
    pfad.addRoundedRect(sockel, 9, 9)
    p.fillPath(pfad, _farbe("#9AA1AC"))                   # Kante der Kappe
    kappe = QRectF(mitte.x() - w / 2, mitte.y() - h / 2 + versatz, w, h - 3)
    pfad = QPainterPath()
    pfad.addRoundedRect(kappe, 9, 9)
    g = QLinearGradient(kappe.topLeft(), kappe.bottomLeft())
    g.setColorAt(0, _farbe("#FFFFFF" if not gedrueckt else "#E9EDF2"))
    g.setColorAt(1, _farbe("#E3E6EB" if not gedrueckt else "#D3D9E1"))
    p.fillPath(pfad, g)
    if gedrueckt:
        p.setPen(QPen(_farbe("#35C0D8"), 2.2))
        p.drawPath(pfad)
    p.setPen(_farbe("#20242B"))
    p.setFont(schrift(17, "halbfett"))
    p.drawText(kappe, Qt.AlignCenter, "F9")
    p.setPen(_farbe("#E8E8EC"))
    p.setFont(schrift(15, "halbfett"))
    p.drawText(QRectF(mitte.x() - w / 2 - 170, mitte.y() - 15, 158, 30),
               Qt.AlignVCenter | Qt.AlignRight, beschriftung)
    p.restore()


def zeichne_zeiger(p, spitze, klick: float = 0.0) -> None:
    """Mauszeiger (Pfeil) für die Fenster-Tour; `klick` > 0 = kurzer Klick-Ring."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath, QPen, QPolygonF

    if klick > 0:
        p.setPen(QPen(_farbe("#35C0D8", int(200 * (1 - klick))), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(spitze, 6 + 16 * klick, 6 + 16 * klick)
    punkte = [(0, 0), (0, 18), (4.6, 13.8), (7.8, 20.6), (10.6, 19.4), (7.5, 12.8), (13.4, 12.8)]
    pfad = QPainterPath()
    pfad.addPolygon(QPolygonF([QPointF(spitze.x() + x * 1.25, spitze.y() + y * 1.25)
                               for x, y in punkte]))
    pfad.closeSubpath()
    p.setPen(QPen(_farbe("#111111"), 1.3))
    p.setBrush(_farbe("#FFFFFF"))
    p.drawPath(pfad)


# -- Szenen-Bausteine -----------------------------------------------------------------

TEXTE = {
    "de": {"halten": "gedrückt halten", "loslassen": "loslassen",
           "notiz": "Notizen — team-update.txt", "kopf": "Wochen-Update",
           "nachricht": "Notizen — antwort.txt", "betreff": "Re: Meeting morgen"},
    "en": {"halten": "hold to talk", "loslassen": "release",
           "notiz": "Notes — team-update.txt", "kopf": "Weekly update",
           "nachricht": "Notes — reply.txt", "betreff": "Re: Meeting tomorrow"},
}


class Buehne:
    """Eine Bühne: Desktop-Hintergrund, Fenster-Attrappe, Pille, Taste."""

    def __init__(self, breite: int, hoehe: int, pille: Pille, platz_unten: int = 24):
        from PySide6.QtCore import QPointF

        self.breite, self.hoehe = breite, hoehe
        self.pille = pille
        self.pille_pos = QPointF((breite - pille.breite) / 2,
                                 hoehe - platz_unten - pille.hoehe)
        self.fenster = None          # (Rechteck, titel, bloecke, optionen)
        self.taste = None            # (beschriftung, gedrueckt, deckkraft)
        self.caret_an = True

    def bild(self):
        from PySide6.QtCore import QPointF

        img = _bild(self.breite, self.hoehe)
        p = _maler(img)
        _hintergrund(p, self.breite, self.hoehe)
        if self.fenster:
            r, titel, bloecke, opt = self.fenster
            zeichne_fenster(p, r, titel, bloecke, caret=self.caret_an, **opt)
        self.pille.zeichne(p, self.pille_pos)
        if self.taste:
            beschriftung, gedrueckt, deckkraft = self.taste
            mitte = QPointF(self.pille_pos.x() - 46, self.pille_pos.y() + self.pille.hoehe / 2)
            zeichne_taste(p, mitte, beschriftung, gedrueckt, deckkraft)
        p.end()
        return img


def _lade_beispiele() -> dict:
    if not BEISPIELE.exists():
        raise SystemExit("examples.json fehlt — erst `make_media.py --beispiele` ausführen.")
    bsp = json.loads(BEISPIELE.read_text(encoding="utf-8"))
    # Passen die gespeicherten Ausgaben noch zu den Rohtexten in diesem Skript? Sonst
    # zeigte ein Neubau Ergebnisse zu Sätzen, die hier gar nicht mehr stehen.
    roh_jetzt = [*HERO_ROH.values(), PROFIL_ROH, *(t for p in BEFEHL_ROH.values() for t in p),
                 *MATHE_ROH, *(e[5] for e in VERLAUF_ROH)]
    roh_json = [*(bsp["hero"][s]["raw"] for s in HERO_ROH), bsp["profiles"]["de"]["raw"],
                *(t for s in BEFEHL_ROH for t in (bsp["command"][s]["diktat_raw"],
                                                 bsp["command"][s]["befehl_raw"])),
                *(f["raw"] for f in bsp["math"]["de"]), *(e["raw"] for e in bsp["verlauf"])]
    if roh_jetzt != roh_json:
        raise SystemExit("examples.json passt nicht mehr zu den Rohtexten im Skript — "
                         "`make_media.py --beispiele` ausführen.")
    return bsp


# =====================================================================================
# Szenen
# =====================================================================================

def szene_hero(bsp: dict) -> None:
    """„F9 halten, sprechen, loslassen“ — je Sprache ein GIF."""
    from PySide6.QtCore import QRectF

    for sprache in ("en", "de"):
        t = TEXTE[sprache]
        daten = bsp["hero"][sprache]
        pille = Pille(_settings())
        pille.ov.set_profile_color(_profilfarbe("Standard"))
        b = Buehne(760, 440, pille)
        kopf = [[(t["kopf"], "fett")], [("", None)]]
        b.fenster = (QRectF(40, 26, 680, 236), t["notiz"], kopf + [[("", None)]], {})
        film = Film(f"hero-{sprache}")
        bild_nr = 0

        def bild(mal=1):
            nonlocal bild_nr
            b.caret_an = (bild_nr // 10) % 2 == 0      # Schreibmarke blinkt (1 s)
            film.bild(b.bild(), mal)
            bild_nr += mal

        # 1) Taste gehalten, Aufnahme läuft — schon das erste Bild erklärt die Szene
        pille.zustand("LISTENING")
        pille.sprich(14)                                 # Waveform vorab gefüllt
        b.taste = (t["halten"], True, 1.0)
        for _ in range(64):
            pille.sprich()
            bild()
        # 2) losgelassen: Verarbeitung, dann Rohtext mit „Bereinige …“
        pille.zustand("PROCESSING")
        b.taste = (t["loslassen"], False, 1.0)
        for _ in range(4):
            pille.sprich()
            bild()
        pille.ov.show_raw_preview(daten["raw"])
        pille.ruhe()
        for i in range(40):
            if i == 34 and "Füge ein …" in daten["statuszeilen"]:
                pille.ov.show_progress("Füge ein …")      # letzte Stufe vor dem Einfügen
                pille.ruhe()
            pille.sprich()
            b.taste = (t["loslassen"], False, max(0.0, 1 - max(0, i - 14) / 8))
            bild()
        b.taste = None
        # 3) fertig: Text kommt auf EINMAL (Fleech fügt ein, es tippt nicht)
        pille.ov.show_transcript(daten["text"])
        pille.zustand("IDLE")
        b.fenster = (b.fenster[0], t["notiz"],
                     kopf + [[(daten["text"], None)]], {})
        for _ in range(7):
            bild(10)
        pille.blase_weg()
        bild(10)
        film.gif(HIER / f"hero.{sprache}.gif")


def szene_profiles(bsp: dict) -> None:
    """Ein Diktat, vier Profile — Ring-Farbe und Namens-Kapsel der echten Pille."""
    from PySide6.QtCore import QRectF

    daten = bsp["profiles"]["de"]
    fenster = {
        "Standard": ("Notizen — website.txt", {}),
        "E-Mail": ("Neue Nachricht", {"kopf": [("An", "team@example.com"),
                                                ("Betreff", "Website-Launch")]}),
        "Stichpunkte": ("Notizen — todo.md", {}),
        "KI-Prompt": ("KI-Chat — neue Unterhaltung",
                      {"art": "chat", "px": 14, "platzhalter": "Nachricht an die KI …"}),
    }
    lesezeit = {"Standard": 30, "E-Mail": 42, "Stichpunkte": 30, "KI-Prompt": 54}
    pille = Pille(_settings())
    b = Buehne(760, 600, pille, platz_unten=70)
    rechteck = QRectF(40, 22, 680, 360)
    film = Film("profiles")
    vorher = PROFILE_IM_FILM[-1]
    for runde, name in enumerate(PROFILE_IM_FILM):
        erg = daten["ergebnisse"][name]
        titel, opt = fenster[name]
        b.fenster = (rechteck, titel, [], opt)
        pille.ov.set_profile_color(_profilfarbe(vorher))
        pille.zustand("LISTENING")
        pille.sprich(8)
        # Profil wechseln (Klick auf den Punkt / Profil-Taste): Ring + Kapsel
        pille.ov.set_profile_color(_profilfarbe(name))
        pille.ov.show_profile(name)
        pille.ruhe()
        for i in range(24):
            pille.sprich()
            b.caret_an = (i // 10) % 2 == 0
            film.bild(b.bild())
        pille.zustand("PROCESSING")                      # Kapsel geht mit der Aufnahme
        for _ in range(3):
            pille.sprich()
            film.bild(b.bild())
        pille.ov.show_raw_preview(daten["raw"])
        pille.ruhe()
        for _ in range(26 if runde == 0 else 8):
            pille.sprich()
            film.bild(b.bild())
        for zeile in erg["statuszeilen"]:               # „E-Mail wird formuliert …“
            if zeile == "Bereinige …":
                continue                                 # steht schon in der Blase
            pille.ov.show_progress(zeile)
            pille.ruhe()
            for _ in range(4 if zeile == "Füge ein …" else 14):
                pille.sprich()
                film.bild(b.bild())
        pille.ov.show_transcript(erg["text"])
        pille.zustand("IDLE")
        b.caret_an = True
        b.fenster = (rechteck, titel, _bloecke(erg["text"]), opt)
        film.bild(b.bild(), 10)
        pille.blase_weg()
        film.bild(b.bild(), lesezeit[name])
        vorher = name
    film.gif(HIER / "profiles.gif")


def szene_command(bsp: dict) -> None:
    """Safe-Word „Kimono“: zweite Aufnahme ersetzt den letzten Satz (Standard-Optik)."""
    from PySide6.QtCore import QRectF

    for sprache in ("en", "de"):
        t = TEXTE[sprache]
        daten = bsp["command"][sprache]
        eingefuegt = next(e[1] for e in daten["log"] if e[0] == "inject")
        ersetzt = next(e for e in daten["log"] if e[0] == "replace_tail")
        alt = eingefuegt[:len(eingefuegt) - ersetzt[1]]
        neu = ersetzt[2]
        pille = Pille(_settings())
        pille.ov.set_profile_color(_profilfarbe("Standard"))
        b = Buehne(760, 440, pille)
        r = QRectF(40, 26, 680, 236)
        film = Film(f"command-{sprache}")
        # 1) Das erste Diktat ist gerade angekommen (Blase zeigt es noch). Darüber
        #    steht Text, der schon vorher im Dokument war — er bleibt unberührt.
        kopf = [[(t["betreff"], "fett")], [("", None)]]
        b.fenster = (r, t["nachricht"], kopf + _bloecke(eingefuegt), {})
        pille.ov.show_transcript(eingefuegt)
        pille.zustand("IDLE")
        for i in range(3):
            b.caret_an = i % 2 == 0
            film.bild(b.bild(), 10)
        # 2) Zweite Aufnahme: „Kimono, …“ — ohne Live-Vorschau (Vorgabe) bleibt die
        #    Pille neutral; das Safe-Word erkennt Fleech nach dem Loslassen.
        pille.zustand("LISTENING")
        b.taste = (t["halten"], True, 1.0)
        for i in range(46):
            pille.sprich()
            b.caret_an = (i // 10) % 2 == 0
            film.bild(b.bild())
        pille.zustand("PROCESSING")
        b.taste = (t["loslassen"], False, 1.0)
        for _ in range(4):
            pille.sprich()
            film.bild(b.bild())
        pille.ov.show_raw_preview(daten["befehl_raw"])
        pille.ruhe()
        for i in range(34):
            pille.sprich()
            b.taste = (t["loslassen"], False, max(0.0, 1 - max(0, i - 12) / 8))
            film.bild(b.bild())
        b.taste = None
        # 3) replace_tail: der letzte Satz wird ersetzt (kurz hervorgehoben)
        pille.ov.show_transcript(neu)
        pille.zustand("IDLE")
        b.caret_an = True
        b.fenster = (r, t["nachricht"], kopf + [[(alt, None), (neu, "neu")]], {})
        film.bild(b.bild(), 24)
        b.fenster = (r, t["nachricht"], kopf + [[(alt, None), (neu, None)]], {})
        film.bild(b.bild(), 40)
        pille.blase_weg()
        film.bild(b.bild(), 16)
        film.gif(HIER / f"command.{sprache}.gif")


def szene_math(bsp: dict) -> None:
    """Gesprochene Mathematik → LaTeX (deterministischer Parser, Opt-in auto_latex)."""
    from PySide6.QtCore import QRectF

    faelle = bsp["math"]["de"]
    pille = Pille(_settings())
    pille.ov.set_profile_color(_profilfarbe("Standard"))
    b = Buehne(760, 460, pille)
    r = QRectF(40, 26, 680, 250)
    titel = "Notizen — mathe.md"
    zeilen = [[("Übung 3", "fett")], [("", None)]]
    film = Film("math")
    for nr, fall in enumerate(faelle):
        b.fenster = (r, titel, zeilen, {})
        pille.zustand("LISTENING")
        if nr == 0:
            pille.sprich(14)                             # erstes Bild = Titelbild
        b.taste = (TEXTE["de"]["halten"], True, 1.0)
        for i in range(32):
            pille.sprich()
            b.caret_an = (i // 10) % 2 == 0
            film.bild(b.bild())
        pille.zustand("PROCESSING")
        b.taste = (TEXTE["de"]["loslassen"], False, 1.0)
        for _ in range(3):
            pille.sprich()
            film.bild(b.bild())
        pille.ov.show_raw_preview(fall["raw"])
        pille.ruhe()
        for i in range(26):
            pille.sprich()
            b.taste = (TEXTE["de"]["loslassen"], False, max(0.0, 1 - max(0, i - 10) / 8))
            film.bild(b.bild())
        b.taste = None
        # Reihenfolge wie in der App: Formel-Vorschau, dann Transkript, dann IDLE.
        pille.ov.show_formula_preview([tuple(f) for f in fall["formeln"]])
        pille.ov.show_transcript(fall["text"])
        pille.zustand("IDLE")
        zeilen = zeilen + _bloecke(fall["text"], "formel")
        b.caret_an = True
        b.fenster = (r, titel, zeilen, {})
        film.bild(b.bild(), 46 if nr == 0 else 76)
        pille.blase_weg()
        film.bild(b.bild(), 6 if nr == 0 else 16)
    film.gif(HIER / "math.gif")


def _pille_aufnahme(seed: int = 3) -> Pille:
    pille = Pille(_settings(), seed=seed)
    pille.ov.set_profile_color(_profilfarbe("Standard"))
    pille.zustand("LISTENING")
    pille.sprich(14)
    return pille


def szene_pille(bsp: dict) -> None:
    """pill.png (die Pille allein) und pill-states.en/.de.png (Zustände, beschriftet)."""
    from PySide6.QtCore import QPointF, QRectF, Qt

    # pill.png: transparent, 2x, mitten in der Aufnahme
    pille = _pille_aufnahme()
    img = _bild(pille.breite + 8, pille.hoehe + 8, transparent=True)
    p = _maler(img)
    pille.zeichne(p, QPointF(4, 4), nur_pille=True, fenster_transparenz=False)
    p.end()
    img.save(str(HIER / "pill.png"))
    print("  docs/media/pill.png")

    roh = "Ähm, kurze Notiz: morgen um neun das Angebot an Frau Berger schicken."

    def aufnahme(pl):
        pass

    def verarbeitung(pl):
        pl.zustand("PROCESSING")
        pl.sprich(3)
        pl.ov.show_raw_preview(roh)
        pl.ruhe()

    def profil(pl):
        pl.ov.set_profile_color(_profilfarbe("E-Mail"))
        pl.ov.show_profile("E-Mail")
        pl.ruhe()

    def pause(pl):
        # Wer pausiert, hat meist gerade aufgehört zu sprechen: ein paar stille
        # Ticks vorher, damit die ruhende Anzeige so aussieht wie im Alltag.
        pl.sprich(13, stumm=True)
        pl.ov.set_paused(True)
        pl.ruhe()

    def kein_ton(pl):
        pl.zustand("LISTENING")
        pl.sprich(14, stumm=True)
        pl.ov.set_kein_ton(True)
        pl.ruhe()

    def ablage(pl):
        pl.zustand("IDLE")
        pl.ov.zeige_in_ablage("Morgen um neun das Angebot an Frau Berger schicken.")
        pl.ruhe()

    zustaende = [aufnahme, verarbeitung, profil, pause, kein_ton, ablage]
    # Die Pille selbst spricht Deutsch (die Oberfläche ist deutsch); nur die
    # Überschriften der Karten gibt es je README in ihrer Sprache.
    beschriftungen = {
        "en": ["Recording",
               "Processing: raw text shows while the AI cleans up",
               "Profile switched: ring colour and name (E-Mail)",
               "Paused",
               "No sound from the microphone",
               "Not inserted: the text waits in the clipboard"],
        "de": ["Aufnahme",
               "Verarbeitung: Rohtext, während die KI aufräumt",
               "Profil gewechselt: Ringfarbe und Name (E-Mail)",
               "Pause",
               "Kein Ton vom Mikrofon",
               "Nicht eingefügt: Text liegt in der Zwischenablage"],
    }
    spalten, zw, zh, rand, kopf = 2, 500, 210, 28, 30
    breite = rand * 2 + spalten * zw + (spalten - 1) * 20
    zeilen_n = math.ceil(len(zustaende) / spalten)
    hoehe = rand * 2 + zeilen_n * zh + (zeilen_n - 1) * 20
    for sprache, labels in beschriftungen.items():
        img = _bild(breite, hoehe)
        p = _maler(img)
        for i, (label, aktion) in enumerate(zip(labels, zustaende)):
            pl = _pille_aufnahme(seed=11 + i)
            aktion(pl)
            zelle = QRectF(rand + (i % spalten) * (zw + 20),
                           rand + (i // spalten) * (zh + 20), zw, zh)
            p.setPen(Qt.NoPen)
            p.setBrush(_farbe("#1E2127"))
            p.drawRoundedRect(zelle, 12, 12)
            p.setPen(_farbe("#9AA0A8"))
            p.setFont(schrift(15, "halbfett"))
            p.drawText(zelle.adjusted(18, 12, -18, 0), Qt.AlignLeft | Qt.AlignTop, label)
            # Pille samt Blasen mittig in den Rest der Zelle setzen
            u = pl.umriss()
            frei = zelle.adjusted(0, kopf, 0, 0)
            pos = QPointF(frei.center().x() - u.center().x(),
                          frei.center().y() - u.center().y())
            pl.zeichne(p, pos)
        p.end()
        img.save(str(HIER / f"pill-states.{sprache}.png"))
        print(f"  docs/media/pill-states.{sprache}.png")


# -- Hauptfenster: erfundener Verlauf, Screenshots und Tour ---------------------------

def _verlauf_fuellen(store, verlauf: list) -> None:
    from fleech import gruende
    from fleech.history import DictationRecord

    jetzt = time.time()
    heute = dt.date.today()
    rnd = random.Random(42)
    for nr, e in enumerate(verlauf):
        stunde, minute = (int(x) for x in e["zeit"].split(":"))
        ts = dt.datetime.combine(heute - dt.timedelta(days=e["tag"]),
                                 dt.time(stunde, minute)).timestamp()
        if e["tag"] == 0:                         # „heute“ nie in der Zukunft
            ts = min(ts, jetzt - (len(verlauf) - nr) * 420)
        woerter = max(len(e["text"].split()), len(e["raw"].split()))
        # ~130–150 Wörter pro Minute: Sprechzeit aus der Wortzahl
        sekunden = round(woerter / rnd.uniform(2.25, 2.5), 1)
        rueckfall = e["status"] == "fallback"
        store.add(DictationRecord(
            ts=ts, raw=e["raw"], cleaned=e["text"], audio_seconds=sekunden,
            app=e["app"], mode=e["mode"], tier=e["tier"] or "complex",
            status=e["status"], stt_ms=rnd.randint(180, 320), llm_ms=e["llm_ms"],
            reason=gruende.OLLAMA if rueckfall else "", profile=e["profil"],
        ))


def _hauptfenster(bsp: dict, breite: int = 1180, hoehe: int = 760):
    from PySide6.QtCore import Qt

    from fleech.history import HistoryStore
    from fleech.ui.main_window import MainWindow
    from fleech.ui.settings_window import SettingsPanel

    _qt()
    s = _settings()
    for item in s.profiles.items:
        if isinstance(item, dict) and item.get("name") in APP_ZUORDNUNG:
            item["apps"] = list(APP_ZUORDNUNG[item["name"]])
    store = HistoryStore(_SANDBOX / "Fleech" / "history.db")
    store.clear()
    _verlauf_fuellen(store, bsp["verlauf"])
    panel = SettingsPanel(s, lambda *a: None, lambda: ["USB-Mikrofon"])
    win = MainWindow(s, store, panel, lambda: None)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.resize(breite, hoehe)
    _qt().processEvents()
    return win, panel


def _fenster_seite(win, panel, schluessel: str):
    """Seite wählen und so vorbereiten, wie man sie im Alltag sähe."""
    if schluessel.startswith("settings"):
        win.show_page("settings")
        panel._nav.setCurrentRow({"settings-ai": 1, "settings-recording": 2}[schluessel])
    else:
        win.show_page(schluessel)
    if schluessel == "profiles":
        liste = win.profiles._profiles_list
        for i in range(liste.count()):
            if "E-Mail" in liste.item(i).text():
                liste.setCurrentRow(i)
    if schluessel == "apps":
        # Die Mail-App zeigen: Dort greift eine Zuordnung (→ E-Mail).
        liste = win.apps._apps
        for i in range(liste.count()):
            if liste.item(i).text().startswith("thunderbird.exe"):
                liste.setCurrentRow(i)
        win.apps._jetzt_aktualisieren()          # sonst erst nach dem 1-s-Takt
        win.apps._jetzt_timer.stop()
    _qt().processEvents()


def _fenster_bild(win, zeiger=None, klick: float = 0.0):
    """Fenster in ein 2x-Bild malen, mit feiner Kante (hebt es vom dunklen GitHub ab)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPen

    img = _bild(win.width(), win.height())
    p = _maler(img)
    p.drawPixmap(QPointF(0, 0), win.grab())
    p.setPen(QPen(_farbe("#3A3F48"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, win.width() - 1, win.height() - 1))
    if zeiger is not None:
        zeichne_zeiger(p, zeiger, klick)
    p.end()
    return img


STANDBILDER = {
    "home": "main-window.png",
    "insights": "insights.png",
    "profiles": "profiles.png",
    "settings-recording": "settings-recording.png",
    "settings-ai": "settings-ai.png",
}


def szene_fenster(bsp: dict) -> None:
    """Statische Screenshots des Hauptfensters (2x)."""
    win, panel = _hauptfenster(bsp)
    for schluessel, datei in STANDBILDER.items():
        _fenster_seite(win, panel, schluessel)
        _fenster_bild(win).save(str(HIER / datei))
        print(f"  docs/media/{datei}")


def szene_tour(bsp: dict) -> None:
    """Home → Insights → Profile → Apps → Einstellungen (KI), harte Schnitte."""
    from PySide6.QtCore import QPoint, QPointF

    win, panel = _hauptfenster(bsp)
    fps = 10
    film = Film("tour", fps=fps)
    folge = ["home", "insights", "profiles", "apps", "settings-ai"]

    def knopf_mitte(schluessel: str) -> QPointF:
        btn = win._nav_buttons["settings" if schluessel.startswith("settings") else schluessel]
        pos = btn.mapTo(win, QPoint(0, 0))
        return QPointF(pos.x() + btn.width() * 0.86, pos.y() + btn.height() / 2)

    zeiger = knopf_mitte("home")
    for i, schluessel in enumerate(folge):
        _fenster_seite(win, panel, schluessel)
        film.bild(_fenster_bild(win, zeiger), 22)
        if i + 1 == len(folge):
            film.bild(_fenster_bild(win, zeiger), 6)
            break
        ziel = knopf_mitte(folge[i + 1])
        for k in range(1, 5):                     # Zeiger gleitet zum nächsten Eintrag
            f = 1 - (1 - k / 4) ** 2
            punkt = zeiger + (ziel - zeiger) * f
            film.bild(_fenster_bild(win, punkt))
        zeiger = ziel
        film.bild(_fenster_bild(win, zeiger, klick=0.4))
    film.gif(HIER / "tour.gif")


# -- Social Preview -------------------------------------------------------------------

def szene_social(bsp: dict) -> None:
    """docs/media/social-preview.png: 1280×640, deckend, Wichtiges im mittleren Bereich."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QFontMetricsF, QPen, QRadialGradient
    from PySide6.QtSvg import QSvgRenderer

    _qt()
    w, h = 1280, 640
    img = _bild(w, h, dpr=1)
    p = _maler(img)
    p.fillRect(QRectF(0, 0, w, h), _farbe("#16181C"))
    glanz = QRadialGradient(QPointF(955, 330), 420)
    glanz.setColorAt(0, _farbe("#35C0D8", 34))
    glanz.setColorAt(1, _farbe("#35C0D8", 0))
    p.fillRect(QRectF(0, 0, w, h), glanz)
    p.translate(0, 22)                 # Inhalt optisch auf die Bildmitte setzen

    # Linke Spalte: Logo, Name, Claim, Unterzeile, Chips
    x0 = 92.0
    QSvgRenderer(str(ASSETS / "logo.svg")).render(p, QRectF(x0, 112, 104, 104))
    p.setPen(_farbe("#E8E8EC"))
    p.setFont(schrift(92, "halbfett"))
    p.drawText(QRectF(x0 + 128, 96, 420, 136), Qt.AlignVCenter | Qt.AlignLeft, "Fleech")
    p.setFont(schrift(40, "halbfett"))
    p.drawText(QRectF(x0, 252, 560, 56), Qt.AlignVCenter | Qt.AlignLeft,
               "Hold a key. Speak. Done.")
    p.setPen(_farbe("#8A8A92"))
    p.setFont(schrift(25))
    p.drawText(QRectF(x0, 318, 540, 80), Qt.AlignLeft | Qt.TextWordWrap,
               "Local Whisper speech-to-text + AI cleanup. "
               "Text lands wherever your cursor is.")
    chips = ["Windows & Linux", "German & English", "Local by default", "MIT"]
    f = schrift(16.5, "halbfett")
    fm = QFontMetricsF(f)
    p.setFont(f)
    x, y = x0, 432.0
    for chip in chips:
        cw = fm.horizontalAdvance(chip) + 28
        if x + cw > x0 + 590:
            x, y = x0, y + 50
        r = QRectF(x, y, cw, 38)
        p.setPen(QPen(_farbe("#3C424C"), 1.5))
        p.setBrush(_farbe("#1D2026"))
        p.drawRoundedRect(r, 19, 19)
        p.setPen(_farbe("#C9CCD2"))
        p.drawText(r, Qt.AlignCenter, chip)
        x += cw + 10

    # Rechte Spalte: echte Pille über einem Textfeld mit einem erfundenen Satz
    feld = QRectF(700, 286, 488, 196)
    zeichne_fenster(p, feld, "Notes", _bloecke(
        "Can we move Thursday’s meeting to 3 pm? I’ll send the agenda tonight."), px=19)
    pille = _pille_aufnahme(seed=5)
    pm = pille.ov.grab()
    faktor = 1.45
    pw, ph = pille.breite * faktor, pille.hoehe * faktor
    ziel = QRectF(feld.center().x() - pw / 2, 180, pw, ph)
    p.setOpacity(0.96)
    p.drawPixmap(ziel, pm, QRectF(0, 0, pm.width(), pm.height()))
    p.setOpacity(1.0)
    p.end()
    # Bewusst NICHT in assets/: Der Ordner wird komplett in die App gebündelt
    # (packaging/fleech.spec), das Bild gehört aber nur auf die GitHub-Seite.
    ziel_datei = HIER / "social-preview.png"
    img.convertToFormat(img.Format.Format_RGB32).save(str(ziel_datei))
    print(f"  docs/media/social-preview.png: {ziel_datei.stat().st_size // 1024} KB")


# =====================================================================================

SZENEN = {
    "hero": szene_hero,
    "profiles": szene_profiles,
    "command": szene_command,
    "math": szene_math,
    "pill": szene_pille,
    "stills": szene_fenster,
    "tour": szene_tour,
    "social": szene_social,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("szenen", nargs="*", help=f"Auswahl aus: {', '.join(SZENEN)}")
    ap.add_argument("--beispiele", action="store_true",
                    help="examples.json mit der echten Pipeline (Ollama) neu erzeugen")
    ap.add_argument("--liste", action="store_true", help="Szenen auflisten")
    args = ap.parse_args()
    if args.liste:
        for name, fn in SZENEN.items():
            print(f"{name:10s} {fn.__doc__.strip().splitlines()[0]}")
        return
    if args.beispiele:
        erzeuge_beispiele()
        if not args.szenen:
            return
    unbekannt = [s for s in args.szenen if s not in SZENEN]
    if unbekannt:
        raise SystemExit(f"Unbekannte Szene(n): {', '.join(unbekannt)}")
    bsp = _lade_beispiele()
    _qt()
    for name in args.szenen or SZENEN:
        print(f"{name} …")
        SZENEN[name](bsp)


if __name__ == "__main__":
    main()
