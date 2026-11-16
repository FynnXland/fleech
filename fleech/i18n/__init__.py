"""Sprache der Oberfläche (seit 6.6.0): Deutsch als Quelltext, Englisch als Katalog.

Jeder sichtbare Text steht weiter auf Deutsch im Code und geht durch `tr()`. Der
deutsche Text ist zugleich der Schlüssel: `fleech/i18n/en/*.json` ordnet ihm die
englische Fassung zu. Fehlt ein Eintrag, bleibt der deutsche Text stehen — besser
ein deutsches Wort in einer englischen Oberfläche als ein leeres Feld.
`tests/test_i18n.py` wacht darüber, dass kein Eintrag fehlt.

Regeln für den Code:

- `tr()` erst beim Anzeigen aufrufen, nie auf Modulebene. Die Sprache steht erst
  fest, wenn die Einstellungen geladen sind — da sind die Module längst importiert.
- Texte, die als Konstante auf Modulebene stehen, mit `N_()` markieren (ändert
  nichts, macht sie für die Prüfung sichtbar) und beim Anzeigen `tr(konstante)`.
- Platzhalter statt f-Strings: `tr("Noch {n} Minuten", n=rest)`. Die Übersetzung
  braucht den ganzen Satz, die Wortstellung ist im Englischen eine andere.
- Logmeldungen und Prompts für das Sprachmodell gehen NICHT durch `tr()` — sie
  sind keine Oberfläche.

Die Sprache wechselt beim Neustart (Einstellungen → Allgemein bietet ihn an):
Fenster, Tray und Pille bauen ihre Texte einmal auf, ein Umschalten zur Laufzeit
hieße jedes Widget neu beschriften.
"""

from __future__ import annotations

import json
import locale
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SPRACHEN = ("de", "en")
QUELLSPRACHE = "de"

_aktuell = QUELLSPRACHE
_katalog: dict[str, str] = {}


def katalog_dir(sprache: str) -> Path:
    if getattr(sys, "frozen", False):
        basis = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "fleech" / "i18n"
    else:
        basis = Path(__file__).resolve().parent
    return basis / sprache


def lade_katalog(sprache: str) -> dict[str, str]:
    """Alle `<sprache>/*.json` zusammengeführt (eine Datei je Bereich der App)."""
    katalog: dict[str, str] = {}
    ordner = katalog_dir(sprache)
    if not ordner.is_dir():
        return katalog
    for datei in sorted(ordner.glob("*.json")):
        try:
            daten = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Sprachkatalog %s nicht lesbar — übersprungen.", datei.name)
            continue
        katalog.update({k: v for k, v in daten.items() if isinstance(v, str) and v})
    return katalog


def systemsprache() -> str:
    """Sprache des Betriebssystems, auf die unterstützten abgebildet: Deutsch
    bleibt Deutsch, alles andere wird Englisch (die verbreitetere Zweitsprache)."""
    code = ""
    if sys.platform == "win32":
        try:
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code = locale.windows_locale.get(lcid, "")
        except Exception:
            code = ""
    if not code:
        try:
            code = locale.getlocale()[0] or ""
        except Exception:
            code = ""
        if not code:
            import os

            code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "")
    code = code.lower()
    if not code:
        return QUELLSPRACHE
    return "de" if code.startswith(("de", "german")) else "en"


def aufloesen(wahl: str) -> str:
    """Einstellungswert („auto“, „de“, „en“) → tatsächliche Sprache."""
    if wahl in SPRACHEN:
        return wahl
    return systemsprache()


def setze(wahl: str) -> str:
    """Oberflächensprache festlegen. Gibt die tatsächlich gewählte zurück."""
    global _aktuell, _katalog
    sprache = aufloesen(wahl)
    _katalog = {} if sprache == QUELLSPRACHE else lade_katalog(sprache)
    _aktuell = sprache
    return sprache


def aktuell() -> str:
    return _aktuell


def tr(text: str, **werte) -> str:
    """Sichtbaren Text in der Oberflächensprache. `werte` füllen `{platzhalter}`."""
    if _aktuell != QUELLSPRACHE:
        text = _katalog.get(text, text)
    return text.format(**werte) if werte else text


def N_(text: str) -> str:
    """Markiert einen Text als übersetzbar, ohne ihn zu übersetzen (Konstanten)."""
    return text


def dezimal(wert: float, stellen: int = 1) -> str:
    """Zahl mit Nachkommastellen im Format der Oberfläche (1,5 / 1.5)."""
    text = f"{wert:.{stellen}f}"
    return text.replace(".", ",") if _aktuell == "de" else text
