"""Kaltstart-Einrichtung: alles besorgen, was Fleech zum ersten Diktat braucht.

Ohne diese Datei sieht ein frisch installiertes Fleech so aus: Nutzer drueckt F9,
spricht — und wartet minutenlang, weil im Hintergrund unsichtbar 1,6 GB
Erkennungsmodell und 3,3 GB Sprachmodell geladen werden, falls Ollama ueberhaupt
laeuft. Genau das soll die Einfuehrung uebernehmen und dabei ZEIGEN, was passiert.

Hier steht nur die Logik (ohne Qt, damit testbar); die Anzeige dazu ist
`fleech/ui/setuppage.py`. Drei Schritte, in dieser Reihenfolge:

    1. Ollama-Dienst      → `fleech/ollama_setup.py` (winget)
    2. Sprachmodell       → `/api/pull` mit Prozentanzeige
    3. Erkennungsmodell   → faster-whisper laedt aus dem HF-Cache, Fortschritt
                            wird ueber die Cache-Groesse gemessen (die Bibliothek
                            bietet keinen Haken dafuer an)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Grobe Erwartungswerte fuer die Anzeige ("… von etwa 1,6 GB"). Bewusst
# Schaetzwerte statt einer HF-Abfrage: eine Netzanfrage nur fuer eine Zahl im
# Text waere Aufwand fuers Falsche. Unbekanntes Modell = keine Zahl.
STT_GROESSEN_GB = {
    "large-v3-turbo": 1.6, "turbo": 1.6, "large-v3": 3.1, "large-v2": 3.1,
    "medium": 1.5, "small": 0.5, "base": 0.15, "tiny": 0.08,
}


@dataclass
class SetupStep:
    """Ein Einrichtungsschritt, wie ihn die Anzeige braucht.

    state: "pending" | "running" | "done" | "failed" | "manual"
    manual: Anleitung, wenn Fleech den Schritt nicht selbst erledigen kann.
    """

    key: str
    title: str
    detail: str = ""
    state: str = "pending"
    note: str = ""
    manual: str = ""
    percent: int = -1                       # -1 = unbestimmt (Balken laeuft)


def whisper_cache_bytes(size: str) -> int:
    """Bytes, die vom Erkennungsmodell bereits im HuggingFace-Cache liegen."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        from faster_whisper.utils import _MODELS
    except Exception:
        return 0
    repo = _MODELS.get(size, size)
    from pathlib import Path

    ordner = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
    if not ordner.is_dir():
        return 0
    gesamt = 0
    try:
        for datei in ordner.rglob("*"):
            if datei.is_file() and not datei.is_symlink():
                gesamt += datei.stat().st_size
    except OSError:
        pass
    return gesamt


def whisper_present(size: str) -> bool:
    """Liegt das Erkennungsmodell vollstaendig lokal? (Kein Netz.)"""
    try:
        from faster_whisper.utils import download_model

        download_model(size, local_files_only=True)
        return True
    except Exception:
        return False


def ensure_whisper(size: str, on_progress=None, poll: float = 1.0) -> bool:
    """Erkennungsmodell laden. `on_progress(text)` bekommt MB-Stand im Sekundentakt.

    faster-whisper bzw. huggingface_hub melden Fortschritt nur ueber tqdm auf
    stderr — in einer GUI unsichtbar. Deshalb misst ein Beobachter-Thread den
    Cache; das ist die einzige Zahl, die ohne Bibliotheks-Interna zu haben ist.
    """
    if whisper_present(size):
        return True
    try:
        from faster_whisper.utils import download_model
    except Exception:
        log.warning("faster-whisper nicht importierbar — Erkennungsmodell uebersprungen.")
        return False

    erwartet = STT_GROESSEN_GB.get(size)
    stop = threading.Event()

    def beobachte() -> None:
        while not stop.wait(poll):
            mb = whisper_cache_bytes(size) / (1024 * 1024)
            if on_progress:
                ziel = f" von etwa {erwartet:.1f} GB".replace(".", ",") if erwartet else ""
                on_progress(f"Lade Erkennungsmodell … {mb:.0f} MB{ziel}")

    if on_progress:
        on_progress("Lade Erkennungsmodell …")
    beobachter = threading.Thread(target=beobachte, daemon=True,
                                  name="stt-download-progress")
    beobachter.start()
    try:
        download_model(size)
        return True
    except Exception as exc:
        log.warning("Erkennungsmodell %s liess sich nicht laden: %s", size, exc)
        return False
    finally:
        stop.set()
        # Kurz einsammeln: sonst schickt der Beobachter noch eine MB-Meldung an
        # eine UI, die den Schritt bereits als fertig anzeigt.
        beobachter.join(timeout=poll + 0.5)


