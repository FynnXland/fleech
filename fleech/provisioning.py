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
    "jimmymeister/whisper-large-v3-turbo-german-ct2": 1.6,
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


def dauer_text(sekunden: float | None) -> str:
    """Restzeit fuer Menschen: „noch ca. 40 s", „noch ca. 3 Min.", „noch ca. 1 Std. 5 Min."."""
    if sekunden is None or sekunden < 0 or sekunden != sekunden:
        return ""
    fuenfer = max(5, int(round(sekunden / 5.0)) * 5)
    if fuenfer < 60:
        return f"noch ca. {fuenfer} s"
    minuten = max(1, int(round(sekunden / 60.0)))
    if minuten < 60:
        return f"noch ca. {minuten} Min."
    stunden, rest = divmod(minuten, 60)
    return f"noch ca. {stunden} Std. {rest} Min." if rest else f"noch ca. {stunden} Std."


class Restzeit:
    """Tempo und Restzeit eines Downloads aus (fertig, gesamt)-Meldungen.

    Gleitender Mittelwert ueber das Tempo, damit die Anzeige nicht bei jedem
    Paket springt. Wechselt `gesamt` (Ollama laedt mehrere Schichten nacheinander)
    oder faellt `fertig`, beginnt die Messung neu.
    """

    def __init__(self, uhr=time.monotonic, takt: float = 0.5):
        self._uhr = uhr
        self._takt = takt
        self._gesamt = None
        self._fertig = 0
        self._t = 0.0
        self._tempo = None
        self._text = ""

    def melde(self, fertig: int, gesamt: int) -> str:
        jetzt = self._uhr()
        if gesamt != self._gesamt or fertig < self._fertig:
            self._gesamt, self._fertig, self._t = gesamt, fertig, jetzt
            self._tempo, self._text = None, ""
            return self._text
        dt = jetzt - self._t
        if dt < self._takt:
            return self._text
        tempo = (fertig - self._fertig) / dt
        self._tempo = tempo if self._tempo is None else 0.7 * self._tempo + 0.3 * tempo
        self._fertig, self._t = fertig, jetzt
        if self._tempo <= 0:
            self._text = "wartet auf Daten …"
            return self._text
        mb_s = self._tempo / (1024 * 1024)
        tempo_text = (f"{mb_s:.0f} MB/s" if mb_s >= 10
                      else f"{mb_s:.1f} MB/s".replace(".", ","))
        rest = dauer_text(max(0, gesamt - fertig) / self._tempo)
        self._text = f"{tempo_text} · {rest}" if rest else tempo_text
        return self._text


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


def ensure_whisper(size: str, on_progress=None, poll: float = 1.0,
                   on_stand=None) -> bool:
    """Erkennungsmodell laden. `on_progress(text)` bekommt MB-Stand im Sekundentakt;
    `on_stand(text, prozent)` zusaetzlich Prozent und Restzeit (Einrichtungsseite).

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

    restzeit = Restzeit()
    ziel_bytes = int(erwartet * 1024 ** 3) if erwartet else 0

    def beobachte() -> None:
        while not stop.wait(poll):
            roh = whisper_cache_bytes(size)
            mb = roh / (1024 * 1024)
            ziel = f" von etwa {erwartet:.1f} GB".replace(".", ",") if erwartet else ""
            text = f"Lade Erkennungsmodell … {mb:.0f} MB{ziel}"
            if on_progress:
                on_progress(text)
            if on_stand:
                prozent = min(99, int(roh * 100 / ziel_bytes)) if ziel_bytes else -1
                rest = restzeit.melde(roh, ziel_bytes) if ziel_bytes else ""
                on_stand(f"{mb:.0f} MB{ziel}" + (f" · {rest}" if rest else ""), prozent)

    if on_progress:
        on_progress("Lade Erkennungsmodell …")
    if on_stand:
        on_stand("Lade Erkennungsmodell …", -1)
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

    Leere `base_url` = keine lokale KI (Cloud-Anbieter oder „Ohne KI"): Dann gibt
    es weder Ollama noch Sprachmodelle einzurichten, nur die Spracherkennung.
    """
    from . import ollama_setup
    from .llm.client import ollama_installed_models

    schritte = []
    if not base_url:
        return schritte + [_stt_schritt(stt_model)]

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
            schritt.note = _llm_groesse_text(modell)
        schritte.append(schritt)

    schritte.append(_stt_schritt(stt_model))
    return schritte


def _llm_groesse_text(modell: str) -> str:
    """„wird geladen (etwa 3,3 GB)" — die Groesse aus dem Modellkatalog."""
    try:
        from .llm.modellberater import mitgelieferter_katalog, ollama_modelle

        for m in ollama_modelle(mitgelieferter_katalog()):
            if m.modell == modell and m.groesse_gb:
                return f"wird geladen (etwa {m.groesse_gb:.1f} GB)".replace(".", ",")
    except Exception:
        log.debug("Modellkatalog fuer die Groesse nicht lesbar.", exc_info=True)
    return "wird geladen"


def _stt_schritt(stt_model: str) -> SetupStep:
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
    return stt


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
        if not self.base_url:              # keine lokale KI gewaehlt
            return self._schritt_stt()

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
            if ollama_pull(self.base_url, modell, on_bytes=self._pull_stand(key)):
                self._melde(key, "done", "geladen")
            else:
                self._melde(key, "failed", "Download fehlgeschlagen")
                alles_gut = False

        return self._schritt_stt() and alles_gut

    def _pull_stand(self, key: str):
        """Byte-Meldungen eines Ollama-Downloads → Prozent, Tempo, Restzeit.

        Ollama laedt ein Modell in Schichten; nur die grosse zaehlt fuer den
        Nutzer. Gemeldet wird nur, wenn sich der Text aendert — ein Signal je
        Netzpaket wuerde die Oberflaeche fluten."""
        restzeit = Restzeit()
        fortschritt = self._fortschritt
        zuletzt = [""]

        def melde(fertig: int, gesamt: int) -> None:
            if gesamt < 50 * 1024 * 1024:          # Vorlage, Lizenz, Parameter
                return
            prozent = int(fertig * 100 / gesamt) if gesamt else -1
            rest = restzeit.melde(fertig, gesamt)
            text = f"{prozent} %" + (f" · {rest}" if rest else "")
            if text != zuletzt[0]:
                zuletzt[0] = text
                fortschritt(key, text, prozent)

        return melde

    def _schritt_stt(self) -> bool:
        if whisper_present(self.stt_model):
            self._melde("stt", "done", "vorhanden")
            return True
        if self._abbruch.is_set():
            return False
        self._melde("stt", "running", "wird geladen")
        fortschritt = self._fortschritt

        def melde_stand(text: str, prozent: int) -> None:
            fortschritt("stt", text, prozent)

        if ensure_whisper(self.stt_model, on_stand=melde_stand):
            self._melde("stt", "done", "geladen")
            return True
        self._melde("stt", "failed", "Download fehlgeschlagen")
        return False
