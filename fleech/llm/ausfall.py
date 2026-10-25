"""Warum ist ein KI-Aufruf gescheitert? Grund fuer Verlauf und Oberflaeche.

Aus `pipeline.py` herausgeloest: Die Einordnung kennt nur Modell und Ausnahme,
nichts vom Diktat.
"""

from __future__ import annotations

import urllib.error

from .. import gruende
from .frist import FristAbgelaufen, Uebersprungen
from .providers import OLLAMA, ist_lokales_ollama


def lokaler_endpunkt_nicht_erreichbar(llm, exc: Exception) -> bool:
    """Ist der Aufruf gescheitert, WEIL der lokale Ollama-Dienst nicht laeuft?

    Befund E-13: Wer die Einfuehrung ueberspringt, hat keinen Ollama-Dienst. Jedes
    Diktat kommt dann als Roh-Transkript an, und der einzige Klartext dazu stand in
    der Logdatei. Damit die Oberflaeche das sagen kann, muessen die zwei Faelle
    getrennt werden: Server antwortet schlecht (HTTP-Fehler, Timeout beim
    Rechnen) — oder es ist gar keiner da.
    """
    if not ist_lokales_ollama(getattr(llm, "cfg", None)):
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return False                     # der Dienst laeuft, er mag nur die Anfrage nicht
    grund = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(grund, TimeoutError):
        # Er laeuft, rechnet aber zu lange. Stand frueher mit in der Offline-Liste
        # (TimeoutError ist eine Unterklasse von OSError) und meldete dann „Lokale
        # KI laeuft nicht", waehrend das Warmhalten Sekunden davor erfolgreich war
        # (Log vom 25.09., 03:52 und 11:38). Ein nicht laufender Dienst lehnt die
        # Verbindung sofort ab, er laeuft nicht in eine Zeitueberschreitung.
        return False
    return isinstance(grund, (ConnectionError, OSError))


def ausfall(llm, exc: Exception) -> tuple[str, str]:
    """(Grund, Fehlerart) eines gescheiterten Aufrufs.

    Fehlerart: "" | "key" | "quota" | "llm_offline" — die Oberflaeche zeigt dazu
    einen eigenen Hinweis. Bei einem Cloud-Anbieter zaehlt der HTTP-Status:
    401/403 = Schluessel, 429 = Kontingent.
    """
    if isinstance(exc, FristAbgelaufen):
        return gruende.KI_FRIST, ""
    if isinstance(exc, Uebersprungen):
        return gruende.UEBERSPRUNGEN, ""
    code = getattr(exc, "code", None)
    art = ""
    if (getattr(getattr(llm, "cfg", None), "provider", OLLAMA) or OLLAMA) == OLLAMA:
        # 5xx: Ollama lief und ist beim Laden/Rechnen gescheitert — kein Ausfall
        # des Dienstes, sondern etwa Grafikspeicher voll.
        abbruch = isinstance(code, int) and code >= 500
        grund = gruende.OLLAMA_FEHLER if abbruch else gruende.OLLAMA
    elif code in (401, 403):
        grund, art = gruende.KI_SCHLUESSEL, "key"
    elif code == 429:
        grund, art = gruende.KI_KONTINGENT, "quota"
    else:
        grund = gruende.KI_DIENST
    if lokaler_endpunkt_nicht_erreichbar(llm, exc):
        art = "llm_offline"
    return grund, art
