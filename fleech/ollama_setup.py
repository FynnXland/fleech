"""Ollama beim Erststart erkennen und — auf Wunsch — selbst installieren.

Fleech braucht einen laufenden Ollama-Dienst. Wer die App weitergibt, kann nicht
voraussetzen, dass der Empfaenger weiss, was das ist. Dieses Modul beantwortet
deshalb drei Fragen und bietet fuer jede einen Weg an:

    1. Laeuft Ollama?          → `service_running()`
    2. Ist es installiert?     → `binary_present()`
    3. Kann Fleech es holen?   → `install_available()` / `install()`

Unter Windows uebernimmt `winget` (auf Windows 11 vorinstalliert, Paket
`Ollama.Ollama`) die Installation. Unter Linux gibt es kein vergleichbar
einheitliches Verfahren — dort wird ehrlich der offizielle Befehl genannt, statt
ein Skript aus dem Netz ohne Rueckfrage auszufuehren.

WICHTIG: Installiert wird NIE von allein. `install()` laeuft nur, wenn der Nutzer
im Einfuehrungsdialog ausdruecklich darauf klickt — eine Softwareinstallation ist
keine Nebenwirkung eines Programmstarts.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import urllib.request

log = logging.getLogger(__name__)

WINGET_PAKET = "Ollama.Ollama"
# Der offizielle Weg fuer Linux — wird ANGEZEIGT, nicht ausgefuehrt.
LINUX_BEFEHL = "curl -fsSL https://ollama.com/install.sh | sh"
DOWNLOAD_SEITE = "https://ollama.com/download"


def service_running(base_url: str = "http://127.0.0.1:11434", timeout: float = 3.0) -> bool:
    """Antwortet der Dienst? Das ist die einzige Frage, die wirklich zaehlt."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=timeout) as antwort:
            return antwort.status == 200
    except Exception:
        return False


def binary_present() -> bool:
    """Ist Ollama installiert, laeuft aber (noch) nicht?

    Der Unterschied ist fuer die Anzeige wichtig: „starte es" ist eine andere
    Anweisung als „installiere es".
    """
    return shutil.which("ollama") is not None


def install_available() -> bool:
    """Kann Fleech die Installation selbst anstossen?"""
    return sys.platform == "win32" and shutil.which("winget") is not None


def manual_hint() -> str:
    """Was der Nutzer tun muss, wenn Fleech es nicht kann."""
    if sys.platform.startswith("linux"):
        return f"Im Terminal ausführen:\n{LINUX_BEFEHL}"
    return f"Ollama von {DOWNLOAD_SEITE} herunterladen und installieren."


def install(on_progress=None, timeout: float = 900.0) -> bool:
    """Ollama per winget installieren. Nur nach ausdruecklichem Klick aufrufen.

    Gibt True zurueck, wenn winget mit Erfolg endet. `on_progress(text)` bekommt
    kurze Statuszeilen fuer den Dialog — eine Installation dauert Minuten und darf
    nicht wie ein Einfrieren aussehen.
    """
    if not install_available():
        return False

    def melde(text: str) -> None:
        if on_progress:
            try:
                on_progress(text)
            except Exception:
                log.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

    melde("Ollama wird installiert — das dauert einige Minuten …")
    try:
        # --silent: kein eigenes Installer-Fenster. Die Zustimmungen sind noetig,
        # weil winget sonst interaktiv nachfragt und in einem GUI-Prozess haengt.
        ergebnis = subprocess.run(
            ["winget", "install", "--id", WINGET_PAKET, "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("winget-Installation von Ollama nach %.0f s abgebrochen.", timeout)
        melde("Installation hat zu lange gedauert — bitte von Hand nachholen.")
        return False
    except Exception:
        log.exception("winget-Aufruf fehlgeschlagen.")
        melde("Installation konnte nicht gestartet werden.")
        return False

    if ergebnis.returncode == 0:
        log.info("Ollama per winget installiert.")
        melde("Ollama ist installiert.")
        return True
    log.warning("winget endete mit Code %s: %s", ergebnis.returncode,
                (ergebnis.stderr or ergebnis.stdout or "")[-300:])
    melde("Installation nicht erfolgreich — bitte von Hand nachholen.")
    return False


def status(base_url: str = "http://127.0.0.1:11434") -> str:
    """Gesamtlage in einem Wort: "ready" | "installed" | "missing".

    Genau die drei Faelle, die der Dialog unterscheiden muss.
    """
    if service_running(base_url):
        return "ready"
    return "installed" if binary_present() else "missing"
