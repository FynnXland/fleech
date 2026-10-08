"""LLM-Zugriff: lokales Ollama (Standard) oder ein Cloud-Anbieter mit eigenem Schluessel.

Lokal laeuft ueber Ollamas eigene HTTP-API (`/api/chat`, `/api/generate`), NICHT
ueber dessen OpenAI-Aufsatz: Der ignoriert `num_ctx` (gemessen), womit lange
Diktate mitten im Satz abbrachen. Cloud-Anbieter sprechen die OpenAI-Form
(`/chat/completions`) oder — Anthropic — ihre eigene Messages-API. Welcher Weg,
entscheidet `endpoint.provider` (Liste in `providers.py`).

Nur die Standardbibliothek; Schluessel kommen aus `apikeys.py`.
"""

from __future__ import annotations

import logging
import re

from .providers import ANTHROPIC_VERSION, anbieter, ist_lokales_ollama

log = logging.getLogger(__name__)

# Denkbloecke, die manche Modelle trotz abgeschaltetem Reasoning in den Content
# schreiben. Bewusst mehrere bekannte Schreibweisen: bei einem Modellwechsel wuerde
# ein unbekanntes Tag sonst sichtbar im eingefuegten Text landen. Solche XML-artigen
# Tags diktiert niemand — die Muster koennen also nicht falsch anschlagen.
_THINK_TAG = re.compile(
    r"<(think|thinking|thought|reasoning|scratchpad|analysis)>.*?</\1>\s*",
    re.DOTALL | re.IGNORECASE,
)
# Provider-spezifische Zusatzmuster koennen in config.yaml je Endpoint ergaenzt
# werden (llm.<endpoint>.reasoning_patterns).

OLLAMA_KEEP_ALIVE = "30m"


def ollama_root(base_url: str) -> str:
    """Wurzel-URL des Ollama-Servers aus der konfigurierten base_url.

    Zwei Korrekturen, beide fuer Bestandskonfigurationen gedacht:

    1. Das `/v1`-Suffix stammt aus der Zeit, als Fleech den OpenAI-Aufsatz ansprach.
       Es wird abgeschnitten statt verboten — ein harter Fehler dafuer waere Schikane.

    2. `localhost` → `127.0.0.1`. GEMESSEN: Unter Windows kostet der Name **2,05 s
       pro Anfrage**, konstant und unabhaengig von der Textlaenge (3,43 s Wanduhr
       gegen 1,19 s ueber die IP; Ollamas eigene Zeitmessung sah in beiden Faellen
       identisch aus). Windows fragt zuerst die IPv6-Adresse `::1` an, auf der
       Ollama standardmaessig nicht lauscht, und laeuft in den Verbindungs-Timeout,
       bevor es IPv4 versucht. Diese zwei Sekunden lagen auf JEDEM Diktat und haben
       jeden Modell- und Prompt-Gewinn ueberdeckt.
    """
    root = (base_url or "http://127.0.0.1:11434").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root.replace("//localhost:", "//127.0.0.1:")


def _ollama_generate_keepalive(endpoint, keep_alive) -> bool:
    """POST /api/generate ohne Prompt: laedt/entlaedt NUR (keine Tokens) und setzt
    keep_alive. Nur fuer localhost — ein entfernter Server wird nie angefasst.

    `num_ctx` MUSS hier mitgeschickt werden, sonst ist das Vorladen wertlos:
    Ollama bindet die Kontextgroesse an die geladene Instanz. Wurde mit 4096
    geladen (Default) und will der Diktat-Aufruf 8192, laedt Ollama das Modell
    KOMPLETT NEU — jedes Mal. Real gemessen: `ollama ps` zeigte CONTEXT 4096
    trotz konfigurierter 8192, und die Cleanup-Zeit lag bei 5 s statt 1,3 s.
    """
    if not ist_lokales_ollama(endpoint):
        return False
    import json
    import urllib.request

    root = ollama_root(endpoint.base_url)
    payload = {"model": endpoint.model, "keep_alive": keep_alive}
    num_ctx = int(getattr(endpoint, "num_ctx", 0) or 0)
    if num_ctx > 0 and keep_alive != 0:      # beim Entladen ist die Groesse egal
        payload["options"] = {"num_ctx": num_ctx}
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{root}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60):
        pass
    return True


