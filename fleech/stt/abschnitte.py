"""Erkennen, während man spricht: Abschnitte an Sprechpausen schon in der Aufnahme.

Bisher begann die Erkennung erst nach dem Loslassen der Taste — bei einem
Diktat von einer Minute wartete man danach 1,5 s nur auf Whisper, unter
Grafikkarten-Last bis zu 7,5 s. Dabei sind die ersten 55 Sekunden zu dem
Zeitpunkt längst gesprochen.

Dieser Erkenner schneidet die laufende Aufnahme an Sprechpausen (≥ 400 ms) und
lässt jeden fertigen Abschnitt im Hintergrund vom GROSSEN Modell erkennen — mit
demselben Priming wie das Diktat und den letzten 40 Wörtern davor als Kontext.
Nach dem Loslassen bleibt nur der letzte Abschnitt.

Gemessen (TTS-Sätze, 20–120 s, RTX 4070): Wartezeit nach dem Sprechende
0,26–0,39 s statt 0,6–3,5 s; Fehler gleich oder weniger als am Stück (120 s:
0 statt 1). Abschnitte unter 6 s lohnen nicht (Whisper rechnet ohnehin ein
30-s-Fenster), über 28 s passen sie nicht mehr in eins.

Was diesen Weg NICHT gefährden darf: das Ergebnis. Jeder Zweifel — andere
Sprache, Grafikkarte überlastet, Fehler im Hintergrund — endet darin, dass der
Rest wie bisher am Stück erkannt wird. Schlimmstenfalls ist es so schnell wie
vorher, nie schlechter.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from ..protokolltext import inhalt


log = logging.getLogger(__name__)

PAUSE_MS = 400          # so lange Stille = Schnittstelle
TAKT_S = 0.5            # wie oft nach einer Pause gesehen wird
MIN_S = 6.0             # kürzere Abschnitte lohnen nicht
MAX_S = 28.0            # spätestens hier schneiden (Whisper-Fenster 30 s)
KONTEXT_WOERTER = 40    # so viel vom bisher Erkannten primt den nächsten Abschnitt
# Braucht ein Abschnitt länger als das, ist die Grafikkarte belegt (Spiel,
# Stimmwandler, Training). Normal: 0,3–0,65 s für 6–21 s Audio. Dann für den Rest
# der Aufnahme aufhören — die Abschnitte würden sich sonst stauen und am Ende
# auf das Diktat warten lassen, statt es zu beschleunigen.
UEBERLAST_GRUND_S = 1.0
UEBERLAST_PRO_S = 0.15
MIN_REST_S = 0.2        # kürzerer Rest = nichts mehr gesagt


def finde_schnitt(sprache: list, laenge: int, sr: int, pause_ms: int = PAUSE_MS,
                  min_s: float = MIN_S, max_s: float = MAX_S) -> int | None:
    """Wo darf das bisher Aufgenommene (ab dem letzten Schnitt) enden?

    `sprache`: Sprachstücke der VAD, relativ zum letzten Schnitt
    ([{"start", "end"}] in Samples). `laenge`: so viel Audio liegt bisher vor.
    Geschnitten wird in der Mitte der LETZTEN abgeschlossenen Pause — einer, hinter
    der wieder gesprochen wurde, oder der laufenden am Ende, wenn sie schon lang
    genug ist. Nie mitten im Wort, außer der Abschnitt passt sonst nicht mehr ins
    Whisper-Fenster (Notschnitt).
    """
    if laenge / sr < min_s:
        return None
    pause = int(pause_ms / 1000 * sr)
    schnitt = None
    for a, b in zip(sprache, sprache[1:]):
        if b["start"] - a["end"] >= pause:
            schnitt = (a["end"] + b["start"]) // 2
    if sprache and laenge - sprache[-1]["end"] >= pause:
        schnitt = sprache[-1]["end"] + pause // 2
    if schnitt is None and laenge / sr >= max_s:
        schnitt = laenge
    if schnitt is not None and schnitt / sr >= min_s:
        return schnitt
    return None


def kontext_prompt(hinweis: str | None, bisher: str) -> str | None:
    """Priming für den nächsten Abschnitt: das Diktat-Priming plus das Ende davor.

    Ohne den Kontext beginnt jeder Abschnitt wie ein neues Diktat — Whisper
    setzt dann gern einen Großbuchstaben oder lässt ein Komma weg, wo der Satz
    eigentlich weiterläuft."""
    ende = " ".join(bisher.split()[-KONTEXT_WOERTER:])
    teile = [t for t in (hinweis, ende) if t]
    return " ".join(teile) or None


def ist_ueberlastet(dauer_s: float, audio_s: float) -> bool:
    return dauer_s > UEBERLAST_GRUND_S + UEBERLAST_PRO_S * audio_s


@dataclass
class Vorerkennung:
    """Was schon während der Aufnahme erkannt wurde."""
    bis: int                     # Samples (Aufnahme-Rate) — ab hier fehlt noch alles
    text: str
    sprache: str                 # mit dieser Sprache erkannt
    hinweis: str | None          # mit diesem Priming
    abschnitte: int = 0
    verworfen: list = field(default_factory=list)   # tonlose Schwänze je Abschnitt


class AbschnittsErkenner:
    """Läuft je Aufnahme EINMAL: start() beim Drücken, ergebnis() im Worker danach.

    Alles injizierbar (Audio, Erkennung, VAD) — testbar ohne Mikrofon und Modell.
    `erkenne(audio, prompt, sprache) -> (text, verworfen)` erkennt ein Stück;
    `vad(audio) -> [{"start", "end"}]` findet die Sprachstücke darin.
    """

    def __init__(self, snapshot, erkenne, vad, samplerate: int = 16000,
                 takt_s: float = TAKT_S):
        self._snapshot = snapshot
        self._erkenne = erkenne
        self._vad = vad
        self._sr = samplerate
        self._takt = takt_s
        self._stopp = threading.Event()
        self._thread: threading.Thread | None = None
        self._ergebnis: Vorerkennung | None = None

    def start(self, hinweis: str | None, sprache: str) -> None:
        self._ergebnis = Vorerkennung(0, "", sprache, hinweis)
        self._thread = threading.Thread(target=self._lauf, name="fleech-abschnitte",
                                        daemon=True)
        self._thread.start()

    def beende(self) -> None:
        """Nicht blockierend — läuft beim Loslassen im Tastatur-Hook."""
        self._stopp.set()

    def ergebnis(self, timeout: float = 30.0) -> Vorerkennung | None:
        """Auf den Abschnitt warten, der vielleicht gerade noch erkannt wird.

        Im Verarbeitungs-Worker, nie im Hook. Das Warten lohnt sich: Ein Abschnitt
        in Arbeit ist fast fertig, ihn am Stück neu zu erkennen dauerte länger."""
        self._stopp.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("Abschnitts-Erkennung nach %.0f s nicht fertig — "
                            "das Diktat wird am Stück erkannt.", timeout)
                return None
        e = self._ergebnis
        return e if e is not None and e.abschnitte else None

    def _lauf(self) -> None:
        e = self._ergebnis
        try:
            while not self._stopp.wait(self._takt):
                audio = self._snapshot()
                if audio is None or audio.size - e.bis < MIN_S * self._sr:
                    continue
                rest = audio[e.bis:]
                schnitt = finde_schnitt(self._vad(rest), rest.size, self._sr)
                if schnitt is None:
                    continue
                stueck = rest[:schnitt]
                t0 = time.perf_counter()
                text, verworfen = self._erkenne(
                    stueck, kontext_prompt(e.hinweis, e.text), e.sprache)
                dauer = time.perf_counter() - t0
                # Erst JETZT übernehmen: Bricht die Erkennung ab, steht `bis`
                # noch davor, und der Rest wird am Ende vollständig erkannt.
                e.text = " ".join(t for t in (e.text, text) if t)
                e.bis += schnitt
                e.abschnitte += 1
                if verworfen:
                    e.verworfen.append(verworfen)
                log.info("Abschnitt %d (%.1f–%.1f s, %.2f s): %s", e.abschnitte,
                         (e.bis - schnitt) / self._sr, e.bis / self._sr, dauer,
                         inhalt(text, 80))
                if ist_ueberlastet(dauer, schnitt / self._sr):
                    log.info("Abschnitts-Erkennung pausiert: %.2f s für %.1f s Audio "
                             "— Grafikkarte belegt, der Rest kommt am Stück.",
                             dauer, schnitt / self._sr)
                    return
        except Exception:
            log.exception("Abschnitts-Erkennung fehlgeschlagen — der Rest kommt "
                          "am Stück.")


def silero_vad(audio: np.ndarray) -> list:
    """Sprachstuecke im Audio — dieselbe VAD, die Whisper beim Diktat nutzt."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    return get_speech_timestamps(
        audio, VadOptions(min_silence_duration_ms=PAUSE_MS, speech_pad_ms=0))


