"""Lizenzschluessel: signiert, offline pruefbar, ohne Geheimnis in der Anwendung.

Das Problem: Die Installationsdatei wandert weiter. Wer sie bekommt, soll Fleech
nicht einfach benutzen koennen — aber es gibt keinen Server, den man fragen koennte,
und Fleech soll auch ohne Internet laufen.

Die Loesung ist eine Signatur, kein Passwort. Der Herausgeber (Fynn) hat einen
PRIVATEN Schluessel, der nie ausgeliefert wird. Fleech kennt nur den zugehoerigen
OEFFENTLICHEN Schluessel — der darf in der EXE stehen, denn mit ihm kann man
Signaturen ausschliesslich PRUEFEN, niemals erzeugen. Ein embedded Zugriffstoken
waere das Gegenteil: auslesbar und damit sofort missbrauchbar.

    Schluessel ausstellen:  packaging/issue_key.py  (braucht den privaten Schluessel)
    Schluessel pruefen:     hier, rein rechnerisch, ohne Netz

Format:  FLEECH-1.<nutzdaten>.<signatur>       (beides base64url ohne Polster)
Nutzdaten (JSON, kompakt):  {"n": Name, "i": Ausstellungsdatum, "e": Ablauf oder ""}

EHRLICHE GRENZE: Das haelt niemanden auf, der die EXE zerlegt und die Pruefung
herauspatcht — das kann keine lokale Pruefung, unabhaengig vom Verfahren. Es
verhindert das, worum es geht: dass eine weitergereichte Datei bei irgendwem
einfach laeuft. Wer sie ohne Schluessel bekommt, kann sie nicht benutzen.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import date

log = logging.getLogger(__name__)

PREFIX = "FLEECH-1."

# Oeffentlicher Ed25519-Schluessel des Herausgebers (32 Bytes, hex). Unbedenklich
# im Klartext: damit laesst sich pruefen, nicht unterschreiben. Der private Teil
# liegt NUR beim Herausgeber (siehe packaging/issue_key.py) und wird nie verteilt.
PUBLIC_KEY_HEX = "74566f79eb86868e670ce33436f1584fd8b78bf1b690801b8c29a329c77e9aa2"


@dataclass
class LicenseState:
    """Ergebnis der Pruefung. `ok` ist das Einzige, was ueber Benutzen entscheidet."""

    ok: bool
    name: str = ""
    expires: str = ""
    reason: str = ""          # Klartext, wenn nicht ok

    @property
    def unlimited(self) -> bool:
        return self.ok and not self.expires


def _b64d(text: str) -> bytes:
    polster = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + polster)


def _b64e(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).decode("ascii").rstrip("=")


def normalize(key: str) -> str:
    """Tippfehler-Toleranz: Leerzeichen und Zeilenumbrueche raus.

    Der Schluessel wird per Mail/Chat weitergegeben und dabei oft umgebrochen —
    ein Zeilenumbruch darf keine abgelehnte Lizenz bedeuten.
    """
    return "".join((key or "").split())


def sign_payload(private_key, name: str, expires: str = "",
                 issued: str = "") -> str:
    """Schluessel ausstellen. Nur der Herausgeber ruft das auf (issue_key.py)."""
    nutzdaten = {"n": name, "i": issued or date.today().isoformat(), "e": expires or ""}
    roh = json.dumps(nutzdaten, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signatur = private_key.sign(roh)
    return f"{PREFIX}{_b64e(roh)}.{_b64e(signatur)}"


def verify(key: str, public_key_hex: str = "", heute: date | None = None) -> LicenseState:
    """Schluessel pruefen — rein rechnerisch, kein Netz, keine Datei.

    Jeder Fehlerfall endet mit `ok=False` und einem Satz, der dem Nutzer sagt, was
    zu tun ist. Keine Ausnahme verlaesst diese Funktion: eine kaputte Zwischenablage
    darf nicht als Absturz enden.
    """
    text = normalize(key)
    if not text:
        return LicenseState(False, reason="Kein Lizenzschlüssel eingetragen.")
    if not text.startswith(PREFIX):
        return LicenseState(False, reason="Das sieht nicht nach einem Fleech-Schlüssel aus.")

    hex_key = public_key_hex or PUBLIC_KEY_HEX
    if not hex_key or hex_key == "__PLATZHALTER__":
        # Entwicklungsbaum ohne hinterlegten Schluessel: nicht sperren, aber laut sein.
        log.warning("Kein oeffentlicher Lizenzschluessel hinterlegt — Pruefung uebersprungen.")
        return LicenseState(True, name="Entwicklung")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        rest = text[len(PREFIX):]
        teil_daten, _, teil_sig = rest.partition(".")
        if not teil_daten or not teil_sig:
            return LicenseState(False, reason="Der Schlüssel ist unvollständig.")
        roh = _b64d(teil_daten)
        signatur = _b64d(teil_sig)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key)).verify(signatur, roh)
    except InvalidSignature:
        return LicenseState(False, reason="Der Schlüssel ist ungültig (Signatur passt nicht).")
    except Exception as exc:
        log.debug("Lizenzpruefung fehlgeschlagen: %s", exc)
        return LicenseState(False, reason="Der Schlüssel konnte nicht gelesen werden.")

    try:
        nutzdaten = json.loads(roh.decode("utf-8"))
    except Exception:
        return LicenseState(False, reason="Der Schlüssel konnte nicht gelesen werden.")

    name = str(nutzdaten.get("n") or "")
    ablauf = str(nutzdaten.get("e") or "")
    if ablauf:
        try:
            if (heute or date.today()) > date.fromisoformat(ablauf):
                return LicenseState(False, name=name, expires=ablauf,
                                    reason=f"Der Schlüssel ist am {ablauf} abgelaufen.")
        except ValueError:
            return LicenseState(False, reason="Der Schlüssel hat ein unlesbares Ablaufdatum.")
    return LicenseState(True, name=name, expires=ablauf)


def check(settings, heute: date | None = None) -> LicenseState:
    """Pruefung gegen die gespeicherte Lizenz der Installation."""
    return verify(getattr(getattr(settings, "general", None), "license_key", ""),
                  heute=heute)
