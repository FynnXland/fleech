"""Wörterbuch-Einträge einsprechen und prüfen, ob die Erkennung sie trifft.

## Warum das nötig ist

Man trägt „PySide6" ins Wörterbuch ein und weiß danach nicht, ob es etwas
gebracht hat. Fleech gibt den Begriff der Erkennung als `initial_prompt` mit
(Priming) — aber ob das bei DER EIGENEN Aussprache reicht, zeigt erst der
Versuch. Bis dahin merkt man es erst mitten im Diktat, wenn wieder „Pi Seite 6"
im Text steht.

## Warum keine Computerstimme

Der naheliegende Weg wäre, das Wort per TTS zu erzeugen und automatisch zu
prüfen — ohne dass jemand etwas tun muss. Das wurde bei der Freihand-Arbeit
gemessen und taugt nicht: Dieselbe Kette verstand das TTS-„Kimono" sauber,
während die echte Stimme über ein echtes Mikrofon als „Kimu", „Gimo" oder
„Kimo no" ankam. Ein Test, der immer besteht, ist kein Test.

## Warum kein Nachtrainieren

Ein Whisper-Modell auf einzelne Wörter nachzutrainieren braucht viele hundert
Aufnahmen, Stunden GPU-Zeit und liefert ein Modell, das nach dem nächsten Update
neu gebaut werden müsste. Priming erreicht dasselbe Ziel zur Laufzeit, kostet
nichts und gilt sofort.

Dieses Modul kennt weder Qt noch ein Audiogerät: Es bekommt fertiges Audio und
eine Erkennungsfunktion hineingereicht.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .freihand import enthaelt_wort, normalisiere

log = logging.getLogger(__name__)

# Mindestlänge einer brauchbaren Probe. Darunter hat der Sprecher das Wort
# offensichtlich nicht gesagt, und Whisper halluziniert aus kurzen Fetzen.
MIN_PROBE_S = 0.4


class Ergebnis:
    TREFFER = "treffer"          # Begriff kam exakt an
    AEHNLICH = "aehnlich"        # nur unscharf getroffen — Priming wirkt noch nicht sicher
    DANEBEN = "daneben"          # etwas anderes verstanden
    NICHTS = "nichts"            # gar nichts erkannt


@dataclass
class Probe:
    """Was bei einem Einsprech-Versuch herauskam."""

    ergebnis: str
    gehoert: str                 # was die Erkennung geliefert hat
    begriff: str
    # Wofür geprüft wurde. Beim Startwort bedeutet dasselbe Ergebnis etwas
    # anderes: „nur ähnlich" heisst dort GENÜGT (Freihand vergleicht unscharf,
    # weil das Prüfmodell Wörter zerreisst), im Wörterbuch heisst es „noch üben".
    zweck: str = "woerterbuch"

    def als_text(self) -> str:
        """Eine Zeile für die Oberfläche — sagt, was zu tun ist, nicht nur was war."""
        if self.zweck == "startwort":
            return self._startwort_text()
        if self.ergebnis == Ergebnis.TREFFER:
            return f"Erkannt: „{self.gehoert}“ — der Eintrag greift."
        if self.ergebnis == Ergebnis.AEHNLICH:
            return (f"Fast: „{self.gehoert}“ statt „{self.begriff}“. Das Wörterbuch "
                    f"korrigiert das meist; bei Wiederholung deutlicher sprechen.")
        if self.ergebnis == Ergebnis.NICHTS:
            return "Nichts verstanden — war das Mikrofon an?"
        if self.vorschlag:
            return (f"Verstanden wurde „{self.gehoert}“ — als Schreibvariante "
                    f"eintragen: {self.vorschlag}")
        return (f"Verstanden wurde „{self.gehoert}“ — das trifft den Eintrag nicht. "
                f"Nochmal versuchen oder deutlicher sprechen.")

    def _startwort_text(self) -> str:
        """Für Freihand zählt eine andere Frage: Würde es auslösen?"""
        if self.ergebnis == Ergebnis.TREFFER:
            return (f"Erkannt: „{self.gehoert}“ — Freihand würde starten.")
        if self.ergebnis == Ergebnis.AEHNLICH:
            return (f"Verstanden wurde „{self.gehoert}“ — nah genug, Freihand "
                    f"würde starten. Das Prüfmodell zerreisst Wörter oft, deshalb "
                    f"wird bewusst unscharf verglichen.")
        if self.ergebnis == Ergebnis.NICHTS:
            return "Nichts verstanden — war das Mikrofon an?"
        return (f"Verstanden wurde „{self.gehoert}“ — damit würde Freihand NICHT "
                f"starten. Nochmal versuchen; bleibt es dabei, ist „{self.begriff}“ "
                f"für deine Aussprache kein gutes Startwort.")

    @property
    def vorschlag(self) -> str:
        """Zeile fürs Wörterbuch, wenn etwas anderes verstanden wurde ("" = keiner).

        Genau dafür ist der Test da: Nicht „hat nicht geklappt", sondern die
        Regel, die es beim nächsten Mal richtig macht."""
        if self.zweck == "startwort":
            # Ein Startwort ersetzt man nicht per Wörterbuch-Regel — man wählt ein
            # anderes. Ein „eintragen"-Knopf wäre hier schlicht falsch.
            return ""
        if self.ergebnis != Ergebnis.DANEBEN or not self.gehoert:
            return ""
        # Nur ein einzelnes Wort taugt als Ersetzungsregel — bei einem ganzen Satz
        # wüsste man nicht, welcher Teil gemeint ist.
        woerter = self.gehoert.split()
        if len(woerter) != 1:
            return ""
        return f"{woerter[0].strip('.,;:!?')} => {self.begriff}"


def bewerte(gehoert: str, begriff: str, zweck: str = "woerterbuch") -> Probe:
    """Erkannten Text gegen den erwarteten Begriff halten.

    Die unscharfe Stufe ist kein Detail: Sie unterscheidet „das Priming wirkt"
    von „es klang nur ähnlich". Beides sähe sonst gleich aus, obwohl das eine
    heißt „fertig" und das andere „üben oder Variante eintragen".
    """
    gehoert = (gehoert or "").strip()
    begriff = (begriff or "").strip()
    if not begriff:
        return Probe(Ergebnis.NICHTS, gehoert, begriff, zweck)
    if not gehoert:
        return Probe(Ergebnis.NICHTS, "", begriff, zweck)
    # Exakt: der Begriff steht als eigenes Wort im Erkannten.
    if enthaelt_wort(gehoert, begriff, unscharf=False):
        return Probe(Ergebnis.TREFFER, gehoert, begriff, zweck)
    # Mehrwortige Begriffe („MCP Server") stehen im Text mit Trennern dazwischen.
    if len(begriff.split()) > 1 and normalisiere(begriff) in normalisiere(gehoert):
        return Probe(Ergebnis.TREFFER, gehoert, begriff, zweck)
    if enthaelt_wort(gehoert, begriff):
        return Probe(Ergebnis.AEHNLICH, gehoert, begriff, zweck)
    return Probe(Ergebnis.DANEBEN, gehoert, begriff, zweck)


def pruefe_audio(audio, begriff: str, erkenne, samplerate: int = 16000,
                 zweck: str = "woerterbuch") -> Probe:
    """Aufnahme → Erkennung → Bewertung.

    `erkenne` ist eine Funktion audio → Text; sie kommt von aussen, damit dieses
    Modul kein Modell laden muss und der Ablauf ohne Mikrofon prüfbar bleibt.
    Genau dort liegt der Unterschied zwischen den beiden Zwecken: Fürs Wörterbuch
    wird mit dem Wörterbuch-Priming erkannt, fürs Startwort mit demselben Weg,
    den Freihand im Betrieb geht.
    """
    if audio is None or not len(audio):
        return Probe(Ergebnis.NICHTS, "", begriff, zweck)
    if len(audio) / float(samplerate or 16000) < MIN_PROBE_S:
        return Probe(Ergebnis.NICHTS, "", begriff, zweck)
    try:
        gehoert = erkenne(audio) or ""
    except Exception:
        log.exception("Wortprobe: Erkennung fehlgeschlagen.")
        return Probe(Ergebnis.NICHTS, "", begriff, zweck)
    probe = bewerte(gehoert, begriff, zweck)
    log.info("Wortprobe %r (%s): %s (gehört: %r)", begriff, zweck,
             probe.ergebnis, gehoert)
    return probe
