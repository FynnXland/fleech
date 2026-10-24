"""Was zwischen Fleech und der KI hin- und herging — je Diktat, Aufruf fuer Aufruf.

Anlass (Nutzer, 2026-10-21): Der Verlauf hob bis 6.4.0 nur das Whisper-Transkript
und den eingefuegten Text auf. Was die KI tatsaechlich bekam (System-Prompt samt
Profil-Vorgaben, eingerahmtes Transkript, bei langen Diktaten je Block) und was sie
zurueckgab, war danach verloren. Am schmerzhaftesten bei einem Rueckfall: Hat ein
Guard die Antwort verworfen, stand sie nirgends mehr, und seit 6.3.0 auch nicht
mehr im Protokoll.

Der Mitschnitt haelt das fest, bis die App den Verlaufseintrag schreibt
(`history.HistoryStore.add`, Ablage in `fleech/kiverlauf.py`). Er schreibt selbst
nichts auf die Platte und nichts ins Protokoll, er lebt nur so lange wie ein Diktat.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class KiAufruf:
    anbieter: str
    modell: str
    system: str
    eingabe: str
    antwort: str = ""
    fehler: str = ""          # leer = Antwort kam; sonst Fehlerart und -text
    ms: int = 0
    abgeschnitten: bool = False


# Die beiden Abbrueche aus `frist.py` tragen keinen Text — lesbar statt Klassenname.
_FEHLERNAMEN = {"Uebersprungen": "Übersprungen (Haken)",
                "FristAbgelaufen": "Zeitgrenze überschritten"}


def _endpunkt(llm) -> tuple[str, str]:
    cfg = getattr(llm, "cfg", None)
    return (str(getattr(cfg, "provider", "") or ""), str(getattr(cfg, "model", "") or ""))


class Mitschnitt:
    """Die KI-Aufrufe des laufenden Diktats, in der Reihenfolge, in der sie liefen."""

    def __init__(self):
        self.aufrufe: list[KiAufruf] = []

    def neu(self) -> None:
        self.aufrufe = []

    def merke(self, llm, system: str, user: str, antwort: str = "",
              fehler: BaseException | None = None, t0: float | None = None) -> None:
        anbieter, modell = _endpunkt(llm)
        text = ""
        if fehler is not None:
            text = _FEHLERNAMEN.get(type(fehler).__name__, type(fehler).__name__)
            if str(fehler):
                text = f"{text}: {fehler}"
        self.aufrufe.append(KiAufruf(
            anbieter=anbieter, modell=modell, system=system or "", eingabe=user or "",
            antwort=antwort or "", fehler=text,
            ms=int((time.perf_counter() - t0) * 1000) if t0 is not None else 0,
            abgeschnitten=fehler is None and bool(getattr(llm, "last_truncated", False)),
        ))

    def frage(self, llm, system: str, user: str) -> str:
        """Ein Aufruf ohne Zeitgrenze (Befehlsweg) — mitgeschnitten wie jeder andere."""
        t0 = time.perf_counter()
        try:
            antwort = llm.complete(system, user)
        except BaseException as exc:
            self.merke(llm, system, user, fehler=exc, t0=t0)
            raise
        self.merke(llm, system, user, antwort=antwort, t0=t0)
        return antwort


def aufrufe_von(pipeline) -> list[KiAufruf]:
    """Die Aufrufe des letzten Diktats; leer bei Pipeline-Attrappen ohne Mitschnitt."""
    mitschnitt = getattr(getattr(pipeline, "frist", None), "mitschnitt", None)
    return list(getattr(mitschnitt, "aufrufe", None) or [])
