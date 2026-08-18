"""Freihand-Modus: Diktieren ohne Taste — Startwort sagen, sprechen, aufhören.

## Warum zwei Stufen statt eines Wake-Word-Modells

Der naheliegende Weg waere eine fertige Wake-Word-Engine (Porcupine,
openWakeWord). Die erkennen aber nur Woerter, auf die sie TRAINIERT wurden — ein
frei waehlbares Startwort ist damit unmoeglich, man muesste je Wort ein Modell
trainieren. Frei waehlbar geht nur ueber echte Spracherkennung, und die permanent
laufen zu lassen ist zu teuer.

Deshalb ein Gate aus zwei Stufen, beide bereits im Projekt vorhanden:

1. **Silero-VAD** (steckt in faster-whisper) hoert auf SPRACHE UEBERHAUPT.
   Gemessen: 1–4 ms je Sekunde Audio — 0,1–0,4 % Dauerlast. Bei Stille und
   Rauschen schlaegt es gar nicht erst an.
2. Erst wenn Stufe 1 anschlaegt, laeuft **Whisper tiny** ueber die letzten
   Sekunden und sucht das Startwort. Gemessen: 170 ms fuer 2 s Audio auf der CPU.

Die GPU bleibt dabei frei — dort liegt das grosse Modell fuer das eigentliche
Diktat.

## Was hier NICHT passiert

Kein Audio wird gespeichert. Der Ringpuffer haelt wenige Sekunden im
Arbeitsspeicher und ueberschreibt sich fortlaufend; erst ab erkanntem Startwort
wird gesammelt. Dieses Modul kennt weder Dateien noch Netzwerk.

Die Zustandsmaschine ist bewusst frei von Audio-I/O und Qt: Sie bekommt
Audio-Bloecke hineingereicht und meldet Ereignisse zurueck. Damit ist der ganze
heikle Teil — wann startet, wann endet ein Diktat — ohne Mikrofon testbar.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

log = logging.getLogger(__name__)

SAMPLERATE = 16000

# Freihand ist VORERST STILLGELEGT (ab 5.10.1, auf ausdrueckliche Anweisung).
#
# Der Modus laesst sich nicht mehr einschalten, und ein bestehendes `aktiv: true`
# in der settings.json wird ignoriert. Der Code bleibt vollstaendig erhalten —
# das hier ist ein Riegel, keine Entfernung: Ein `False` an dieser Stelle macht
# ihn wieder verfuegbar, ohne dass sonst etwas anzufassen waere.
#
# Der Grund steht ausfuehrlich in docs/fleech-gesamtkonzept.md, Abschnitt 21.5:
# Ein dauerhaft offenes Mikrofon per Sprache auszuloesen ist in einem Raum mit
# Nebengeraeuschen nicht zuverlaessig zu bekommen — und jeder Fehlstart tippt
# Text in das gerade fokussierte Fenster. Der Bedienmodus „Anstupsen" liefert
# den eigentlich gewollten Teil (automatisches Ende) ohne diese Schwaeche.
#
# Die Teile, die Freihand mitgebracht hat, bleiben in Benutzung: das VAD-Fenster
# und seine Messwerte tragen `stillewache.py`, `enthaelt_wort`/`zerlege_woerter`
# die Wortprobe.
STILLGELEGT = True

# Wie viel Audio das Startwort-Fenster umfasst. Zwei Sekunden fassen ein
# mehrsilbiges Wort samt Anlauf; laenger kostet nur Rechenzeit und erhoeht die
# Chance, dass ein zufaelliges Wort aus dem Vorsatz mit hineinrutscht.
FENSTER_S = 2.0

# Mindestabstand zwischen zwei Startwort-Pruefungen. Ohne das liefe tiny bei
# durchgehendem Sprechen (Meeting, Video) permanent.
PRUEF_ABSTAND_S = 0.6

# Nach einer Aktivierung erst wieder lauschen, wenn so viel Zeit vergangen ist —
# sonst loest das eigene „los geht's" direkt die naechste Aufnahme aus.
SPERRE_NACH_START_S = 1.0

# Kuerzere Aufnahmen gelten als Versehen und werden verworfen. Ein Diktat, das
# sich lohnt, dauert laenger als eine halbe Sekunde — und Whisper halluziniert
# aus kurzen Rauschfetzen zuverlaessig Unsinn.
MIN_DIKTAT_S = 0.6

# Nach dieser Laufzeit wird ein Freihand-Diktat auf jeden Fall beendet. Zweite
# Sicherung fuer den Fall, dass die Stille-Erkennung nie greift — in einem Raum
# mit laufendem Video meldet das VAD dauerhaft Sprache. Zwei Minuten sind
# grosszuegig fuer ein Diktat und kurz genug, dass niemand ewig feststeckt.
MAX_DIKTAT_S = 120.0

# Wie viel Audio das VAD waehrend der AUFNAHME beurteilt. Gemessen: Auf einem
# einzelnen 0,2-s-Block meldet Silero NIE Sprache (0 %), ab 0,8 s sind es 98,6 %,
# ab 1,0 s volle 100 % — bei null Fehlalarmen auf Rauschen. Der Wert entscheidet,
# ob ein Diktat weiterlaufen darf oder nach `stille_s` abgeschnitten wird.
VAD_FENSTER_S = 1.0

# Anlaufzeit nach dem Startwort: So lange wird ein Diktat NICHT wegen Stille
# beendet. Das ist keine Bequemlichkeit, sondern eine Messgrenze.
#
# Das VAD braucht mindestens 0,8 s Audio, um Sprache zu melden (siehe oben).
# Direkt nach dem Startwort ist die Aufnahme aber erst 0,2 s lang, dann 0,4 s …
# — in dieser Zeit meldet das VAD zwangslaeufig „keine Sprache", ganz egal, ob
# jemand spricht. Die Stille-Uhr lief also von der ersten Sekunde an gegen einen
# Messfehler statt gegen echte Stille.
#
# Im Protokoll sah das so aus (immer exakt `stille_s`):
#
#     15:37:38  Startwort erkannt in 'Apfel.'
#     15:37:38  Aufnahme ohne Sprache — verworfen (2.0 s)
#
# Fuer den Nutzer hiess das: Die Pille kam und war wieder weg, bevor er
# reagieren konnte — gemeldet als „ich kann nicht abbrechen". Der Abbruch-Knopf
# war dabei in Ordnung; es gab schlicht nichts mehr abzubrechen.
#
# 1,5 s statt der reinen 1,0 s Fensterlaenge: Danach ist das Fenster voll UND
# man hatte einen Moment, um nach dem Startwort Luft zu holen.
ANLAUF_S = 1.5


class Zustand(Enum):
    AUS = "aus"              # Freihand abgeschaltet oder App ausgeschlossen
    LAUSCHT = "lauscht"      # wartet auf das Startwort
    AUFNAHME = "aufnahme"    # Startwort erkannt, es wird gesammelt


class Ereignis(Enum):
    START = "start"          # Startwort erkannt → Aufnahme beginnt
    ENDE = "ende"            # lange genug still → Diktat fertig
    ABBRUCH = "abbruch"      # Abbruchwort erkannt → verwerfen


def normalisiere(text: str) -> str:
    """Text auf Vergleichsform bringen: klein, ohne Satzzeichen und Diakritika.

    Whisper schreibt dasselbe Wort mal mit, mal ohne Komma, mal gross — ein
    Startwort, das an einem Punkt scheitert, waere im Alltag unbrauchbar.
    """
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", text)


def _abstand(a: str, b: str) -> int:
    """Levenshtein-Distanz. Klein genug, um sie nicht als Abhaengigkeit zu holen."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    vorher = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        jetzt = [i]
        for j, cb in enumerate(b, 1):
            jetzt.append(min(vorher[j] + 1, jetzt[j - 1] + 1,
                             vorher[j - 1] + (ca != cb)))
        vorher = jetzt
    return vorher[-1]


