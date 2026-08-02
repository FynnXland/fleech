"""Lizenzschluessel ausstellen — laeuft NUR beim Herausgeber.

    python packaging/issue_key.py --init                 # einmalig: Schluesselpaar
    python packaging/issue_key.py "Max Mustermann"       # unbefristeter Schluessel
    python packaging/issue_key.py "Max" --days 365       # befristet
    python packaging/issue_key.py --frage                # fragt nach Namen (Dialog)
    python packaging/issue_key.py --show-public          # oeffentlichen Teil zeigen

Im Alltag reicht ein Doppelklick auf „Schluessel erstellen.bat" im Projektordner —
die ruft `--frage` und legt den fertigen Schluessel in die Zwischenablage.

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

import shutil
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


def _frage_interaktiv() -> int:
    """Dialog-Modus fuer „Schluessel erstellen.bat" — Name eintippen, fertig.

    Der Schluessel landet zusaetzlich in der Zwischenablage: Wer ihn aus einem
    Konsolenfenster mit der Maus markiert, erwischt schnell ein Zeichen zu wenig,
    und ein halber Schluessel scheitert beim Empfaenger ohne erkennbaren Grund.
    """
    print("=" * 68)
    print("  Fleech — Lizenzschluessel ausstellen")
    print("=" * 68)
    print()
    name = input("  Name der Person (z. B. Max Mustermann): ").strip()
    if not name:
        print("\n  Kein Name eingegeben — abgebrochen.")
        return 1
    roh = input("  Gueltig fuer wie viele Tage? (Enter = unbefristet): ").strip()
    tage = 0
    if roh:
        if not roh.isdigit() or int(roh) <= 0:
            print(f"\n  '{roh}' ist keine Anzahl Tage — abgebrochen.")
            return 1
        tage = int(roh)

    privat = _laden()
    if privat is None:
        print(f"\n  Kein privater Signaturschluessel unter:\n    {KEY_PATH}")
        print("  Ohne ihn lassen sich keine Schluessel ausstellen.")
        return 1

    ablauf = (date.today() + timedelta(days=tage)).isoformat() if tage else ""
    schluessel = sign_payload(privat, name, expires=ablauf)
    probe = verify(schluessel, PUBLIC_KEY_HEX)

    print()
    print("-" * 68)
    print(f"  Lizenz fuer : {name}")
    print(f"  Gueltigkeit : {'bis ' + ablauf if ablauf else 'unbefristet'}")
    print(f"  Gegenprobe  : {'gueltig' if probe.ok else 'FEHLGESCHLAGEN — ' + probe.reason}")
    print("-" * 68)
    print()
    print(schluessel)
    print()
    if not probe.ok:
        print("  NICHT verschicken. Passt PUBLIC_KEY_HEX in fleech/licensing.py")
        print("  zum privaten Schluessel?")
        return 1
    if _in_zwischenablage(schluessel):
        print("  -> Der Schluessel liegt in der Zwischenablage (Strg+V zum Einfuegen).")
    print("  Zusammen mit diesem Link verschicken:")
    print("    https://github.com/FynnXland/fleech-releases/releases/latest")
    return 0


def _in_zwischenablage(text: str) -> bool:
    import subprocess

    try:
        # `clip` liegt auf jedem Windows; unter Linux xclip, sonst still lassen.
        if sys.platform == "win32":
            befehl = ["clip"]
        elif shutil.which("xclip"):
            befehl = ["xclip", "-selection", "clipboard"]
        else:
            return False
        subprocess.run(befehl, input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--init" in args:
        return _erzeugen()
    if "--frage" in args:
        return _frage_interaktiv()
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
