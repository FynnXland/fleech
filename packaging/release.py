"""Release veroeffentlichen: EXE + Installer bauen, Pruefsumme bilden, GitHub-Release.

Aufruf (Windows, im Projektordner):

    .venv\\Scripts\\python packaging\\release.py            # baut und veroeffentlicht
    .venv\\Scripts\\python packaging\\release.py --dry-run  # baut nur, kein Upload

Der Ablauf entspricht dem, was der Update-Client in `fleech/ui/updates.py` erwartet:

1. `build.py` (EXE) und `build.py --installer` (Inno Setup) laufen lassen.
2. SHA-256 des Installers bilden — sie landet als Zeile `SHA256: <hex>` in den
   Release-Notizen. Der Client verweigert die Installation, wenn sie nicht passt.
3. Release `v<APP_VERSION>` anlegen und die Setup-Datei als Asset hochladen (`gh`).

Voraussetzungen: Inno Setup 6 (`winget install JRSoftware.InnoSetup`) und ein
angemeldetes `gh` (`gh auth status`). Beides wird vorab geprueft, damit der Fehler
nicht erst nach dem 10-minuetigen Build kommt.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fleech.version import APP_VERSION           # noqa: E402


def sha256(datei: Path) -> str:
    hasher = hashlib.sha256()
    with open(datei, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def pruefe_werkzeuge(dry_run: bool) -> list:
    """Fehlende Voraussetzungen NENNEN, bevor der lange Build laeuft."""
    fehlt = []
    sys.path.insert(0, str(ROOT / "packaging"))
    from build import find_iscc                  # noqa: E402

    if find_iscc() is None:
        fehlt.append("Inno Setup 6 fehlt — winget install JRSoftware.InnoSetup")
    if not dry_run:
        if shutil.which("gh") is None:
            fehlt.append("GitHub CLI fehlt — winget install GitHub.cli")
        else:
            if subprocess.run(["gh", "auth", "status"],
                              capture_output=True).returncode != 0:
                fehlt.append("gh ist nicht angemeldet — gh auth login")
    return fehlt


def notizen(hash_hex: str, datei: Path) -> str:
    mb = datei.stat().st_size / (1024 * 1024)
    return (
        f"Fleech {APP_VERSION}\n\n"
        f"Installation: `{datei.name}` herunterladen und ausführen (per-user, kein "
        f"Administrator nötig). Ein laufendes Fleech bitte vorher beenden.\n\n"
        f"Größe: {mb:.0f} MB\n"
        f"SHA256: {hash_hex}\n\n"
        f"Die App prüft diese Summe vor jeder Installation — stimmt sie nicht, wird "
        f"die Datei verworfen."
    )


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    fehlt = pruefe_werkzeuge(dry_run)
    if fehlt:
        print("[release] Abbruch — Voraussetzungen fehlen:")
        for zeile in fehlt:
            print("  •", zeile)
        return 1

    python = sys.executable
    for argumente in ([], ["--installer"]):
        cmd = [python, str(ROOT / "packaging" / "build.py"), *argumente]
        print("[release]", " ".join(cmd))
        if subprocess.run(cmd, cwd=ROOT).returncode != 0:
            print("[release] Build fehlgeschlagen.")
            return 1

    setup = ROOT / "dist" / f"FleechSetup-{APP_VERSION}.exe"
    if not setup.is_file():
        print(f"[release] {setup.name} nicht gefunden.")
        return 1
    hash_hex = sha256(setup)
    print(f"[release] {setup.name}  SHA256 {hash_hex}")

    if dry_run:
        print("[release] --dry-run: kein Upload. Notizen wären:\n")
        print(notizen(hash_hex, setup))
        return 0

    tag = f"v{APP_VERSION}"
    cmd = ["gh", "release", "create", tag, str(setup),
           "--title", f"Fleech {APP_VERSION}",
           "--notes", notizen(hash_hex, setup)]
    print("[release] gh release create", tag)
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        print("[release] Release-Erstellung fehlgeschlagen (Tag schon vorhanden?).")
        return 1
    print(f"[release] Fertig: {tag} veröffentlicht.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
