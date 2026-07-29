"""Updates: pruefen, herunterladen, pruefsummen-verifizieren, Installer starten.

Quelle ist standardmaessig das GitHub-Repository (`GITHUB_REPO`) ueber die
Releases-API. Wer eine eigene Quelle braucht, setzt `settings.advanced.update_feed_url`
auf einen JSON-Feed der Form {"version": "3.14.0", "url": "https://…/Setup.exe",
"sha256": "…"} — derselbe Ablauf, nur andere Herkunft.

Sicherheitsregeln, die hier bewusst hart drinstehen:

- **Nur HTTPS.** Ein Update ueber http:// wird nicht geladen.
- **Host-Sperre.** Der Standardweg akzeptiert ausschliesslich GitHub-Hosts, auch nach
  Weiterleitungen (Release-Assets landen auf *.githubusercontent.com). Ein eigener Feed
  darf nur auf seinen eigenen Host verweisen — ein Feed kann so keine Datei von
  irgendwoher nachladen.
- **Pruefsumme.** Nennt das Release eine SHA-256 (Zeile `SHA256: <hex>` in den
  Release-Notizen oder Feld `sha256` im Feed), MUSS sie stimmen; sonst wird die Datei
  geloescht und nicht installiert. Zusaetzlich muss die Groesse zur API-Angabe passen.
- **Installiert wird nur auf Klick.** Pruefen und Herunterladen darf automatisch
  laufen; das Ausfuehren des Installers ist eine Nutzerentscheidung (die App startet
  dabei neu).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ..version import APP_VERSION

log = logging.getLogger(__name__)

GITHUB_REPO = "FynnXland/fleech"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Erlaubte Hosts fuer den Standardweg (GitHub liefert Assets ueber Subdomains von
# githubusercontent.com aus — die Liste deckt api, Weiterleitung und Asset ab).
_GITHUB_HOSTS = ("github.com", "githubusercontent.com")

_SHA256 = re.compile(r"\b([0-9a-fA-F]{64})\b")
_ASSET = re.compile(r"^FleechSetup-.*\.exe$", re.IGNORECASE)
_UA = {"User-Agent": f"Fleech/{APP_VERSION}", "Accept": "application/vnd.github+json"}


def _parse_version(v: str) -> tuple:
    parts = []
    for p in str(v).split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _host_ok(url: str, erlaubt=_GITHUB_HOSTS) -> bool:
    """HTTPS und Host aus der Erlaubnisliste (auch als Subdomain)."""
    teile = urlparse(url or "")
    if teile.scheme != "https" or not teile.hostname:
        return False
    host = teile.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in erlaubt)


def _fetch_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=timeout) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


def _from_github(data: dict) -> dict:
    """Release-JSON → {latest, url, size, sha256, notes}."""
    version = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    notizen = str(data.get("body") or "")
    treffer = _SHA256.search(notizen)
    asset = None
    for eintrag in data.get("assets") or []:
        if _ASSET.match(str(eintrag.get("name") or "")):
            asset = eintrag
            break
    return {
        "latest": version,
        "url": (asset or {}).get("browser_download_url", ""),
        "size": int((asset or {}).get("size") or 0),
        "sha256": (treffer.group(1).lower() if treffer else ""),
        "notes": notizen.strip(),
    }


def check_for_updates(feed_url: str | None = None, timeout: float = 8.0) -> dict:
    """Gibt {status, current, …} zurueck. Wirft nie.

    status: "update_available" | "up_to_date" | "no_release" | "error"
    """
    quelle = (feed_url or "").strip() or RELEASES_API
    eigener_feed = quelle != RELEASES_API
    erlaubt = ((urlparse(quelle).hostname or "",) if eigener_feed else _GITHUB_HOSTS)
    if not _host_ok(quelle, erlaubt):
        return {"status": "error", "current": APP_VERSION,
                "message": "Update-Quelle muss eine HTTPS-Adresse sein."}
    try:
        data = _fetch_json(quelle, timeout)
    except Exception as exc:
        # 404 heisst bei GitHub: Repository ohne Release — kein Fehler des Nutzers.
        if getattr(exc, "code", None) == 404 and not eigener_feed:
            return {"status": "no_release", "current": APP_VERSION,
                    "message": "Noch keine Veröffentlichung vorhanden."}
        log.info("Update-Pruefung fehlgeschlagen: %s", exc)
        return {"status": "error", "current": APP_VERSION, "message": str(exc)}

    if eigener_feed:
        info = {"latest": str(data.get("version", "")), "url": data.get("url", ""),
                "size": int(data.get("size") or 0),
                "sha256": str(data.get("sha256", "")).lower(),
                "notes": str(data.get("notes", ""))}
    else:
        info = _from_github(data)

    ergebnis = {"current": APP_VERSION, **info}
    if not info["latest"]:
        ergebnis["status"] = "no_release"
        return ergebnis
    if not is_newer(info["latest"]):
        ergebnis["status"] = "up_to_date"
        return ergebnis
    if not info["url"]:
        # Version ist neuer, aber ohne Datei — ehrlich benennen statt "verfuegbar".
        ergebnis["status"] = "error"
        ergebnis["message"] = ("Version " + info["latest"] +
                               " ist veröffentlicht, aber ohne Installationsdatei.")
        return ergebnis
    if not _host_ok(info["url"], erlaubt):
        ergebnis["status"] = "error"
        ergebnis["message"] = "Download-Adresse gehört nicht zur Update-Quelle."
        return ergebnis
    ergebnis["status"] = "update_available"
    return ergebnis


def download_update(url: str, ziel_ordner: Path, on_progress=None,
                    expected_size: int = 0, expected_sha256: str = "",
                    erlaubte_hosts=_GITHUB_HOSTS, timeout: float = 60.0):
    """Installationsdatei laden und pruefen. Gibt den Pfad zurueck oder None.

    `on_progress(prozent, text)` — ein 900-MB-Download darf nicht wie ein Haenger
    aussehen. Bei jedem Zweifel (Host, Groesse, Pruefsumme) wird die Datei geloescht:
    eine halb geladene oder fremde Setup-Datei darf nie im Ordner liegenbleiben.
    """
    if not _host_ok(url, erlaubte_hosts):
        log.warning("Update-Download abgelehnt (Host/Schema): %s", url)
        return None
    ziel_ordner = Path(ziel_ordner)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    name = Path(urlparse(url).path).name or "FleechSetup.exe"
    ziel = ziel_ordner / name

    def melde(prozent: int, text: str) -> None:
        if on_progress:
            try:
                on_progress(prozent, text)
            except Exception:
                log.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

    hasher = hashlib.sha256()
    geladen = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
        with urllib.request.urlopen(request, timeout=timeout) as antwort:
            # Nach Weiterleitungen erneut pruefen — die Erlaubnisliste gilt fuer das
            # ZIEL, nicht nur fuer die zuerst angefragte Adresse.
            tatsaechlich = antwort.geturl()
            if not _host_ok(tatsaechlich, erlaubte_hosts):
                log.warning("Update-Download nach Weiterleitung abgelehnt: %s", tatsaechlich)
                return None
            gesamt = expected_size or int(antwort.headers.get("Content-Length") or 0)
            melde(0, "Lade Update …")
            zuletzt = -5
            with open(ziel, "wb") as datei:
                while True:
                    block = antwort.read(256 * 1024)
                    if not block:
                        break
                    datei.write(block)
                    hasher.update(block)
                    geladen += len(block)
                    if gesamt:
                        prozent = int(geladen * 100 / gesamt)
                        if prozent >= zuletzt + 5:
                            zuletzt = prozent
                            melde(prozent, f"Lade Update … {prozent} %")
                    else:
                        melde(-1, f"Lade Update … {geladen // (1024 * 1024)} MB")
    except Exception as exc:
        log.warning("Update-Download fehlgeschlagen: %s", exc)
        ziel.unlink(missing_ok=True)
        return None

    if expected_size and geladen != expected_size:
        log.warning("Update-Groesse weicht ab (%s statt %s Bytes) — verworfen.",
                    geladen, expected_size)
        ziel.unlink(missing_ok=True)
        return None
    if expected_sha256:
        ist = hasher.hexdigest()
        if ist != expected_sha256.lower():
            log.warning("Update-Pruefsumme falsch (%s) — verworfen.", ist)
            ziel.unlink(missing_ok=True)
            return None
        log.info("Update-Pruefsumme bestaetigt.")
    else:
        log.info("Update ohne veroeffentlichte Pruefsumme geladen (nur Groesse geprueft).")
    melde(100, "Update geladen.")
    return ziel


def install_update(installer: Path) -> bool:
    """Installer starten und True zurueckgeben — der Aufrufer beendet danach die App.

    Der Installer laeuft per-user (kein UAC) und ersetzt einen laufenden Fleech nicht
    im Betrieb; deshalb muss die App beendet werden, sobald dieser Aufruf gelungen ist.
    """
    installer = Path(installer)
    if not installer.is_file():
        return False
    if sys.platform != "win32":
        log.info("Automatische Installation gibt es nur unter Windows.")
        return False
    try:
        # /SILENT zeigt nur den Fortschritt, /NORESTART verbietet einen Reboot.
        subprocess.Popen([str(installer), "/SILENT", "/NORESTART"], close_fds=True)
        log.info("Update-Installer gestartet: %s", installer.name)
        return True
    except Exception:
        log.exception("Update-Installer liess sich nicht starten.")
        return False