# Wie weit darf das Gehoerte vom Startwort abweichen? An echten Ausgaben des
# kleinen Modells kalibriert: Es lieferte fuer „Kimono" unter anderem „Kimunno".
# Bei Distanz 2 liegen aber auch „Kino", „Mono", „Simon" und „Simone" — deshalb
# reicht die Distanz allein NICHT. Erst zusammen mit gleichem Wortanfang trennt
# es sauber (gemessen: 15 von 16 Faellen richtig, kein Fehlalarm).
_MAX_ABSTAND = 2
_GLEICHER_ANFANG = 3
# Laengenfenster 2, NICHT 1. Der erste Entwurf stand auf 1 — kalibriert an
# TTS-Stimmen, wo „Kimono" sauber als „Kimono" oder „Kimunno" ankam. An einer
# echten Stimme ueber ein echtes Mikrofon sieht es anders aus: Im Protokoll
# standen „Kimu", „Kimun", „Kimo no" und „Gimo". Das Modell SCHNEIDET das Wort
# ab, es verfaelscht es nicht nur — und abgeschnittene Fassungen sind kuerzer
# als 1 Zeichen Unterschied.
#
# Der Preis: „Kimo" zaehlt jetzt als Treffer. Das ist richtig so — es ist eine
# zerrissene Fassung des Startworts, kein fremdes Wort. Aehnliche Alltagswoerter
# bleiben draussen, weil zusaetzlich der Wortanfang stimmen muss: „Kino" (kin),
# „Mono" (mon) und „Simon" (sim) scheitern daran.
_MAX_LAENGEN_DIFF = 2
# Zu kurze Fetzen bleiben aussen vor: Unter vier Zeichen traegt der
# Anfangsvergleich nicht mehr — „Kim" laege dann neben „Kind" und „Kiel".
_MIN_GEHOERT = 4
# Beim abgeschnittenen Wort wird gegen den gleichlangen ANFANG verglichen — dort
# ist nur ein Fehler erlaubt, sonst faengt „Kimme" mit ein.
_MAX_ABSCHNITT_FEHLER = 1


def _klingt_wie(gehoert: str, ziel: str) -> bool:
    """Ist `gehoert` eine verunglueckte Fassung von `ziel`?

    NICHT bei Woertern, die mit dem vollstaendigen Startwort BEGINNEN: „Kimonos"
    und „Kimonoartiges" sind eigene Woerter, keine Hoerfehler — das war schon
    immer so und bleibt so. Genau diese Regel macht die Unschaerfe vertretbar.
    """
    if gehoert == ziel:
        return True
    if gehoert.startswith(ziel):
        return False                      # Flexion/Zusammensetzung → anderes Wort
    if len(gehoert) < _MIN_GEHOERT:
        return False
    if gehoert[:_GLEICHER_ANFANG] != ziel[:_GLEICHER_ANFANG]:
        # Der Wortanfang muss sitzen. Das ist die Bedingung, die „Kino", „Mono"
        # und „Simon" draussen haelt — sie liegen distanzmaessig genauso nah.
        return False
    # a) verfaelscht: „Kimunno", „Kimano" — aehnliche Laenge, wenige Fehler
    if (abs(len(gehoert) - len(ziel)) <= _MAX_LAENGEN_DIFF
            and _abstand(gehoert, ziel) <= _MAX_ABSTAND):
        return True
    # b) ABGESCHNITTEN: „Kimu", „Kimo". Das Modell bricht bei undeutlicher
    # Aussprache mitten im Wort ab — real im Protokoll. Solche Fetzen haben zum
    # ganzen Wort eine grosse Distanz (kimu→kimono = 3), zum gleichlangen ANFANG
    # aber fast keine (kimu→kimo = 1). Deshalb dagegen vergleichen.
    if len(gehoert) < len(ziel):
        return _abstand(gehoert, ziel[:len(gehoert)]) <= _MAX_ABSCHNITT_FEHLER
    return False


def zerlege_woerter(roh) -> tuple:
    """„Kimono, Apfel" oder eine Liste → („Kimono", „Apfel").

    Eine Zeile pro Wort ist die Eingabeform in den Einstellungen; Kommas werden
    zusaetzlich akzeptiert, weil man sie beim Tippen ohnehin setzt. Reihenfolge
    bleibt erhalten (das erste Wort ist das, was in der Pille steht), Doppelte und
    Leeres fallen heraus.
    """
    if roh is None:
        return ()
    teile = roh if isinstance(roh, (list, tuple)) else re.split(r"[\n,;]+", str(roh))
    gesehen, ergebnis = set(), []
    for teil in teile:
        wort = str(teil).strip()
        if not wort or wort.lower() in gesehen:
            continue
        gesehen.add(wort.lower())
        ergebnis.append(wort)
    return tuple(ergebnis)


def woerter_als_text(roh) -> str:
    """Fuer Anzeige und Protokoll: („Kimono", „Apfel") → „Kimono oder Apfel".

    Die gespeicherte Form ist zeilengetrennt; die direkt ins Tray-Menue oder in
    eine Statuszeile zu haengen ergaebe dort einen Umbruch mitten im Satz.
    """
    woerter = zerlege_woerter(roh)
    if len(woerter) <= 1:
        return woerter[0] if woerter else ""
    return " oder ".join((", ".join(woerter[:-1]), woerter[-1]))


