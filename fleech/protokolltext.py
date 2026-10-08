"""Was vom Diktat ins Protokoll darf: standardmaessig nur sein Umfang.

Bis 6.2 stand jedes Diktat im Volltext in `fleech.log` — erkannt, bereinigt,
eingefuegt, dazu jeder verworfene Schwanz und jede verworfene KI-Antwort. Das
Protokoll ist die Datei, die man zur Fehlersuche weitergibt, und sie war mit
60 MB die vollstaendigste Sammlung aller Diktate auf dem Rechner, unverschluesselt.

Seitdem geht jeder Text aus einem Diktat (und jeder Fenstertitel) durch
`inhalt()`. Ohne ausdrueckliche Freigabe steht dort nur „‹12 Wörter›".
Freigeben laesst es sich in Einstellungen → Erweitert, fuer die Fehlersuche;
der Schalter sagt dabei, was er tut, und der Start schreibt eine Warnzeile.
"""

from __future__ import annotations

_zeigen = False


def zeige_inhalte(an: bool) -> None:
    global _zeigen
    _zeigen = bool(an)


def zeigt_inhalte() -> bool:
    return _zeigen


def inhalt(text, laenge: int | None = None) -> str:
    """Text fuer eine Log-Zeile: freigegeben der Text (ggf. gekuerzt), sonst sein Umfang."""
    text = "" if text is None else str(text)
    if not text.strip():
        return "<leer>"
    if _zeigen:
        return text[:laenge] if laenge else text
    woerter = len(text.split())
    return f"‹{woerter} Wort›" if woerter == 1 else f"‹{woerter} Wörter›"