def erkenne_mit_vorab(stt, audio: np.ndarray, samplerate: int, hinweis: str | None,
                      vorab: Vorerkennung | None) -> str:
    """Das ganze Diktat erkennen — mit dem, was schon erkannt ist, nur noch den Rest.

    Die Sprache MUSS passen: Das Profil kann sie je App umstellen, und erst die
    Verarbeitung weiß sicher, welches gilt. Passt sie nicht, zählt die Vorarbeit
    nicht. Verworfene Schwänze der Abschnitte landen dort, wo die Pipeline sie
    abholt (`letzter_schwanz_ohne_ton`) — Gelöschtes verschwindet nie still.
    """
    sprache = getattr(getattr(stt, "cfg", None), "language", "")
    if vorab is None or vorab.sprache != sprache or vorab.bis > audio.size:
        if vorab is not None:
            log.info("Abschnitte verworfen (Sprache %r statt %r) — am Stück.",
                     vorab.sprache, sprache)
        return stt.transcribe(audio, samplerate, initial_prompt=hinweis)
    rest = audio[vorab.bis:]
    text = eigenes = ""
    if rest.size >= MIN_REST_S * samplerate:
        text = stt.transcribe(rest, samplerate,
                              initial_prompt=kontext_prompt(hinweis, vorab.text))
        eigenes = getattr(stt, "letzter_schwanz_ohne_ton", "") or ""
    # Immer neu setzen: Ohne Rest-Erkennung stuende dort noch der Schwanz des
    # letzten Abschnitts — und der ist in `vorab.verworfen` schon enthalten.
    stt.letzter_schwanz_ohne_ton = " ".join(
        t for t in (*vorab.verworfen, eigenes) if t)
    log.info("Aus %d Abschnitt(en) + Rest (%.1f s) zusammengesetzt.",
             vorab.abschnitte, rest.size / samplerate)
    return " ".join(t for t in (vorab.text, text) if t).strip()
