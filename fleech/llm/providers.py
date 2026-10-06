"""Welche KI bereinigt den Text? — die Anbieter als feste Liste.

Lokal (Ollama) ist und bleibt der Standard: kein Konto, kein Schluessel, kein Text
verlaesst den Rechner. Wer lieber ein Cloud-Modell nimmt, traegt einen eigenen
API-Schluessel ein. Ein Abo (ChatGPT Plus, Claude Pro, Gemini Advanced) laesst
sich dafuer NICHT verwenden — die Anbieter trennen Abo und Programmierschnittstelle
bewusst, und ein nachgebauter Abo-Login wuerde deren Nutzungsbedingungen brechen.

Drei Schnittstellen-Arten reichen fuer alle:
  ollama     — Ollamas eigene `/api/chat` (wegen `num_ctx`, siehe client.py)
  openai     — `/chat/completions` mit Bearer-Schluessel. Gemini, Groq, Mistral
               und OpenRouter bieten genau diese Form an.
  anthropic  — die eigene Messages-API (`x-api-key`, `anthropic-version`).

`aus` ist kein Anbieter, sondern der bewusste Verzicht: Fleech fuegt dann das
erkannte Transkript ein (Fuellwoerter entfernt, Woerterbuch angewandt), ohne
dass ein Modell den Text sieht — und ohne das als Fehler zu melden.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

OLLAMA = "ollama"
AUS = "aus"
EIGENER = "custom"


@dataclass(frozen=True)
class Anbieter:
    id: str
    name: str
    api: str                       # "ollama" | "openai" | "anthropic" | ""
    base_url: str = ""
    modell: str = ""               # Startwert, bis die Liste vom Anbieter da ist
    braucht_schluessel: bool = False
    lokal: bool = False
    schluessel_url: str = ""       # wo man einen Schluessel bekommt
    # Umgebungsvariable, die der Anbieter selbst dokumentiert — wer sie schon
    # gesetzt hat, muss nichts eintragen.
    umgebung: str = ""
    # Bevorzugte Namensbestandteile, wenn aus der Modellliste ein Startmodell
    # gewaehlt wird: schnell und guenstig vor gross und teuer.
    bevorzugt: tuple = field(default_factory=tuple)


ANBIETER = (
    Anbieter(OLLAMA, "Lokal (Ollama) — empfohlen", "ollama",
             "http://127.0.0.1:11434", "gemma3:4b", lokal=True),
    Anbieter("openai", "OpenAI", "openai", "https://api.openai.com/v1",
             "gpt-4o-mini", True, schluessel_url="https://platform.openai.com/api-keys",
             umgebung="OPENAI_API_KEY", bevorzugt=("nano", "mini")),
    Anbieter("anthropic", "Anthropic (Claude)", "anthropic",
             "https://api.anthropic.com/v1", "claude-haiku-4-5", True,
             schluessel_url="https://console.anthropic.com/settings/keys",
             umgebung="ANTHROPIC_API_KEY", bevorzugt=("haiku",)),
    Anbieter("gemini", "Google Gemini", "openai",
             "https://generativelanguage.googleapis.com/v1beta/openai",
             "gemini-2.5-flash", True,
             schluessel_url="https://aistudio.google.com/apikey",
             umgebung="GEMINI_API_KEY", bevorzugt=("flash-lite", "flash")),
    Anbieter("mistral", "Mistral", "openai", "https://api.mistral.ai/v1",
             "mistral-small-latest", True,
             schluessel_url="https://console.mistral.ai/api-keys",
             umgebung="MISTRAL_API_KEY", bevorzugt=("small",)),
    Anbieter("groq", "Groq", "openai", "https://api.groq.com/openai/v1",
             "llama-3.3-70b-versatile", True,
             schluessel_url="https://console.groq.com/keys",
             umgebung="GROQ_API_KEY", bevorzugt=("versatile", "instant")),
    Anbieter("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1",
             "openai/gpt-4o-mini", True,
             schluessel_url="https://openrouter.ai/keys",
             umgebung="OPENROUTER_API_KEY", bevorzugt=("mini", "flash")),
    # Jeder Server mit OpenAI-Form: LM Studio, vLLM, llama.cpp, ein Firmen-Proxy …
    Anbieter(EIGENER, "Eigener Server (OpenAI-kompatibel)", "openai", "", ""),
    Anbieter(AUS, "Ohne KI — nur Spracherkennung", ""),
)

_NACH_ID = {a.id: a for a in ANBIETER}


def anbieter(ident: str) -> Anbieter:
    """Unbekannte Kennung (Tippfehler in settings.json) → lokal, nie ein Absturz."""
    return _NACH_ID.get(str(ident or "").strip().lower(), _NACH_ID[OLLAMA])


def ki_lokal(settings) -> bool:
    """Bereinigt das eigene Ollama? Nein bei Cloud-Anbieter und bei „Ohne KI"."""
    wahl = getattr(getattr(settings, "ki", None), "anbieter", OLLAMA)
    return anbieter(wahl).id == OLLAMA