def ollama_auf_cpu(endpoint) -> bool | None:
    """Ist das Modell geladen, liegt aber mit 0 Byte auf der Grafikkarte?

    True = es rechnet komplett auf dem Prozessor. None = unbekannt (nicht geladen,
    entfernter Server, Ollama nicht erreichbar).

    Anlass: Am 2026-10-02 fand Ollama nach einem Selbst-Update die Grafikkarte
    nicht (`inference compute id=cpu`, `size_vram 0`). Jede Bereinigung dauerte
    dadurch 13–27 s statt ~0,5 s, und das Modell belegte 2,8 GB Arbeitsspeicher.
    Fleech merkte nichts — der Nutzer sah nur „dauert ewig".
    """
    if not ist_lokales_ollama(endpoint):
        return None
    import json
    import urllib.request

    try:
        root = ollama_root(endpoint.base_url)
        with urllib.request.urlopen(f"{root}/api/ps", timeout=3) as antwort:
            daten = json.load(antwort)
    except Exception:
        log.debug("Ollama /api/ps nicht abfragbar.", exc_info=True)
        return None
    for modell in daten.get("models") or []:
        if endpoint.model in (modell.get("name"), modell.get("model")):
            if int(modell.get("size") or 0) <= 0:
                return None
            return int(modell.get("size_vram") or 0) == 0
    return None


def ollama_preload(endpoint, keep_alive: str = OLLAMA_KEEP_ALIVE) -> bool:
    """Laedt das Modell eines LOKALEN Ollama in den VRAM und setzt keep_alive.

    Hintergrund (gemessen): Ollamas OpenAI-Endpoint ignoriert keep_alive im Request
    → Modell wird nach 5 min Leerlauf entladen, das naechste Diktat zahlt ~8 s
    Ladezeit. Wird beim App-Start und periodisch aufgerufen.
    """
    try:
        if not _ollama_generate_keepalive(endpoint, keep_alive):
            return False
        log.info("Ollama-Modell %s vorgeladen (keep_alive=%s).", endpoint.model, keep_alive)
        return True
    except Exception as exc:
        log.debug("Ollama-Preload fehlgeschlagen: %s", exc)
        return False


def ollama_unload(endpoint) -> bool:
    """Entlaedt das Modell eines LOKALEN Ollama SOFORT (keep_alive=0) — gibt RAM/VRAM
    frei, statt das keep_alive bis zu 30 min nachlaufen zu lassen. Genutzt, wenn ein
    Spiel erkannt wird oder das Smart-Warmhaltefenster ablaeuft."""
    try:
        if not _ollama_generate_keepalive(endpoint, 0):
            return False
        log.info("Ollama-Modell %s entladen (RAM/VRAM freigegeben).", endpoint.model)
        return True
    except Exception as exc:
        log.debug("Ollama-Unload fehlgeschlagen: %s", exc)
        return False