def enthaelt_eines(text: str, woerter, unscharf: bool = True) -> str:
    """Welches der Woerter kommt in `text` vor? ("" = keines).

    Gibt das TREFFENDE Wort zurueck, nicht nur True: Im Protokoll soll stehen,
    worauf Fleech angesprungen ist — bei mehreren Startwoertern ist „es hat
    ausgeloest" sonst nur die halbe Auskunft.
    """
    for wort in zerlege_woerter(woerter):
        if enthaelt_wort(text, wort, unscharf=unscharf):
            return wort
    return ""


def enthaelt_wort(text: str, wort: str, unscharf: bool = True) -> bool:
    """Kommt `wort` als eigenstaendiges Wort in `text` vor?

    Wortgrenzen sind Pflicht: Ein Startwort „Kimono" darf nicht in „Kimonos"
    oder mitten in einem laengeren Wort anschlagen.

    `unscharf` faengt zusaetzlich Hoerfehler des kleinen Pruefmodells ab. Das ist
    kein Feinschliff, sondern noetig: Gemessen machte es aus „Kimono" im Satz
    „Kimunno" — der exakte Vergleich schlug fehl, und Freihand loeste nie aus,
    obwohl alles richtig eingestellt war.
    """
    wort = normalisiere(wort).strip()
    if not wort:
        return False
    normaler_text = normalisiere(text)
    if re.search(rf"(?<!\w){re.escape(wort)}(?!\w)", normaler_text) is not None:
        return True
    if not unscharf or len(wort) < 4:
        # Unter vier Zeichen ist jede Toleranz zu gross — „Kim" laege dann neben
        # „Kind", „Kim" und „Kiel".
        return False
    woerter = normaler_text.split()
    if any(_klingt_wie(w, wort) for w in woerter):
        return True
    # Zerrissene Schreibweise: Das Modell setzt bei unklarer Aussprache gern eine
    # Luecke mitten ins Wort — real gemessen „Kimo no" fuer „Kimono". Deshalb
    # zusaetzlich benachbarte Wortpaare zusammengezogen pruefen.
    return any(_klingt_wie(a + b, wort) for a, b in zip(woerter, woerter[1:]))


@dataclass
class Einstellungen:
    """Alles, was der Nutzer am Freihand-Modus einstellen kann."""

    aktiv: bool = False
    # Das Startwort — ODER mehrere, durch Zeilenumbruch/Komma getrennt. Mehrere
    # sind der Normalfall geworden: Welches Wort die eigene Aussprache zuverlaessig
    # trifft, laesst sich nicht vorhersagen, und zwei oder drei Kandidaten
    # nebeneinander ersetzen das Herumprobieren mit einem einzigen.
    startwort: str = "Kimono"

    @property
    def startwoerter(self) -> tuple:
        """Alle Startwoerter als Tupel — leere und doppelte fallen heraus."""
        return zerlege_woerter(self.startwort)
    abbruchwort: str = "Abbrechen"
    # Wie lange Stille ein Diktat beendet. 2 s ist der Vorschlag aus dem
    # Briefing: kurz genug, um nicht zu warten, lang genug fuer eine Denkpause.
    stille_s: float = 2.0
    # Prozessnamen (klein), in denen NICHT gelauscht wird — Spiele, Meetings.
    ausgeschlossene_apps: tuple = ()

    def clamp(self) -> "Einstellungen":
        self.stille_s = max(1.0, min(4.0, float(self.stille_s or 2.0)))
        return self


@dataclass
class Statistik:
    """Fehlaktivierungen im Betrieb messbar machen — wie bei den Guards.

    Ohne Zahlen bliebe „gefuehlt zu oft" die einzige Bewertung, und daraus laesst
    sich kein Schwellenwert ableiten.
    """

    pruefungen: int = 0          # tiny lief (VAD hatte Sprache gemeldet)
    aktivierungen: int = 0       # Startwort erkannt
    verworfen: int = 0           # per Abbruchwort weggeworfen
    seit: float = field(default_factory=time.monotonic)

    def als_text(self) -> str:
        stunden = max((time.monotonic() - self.seit) / 3600.0, 1e-6)
        return (f"{self.aktivierungen} Aktivierungen aus {self.pruefungen} "
                f"Prüfungen ({self.aktivierungen / stunden:.1f}/h)")