def build_steps(endpoints, stt_model: str, base_url: str) -> list:
    """Aktuellen Stand erheben und die Schritte liefern, die noch offen sind.

    Erledigte Schritte bleiben in der Liste (als "done") — wer sieht, dass zwei
    von drei Haken schon stehen, versteht die Lage schneller als bei einer leeren
    Seite.
    """
    from . import ollama_setup
    from .llm.client import ollama_installed_models

    schritte = []

    lage = ollama_setup.status(base_url)
    ollama_schritt = SetupStep(
        key="ollama", title="Ollama-Dienst",
        detail="führt die lokale KI aus — ohne ihn bleibt der Text unbereinigt.",
    )
    if lage == "ready":
        ollama_schritt.state = "done"
        ollama_schritt.note = "läuft"
    elif lage == "installed":
        ollama_schritt.note = "installiert, aber nicht gestartet"
    elif not ollama_setup.install_available():
        ollama_schritt.state = "manual"
        ollama_schritt.manual = ollama_setup.manual_hint()
        ollama_schritt.note = "fehlt"
    else:
        ollama_schritt.note = "fehlt — Fleech kann es installieren"
    schritte.append(ollama_schritt)

    vorhanden = ollama_installed_models(base_url) if lage == "ready" else set()
    for endpoint in endpoints or []:
        modell = getattr(endpoint, "model", "")
        if not modell or any(s.key == f"llm:{modell}" for s in schritte):
            continue
        schritt = SetupStep(
            key=f"llm:{modell}", title=f"Sprachmodell {modell}",
            detail="bereinigt das Diktat (Füllwörter, Versprecher, Zeichensetzung).",
        )
        if modell in vorhanden:
            schritt.state = "done"
            schritt.note = "vorhanden"
        else:
            schritt.note = "wird geladen (rund 3 GB)"
        schritte.append(schritt)

    stt = SetupStep(
        key="stt", title=f"Erkennungsmodell {stt_model}",
        detail="wandelt deine Stimme in Text — läuft auf der Grafikkarte.",
    )
    if whisper_present(stt_model):
        stt.state = "done"
        stt.note = "vorhanden"
    else:
        gb = STT_GROESSEN_GB.get(stt_model)
        stt.note = (f"wird geladen (etwa {gb:.1f} GB)".replace(".", ",") if gb
                    else "wird geladen")
    schritte.append(stt)
    return schritte


