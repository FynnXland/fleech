"""Wo der Hauptschluessel liegt — die eine plattformabhaengige Stelle des Tresors.

Windows: DPAPI (`CryptProtectData`, Benutzerbereich). Der Schluessel liegt als
geschuetzter Block in `schluessel.dpapi` neben den Daten. Oeffnen kann ihn nur
dasselbe Windows-Konto auf demselben Rechner: Wer den Ordner kopiert, die Platte
ausbaut oder sich als anderer Benutzer anmeldet, haelt einen Block in der Hand,
mit dem er nichts anfangen kann. Bewusst eine Datei und nicht die
Anmeldeinformationsverwaltung (wie bei den API-Schluesseln): Deren Eintraege
wandern in Domaenen mit servergespeichertem Profil auf andere Rechner mit, und
der Schluessel soll genau hier bleiben.

Linux: Secret Service ueber `keyring` (KWallet/GNOME-Schluesselbund). Fehlt der,
bleibt nur eine Datei mit Rechten 0600 — das schuetzt gegen andere Konten, nicht
gegen eine ausgebaute Platte. `beschreibung()` sagt das offen, die Einstellungen
zeigen es an.

Kein Aufrufer kennt `sys.platform`: Alles ausser `aktuell()` ist Innenleben.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DATEINAME_DPAPI = "schluessel.dpapi"
DATEINAME_ROH = "schluessel.roh"   # nur Linux ohne Schluesselbund
DIENST = "Fleech"
KONTO = "datenschluessel"

# Zusaetzliche Entropie fuer DPAPI: Ein anderes Programm desselben Kontos, das den
# Block findet, kann ihn ohne diesen Wert nicht mit einem blanken
# `CryptUnprotectData` oeffnen. Kein Geheimnis (steht im Quelltext), aber eine
# Huerde gegen generische Werkzeuge, die DPAPI-Bloecke reihenweise aufmachen.
_ENTROPIE = b"Fleech-Datenschluessel-v1"


def _schreibe_atomar(pfad: Path, daten: bytes) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(daten)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, pfad)


class DpapiAblage:
    """Windows: DPAPI-geschuetzter Block in einer Datei neben den Daten."""

    def __init__(self, ordner: Path):
        self.pfad = Path(ordner) / DATEINAME_DPAPI

    def beschreibung(self) -> str:
        return "an dein Windows-Konto gebunden (DPAPI)"

    def lies(self) -> bytes | None:
        if not self.pfad.is_file():
            return None
        return _dpapi(self.pfad.read_bytes(), schuetzen=False)

    def speichere(self, schluessel: bytes) -> None:
        _schreibe_atomar(self.pfad, _dpapi(schluessel, schuetzen=True))


class SchluesselbundAblage:
    """Linux: Secret Service; ohne ihn eine Datei mit Rechten 0600."""

    def __init__(self, ordner: Path):
        self.datei = Path(ordner) / DATEINAME_ROH

    @staticmethod
    def _bund():
        try:
            import keyring
            from keyring.backends import fail

            if isinstance(keyring.get_keyring(), fail.Keyring):
                return None
            return keyring
        except Exception:
            log.debug("keyring nicht verfuegbar.", exc_info=True)
            return None

    def beschreibung(self) -> str:
        if self._bund() is not None:
            return "im Schlüsselbund deines Benutzerkontos abgelegt"
        return "in einer Datei nur für dein Konto abgelegt (kein Schlüsselbund gefunden)"

    def lies(self) -> bytes | None:
        bund = self._bund()
        if bund is not None:
            wert = bund.get_password(DIENST, KONTO)
            if wert:
                return bytes.fromhex(wert)
        if self.datei.is_file():
            return bytes.fromhex(self.datei.read_text(encoding="ascii").strip())
        return None

    def speichere(self, schluessel: bytes) -> None:
        bund = self._bund()
        if bund is not None:
            bund.set_password(DIENST, KONTO, schluessel.hex())
            return
        log.warning("Kein Schluesselbund erreichbar — Datenschluessel liegt in %s "
                    "(nur fuer dieses Konto lesbar).", self.datei.name)
        _schreibe_atomar(self.datei, schluessel.hex().encode("ascii"))
        os.chmod(self.datei, 0o600)


def aktuell(ordner: Path):
    """Die Ablage dieser Plattform fuer den Datenordner `ordner`."""
    if sys.platform == "win32":
        return DpapiAblage(ordner)
    return SchluesselbundAblage(ordner)


# -- DPAPI ueber ctypes ----------------------------------------------------------------


def _dpapi(daten: bytes, schuetzen: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(roh: bytes):
        puffer = ctypes.create_string_buffer(roh, len(roh))
        return _Blob(len(roh), ctypes.cast(puffer, ctypes.POINTER(ctypes.c_char))), puffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    signatur = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.POINTER(_Blob),
                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    for fn in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
        fn.argtypes = signatur
        fn.restype = wintypes.BOOL

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ein, _halt1 = blob(daten)
    entropie, _halt2 = blob(_ENTROPIE)
    aus = _Blob()
    if schuetzen:
        ok = crypt32.CryptProtectData(ctypes.byref(ein), "Fleech", ctypes.byref(entropie),
                                      None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                      ctypes.byref(aus))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(ein), None, ctypes.byref(entropie),
                                        None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                        ctypes.byref(aus))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI-Aufruf fehlgeschlagen")
    try:
        return ctypes.string_at(aus.pbData, aus.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(aus.pbData, ctypes.c_void_p))
