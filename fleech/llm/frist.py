"""Zeitgrenze fuer die KI-Bereinigung — und was passiert, wenn sie reisst.

Anlass (Nutzer, 2026-10-19): Laufen nebenher viele Programme, wartet ein Diktat
mitunter ewig auf die lokale KI. Das Protokoll bestaetigt es: An 618 Bereinigungen
lag der Median bei 1,1 s und das 95. Perzentil je Laengenklasse unter 6,4 s — aber
einzelne Diktate brauchten 11, 18, 32 s, zwei liefen erst nach 60 s in die
Zeitueberschreitung (eines davon kam 86 s nach Aufnahmeende an). Immer dann, wenn
Grafikkarte oder Speicher von anderen Programmen belegt waren.

Drei Antworten, alle hier:

1. **Zeitgrenze je Diktat** statt 60 s je Aufruf. Sie waechst mit der Laenge, weil
   lange Diktate legitim laenger brauchen (gemessen, Summe aller Bloecke eines
   Diktats: unter 100 Woerter p95 1,9 s; 200–399 p95 6,4 s; ab 400 Median 7,6 s),
   und bekommt einen Zuschlag, wenn das Modell erst geladen werden muss.
2. **Ueberspringen**: Der Haken der Pille fuegt waehrend der Verarbeitung sofort
   den erkannten Text ein, ohne auf die KI zu warten.
3. **Ausweichen** (nur, wenn eingeschaltet): Reisst die Zeitgrenze oder faellt die
   lokale KI aus, bereinigt der gewaehlte Cloud-Anbieter dieses eine Diktat. Ohne
   diese Wahl verlaesst kein Text den Rechner — dann kommt wie bisher der Rohtext.

Abbrechen ist billig: Ollama stoppt die Rechnung, sobald die Verbindung zugeht
(live gemessen: die naechste Anfrage kam 0,08 s nach dem Abbruch durch). Deshalb
bekommt der Aufruf die Restzeit als Socket-Timeout mit, statt nur im Hintergrund
weiterzulaufen und die naechste Anfrage zu blockieren.
"""

from __future__ import annotations

import logging
import threading
import time

from .mitschnitt import Mitschnitt

log = logging.getLogger(__name__)

GRUND_S = 6.0          # deutlich ueber dem p95 kurzer Diktate (1,9 s)
PRO_WORT_S = 0.025     # 400 Woerter → 16 s (gemessen: Median 7,6 s, Maximum 13,9 s)
LADEN_S = 20.0         # Modell war entladen (Leerlauf/Spiel): Laden kostet 8–13 s
HOECHSTENS_S = 60.0    # nie laenger als der bisherige Timeout je Aufruf
AUSWEICH_S = 20.0      # eigene Grenze fuer den Cloud-Aufruf
_TAKT_S = 0.05


class Uebersprungen(Exception):
    """Der Nutzer will den Text sofort — ohne auf die KI zu warten."""


class FristAbgelaufen(TimeoutError):
    """Die KI kam nicht innerhalb der Zeitgrenze des Diktats."""


def frist_s(woerter: int, laden: bool = False) -> float:
    """Zeitgrenze fuer die gesamte Bereinigung eines Diktats (alle Bloecke)."""
    s = GRUND_S + PRO_WORT_S * max(0, int(woerter)) + (LADEN_S if laden else 0.0)
    return min(s, HOECHSTENS_S + (LADEN_S if laden else 0.0))


def ausweich_endpunkt(ki):
    """Endpunkt der Cloud-Ausweiche aus der KI-Wahl, oder None.

    Nur, wenn lokal bereinigt wird (bei einem Cloud-Hauptanbieter gibt es nichts
    auszuweichen) und der gewaehlte Ausweich-Anbieter einen Schluessel braucht —
    `ki` ist das `KiSettings`-Dataclass, hier nur ueber seine Felder gelesen."""
    from ..config import LLMEndpointConfig
    from .providers import OLLAMA, anbieter

    if anbieter(getattr(ki, "anbieter", OLLAMA)).id != OLLAMA:
        return None
    wahl = str(getattr(ki, "ausweichen", "") or "").strip().lower()
    eintrag = anbieter(wahl)
    if not wahl or eintrag.id != wahl or not eintrag.braucht_schluessel:
        return None
    modell = str(getattr(ki, "ausweichen_modell", "") or "").strip() or eintrag.modell
    return LLMEndpointConfig(provider=eintrag.id, base_url=eintrag.base_url,
                             model=modell, timeout=AUSWEICH_S, num_ctx=0)


def ausweich_modell(eintrag, modelle: list) -> str:
    """Das schnellste aktuelle Modell aus der Liste des Anbieters.

    Anders als beim Hauptmodell zaehlt hier Tempo vor allem: Die Ausweiche springt
    ein, wenn schon gewartet wurde. Rueckwaerts sortiert, damit bei gleichem
    Namensbestandteil die neuere Generation gewinnt („gemini-flash-lite-latest"
    vor „gemini-2.0-flash-lite"); Vorschau- und Experimentiermodelle nur, wenn es
    nichts anderes gibt."""
    stabil = [m for m in modelle if not any(x in m.lower() for x in ("preview", "exp"))]
    for teil in eintrag.bevorzugt:
        for name in sorted(stabil or modelle, reverse=True):
            if teil in name.lower():
                return name
    return eintrag.modell if eintrag.modell in modelle or not modelle else modelle[0]