@dataclass
class SetupRunner:
    """Fuehrt die offenen Schritte der Reihe nach aus (im Hintergrund-Thread).

    on_state(key, state, note): Zustandswechsel eines Schritts.
    on_progress(key, text, percent): Fortschritt innerhalb eines Schritts;
        percent < 0 = unbestimmt.
    Rueckgabe von `run()`: True, wenn am Ende ALLES bereit ist.
    """

    endpoints: list
    stt_model: str
    base_url: str = "http://127.0.0.1:11434"
    on_state: object = None
    on_progress: object = None
    _abbruch: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        """Nach dem laufenden Schritt anhalten. Ein Download wird nicht mitten
        durchgeschnitten — Ollama und HF nehmen die Teile beim naechsten Mal
        wieder auf, ein harter Abbruch bringt also nichts ausser Risiko."""
        self._abbruch.set()

    # -- intern ---------------------------------------------------------------

    def _melde(self, key: str, state: str, note: str = "") -> None:
        if self.on_state:
            try:
                self.on_state(key, state, note)
            except Exception:
                log.debug("Zustandsmeldung fehlgeschlagen.", exc_info=True)

    def _fortschritt(self, key: str, text: str, percent: int = -1) -> None:
        if self.on_progress:
            try:
                self.on_progress(key, text, percent)
            except Exception:
                log.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

    def _schritt_ollama(self) -> bool:
        from . import ollama_setup

        if ollama_setup.service_running(self.base_url):
            return True

        if not ollama_setup.binary_present():
            if not ollama_setup.install_available():
                self._melde("ollama", "manual", "muss von Hand installiert werden")
                return False
            self._melde("ollama", "running", "wird installiert")
            fortschritt = self._fortschritt

            def melde_text(text: str) -> None:
                fortschritt("ollama", text, -1)

            if not ollama_setup.install(on_progress=melde_text):
                self._melde("ollama", "manual", ollama_setup.manual_hint())
                return False

        # Nach der Installation startet Ollama seinen Dienst selbst — aber nicht
        # sofort. Kurz warten, statt den Nutzer mit "fehlt" zurueckzulassen.
        self._melde("ollama", "running", "wird gestartet")
        for _ in range(30):
            if ollama_setup.service_running(self.base_url, timeout=2.0):
                return True
            if self._abbruch.is_set():
                return False
            time.sleep(1.0)
        return ollama_setup.service_running(self.base_url)

    def run(self) -> bool:
        """Alles Offene abarbeiten. Blockiert — immer in einem Thread aufrufen."""
        from .llm.client import ollama_installed_models, ollama_pull

        alles_gut = True

        if self._schritt_ollama():
            self._melde("ollama", "done", "läuft")
        else:
            # Ohne Dienst sind die Modell-Schritte sinnlos: sie laufen ueber
            # dessen API. Ehrlich abbrechen statt drei Fehler hintereinander.
            self._melde("ollama", "manual", "nicht erreichbar")
            for endpoint in self.endpoints or []:
                self._melde(f"llm:{getattr(endpoint, 'model', '')}", "pending",
                            "wartet auf Ollama")
            alles_gut = False

        if not alles_gut:
            return self._schritt_stt() and False

        vorhanden = ollama_installed_models(self.base_url)
        for endpoint in self.endpoints or []:
            modell = getattr(endpoint, "model", "")
            if not modell:
                continue
            key = f"llm:{modell}"
            if modell in vorhanden:
                self._melde(key, "done", "vorhanden")
                continue
            if self._abbruch.is_set():
                return False
            self._melde(key, "running", "wird geladen")
            fortschritt = self._fortschritt

            def melde_text(text: str, _key=key) -> None:
                # "Lade Sprachmodell gemma3:4b … 42 %" → Prozent fuer den Balken.
                prozent = -1
                if "%" in text:
                    zahl = text.rsplit("…", 1)[-1].replace("%", "").strip()
                    if zahl.isdigit():
                        prozent = int(zahl)
                fortschritt(_key, text, prozent)

            if ollama_pull(self.base_url, modell, on_progress=melde_text):
                self._melde(key, "done", "geladen")
            else:
                self._melde(key, "failed", "Download fehlgeschlagen")
                alles_gut = False

        return self._schritt_stt() and alles_gut

    def _schritt_stt(self) -> bool:
        if whisper_present(self.stt_model):
            self._melde("stt", "done", "vorhanden")
            return True
        if self._abbruch.is_set():
            return False
        self._melde("stt", "running", "wird geladen")
        fortschritt = self._fortschritt

        def melde_text(text: str) -> None:
            fortschritt("stt", text, -1)

        if ensure_whisper(self.stt_model, on_progress=melde_text):
            self._melde("stt", "done", "geladen")
            return True
        self._melde("stt", "failed", "Download fehlgeschlagen")
        return False
