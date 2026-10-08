"""Testhelfer: verschluesselte Dateien des Tresors lesen wie frueher den Klartext."""

from __future__ import annotations

import json
from pathlib import Path


def lies_text(pfad) -> str:
    """settings.json & Co. entschluesselt (Klartext geht unveraendert durch)."""
    from fleech import tresor

    return tresor.oeffne(Path(pfad).read_bytes(), tresor.EINSTELLUNGEN).decode("utf-8")


def lies_json(pfad):
    return json.loads(lies_text(pfad))


def verbinde(pfad, zweck: str = "kontext"):
    """SQLCipher-Verbindung zu einer Testdatenbank (statt sqlite3.connect)."""
    from fleech import tresor

    return tresor.verbinde(Path(pfad), zweck)
