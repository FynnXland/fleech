"""Umschlag fuer einzelne Dateien: AES-256-GCM.

Aufbau: `MAGIC` (8 Byte: Kennung + Formatversion) · Nonce (12 Byte, zufaellig) ·
Geheimtext mit 16-Byte-Tag. GCM verschluesselt UND beglaubigt: Eine veraenderte,
abgeschnittene oder mit falschem Schluessel gelesene Datei faellt beim Oeffnen
auf (`Unlesbar`), statt still Unsinn zu liefern.

Der Zweck ("einstellungen" …) geht als zusaetzlich beglaubigte Daten mit ein.
Damit laesst sich ein Umschlag nicht unbemerkt an die Stelle eines anderen
setzen, selbst wenn beide mit Teilschluesseln desselben Hauptschluessels
entstanden sind.

Reine Kryptografie: kein Pfad, kein Schluesselabruf — das macht die Fassade.
"""

from __future__ import annotations

import os

MAGIC = b"FLEECH\x00\x01"
_NONCE = 12


class Unlesbar(Exception):
    """Umschlag kaputt, manipuliert oder mit anderem Schluessel verschlossen."""


def ist_umschlag(roh: bytes) -> bool:
    return roh[:len(MAGIC)] == MAGIC


def verschluessele(daten: bytes, schluessel: bytes, zweck: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(_NONCE)
    geheim = AESGCM(schluessel).encrypt(nonce, daten, MAGIC + zweck.encode("utf-8"))
    return MAGIC + nonce + geheim


def entschluessele(roh: bytes, schluessel: bytes, zweck: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not ist_umschlag(roh) or len(roh) < len(MAGIC) + _NONCE + 16:
        raise Unlesbar("kein Fleech-Umschlag")
    nonce = roh[len(MAGIC):len(MAGIC) + _NONCE]
    try:
        return AESGCM(schluessel).decrypt(nonce, roh[len(MAGIC) + _NONCE:],
                                          MAGIC + zweck.encode("utf-8"))
    except InvalidTag as exc:
        raise Unlesbar("Pruefsumme stimmt nicht") from exc
