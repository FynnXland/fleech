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
import re
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

log = logging.getLogger(__name__)

SAMPLERATE = 16000

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


def enthaelt_wort(text: str, wort: str) -> bool:
    """Kommt `wort` als eigenstaendiges Wort in `text` vor?

    Wortgrenzen sind Pflicht: Ein Startwort „Kimono" darf nicht in „Kimonos"
    oder mitten in einem laengeren Wort anschlagen.
    """
    wort = normalisiere(wort).strip()
    if not wort:
        return False
    return re.search(rf"(?<!\w){re.escape(wort)}(?!\w)", normalisiere(text)) is not None


@dataclass
class Einstellungen:
    """Alles, was der Nutzer am Freihand-Modus einstellen kann."""

    aktiv: bool = False
    startwort: str = "Kimono"
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
                 samplerate: int = SAMPLERATE):
        self.einstellungen = einstellungen.clamp()
        self._vad = vad                  # callable(np.ndarray) -> bool (Sprache?)
        self._erkenner = erkenner        # callable(np.ndarray) -> str (Text)
        self.samplerate = samplerate
        self.statistik = Statistik()

        self.zustand = Zustand.AUS
        self._ring = np.zeros(0, dtype=np.float32)   # letzte Sekunden (Lauschen)
        self._aufnahme: list = []                    # gesammelte Bloecke (Diktat)
        self._letzte_pruefung = 0.0
        self._letzte_sprache = 0.0
        self._sperre_bis = 0.0

    # -- Steuerung -------------------------------------------------------------------

    def start_lauschen(self) -> None:
        if not self.einstellungen.aktiv:
            self.zustand = Zustand.AUS
            return
        self.zustand = Zustand.LAUSCHT
        self._ring = np.zeros(0, dtype=np.float32)
        self._aufnahme = []
        log.info("Freihand: lauscht auf %r.", self.einstellungen.startwort)

    def stop_lauschen(self) -> None:
        self.zustand = Zustand.AUS
        self._ring = np.zeros(0, dtype=np.float32)
        self._aufnahme = []

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
        if enthaelt_wort(text, self.einstellungen.startwort):
            self.statistik.aktivierungen += 1
            log.info("Freihand: Startwort erkannt in %r.", text.strip()[:60])
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
        self._aufnahme.append(block)
        if self._ist_sprache(block):
            self._letzte_sprache = jetzt
            return None
        if jetzt - self._letzte_sprache < self.einstellungen.stille_s:
            return None

        # Lange genug still: Diktat zu Ende. Vorher pruefen, ob das Abbruchwort
        # gefallen ist — dann wird verworfen statt eingefuegt.
        text = self._erkenne(self.aufnahme_audio())
        if text and enthaelt_wort(text, self.einstellungen.abbruchwort):
            self.statistik.verworfen += 1
            log.info("Freihand: Abbruchwort erkannt — verworfen.")
            self._nach_diktat(jetzt)
            return Ereignis.ABBRUCH
        self._nach_diktat(jetzt)
        return Ereignis.ENDE

    def _nach_diktat(self, jetzt: float) -> None:
        """Zurueck ins Lauschen. Das Diktat holt der Aufrufer vorher ab.

        Die Sperre verhindert, dass der eigene Nachsatz sofort die naechste
        Aufnahme ausloest — das Abbruchwort wirkt bewusst NUR als Verwerfen, nicht
        als Neustart: Sonst machte ein Versprecher daraus eine Endlosschleife.
        """
        self.zustand = Zustand.LAUSCHT
        self._ring = np.zeros(0, dtype=np.float32)
        self._sperre_bis = jetzt + SPERRE_NACH_START_S

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
            return self._erkenner(audio) or ""
        except Exception:
            log.debug("Startwort-Erkennung fehlgeschlagen.", exc_info=True)
            return ""


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


def baue_erkenner(modell_groesse: str = "tiny", sprache: str = "de"):
    """Kleines Whisper-Modell fuer das Startwort. Rueckgabe: callable(audio) -> str.

    BEWUSST AUF DER CPU: Die Grafikkarte gehoert dem grossen Modell, das gleich
    das eigentliche Diktat verarbeiten soll. `beam_size=1` — es geht nur um die
    Frage, ob ein bestimmtes Wort gefallen ist, nicht um schoene Saetze.
    """
    from faster_whisper import WhisperModel

    modell = WhisperModel(modell_groesse, device="cpu", compute_type="int8")

    def erkenne(audio: np.ndarray) -> str:
        segmente, _info = modell.transcribe(
            audio, language=sprache, beam_size=1, vad_filter=False,
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
    """

    BLOCK_S = 0.2      # Groesse der Bloecke, die der Lauscher bekommt

    def __init__(self, lauscher: Lauscher, on_ereignis, geraet=None,
                 samplerate: int = SAMPLERATE):
        self.lauscher = lauscher
        self._on_ereignis = on_ereignis      # callable(Ereignis, audio|None)
        self._geraet = geraet
        self.samplerate = samplerate
        self._stream = None
        self._pausiert = False

    @property
    def laeuft(self) -> bool:
        return self._stream is not None

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd

            self._stream = sd.InputStream(
                samplerate=self.samplerate, channels=1, dtype="float32",
                device=self._geraet, blocksize=int(self.BLOCK_S * self.samplerate),
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            log.exception("Freihand-Strom nicht startbar — Modus bleibt aus.")
            self._stream = None
            return False
        self.lauscher.start_lauschen()
        log.info("Freihand-Strom laeuft (Startwort %r).",
                 self.lauscher.einstellungen.startwort)
        return True

    def stop(self) -> None:
        strom, self._stream = self._stream, None
        self.lauscher.stop_lauschen()
        if strom is None:
            return
        try:
            strom.stop()
            strom.close()
        except Exception:
            log.debug("Freihand-Strom liess sich nicht sauber schliessen.",
                      exc_info=True)
        log.info("Freihand-Strom beendet.")

    def pausiere(self, an: bool) -> None:
        """Waehrend einer normalen Aufnahme oder in ausgeschlossenen Apps."""
        if an != self._pausiert:
            log.debug("Freihand %s.", "pausiert" if an else "hoert wieder")
        self._pausiert = an
        if an:
            # Zustand zuruecksetzen: Ein halb gefuellter Ringpuffer aus der Zeit
            # davor waere beim Fortsetzen ein falscher Bezugspunkt.
            self.lauscher.start_lauschen()

    def _callback(self, indata, frames, time_info, status) -> None:
        """Audio-Thread! Hier NICHTS Schweres und NICHTS mit Qt.

        Die Zustandsmaschine ist reine Rechnung (VAD + gelegentlich tiny) und
        laeuft deshalb direkt hier. Das Ereignis geht sofort an den Aufrufer, der
        es in seinen eigenen Thread bringt.
        """
        if self._pausiert or status is not None and getattr(status, "input_overflow", False):
            return
        try:
            block = np.asarray(indata, dtype=np.float32).reshape(-1)
            ereignis = self.lauscher.verarbeite(block)
            if ereignis is None:
                return
            audio = (self.lauscher.aufnahme_audio()
                     if ereignis is Ereignis.ENDE else None)
            self._on_ereignis(ereignis, audio)
        except Exception:
            log.exception("Freihand-Verarbeitung fehlgeschlagen.")
