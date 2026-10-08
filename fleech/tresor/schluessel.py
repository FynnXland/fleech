"""Der Hauptschluessel: einmal zufaellig erzeugt, vom System verwahrt (`ablage`).

Aus ihm leitet HKDF-SHA256 je Zweck einen eigenen Teilschluessel ab (Verlauf,
Gedaechtnis, Einstellungen). Kein Teilschluessel verraet den Hauptschluessel
oder einen anderen.

Der Wiederherstellungscode ist der Hauptschluessel selbst, lesbar geschrieben
(Base32, 11 Gruppen zu 5 Zeichen, mit Pruefsumme gegen Tippfehler). Er ist der
einzige Weg zurueck, wenn das Windows-Konto verloren geht oder Windows neu
installiert wird — DPAPI bindet den Schluessel genau an dieses Konto.

Wichtigste Regel: Ein NEUER Schluessel entsteht nur, wenn im Datenordner nichts
Verschluesseltes liegt. Sonst `SchluesselFehlt` — ein frischer Schluessel wuerde
die vorhandenen Daten nicht oeffnen, und der naechste Schreibvorgang mischte
zwei Schluessel in einem Ordner.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
from pathlib import Path

from ..platformpaths import user_data_dir
from . import ablage as _ablagen
from .datei import ist_umschlag
from .datenbank import ist_verschluesselt

log = logging.getLogger(__name__)

LAENGE = 32
# Tests biegen ihn um (conftest), genauso wie die Ablage.
DATENORDNER = user_data_dir()

_lock = threading.RLock()
_cache: bytes | None = None
_teile: dict[str, bytes] = {}
_neu_erzeugt = False


class SchluesselFehlt(Exception):
    """Es liegen verschluesselte Daten vor, aber kein passender Schluessel."""


def ablage():
    return _ablagen.aktuell(DATENORDNER)


def verschluesselte_daten_vorhanden(ordner: Path | None = None) -> bool:
    ordner = Path(ordner or DATENORDNER)
    if any(ist_verschluesselt(ordner / n) for n in ("history.db", "kontext.db")):
        return True
    for name in ("settings.json", "settings.json.bak"):
        try:
            with open(ordner / name, "rb") as f:
                if ist_umschlag(f.read(16)):
                    return True
        except OSError:
            continue
    return False


def hauptschluessel() -> bytes:
    global _cache, _neu_erzeugt
    with _lock:
        if _cache is not None:
            return _cache
        quelle = ablage()
        try:
            schluessel = quelle.lies()
        except Exception as exc:
            # Block da, aber nicht zu oeffnen (anderes Konto, beschaedigt): wie
            # fehlend behandeln, aber NICHT ueberschreiben — vielleicht hilft der Code.
            raise SchluesselFehlt("Datenschluessel nicht lesbar") from exc
        if schluessel is None:
            if verschluesselte_daten_vorhanden():
                raise SchluesselFehlt("Verschluesselte Daten ohne Schluessel")
            schluessel = secrets.token_bytes(LAENGE)
            quelle.speichere(schluessel)
            _neu_erzeugt = True
            log.info("Neuer Datenschluessel erzeugt — %s.", quelle.beschreibung())
        if len(schluessel) != LAENGE:
            raise SchluesselFehlt("Datenschluessel hat die falsche Laenge")
        _cache = schluessel
        return schluessel


def fehlt() -> bool:
    try:
        hauptschluessel()
        return False
    except SchluesselFehlt:
        return True


def frisch_erzeugt() -> bool:
    """Entstand der Schluessel in diesem Prozess (Erststart oder Umstellung)?"""
    return _neu_erzeugt


def ableiten(haupt: bytes, zweck: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"fleech/tresor/" + zweck.encode("utf-8")).derive(haupt)


def teilschluessel(zweck: str) -> bytes:
    with _lock:
        if zweck not in _teile:
            _teile[zweck] = ableiten(hauptschluessel(), zweck)
        return _teile[zweck]


def uebernimm(schluessel: bytes) -> None:
    """Schluessel aus dem Wiederherstellungscode in die Ablage legen und nutzen."""
    global _cache
    with _lock:
        ablage().speichere(schluessel)
        _cache = schluessel
        _teile.clear()
    log.info("Datenschluessel aus dem Wiederherstellungscode uebernommen.")


def vergiss() -> None:
    """Zwischenspeicher leeren (Tests; nach dem Beiseitelegen alter Daten)."""
    global _cache, _neu_erzeugt
    with _lock:
        _cache = None
        _teile.clear()
        _neu_erzeugt = False


# -- Wiederherstellungscode ----------------------------------------------------------

# Base32 kennt weder 0, 1 noch 8 — wer sie abtippt, meint O, I und B.
_VERWECHSLUNG = str.maketrans({"0": "O", "1": "I", "8": "B"})


def code_aus(schluessel: bytes) -> str:
    roh = schluessel + hashlib.sha256(schluessel).digest()[:2]
    zeichen = base64.b32encode(roh).decode("ascii").rstrip("=")
    return "-".join(zeichen[i:i + 5] for i in range(0, len(zeichen), 5))


def schluessel_aus(code: str) -> bytes:
    """Code → Schluessel. ValueError bei Tippfehler oder falscher Laenge."""
    zeichen = "".join(c for c in str(code or "").upper().translate(_VERWECHSLUNG)
                      if c.isalnum())
    try:
        roh = base64.b32decode(zeichen + "=" * (-len(zeichen) % 8))
    except Exception as exc:
        raise ValueError("Das ist kein gültiger Wiederherstellungscode.") from exc
    if len(roh) != LAENGE + 2:
        raise ValueError("Der Code ist zu kurz oder zu lang.")
    schluessel, pruef = roh[:LAENGE], roh[LAENGE:]
    if hashlib.sha256(schluessel).digest()[:2] != pruef:
        raise ValueError("Der Code enthält einen Tippfehler.")
    return schluessel


def passt_zu_daten(schluessel: bytes, ordner: Path | None = None) -> bool:
    """Oeffnet dieser Hauptschluessel die vorhandenen Daten?"""
    from .datei import Unlesbar, entschluessele
    from .datenbank import oeffnet_mit

    ordner = Path(ordner or DATENORDNER)
    for name, zweck in (("history.db", "verlauf"), ("kontext.db", "kontext")):
        if ist_verschluesselt(ordner / name):
            return oeffnet_mit(ordner / name, ableiten(schluessel, zweck))
    for name in ("settings.json", "settings.json.bak"):
        try:
            roh = (ordner / name).read_bytes()
        except OSError:
            continue
        if ist_umschlag(roh):
            try:
                entschluessele(roh, ableiten(schluessel, "einstellungen"), "einstellungen")
                return True
            except Unlesbar:
                return False
    return False
