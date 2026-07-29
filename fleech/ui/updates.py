"""Update-Basis (bewusst noch KEIN Auto-Updater — nur die Struktur dafuer).

Aktueller Stand:
- Versionsstruktur steht (fleech/version.py: APP_VERSION + BUILD).
- check_for_updates() fragt einen optionalen JSON-Feed ab, wenn eine URL konfiguriert
  ist (settings.advanced.update_feed_url). Ohne URL: "not_configured".
- Verteilung erfolgt vorerst manuell ueber ein neues Installer-Setup (siehe
  docs/packaging.md). Ein echter In-App-Downloader kommt spaeter.

Der Feed (Zukunft) hat die Form: {"version": "1.1.0", "url": "https://.../FleechSetup.exe"}.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from ..version import APP_VERSION

log = logging.getLogger(__name__)


def _parse_version(v: str) -> tuple:
    parts = []
    for p in str(v).split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


def check_for_updates(feed_url: str | None, timeout: float = 5.0) -> dict:
    """Gibt {status, current, [latest, url, message]} zurueck. Wirft nie."""
    if not feed_url:
        return {
            "status": "not_configured",
            "current": APP_VERSION,
            "message": "Kein Update-Feed konfiguriert. Updates werden vorerst manuell "
                       "über ein neues Setup verteilt.",
        }
    try:
        with urllib.request.urlopen(feed_url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = str(data.get("version", ""))
        if latest and is_newer(latest):
            return {"status": "update_available", "current": APP_VERSION,
                    "latest": latest, "url": data.get("url", "")}
        return {"status": "up_to_date", "current": APP_VERSION, "latest": latest}
    except Exception as exc:
        log.info("Update-Check fehlgeschlagen: %s", exc)
        return {"status": "error", "current": APP_VERSION, "message": str(exc)}