class Lauscher:
    """Zustandsmaschine fuer den Freihand-Modus.

    Kennt kein Audio-Geraet und kein Qt: Audio kommt ueber `verarbeite()` herein,
    Ereignisse kommen als Rueckgabewert heraus. Der Aufrufer entscheidet, was
    daraus folgt.

    `vad` und `erkenner` werden hineingereicht statt hier erzeugt — so laeuft die
    ganze Logik im Test mit Attrappen, ohne Modelle zu laden.
    """

    def __init__(self, einstellungen: Einstellungen, vad=None, erkenner=None,
                 samplerate: int = SAMPLERATE, mitschnitt=None):
        self.einstellungen = einstellungen.clamp()
        self._vad = vad                  # callable(np.ndarray) -> bool (Sprache?)
        self._erkenner = erkenner        # callable(np.ndarray) -> str (Text)
        # Optional: callable(audio, text, treffer) — schreibt das GEPRUEFTE Fenster
        # zur Fehlersuche weg. Wird von aussen hineingereicht, damit dieses Modul
        # dateifrei bleibt; das ist die technische Zusicherung hinter „kein
        # Mitschnitt", und sie soll nicht durch eine Diagnose aufgeweicht werden,
        # die versehentlich immer mitläuft.
        self._mitschnitt = mitschnitt
        self.samplerate = samplerate
        self.statistik = Statistik()

        self.zustand = Zustand.AUS
        self._ring = np.zeros(0, dtype=np.float32)   # letzte Sekunden (Lauschen)
        self._aufnahme: list = []                    # gesammelte Bloecke (Diktat)
        self._letzte_pruefung = 0.0
        self._letzte_sprache = 0.0
        self._sperre_bis = 0.0
        # Wuensche aus der Pille. BEWUSST als Flags und nicht als direkter
        # Eingriff: Die Knoepfe werden im GUI-Thread geklickt, die
        # Zustandsmaschine laeuft im Pruef-Thread. Ein einfaches Bool zu setzen
        # ist atomar; die Maschine wertet es beim naechsten Block aus (< 200 ms)
        # und bleibt damit der einzige Ort, an dem der Zustand wechselt.
        self._ende_gewuenscht = False
        self._abbruch_gewuenscht = False
        self._pausiert = False

    # -- Steuerung -------------------------------------------------------------------

    def start_lauschen(self) -> None:
        if not self.einstellungen.aktiv:
            self.zustand = Zustand.AUS
            return
        self.zustand = Zustand.LAUSCHT
        self._ring = np.zeros(0, dtype=np.float32)
        self._aufnahme = []
        log.info("Freihand: lauscht auf %s.",
                 woerter_als_text(self.einstellungen.startwort) or "—")

    def stop_lauschen(self) -> None:
        self.zustand = Zustand.AUS
        self._ring = np.zeros(0, dtype=np.float32)
        self._aufnahme = []

    @property
    def erkenner(self):
        """Die laufende Startwort-Erkennung (None = keine).

        Öffentlich, damit die Startwort-Probe in den Einstellungen GENAU DIE
        Instanz benutzt, die im Betrieb entscheidet — statt eine gleichartige
        nachzubauen, die dann doch woanders steht.
        """
        return self._erkenner

    # -- Eingriffe aus der Pille ------------------------------------------------------
    #
    # Ohne diese drei war die Pille beim Freihand-Diktat eine Attrappe: Sie zeigte
    # „Aufnahme laeuft" und aktivierte ihre Knoepfe, aber alle drei wirkten auf den
    # `RecordingController` — und der laeuft beim Freihand-Weg gar nicht. Abbrechen
    # tat nichts, Fertig tat nichts, Pause meldete „es laeuft keine Aufnahme".
    #
    # Schlimmer noch in einem Raum mit Hintergrundgeraeuschen: Das VAD meldet dort
    # dauernd Sprache, die Stille-Erkennung greift nie, und ohne wirksamen Knopf
    # kommt man aus der Aufnahme nicht mehr heraus.

    def beende_vorzeitig(self) -> bool:
        """Pille ✓ — jetzt fertig, Diktat verarbeiten. False = es lief nichts."""
        if self.zustand is not Zustand.AUFNAHME:
            return False
        self._ende_gewuenscht = True
        return True

    def verwirf_vorzeitig(self) -> bool:
        """Pille ✕ — Aufnahme wegwerfen, nichts einfuegen."""
        if self.zustand is not Zustand.AUFNAHME:
            return False
        self._abbruch_gewuenscht = True
        return True

    def pausiere_diktat(self, an: bool) -> bool:
        """Pille ⏸ — sammeln anhalten, ohne das Diktat zu verlieren.

        Die Stille-Uhr ruht mit: Sonst waere das Diktat nach `stille_s` beendet,
        waehrend man noch mit jemandem spricht — genau das, was die Pause
        verhindern soll.
        """
        if self.zustand is not Zustand.AUFNAHME:
            return False
        self._pausiert = bool(an)
        return True

    @property
    def diktat_pausiert(self) -> bool:
        return self._pausiert and self.zustand is Zustand.AUFNAHME

    def app_erlaubt(self, app: str) -> bool:
        """Darf in dieser Anwendung gelauscht werden?

        Spiele und Meeting-Werkzeuge stehen auf der Ausschlussliste: Dort ist
        Sprache im Raum die Regel, und eine Fehlaktivierung faellt mitten in ein
        Gespraech.
        """
        app = (app or "").strip().lower()
        return bool(app) and app not in {
            a.strip().lower() for a in self.einstellungen.ausgeschlossene_apps}

    def aufnahme_audio(self) -> np.ndarray:
        """Das gesammelte Diktat (ohne das Startwort-Fenster)."""
        if not self._aufnahme:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._aufnahme)

    # -- Der Kern --------------------------------------------------------------------

    def verarbeite(self, block: np.ndarray, jetzt: float | None = None):
        """Einen Audio-Block hineingeben. Rueckgabe: `Ereignis` oder None.

        `jetzt` ist injizierbar, damit Tests die Stille-Erkennung ohne echtes
        Warten pruefen koennen.
        """
        if self.zustand is Zustand.AUS or block is None or not len(block):
            return None
        jetzt = time.monotonic() if jetzt is None else jetzt
        block = np.asarray(block, dtype=np.float32).reshape(-1)

        if self.zustand is Zustand.LAUSCHT:
            return self._lausche(block, jetzt)
        return self._nimm_auf(block, jetzt)

    def _lausche(self, block: np.ndarray, jetzt: float):
        # Ringpuffer: nur die letzten Sekunden, alles davor faellt heraus. Das ist
        # die technische Zusicherung hinter „kein Mitschnitt".
        self._ring = np.concatenate([self._ring, block])
        grenze = int(FENSTER_S * self.samplerate)
        if len(self._ring) > grenze:
            self._ring = self._ring[-grenze:]

        if jetzt < self._sperre_bis:
            return None
        if len(self._ring) < int(0.8 * self.samplerate):
            return None                      # zu wenig Material fuer ein Wort
        if jetzt - self._letzte_pruefung < PRUEF_ABSTAND_S:
            return None
        if not self._ist_sprache(self._ring):
            return None                      # Stufe 1 haelt — tiny bleibt aus

        self._letzte_pruefung = jetzt
        self.statistik.pruefungen += 1
        text = self._erkenne(self._ring)
        if not text:
            return None
        treffer = enthaelt_eines(text, self.einstellungen.startwort)
        if treffer:
            self.statistik.aktivierungen += 1
            # Welches Wort getroffen hat, gehoert ins Protokoll: Bei mehreren
            # Startwoertern ist „hat ausgeloest" sonst nur die halbe Auskunft.
            log.info("Freihand: Startwort %r erkannt in %r.",
                     treffer, text.strip()[:60])
            self.zustand = Zustand.AUFNAHME
            # Das Startwort-Fenster wird NICHT ins Diktat uebernommen — sonst
            # stuende „Kimono" am Anfang jedes Textes.
            self._aufnahme = []
            self._ring = np.zeros(0, dtype=np.float32)
            self._letzte_sprache = jetzt
            self._sperre_bis = jetzt + SPERRE_NACH_START_S
            return Ereignis.START
        return None

    def _nimm_auf(self, block: np.ndarray, jetzt: float):
        # Die Knoepfe der Pille zuerst — sie sollen sofort wirken und nicht erst,
        # wenn die Stille-Erkennung zufaellig zustimmt.
        if self._abbruch_gewuenscht:
            log.info("Freihand: per Pille verworfen.")
            self.statistik.verworfen += 1
            self._nach_diktat(jetzt)
            return Ereignis.ABBRUCH
        if self._ende_gewuenscht:
            log.info("Freihand: per Pille beendet (%.1f s).",
                     len(self.aufnahme_audio()) / float(self.samplerate or SAMPLERATE))
            # Bewusst ueber denselben Abschluss wie die Stille-Erkennung: Der
            # Fertig-Knopf darf die Inhaltspruefung NICHT umgehen. Wer ihn direkt
            # nach dem Startwort drueckt, hat nichts gesagt — ohne die Pruefung
            # ginge Mikrofonrauschen in die Pipeline, und Whisper macht daraus
            # „G-G-G-G-…" (real passiert, siehe _hat_inhalt).
            return self._schliesse_ab(jetzt)
        if self._pausiert:
            # Nichts sammeln UND die Stille-Uhr mitziehen: Sonst waere das Diktat
            # nach `stille_s` beendet, waehrend man noch daneben spricht.
            self._letzte_sprache = jetzt
            return None
        self._aufnahme.append(block)
        # Deckel gegen die Aufnahme, die nie endet. In einem Raum mit laufendem
        # Video meldet das VAD dauernd Sprache — die Stille-Erkennung greift dann
        # nie, und ohne wirksamen Knopf sass man fest. Der Knopf wirkt jetzt; der
        # Deckel ist die zweite Sicherung fuer den Fall, dass niemand hinsieht.
        if len(self.aufnahme_audio()) / float(self.samplerate or SAMPLERATE) >= MAX_DIKTAT_S:
            log.warning("Freihand: %.0f s erreicht — Diktat wird beendet.", MAX_DIKTAT_S)
            self._nach_diktat(jetzt)
            return Ereignis.ENDE
        # Das VAD bekommt ein FENSTER, nicht den einzelnen Block. Gemessen:
        #
        #   Fensterlaenge   Sprache erkannt (bei laufender Rede)
        #   0,2 s (= 1 Block)     0,0 %      <- so war es
        #   0,8 s                98,6 %
        #   1,0 s               100,0 %
        #
        # Silero verlangt `min_speech_duration_ms=200` — genau die Blocklaenge.
        # Auf einem einzelnen Block meldete es deshalb NIE Sprache, die Stille-Uhr
        # lief durch, und jede Aufnahme endete nach exakt `stille_s`. Im Protokoll
        # war jedes Freihand-Diktat 2,0 s lang: Alles, was der Nutzer danach sagte,
        # fehlte — und aus dem Rauschen wurde „T-T-T-T-…".
        if self._ist_sprache(self._sprach_fenster()):
            self._letzte_sprache = jetzt
            return None
        # Anlaufzeit: Solange zu wenig Audio da ist, KANN das VAD keine Sprache
        # melden — die Uhr wuerde einen Messfehler messen (siehe ANLAUF_S).
        rate = float(self.samplerate or SAMPLERATE)
        if len(self.aufnahme_audio()) / rate < ANLAUF_S:
            self._letzte_sprache = jetzt
            return None
        if jetzt - self._letzte_sprache < self.einstellungen.stille_s:
            return None
        return self._schliesse_ab(jetzt)

    def _schliesse_ab(self, jetzt: float):
        """Diktat zu Ende — der EINE Weg dorthin, egal ob Stille oder Knopf.

        Beide muessen durch dieselben zwei Pruefungen: Abbruchwort und „war
        ueberhaupt Sprache drin". Ein zweiter Weg daran vorbei waere genau die
        Sorte Abkuerzung, die spaeter Rauschen ins Textfeld schreibt.
        """
        # Vorher pruefen, ob das Abbruchwort gefallen ist — dann wird verworfen
        # statt eingefuegt.
        text = self._erkenne(self.aufnahme_audio())
        if text and enthaelt_wort(text, self.einstellungen.abbruchwort):
            self.statistik.verworfen += 1
            log.info("Freihand: Abbruchwort erkannt — verworfen.")
            self._nach_diktat(jetzt)
            return Ereignis.ABBRUCH
        # War ueberhaupt etwas drin? Real passiert: Man sagt das Startwort und
        # wartet, ob Fleech reagiert — dabei laeuft die Aufnahme in die Stille.
        # Das Ergebnis waren zwei Sekunden Mikrofonrauschen, aus denen Whisper
        # „G-G-G-G-G-G-…" halluzinierte und einfuegte. Das VAD ist ohnehin da.
        if not self._hat_inhalt():
            self.statistik.verworfen += 1
            log.info("Freihand: Aufnahme ohne Sprache — verworfen (%.1f s).",
                     len(self.aufnahme_audio()) / float(self.samplerate or SAMPLERATE))
            self._nach_diktat(jetzt)
            return Ereignis.ABBRUCH
        self._nach_diktat(jetzt)
        return Ereignis.ENDE

    def _sprach_fenster(self) -> np.ndarray:
        """Die letzten Sekunden der laufenden Aufnahme — Material fuers VAD.

        Der Preis fuer das groessere Fenster: Die Stille-Erkennung wird um bis zu
        eine Fensterlaenge traeger, weil am Ende noch Sprache im Fenster steht.
        Das ist der richtige Handel — lieber eine Sekunde spaeter fertig als ein
        Diktat, das nach zwei Sekunden abgeschnitten wird.
        """
        if not self._aufnahme:
            return np.zeros(0, dtype=np.float32)
        rate = int(self.samplerate or SAMPLERATE)
        noetig = int(VAD_FENSTER_S * rate)
        gesammelt = []
        laenge = 0
        for block in reversed(self._aufnahme):
            gesammelt.append(block)
            laenge += len(block)
            if laenge >= noetig:
                break
        return np.concatenate(list(reversed(gesammelt)))[-noetig:]

    def _hat_inhalt(self) -> bool:
        """Enthaelt die gesammelte Aufnahme genug echte Sprache?

        Bewusst mit demselben VAD, das schon Stufe 1 macht: Ein zweiter, eigener
        Schwellenwert waere eine zweite Stellschraube, die irgendwann anders
        eingestellt ist als die erste.
        """
        # `_aufnahme` ist eine LISTE von Bloecken — `aufnahme_audio()` fuegt sie
        # zusammen. Direkt darauf zu messen zaehlte Bloecke statt Samples.
        audio = self.aufnahme_audio()
        if audio is None or not len(audio):
            return False
        rate = float(self.samplerate or SAMPLERATE)
        if len(audio) / rate < MIN_DIKTAT_S:
            return False
        return self._ist_sprache(audio)

    def _nach_diktat(self, jetzt: float) -> None:
        """Zurueck ins Lauschen. Das Diktat holt der Aufrufer vorher ab.

        Die Sperre verhindert, dass der eigene Nachsatz sofort die naechste
        Aufnahme ausloest — das Abbruchwort wirkt bewusst NUR als Verwerfen, nicht
        als Neustart: Sonst machte ein Versprecher daraus eine Endlosschleife.
        """
        self.zustand = Zustand.LAUSCHT
        self._ring = np.zeros(0, dtype=np.float32)
        self._sperre_bis = jetzt + SPERRE_NACH_START_S
        # Wuensche gelten immer nur fuer das Diktat, in dem sie geaeussert wurden.
        # Ein stehengebliebenes Flag wuerde das NAECHSTE sofort wieder beenden.
        self._ende_gewuenscht = False
        self._abbruch_gewuenscht = False
        self._pausiert = False

    # -- Die zwei Stufen -------------------------------------------------------------

    def _ist_sprache(self, audio: np.ndarray) -> bool:
        if self._vad is None:
            return True                      # ohne VAD: jede Pruefung durchlassen
        try:
            return bool(self._vad(audio))
        except Exception:
            log.debug("VAD-Fehler — Block gilt als Sprache.", exc_info=True)
            return True

    def _erkenne(self, audio: np.ndarray) -> str:
        if self._erkenner is None or not len(audio):
            return ""
        try:
            text = self._erkenner(audio) or ""
        except Exception:
            log.debug("Startwort-Erkennung fehlgeschlagen.", exc_info=True)
            return ""
        # DIAGNOSE: Ohne diese Zeile ist nicht feststellbar, warum Freihand nicht
        # ausloest — man sieht nur, dass nichts passiert, und verdaechtigt das
        # Startwort. Genau daran ist die erste Fehlersuche gescheitert. Auf INFO,
        # weil es je Pruefung hoechstens einmal pro Sekunde anfaellt und im
        # Zweifelsfall die einzige Spur ist.
        wort = " / ".join(self.einstellungen.startwoerter) or "—"
        treffer = bool(text) and bool(
            enthaelt_eines(text, self.einstellungen.startwort))
        if text:
            log.info("Freihand hoerte: %r  (Startwort %r: %s)", text, wort,
                     "TREFFER" if treffer else "kein Treffer")
        if self._mitschnitt is not None:
            # Auch bei LEEREM Text mitschneiden — „das Modell hat gar nichts
            # gehoert" ist als Befund genauso wertvoll wie ein falsches Wort.
            try:
                self._mitschnitt(audio, text, treffer)
            except Exception:
                log.debug("Freihand-Mitschnitt fehlgeschlagen.", exc_info=True)
        return text