def ollama_installed_models(base_url: str, timeout: float = 10.0) -> set:
    """Namen der lokal vorhandenen Modelle (leer, wenn Ollama nicht erreichbar)."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"{ollama_root(base_url)}/api/tags", timeout=timeout
        ) as response:
            data = json.loads(response.read())
    except Exception as exc:
        log.debug("Ollama-Modellliste nicht abrufbar: %s", exc)
        return set()
    namen = set()
    for eintrag in data.get("models") or []:
        name = eintrag.get("name") or eintrag.get("model") or ""
        if name:
            namen.add(name)
            if name.endswith(":latest"):   # "gemma3:4b" vs "gemma3:4b:latest"
                namen.add(name[: -len(":latest")])
    return namen


def ollama_pull(base_url: str, model: str, on_progress=None, timeout: float = 3600.0,
                on_bytes=None) -> bool:
    """Ein fehlendes Modell herunterladen (`/api/pull`, gestreamt).

    Damit ist eine frische Installation ohne Handgriffe startklar: Fleech holt sich
    beim ersten Start selbst, was es braucht. `on_progress(text)` bekommt kurze
    Statuszeilen ("Lade gemma3:4b … 42 %") fuer Log und Pille — ein mehrere Gigabyte
    grosser Download darf nicht als eingefrorene App erscheinen.
    `on_bytes(fertig, gesamt)` bekommt jeden Stand — daraus rechnet die
    Einrichtung Tempo und Restzeit (`provisioning.Restzeit`).
    """
    import json
    import urllib.request

    body = json.dumps({"model": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{ollama_root(base_url)}/api/pull",
        data=body, headers={"Content-Type": "application/json"},
    )
    zuletzt = -1
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for zeile in response:
                if not zeile.strip():
                    continue
                try:
                    schritt = json.loads(zeile)
                except ValueError:
                    continue
                if schritt.get("error"):
                    log.error("Ollama-Download %s: %s", model, schritt["error"])
                    return False
                gesamt = schritt.get("total") or 0
                fertig = schritt.get("completed") or 0
                if gesamt and on_bytes:
                    on_bytes(int(fertig), int(gesamt))
                if gesamt and on_progress:
                    prozent = int(fertig * 100 / gesamt)
                    if prozent >= zuletzt + 5:     # nicht bei jedem Chunk melden
                        zuletzt = prozent
                        on_progress(f"Lade Sprachmodell {model} … {prozent} %")
    except Exception as exc:
        log.warning("Ollama-Download von %s fehlgeschlagen: %s", model, exc)
        return False
    log.info("Ollama-Modell %s heruntergeladen.", model)
    return True


def ensure_ollama_models(endpoints, on_progress=None) -> list:
    """Fehlende Modelle der uebergebenen Endpoints nachladen. Gibt die geholten zurueck.

    Best-Effort: Ist Ollama nicht erreichbar, passiert nichts — die App startet
    trotzdem und meldet das Problem erst, wenn wirklich diktiert wird. Ein blockierter
    Start waere die schlechtere Antwort auf einen laufenden Ollama-Neustart.
    """
    lokal, geholt = None, []
    for endpoint in endpoints:
        base = getattr(endpoint, "base_url", "")
        if not ist_lokales_ollama(endpoint):
            continue                      # entfernte Server verwalten wir nicht
        if lokal is None:
            lokal = ollama_installed_models(base)
            if not lokal:
                return geholt             # Ollama laeuft nicht → nichts erzwingen
        if endpoint.model in lokal:
            continue
        log.info("Sprachmodell %s fehlt — wird geladen.", endpoint.model)
        if on_progress:
            on_progress(f"Lade Sprachmodell {endpoint.model} …")
        if ollama_pull(base, endpoint.model, on_progress):
            geholt.append(endpoint.model)
            lokal.add(endpoint.model)
    return geholt


def strip_reasoning(text: str, extra_patterns=None) -> str:
    """Entfernt Inline-Denkbloecke, die manche Thinking-Modelle in den Content schreiben.

    extra_patterns: provider-spezifische Regexe aus der Config. Ein kaputtes Muster
    wird uebersprungen — eine Nutzer-Regex darf das Diktat nie reissen."""
    cleaned = _THINK_TAG.sub("", text)
    for pattern in extra_patterns or ():
        try:
            cleaned = re.sub(str(pattern), "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        except re.error:
            log.warning("Ungueltiges reasoning_pattern uebersprungen: %r", pattern)
    return cleaned.strip()


class ChatClient:
    def __init__(self, endpoint):
        self.cfg = endpoint
        self.last_truncated = False

    def _create(self, system_prompt: str, user_text: str) -> str:
        """Ein Chat-Aufruf — der Weg haengt am gewaehlten Anbieter."""
        api = anbieter(getattr(self.cfg, "provider", "")).api
        if api == "openai":
            return self._openai(system_prompt, user_text)
        if api == "anthropic":
            return self._anthropic(system_prompt, user_text)
        return self._ollama(system_prompt, user_text)

    def _schluessel(self) -> str:
        from .apikeys import lies

        return lies(getattr(self.cfg, "provider", ""))

    def _post(self, url: str, body: dict, kopf: dict) -> dict:
        import json
        import urllib.request

        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **kopf},
        )
        with urllib.request.urlopen(request, timeout=self.cfg.timeout) as response:
            return json.loads(response.read())

    def _openai(self, system_prompt: str, user_text: str) -> str:
        """OpenAI-Form (`/chat/completions`): OpenAI, Gemini, Groq, Mistral,
        OpenRouter, eigene Server.

        `temperature` faellt bei den Denk-Modellen von OpenAI weg (o-Reihe,
        gpt-5): Die nehmen nur ihren Vorgabewert an und lehnen jeden anderen mit
        HTTP 400 ab. `finish_reason == "length"` ist dasselbe wie Ollamas volles
        Kontextfenster — der Aufrufer nimmt dann den Rohtext.
        """
        self.last_truncated = False
        body = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        if not str(self.cfg.model).lower().startswith(("o1", "o3", "o4", "gpt-5")):
            body["temperature"] = self.cfg.temperature
        schluessel = self._schluessel()
        kopf = {"Authorization": f"Bearer {schluessel}"} if schluessel else {}
        data = self._post(f"{self.cfg.base_url.rstrip('/')}/chat/completions", body, kopf)
        wahl = (data.get("choices") or [{}])[0]
        self.last_truncated = wahl.get("finish_reason") == "length"
        return strip_reasoning(
            (wahl.get("message") or {}).get("content") or "",
            getattr(self.cfg, "reasoning_patterns", None),
        )

    def _anthropic(self, system_prompt: str, user_text: str) -> str:
        """Anthropics eigene Messages-API: System-Prompt als eigenes Feld,
        `max_tokens` ist Pflicht, die Antwort kommt als Liste von Bloecken."""
        self.last_truncated = False
        body = {
            "model": self.cfg.model,
            "max_tokens": 8192,
            "temperature": self.cfg.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_text}],
        }
        kopf = {"x-api-key": self._schluessel(), "anthropic-version": ANTHROPIC_VERSION}
        data = self._post(f"{self.cfg.base_url.rstrip('/')}/messages", body, kopf)
        self.last_truncated = data.get("stop_reason") == "max_tokens"
        text = "".join(b.get("text", "") for b in data.get("content") or []
                       if b.get("type") == "text")
        return strip_reasoning(text, getattr(self.cfg, "reasoning_patterns", None))

    def _ollama(self, system_prompt: str, user_text: str) -> str:
        """Ein Chat-Aufruf gegen Ollama.

        `num_ctx` ist der Grund, warum hier Ollamas eigene API steht und nicht mehr
        der OpenAI-Aufsatz: Ollama laedt Modelle mit 4096 Token Kontext, egal was das
        Modell koennte — und der Aufsatz ignoriert jede Option dagegen (gemessen:
        identische Token-Zahlen mit und ohne). Bei einem langen Diktat frisst allein
        der System-Prompt ~3000 der 4096 Token; fuer die Antwort bleiben ~110, und der
        bereinigte Text bricht mitten im Satz ab (real: 610 Woerter rein, 84 raus).

        `last_truncated`: Hat das Modell aufgehoert, weil das Fenster voll war? Der
        Aufrufer entscheidet dann fuer den Rohtext — ein halber Satz ist schlimmer
        als ein unbereinigter ganzer.
        """
        import json
        import urllib.request

        self.last_truncated = False
        options = {"temperature": self.cfg.temperature}
        num_ctx = int(getattr(self.cfg, "num_ctx", 0) or 0)
        if num_ctx > 0:
            options["num_ctx"] = num_ctx
        body = {
            "model": self.cfg.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "options": options,
            # Ohne dieses Feld setzt Ollama nach JEDEM Diktat seine eigene Vorgabe
            # (OLLAMA_KEEP_ALIVE, hier 5 min) — kuerzer als Fleechs Warmhaltefenster.
            # Deshalb musste ein Takt das Modell jede Minute neu „vorladen" (im Log
            # 82-mal am Tag). Mit demselben Wert wie beim Vorladen haelt schon das
            # Diktat selbst das Modell warm.
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        # Bereinigen braucht kein Nachdenken: Fleech sagt das jedem lokalen Modell
        # ausdruecklich, ausser reasoning_effort verlangt eine Stufe (low/medium/
        # high). Frueher kam `think: false` nur bei "none" — wer in der Modellwahl
        # ein Thinking-Modell nahm (gemma4:e4b), wartete mit dem echten Prompt
        # 3,5 s statt 0,2 s, bei langen Diktaten 10–40 s. gemma3 nimmt das Feld
        # ohne Unterschied an (live gemessen, Ollama 0.35.1).
        aufwand = str(getattr(self.cfg, "reasoning_effort", "") or "").lower()
        if aufwand in ("", "none"):
            body["think"] = False
        request = urllib.request.Request(
            f"{ollama_root(self.cfg.base_url)}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.cfg.timeout) as response:
            data = json.loads(response.read())
        self.last_truncated = data.get("done_reason") == "length"
        return strip_reasoning(
            (data.get("message") or {}).get("content") or "",
            getattr(self.cfg, "reasoning_patterns", None),
        )

    def complete(self, system_prompt: str, user_text: str) -> str:
        return self._create(system_prompt, user_text)
