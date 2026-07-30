"""Lizenzschluessel ausstellen — laeuft NUR beim Herausgeber.

    python packaging/issue_key.py --init                 # einmalig: Schluesselpaar
    python packaging/issue_key.py "Max Mustermann"       # unbefristeter Schluessel
    python packaging/issue_key.py "Max" --days 365       # befristet
    python packaging/issue_key.py --show-public          # oeffentlichen Teil zeigen

Der PRIVATE Schluessel liegt bewusst AUSSERHALB des Projektordners:

    %APPDATA%\\Fleech\\signing\\fleech-signing-key.pem   (Windows)
    ~/.config/Fleech/signing/fleech-signing-key.pem      (Linux)

Damit kann er weder versehentlich committet noch mitgepackt werden. Geht er
verloren, lassen sich keine neuen Schluessel mehr ausstellen — dann ein neues Paar
erzeugen, `PUBLIC_KEY_HEX` in `fleech/licensing.py` ersetzen und alle Schluessel
neu ausgeben. Wird er KOPIERT, kann der Empfaenger beliebige Schluessel ausstellen:
diese eine Datei ist das ganze Geheimnis.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fleech.licensing import PUBLIC_KEY_HEX, sign_payload, verify   # noqa: E402
from fleech.platformpaths import user_data_dir                       # noqa: E402

KEY_PATH = user_data_dir() / "signing" / "fleech-signing-key.pem"


def _laden():
    from cryptography.hazmat.primitives import serialization

    if not KEY_PATH.is_file():
        return None
    return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)


def _erzeugen():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if KEY_PATH.is_file():
        print(f"[key] Es gibt bereits ein Schluesselpaar: {KEY_PATH}")
        print("[key] Ein neues wuerde ALLE ausgestellten Schluessel entwerten.")
        return 1
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    privat = Ed25519PrivateKey.generate()
    KEY_PATH.write_bytes(privat.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:                      # unter Windows wirkungslos, unter Linux sinnvoll
        KEY_PATH.chmod(0o600)
    except OSError:
        pass
    oeffentlich = privat.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    print(f"[key] Privater Schluessel angelegt: {KEY_PATH}")
    print("[key] Diese Datei NIE weitergeben und nie ins Repository legen.")
    print(f"[key] Oeffentlicher Schluessel (gehoert in fleech/licensing.py):\n{oeffentlich}")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--init" in args:
        return _erzeugen()
    if "--show-public" in args:
        privat = _laden()
        if privat is None:
            print(f"[key] Kein privater Schluessel unter {KEY_PATH} — erst --init.")
            return 1
        from cryptography.hazmat.primitives import serialization

        print(privat.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex())
        return 0

    tage = 0
    if "--days" in args:
        i = args.index("--days")
        tage = int(args[i + 1])
        del args[i:i + 2]
    namen = [a for a in args if not a.startswith("--")]
    if not namen:
        print(__doc__)
        return 1

    privat = _laden()
    if privat is None:
        print(f"[key] Kein privater Schluessel unter {KEY_PATH} — erst --init.")
        return 1

    ablauf = (date.today() + timedelta(days=tage)).isoformat() if tage else ""
    schluessel = sign_payload(privat, namen[0], expires=ablauf)

    # Gegenprobe mit genau dem Code, der spaeter in der App laeuft: ein Schluessel,
    # der hier durchfaellt, wuerde beim Empfaenger scheitern — das will man VOR dem
    # Verschicken wissen, nicht danach.
    probe = verify(schluessel, PUBLIC_KEY_HEX)
    print(f"\nLizenz für: {namen[0]}"
          + (f"   gültig bis {ablauf}" if ablauf else "   unbefristet"))
    print(f"Gegenprobe: {'gültig' if probe.ok else 'FEHLGESCHLAGEN — ' + probe.reason}")
    print("\n" + schluessel + "\n")
    if not probe.ok:
        print("[key] Passt PUBLIC_KEY_HEX in fleech/licensing.py zum privaten Schluessel?")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