# -- Die zwei Stufen als echte Implementierung -----------------------------------------


def baue_vad(schwelle: float = 0.5):
    """Silero-VAD aus faster-whisper. Rueckgabe: callable(audio) -> bool.

    Bewusst kein eigenes Paket: Das Modell steckt bereits im Bundle, jede weitere
    Abhaengigkeit waere 30 MB im Installer fuer dieselbe Funktion.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    optionen = VadOptions(threshold=schwelle, min_speech_duration_ms=200)

    def hat_sprache(audio: np.ndarray) -> bool:
        return bool(get_speech_timestamps(audio, optionen, sampling_rate=SAMPLERATE))

    return hat_sprache


def baue_erkenner_aus_engine(engine, sprache: str = "de", startwort: str = ""):
    """Startwort-Pruefung ueber das Modell, das ohnehin fuers Diktat geladen ist.

    Das ist seit 5.7.0 der Normalfall — aus drei Gruenden, alle gemessen:

    - **Schneller.** 2 s Audio: large-v3-turbo auf der GPU 141 ms (Median),
      `base` auf der CPU 437 ms. Und die Rechenzeit war hier nie nur Komfort:
      Sie hat den Mikrofonstrom zerhackt (siehe `FreihandStream`).
    - **Genauer.** Es ist dasselbe Modell, das im Diktat jedes Wort trifft.
    - **Kein zusaetzliches VRAM**, weil kein zweites Modell geladen wird.

    Der Preis ist GPU-Last waehrend des Lauschens — aber nur, wenn das VAD
    ueberhaupt Sprache meldet, und hoechstens alle `PRUEF_ABSTAND_S`.
    """
    # Bei MEHREREN Startwoertern werden alle vorgesagt: Das Priming wirkt je
    # Wort, und ein nicht geprimtes Wort waere genau das, das nie erkannt wird.
    _woerter = zerlege_woerter(startwort)
    prompt = " ".join(f"{w}." for w in _woerter) if _woerter else None
    sprache = (sprache or "de").lower()
    sprache = None if sprache in ("", "auto") else sprache

    def erkenne(audio: np.ndarray) -> str:
        return engine.transcribe_kurz(audio, language=sprache,
                                      initial_prompt=prompt)

    return erkenne


def baue_erkenner(modell_groesse: str = "tiny", sprache: str = "de",
                  startwort: str = ""):
    """Eigenes kleines Whisper-Modell fuer das Startwort — der SPARSAME Weg.

    Fuer Rechner ohne brauchbare GPU, wo `baue_erkenner_aus_engine` das Diktat
    ausbremsen wuerde. Auf der CPU, damit die Grafikkarte frei bleibt;
    `beam_size=1`, weil es nur um die Frage geht, ob ein bestimmtes Wort gefallen
    ist, nicht um schoene Saetze.

    `startwort` wird dem Modell als `initial_prompt` vorgesagt — derselbe Weg,
    den die Pipeline fuers Woerterbuch nutzt. Gemessen bringt das zweierlei: Das
    Wort wird zuverlaessiger getroffen (aus „Kimo no" wurde „Kimono"), und die
    Pruefung wird SCHNELLER, weil das Modell weniger raet (350 → 226 ms).

    Die naheliegende Sorge — das Modell koennte das vorgesagte Wort in beliebiges
    Gerede hineinhoeren — wurde geprueft: an zwoelf normalen Saetzen plus
    Rauschen und Stille null Fehlalarme. Das ABBRUCHWORT wird bewusst NICHT
    mitgegeben; dort trat in derselben Messung ein Fehltreffer auf („Apfel"
    wurde zu „Abbrechen").
    """
    from faster_whisper import WhisperModel

    modell = WhisperModel(modell_groesse, device="cpu", compute_type="int8")
    # Bei MEHREREN Startwoertern werden alle vorgesagt: Das Priming wirkt je
    # Wort, und ein nicht geprimtes Wort waere genau das, das nie erkannt wird.
    _woerter = zerlege_woerter(startwort)
    prompt = " ".join(f"{w}." for w in _woerter) if _woerter else None

    def erkenne(audio: np.ndarray) -> str:
        # `vad_filter=True`: Das Prueffenster ist 2 s lang, das Wort darin oft
        # nur 0,4 s — der Rest ist Stille. Genau daraus halluziniert Whisper
        # („Vielen Dank.", „Ich bin hier.", alles echt aus dem Protokoll) und
        # ueberdeckt damit, was wirklich gesagt wurde.
        segmente, _info = modell.transcribe(
            audio, language=sprache, beam_size=1, vad_filter=True,
            initial_prompt=prompt,
        )
        return " ".join(s.text for s in segmente).strip()

    return erkenne


class FreihandStream:
    """Dauer-Mikrofonstrom, der den Lauscher fuettert.

    BEWUSST EIN EIGENER STROM statt eines Umbaus am `Recorder`: Der ist der
    erprobte Pfad fuer jedes normale Diktat, und das Briefing sagt ausdruecklich,
    dass Freihand dazukommt und nichts ersetzt. Ein Fehler hier darf den Hotkey-Weg
    nicht mitreissen.

    Solange eine normale Aufnahme laeuft, PAUSIERT dieser Strom (`pausiere`) —
    zwei gleichzeitig sammelnde Wege waeren nicht nur doppelte Last, sondern
    zwei konkurrierende Diktate.

    ## Warum ein eigener Arbeiter-Thread

    Bis 5.6.0 lief die Zustandsmaschine DIREKT im Audio-Callback — und damit auch
    das Whisper-Pruefmodell. Das war der Grund, warum Freihand so viel schlechter
    hoerte als der Hotkey-Weg, und es hatte nichts mit dem Startwort zu tun.
    Gemessen an echter Hardware, 200-ms-Bloecke:

        Rechenzeit im Callback     Audio, das ankommt
        keine                            97,3 %
        140 ms                           97,3 %
        440 ms  (base auf der CPU)       49,6 %   <- der Ist-Zustand
        900 ms                           36,1 %

    PortAudio wartet nicht: Was waehrend der Rechnung hereinkommt, faellt weg
    (`input_overflow`). Bei den gemessenen 437 ms Median je Pruefung ging also
    ungefaehr die HAELFTE des Gesprochenen verloren — das Pruefmodell bekam
    zerhackte Fetzen und machte daraus „Ich bin hier.", „Wirksam.", „Das ist
    nicht so." (alles echt aus dem Protokoll). Der Hotkey-Weg blieb tadellos,
    weil `audio.Recorder` im Callback nur kopiert.

    Deshalb: Der Callback legt den Block nur in eine Warteschlange (Mikrosekunden),
    ein eigener Thread rechnet. Der Zeitstempel wird MITGEGEBEN statt im Arbeiter
    genommen — sonst waere die Stille-Uhr um den Rueckstand verschoben.
    """

    BLOCK_S = 0.2      # Groesse der Bloecke, die der Lauscher bekommt

    # Deckel fuer die Warteschlange. 15 s Rueckstand heisst, dass das Pruefmodell
    # dauerhaft langsamer als Echtzeit ist — dann ist Verwerfen mit Warnung
    # ehrlicher als unbegrenzt wachsender Speicher.
    WARTESCHLANGE_MAX = int(15.0 / BLOCK_S)

    def __init__(self, lauscher: Lauscher, on_ereignis, geraet=None,
                 samplerate: int = SAMPLERATE):
        self.lauscher = lauscher
        self._on_ereignis = on_ereignis      # callable(Ereignis, audio|None)
        self._geraet = geraet
        self.samplerate = samplerate
        self._stream = None
        self._pausiert = False
        # Aktueller Eingangspegel (RMS). Die Pille zeigte beim Freihand-Diktat
        # eine tote Wellenlinie: Ihr Pegel kommt vom Recorder, und der laeuft
        # hier gar nicht — es gab schlicht niemanden, der ihn speist.
        self.level = 0.0
        self._warteschlange: queue.Queue = queue.Queue(
            maxsize=self.WARTESCHLANGE_MAX)
        self._arbeiter: threading.Thread | None = None
        self._arbeitet = threading.Event()
        self._ueberlauf = 0                  # verworfene Bloecke (Diagnose)

    @property
    def laeuft(self) -> bool:
        return self._stream is not None

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd

            # Den Geraetenamen AUFLOESEN statt ihn durchzureichen. Unter Windows
            # meldet dasselbe Mikrofon sich einmal je Host-API — ein Scarlett Solo
            # taucht als MME, DirectSound, WASAPI und WDM-KS auf. sounddevice
            # weigert sich dann mit „Multiple input devices found" und der Strom
            # startet NIE: Freihand blieb stumm aus, unabhaengig vom Startwort.
            #
            # Der Hotkey-Weg (audio.Recorder) macht das laengst richtig; hier fehlte
            # es. Bewusst dieselbe Funktion und keine zweite Auflösung, damit die
            # beiden Wege nicht wieder auseinanderlaufen.
            from .audio import resolve_input_device

            geraet = resolve_input_device(self._geraet)
            self._stream = self._oeffne(sd, geraet)
            self._starte_arbeiter()
            self._stream.start()
        except Exception:
            # Zweiter Versuch auf dem Systemstandard. Ein defektes oder abgezogenes
            # Wunschmikrofon soll Freihand nicht abschalten — der Hotkey-Weg wuerde
            # in derselben Lage ebenfalls weiterlaufen.
            log.warning("Freihand-Strom mit %r nicht startbar — versuche Standardgeraet.",
                        self._geraet, exc_info=True)
            try:
                import sounddevice as sd

                self._stream = self._oeffne(sd, None)
                self._starte_arbeiter()
                self._stream.start()
            except Exception:
                log.exception("Freihand-Strom nicht startbar — Modus bleibt aus.")
                self._stream = None
                return False
        self.lauscher.start_lauschen()
        log.info("Freihand-Strom laeuft (Startwort: %s).",
                 woerter_als_text(self.lauscher.einstellungen.startwort))
        return True

    def _oeffne(self, sd, geraet):
        return sd.InputStream(
            samplerate=self.samplerate, channels=1, dtype="float32",
            device=geraet, blocksize=int(self.BLOCK_S * self.samplerate),
            callback=self._callback,
        )

    def stop(self) -> None:
        strom, self._stream = self._stream, None
        self.lauscher.stop_lauschen()
        # ERST den Strom schliessen, dann den Arbeiter: Andersherum schoebe der
        # noch laufende Callback Bloecke in eine Warteschlange, die niemand mehr
        # leert.
        if strom is not None:
            try:
                strom.stop()
                strom.close()
            except Exception:
                log.debug("Freihand-Strom liess sich nicht sauber schliessen.",
                          exc_info=True)
        self._stoppe_arbeiter()
        if strom is not None:
            log.info("Freihand-Strom beendet.")

    # -- Arbeiter-Thread ---------------------------------------------------------------

    def _starte_arbeiter(self) -> None:
        if self._arbeiter is not None:
            return
        self._arbeitet.set()
        self._arbeiter = threading.Thread(
            target=self._arbeite, name="freihand-pruefung", daemon=True)
        self._arbeiter.start()

    def _stoppe_arbeiter(self) -> None:
        self._arbeitet.clear()
        arbeiter, self._arbeiter = self._arbeiter, None
        if arbeiter is not None:
            # Kurz warten reicht: Der Thread prueft das Ereignis im Sekundentakt
            # und ist ein Daemon — ein haengendes Modell darf das Beenden der App
            # nicht aufhalten.
            arbeiter.join(timeout=2.0)
        while True:
            try:
                self._warteschlange.get_nowait()
            except queue.Empty:
                break

    def _arbeite(self) -> None:
        """Hier laeuft die teure Arbeit — VAD und Whisper, ausserhalb des Audio-Threads."""
        while self._arbeitet.is_set():
            self.verarbeite_wartende(timeout=0.25)

    def verarbeite_wartende(self, timeout: float = 0.0) -> int:
        """Wartende Bloecke durch die Zustandsmaschine schicken. Rueckgabe: Anzahl.

        Der Arbeiter-Thread ruft das in seiner Schleife auf; Tests rufen es direkt
        und kommen so ohne Thread und ohne Warten aus. Deshalb ist es eine
        richtige Methode und kein Testhilfsmittel: Es gibt genau EINEN Weg, wie
        ein Block verarbeitet wird.
        """
        gemacht = 0
        while True:
            try:
                block, zeitpunkt = (self._warteschlange.get(timeout=timeout)
                                    if timeout else
                                    self._warteschlange.get_nowait())
            except queue.Empty:
                return gemacht
            gemacht += 1
            try:
                # Der Zeitstempel stammt aus dem Callback, NICHT von hier: Haengt
                # der Arbeiter zurueck, liefe die Stille-Uhr sonst zu schnell und
                # schnitte Diktate mitten im Satz ab.
                ereignis = self.lauscher.verarbeite(block, zeitpunkt)
                if ereignis is not None:
                    audio = (self.lauscher.aufnahme_audio()
                             if ereignis is Ereignis.ENDE else None)
                    self._on_ereignis(ereignis, audio)
            except Exception:
                log.exception("Freihand-Verarbeitung fehlgeschlagen.")
            if timeout:
                return gemacht          # im Thread: pro Runde einer, dann Abbruch pruefen

    def rueckstand(self) -> float:
        """Wie viele Sekunden Audio noch auf ihre Pruefung warten (Diagnose)."""
        return self._warteschlange.qsize() * self.BLOCK_S

    def pausiere(self, an: bool) -> None:
        """Waehrend einer normalen Aufnahme oder in ausgeschlossenen Apps."""
        if an != self._pausiert:
            log.debug("Freihand %s.", "pausiert" if an else "hoert wieder")
        self._pausiert = an
        if an:
            # Zustand zuruecksetzen: Ein halb gefuellter Ringpuffer aus der Zeit
            # davor waere beim Fortsetzen ein falscher Bezugspunkt. Aus demselben
            # Grund muss die Warteschlange leer sein — noch nicht verarbeitete
            # Bloecke stammen aus der Zeit VOR der Pause.
            while True:
                try:
                    self._warteschlange.get_nowait()
                except queue.Empty:
                    break
            self.lauscher.start_lauschen()

    def _callback(self, indata, frames, time_info, status) -> None:
        """Audio-Thread! Hier NICHTS Schweres und NICHTS mit Qt.

        Nur kopieren, Pegel rechnen, ablegen — alles im Mikrosekundenbereich. Die
        Zustandsmaschine lief bis 5.6.0 direkt hier; siehe den Klassenkommentar,
        warum das die halbe Aufnahme kostete.
        """
        if self._pausiert:
            return
        if status is not None and getattr(status, "input_overflow", False):
            # Der Block SELBST ist gueltig — der Ueberlauf meldet nur, dass davor
            # etwas verloren ging. Ihn wegzuwerfen (so war es) machte den Verlust
            # groesser statt kleiner.
            self._ueberlauf += 1
            if self._ueberlauf in (1, 10, 100, 1000):
                log.warning("Freihand: Audio-Ueberlauf (%d.) — Eingang haengt.",
                            self._ueberlauf)
        try:
            # `.copy()` ist PFLICHT, nicht Vorsicht: sounddevice reicht immer
            # denselben Puffer herein und ueberschreibt ihn beim naechsten
            # Callback. `np.asarray` kopiert nicht, wenn Typ und Form passen —
            # die gesammelten Bloecke zeigten also alle auf denselben Speicher,
            # und die fertige „Aufnahme" war n-mal der LETZTE Block.
            #
            # Weil die Aufnahme bei Stille endet, war dieser letzte Block still:
            # Das Diktat kam leer an und wurde als „ohne Sprache" verworfen. Und
            # wo doch etwas ankam, ergab derselbe Block aneinandergereiht ein
            # periodisches Signal — daher die „T-T-T-T-…" und „G-G-G-G-…" im
            # Textfeld. `audio.Recorder` macht die Kopie seit jeher.
            block = np.array(indata, dtype=np.float32).reshape(-1)
            # Pegel fuer die Wellenlinie in der Pille. Nur waehrend der Aufnahme —
            # beim blossen Lauschen soll die Pille nicht zappeln, das waere die
            # falsche Aussage („es wird aufgenommen").
            if self.lauscher.zustand is Zustand.AUFNAHME and len(block):
                self.level = float(np.sqrt(np.mean(np.square(block))))
            else:
                self.level = 0.0
            try:
                self._warteschlange.put_nowait((block, time.monotonic()))
            except queue.Full:
                # 15 s Rueckstand: Das Pruefmodell ist dauerhaft langsamer als
                # Echtzeit. Lautlos weiterzusammeln waere schlimmer — der
                # Speicher waechst und das Diktat kommt trotzdem zerhackt an.
                self._ueberlauf += 1
                if self._ueberlauf in (1, 10, 100, 1000):
                    log.warning(
                        "Freihand: Pruefung haengt %.0f s zurueck — Block "
                        "verworfen (%d.). Kleineres Modell waehlen.",
                        self.WARTESCHLANGE_MAX * self.BLOCK_S, self._ueberlauf)
        except Exception:
            log.exception("Freihand: Audio-Block nicht uebernehmbar.")
