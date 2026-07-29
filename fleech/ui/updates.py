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
- **Der Token verlaesst GitHub nicht.** Bei einem PRIVATEN Repository braucht die
  Abfrage einen Zugriffstoken (`FLEECH_UPDATE_TOKEN` oder
  `settings.advanced.update_token`). Er wird ausschliesslich an GitHub-Hosts
  gesendet — nie an einen eigenen Feed, nie nach einer Weiterleitung woandershin —
  und nie ins Log geschrieben.
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


def update_token(settings=None) -> str:
    """Zugriffstoken fuer ein privates Repository (leer = oeffentlicher Zugriff).

    Reihenfolge: Umgebungsvariable zuerst (fuer Entwickler/CI), dann die
    Einstellungen. Fleech erzeugt NIE selbst einen Token — der Nutzer legt ihn an
    und traegt ihn ein.
    """
    import os

    aus_env = (os.environ.get("FLEECH_UPDATE_TOKEN") or "").strip()
    if aus_env:
        return aus_env
    return (getattr(getattr(settings, "advanced", None), "update_token", "") or "").strip()


def _auth_headers(url: str, token: str) -> dict:
    """Kopfzeilen fuer eine Anfrage — Token NUR an GitHub.

    Ein eigener Feed oder eine Weiterleitung auf einen fremden Host bekommt ihn
    nicht: ein Zugriffstoken darf nie an einen Server gehen, den der Nutzer nicht
    als Update-Quelle gemeint hat.
    """
    kopf = dict(_UA)
    if token and _host_ok(url, _GITHUB_HOSTS):
        kopf["Authorization"] = f"Bearer {token}"
    return kopf


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen: Token abstreifen, fremde Ziele verweigern.

    Beides ist noetig, nicht kosmetisch:

    1. GitHub leitet Asset-Downloads auf eine vorsignierte Adresse um. Wird der
       `Authorization`-Kopf mitgeschleppt, antwortet der Speicher mit einem Fehler
       ("nur ein Anmeldeverfahren erlaubt") — der Download scheitert also, wenn man
       den Token NICHT abstreift.
    2. Ein Ziel ausserhalb der Erlaubnisliste wird gar nicht erst angefragt. Sonst
       koennte eine manipulierte Antwort den Download (und im Fall 1 auch den Token)
       irgendwohin lenken.
    """

    def __init__(self, erlaubte_hosts=_GITHUB_HOSTS):
        self._erlaubt = erlaubte_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_ok(newurl, self._erlaubt):
            log.warning("Weiterleitung auf nicht erlaubten Host abgelehnt.")
            return None
        neu = super().redirect_request(req, fp, code, msg, headers, newurl)
        if neu is not None:
            neu.headers.pop("Authorization", None)
            neu.unredirected_hdrs.pop("Authorization", None)
        return neu


def _fetch_json(url: str, timeout: float, token: str = "") -> dict:
    request = urllib.request.Request(url, headers=_auth_headers(url, token))
    with urllib.request.urlopen(request, timeout=timeout) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


def _from_github(data: dict, token: str = "") -> dict:
    """Release-JSON → {latest, url, size, sha256, notes}.

    Bei privatem Repository fuehrt `browser_download_url` ohne Anmeldung ins Leere;
    die API-Adresse des Assets (`url` mit `Accept: application/octet-stream`) ist
    der Weg, der mit Token funktioniert. Darum haengt die Wahl am Token.
    """
    version = str(data.get("tag_name") or data.get("name") or "").lstrip("vV")
    notizen = str(data.get("body") or "")
    treffer = _SHA256.search(notizen)
    asset = None
    for eintrag in data.get("assets") or []:
        if _ASSET.match(str(eintrag.get("name") or "")):
            asset = eintrag
            break
    asset = asset or {}
    adresse = (asset.get("url", "") if token else "") or asset.get("browser_download_url", "")
    return {
        "latest": version,
        "url": adresse,
        "name": asset.get("name", ""),
        "size": int(asset.get("size") or 0),
        "sha256": (treffer.group(1).lower() if treffer else ""),
        "notes": notizen.strip(),
    }


def check_for_updates(feed_url: str | None = None, timeout: float = 8.0,
                      token: str = "") -> dict:
    """Gibt {status, current, …} zurueck. Wirft nie.

    status: "update_available" | "up_to_date" | "no_release" | "auth_required" | "error"
    """
    quelle = (feed_url or "").strip() or RELEASES_API
    eigener_feed = quelle != RELEASES_API
    erlaubt = ((urlparse(quelle).hostname or "",) if eigener_feed else _GITHUB_HOSTS)
    if not _host_ok(quelle, erlaubt):
        return {"status": "error", "current": APP_VERSION,
                "message": "Update-Quelle muss eine HTTPS-Adresse sein."}
    try:
        data = _fetch_json(quelle, timeout, token=token)
    except Exception as exc:
        # GitHub antwortet auf ein privates Repository ohne Berechtigung mit 404 —
        # nicht mit 403. Ein 404 heisst deshalb ZWEI Dinge, und die Unterscheidung
        # macht der Token: ohne ihn ist es vermutlich fehlende Berechtigung, mit ihm
        # gibt es wirklich noch kein Release. Sonst wuerde Fleech bei einem privaten
        # Repository fuer immer "keine Veroeffentlichung" behaupten.
        if getattr(exc, "code", None) == 404 and not eigener_feed:
            if not token:
                return {"status": "auth_required", "current": APP_VERSION,
                        "message": "Kein Zugriff auf die Update-Quelle — bei einem "
                                   "privaten Repository fehlt der Zugriffstoken."}
            return {"status": "no_release", "current": APP_VERSION,
                    "message": "Noch keine Veröffentlichung vorhanden."}
        if getattr(exc, "code", None) in (401, 403) and not eigener_feed:
            return {"status": "auth_required", "current": APP_VERSION,
                    "message": "Der Zugriffstoken wurde abgelehnt (abgelaufen oder "
                               "ohne Leserecht)."}
        log.info("Update-Pruefung fehlgeschlagen: %s", exc)
        return {"status": "error", "current": APP_VERSION, "message": str(exc)}

    if eigener_feed:
        info = {"latest": str(data.get("version", "")), "url": data.get("url", ""),
                "size": int(data.get("size") or 0),
                "sha256": str(data.get("sha256", "")).lower(),
                "notes": str(data.get("notes", ""))}
    else:
        info = _from_github(data, token=token)

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
                    erlaubte_hosts=_GITHUB_HOSTS, timeout: float = 60.0,
                    token: str = "", dateiname: str = ""):
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
    # Bei der API-Adresse eines Assets endet der Pfad auf die Asset-ID (".../assets/42")
    # — dann muss der Name aus dem Release kommen, sonst hiesse die Datei "42".
    name = dateiname or Path(urlparse(url).path).name or "FleechSetup.exe"
    if not name.lower().endswith(".exe"):
        name = "FleechSetup.exe"
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
        kopf = _auth_headers(url, token)
        # Asset-Bytes statt JSON — ohne diesen Accept liefert die API die
        # Metadaten des Assets, nicht die Datei.
        kopf["Accept"] = "application/octet-stream"
        request = urllib.request.Request(url, headers=kopf)
        opener = urllib.request.build_opener(_RedirectHandler(erlaubte_hosts))
        with opener.open(request, timeout=timeout) as antwort:
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