class KiFrist:
    """Zeitgrenze, Ueberspringen und Ausweichen fuer EIN Diktat nach dem anderen.

    Die App ruft `neues_diktat()` vor jeder Verarbeitung, die Pipeline `starte()`,
    sobald der Rohtext steht, und jeden KI-Aufruf ueber `frage()`. Ohne `starte()`
    (Nachbearbeitung aus dem Verlauf) gilt keine Zeitgrenze — dort wartet niemand
    auf einen Cursor."""

    def __init__(self):
        self.ausweich_llm = None     # ChatClient des Cloud-Anbieters oder None
        self.ausweich_name = ""      # „Google Gemini" — fuer Protokoll und Verlauf
        self.laden = False           # Modell war entladen → Zuschlag
        self.ausgewichen = False     # dieses Diktat lief (teils) ueber die Cloud
        self._ende = None
        self._skip = threading.Event()
        # Was hin- und herging, fuer den Verlaufseintrag (`mitschnitt.py`).
        self.mitschnitt = Mitschnitt()

    def neues_diktat(self, laden: bool = False) -> None:
        self._skip.clear()
        self.laden = bool(laden)
        self._ende = None
        self.ausgewichen = False
        self.mitschnitt.neu()

    def starte(self, woerter: int) -> None:
        self._ende = time.monotonic() + frist_s(woerter, self.laden)
        self.mitschnitt.neu()      # auch ohne `neues_diktat()` (direkter process-Aufruf)

    def zuschlag(self, woerter: int) -> None:
        """Mehr Zeit fuer einen weiteren Aufruf desselben Diktats (Uebersetzung).

        Nur, solange die Grenze nicht gerissen ist: War die KI fuer die
        Bereinigung zu langsam, ist sie es fuer die Uebersetzung auch."""
        rest = self.rest()
        if rest is not None and rest > 0:
            self._ende += frist_s(woerter)

    def ueberspringen(self) -> None:
        self._skip.set()

    @property
    def uebersprungen(self) -> bool:
        return self._skip.is_set()

    def rest(self) -> float | None:
        """Verbleibende Sekunden; None = keine Zeitgrenze."""
        return None if self._ende is None else self._ende - time.monotonic()

    def frage(self, llm, system: str, user: str) -> str:
        """Ein KI-Aufruf unter der Zeitgrenze. Wirft `Uebersprungen`,
        `FristAbgelaufen` oder den Fehler des Aufrufs."""
        if self._skip.is_set():
            raise Uebersprungen()
        if self.ausgewichen and self.ausweich_llm is not None:
            return self._ausweichen(system, user)
        rest = self.rest()
        try:
            if rest is not None and rest <= 0:
                raise FristAbgelaufen()
            return self._warte(llm, system, user, rest)
        except Uebersprungen:
            raise
        except Exception as exc:
            if not isinstance(exc, FristAbgelaufen) and self._abgelaufen():
                exc = FristAbgelaufen()       # Socket-Timeout an der Grenze
            if self.ausweich_llm is None or llm is self.ausweich_llm:
                raise exc from None
            log.warning("Lokale KI %s — weiche fuer dieses Diktat auf %s aus.",
                        "zu langsam" if isinstance(exc, FristAbgelaufen)
                        else f"ausgefallen ({exc})", self.ausweich_name)
            self.ausgewichen = True
            try:
                return self._ausweichen(system, user)
            except Uebersprungen:
                raise
            except Exception as exc2:
                log.warning("Ausweichen auf %s fehlgeschlagen (%s).",
                            self.ausweich_name, exc2)
                raise exc from None

    def _abgelaufen(self) -> bool:
        rest = self.rest()
        return rest is not None and rest <= 0.2

    def _ausweichen(self, system: str, user: str) -> str:
        return self._warte(self.ausweich_llm, system, user, AUSWEICH_S)

    def _warte(self, llm, system: str, user: str, sekunden: float | None) -> str:
        """Aufruf im Hintergrund, Warten mit Blick auf Knopf und Uhr.

        Ohne Zeitgrenze und ohne Knopf waere das ein gewoehnlicher Aufruf — der
        Thread kostet nichts Spuerbares gegen eine KI-Antwort."""
        from .client import ChatClient

        def aufruf():
            if isinstance(llm, ChatClient):
                return llm.complete(system, user, timeout=sekunden)
            return llm.complete(system, user)

        ergebnis: dict = {}
        fertig = threading.Event()

        def arbeite():
            try:
                ergebnis["text"] = aufruf()
            except BaseException as exc:      # an den wartenden Thread weiterreichen
                ergebnis["fehler"] = exc
            finally:
                fertig.set()

        t0 = time.perf_counter()
        threading.Thread(target=arbeite, daemon=True, name="fleech-ki-aufruf").start()
        # Etwas Luft ueber der Grenze: Der Socket-Timeout soll zuerst zuschlagen —
        # dann ist die Verbindung zu und Ollama hoert auf zu rechnen.
        ende = None if sekunden is None else time.monotonic() + max(0.0, sekunden) + 0.5
        try:
            while not fertig.wait(_TAKT_S):
                if self._skip.is_set():
                    raise Uebersprungen()
                if ende is not None and time.monotonic() >= ende:
                    raise FristAbgelaufen()
            if "fehler" in ergebnis:
                raise ergebnis["fehler"]
        except BaseException as exc:
            self.mitschnitt.merke(llm, system, user, fehler=exc, t0=t0)
            raise
        self.mitschnitt.merke(llm, system, user, antwort=ergebnis["text"], t0=t0)
        return ergebnis["text"]
