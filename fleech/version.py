"""Zentrale Versionsangaben.

- APP_VERSION: semantische App-Version (SemVer), Quelle der Wahrheit fuer Installer & UI.
- BUILD: Build-Stamp (Datum/Commit). Wird vom Build-Skript in build.txt geschrieben und
  ins Paket gebundelt; im Dev-Modus ohne build.txt = "dev".
"""

from __future__ import annotations

APP_VERSION = "4.3.0"  # 4.3.0: Formel-Erkennung gehaertet + gesprochene Zeichen


def _read_build() -> str:
    try:
        from .resources import resource_dir

        stamp = resource_dir() / "build.txt"
        if stamp.is_file():
            return stamp.read_text(encoding="utf-8").strip() or "dev"
    except Exception:
        pass
    return "dev"


BUILD = _read_build()


def version_string() -> str:
    return f"{APP_VERSION} (Build {BUILD})"