def ist_lokales_ollama(endpoint) -> bool:
    """Darf Fleech diesen Endpunkt wie sein eigenes Ollama behandeln — vorladen,
    entladen, Modelle ziehen, auf der Grafikkarte nachsehen?

    Frueher entschied das allein `localhost` in der Adresse. Ein lokaler Server
    anderer Bauart (LM Studio auf localhost:1234) haette dann Ollama-Aufrufe
    bekommen. Jetzt zaehlen Schnittstelle UND Adresse.
    """
    if (getattr(endpoint, "provider", OLLAMA) or OLLAMA) != OLLAMA:
        return False
    base = str(getattr(endpoint, "base_url", "") or "")
    return "localhost" in base or "127.0.0.1" in base


def modell_vorschlag(eintrag: Anbieter, modelle: list) -> str:
    """Aus der Liste des Anbieters ein Startmodell waehlen: das erste, das einen
    bevorzugten Namensbestandteil traegt, sonst der bisherige Startwert."""
    if eintrag.modell in modelle:
        return eintrag.modell
    for teil in eintrag.bevorzugt:
        for name in modelle:
            if teil in name.lower():
                return name
    return eintrag.modell or (modelle[0] if modelle else "")


def modelle_abrufen(eintrag: Anbieter, schluessel: str, base_url: str = "",
                    timeout: float = 10.0) -> list:
    """Die Modelle, die dieser Schluessel nutzen darf — direkt beim Anbieter.

    Damit veraltet keine fest eingetragene Liste: Neue Modelle erscheinen, sobald
    der Anbieter sie freischaltet. Wirft bei Netz- und Schluesselfehlern; der
    Aufrufer zeigt die Meldung.
    """
    base = (base_url or eintrag.base_url).rstrip("/")
    if eintrag.api == "ollama":
        from .client import ollama_installed_models

        return sorted(n for n in ollama_installed_models(base) if ":latest" not in n)
    if eintrag.api == "anthropic":
        kopf = {"x-api-key": schluessel, "anthropic-version": ANTHROPIC_VERSION}
    else:
        kopf = {"Authorization": f"Bearer {schluessel}"} if schluessel else {}
    request = urllib.request.Request(f"{base}/models", headers=kopf)
    with urllib.request.urlopen(request, timeout=timeout) as antwort:
        daten = json.loads(antwort.read())
    namen = [str(m.get("id") or "") for m in daten.get("data") or []]
    # Gemini liefert "models/gemini-…" — die Chat-Schnittstelle will den Namen ohne.
    namen = [n.removeprefix("models/") for n in namen if n]
    # Nur Text-Chatmodelle: Einbettung, Bild, Ton und Moderation helfen hier nicht.
    raus = ("embed", "whisper", "tts", "dall-e", "image", "moderation", "audio",
            "transcribe", "realtime", "search", "veo", "imagen")
    return sorted(n for n in namen if not any(r in n.lower() for r in raus))


ANTHROPIC_VERSION = "2023-06-01"


def wende_an(wahl, config) -> None:
    """Die Wahl aus den Einstellungen auf die drei Endpunkte legen.

    Lokal bleibt `config.yaml` massgeblich (Adresse, `num_ctx`, Reasoning) — nur
    ein ausdruecklich gewaehltes Modell wird uebernommen. „Ohne KI" laesst die
    Endpunkte unberuehrt; die Pipeline fragt dann gar kein Modell
    (`Pipeline.ki_aus`).
    """
    eintrag = anbieter(getattr(wahl, "anbieter", OLLAMA))
    modell = str(getattr(wahl, "modell", "") or "").strip()
    endpunkte = (config.llm_cleanup, config.llm_cleanup_fast, config.llm_command)
    if eintrag.id == AUS:
        return
    if eintrag.id == OLLAMA:
        if modell:
            for ep in endpunkte:
                ep.model = modell
        return
    adresse = (str(getattr(wahl, "adresse", "") or "").strip()
               if eintrag.id == EIGENER else eintrag.base_url)
    for ep in endpunkte:
        ep.provider = eintrag.id
        ep.base_url = adresse
        ep.model = modell or eintrag.modell
        # Ollama-Eigenheiten gelten fuer Cloud-Modelle nicht.
        ep.reasoning_effort = ""
        ep.num_ctx = 0
