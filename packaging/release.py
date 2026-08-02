"""Release veroeffentlichen: EXE + Installer bauen, Pruefsumme bilden, GitHub-Release.

Aufruf (Windows, im Projektordner):

    .venv\\Scripts\\python packaging\\release.py            # baut und veroeffentlicht
    .venv\\Scripts\\python packaging\\release.py --dry-run  # baut nur, kein Upload

Der Ablauf entspricht dem, was der Update-Client in `fleech/ui/updates.py` erwartet:

1. `build.py` (EXE) und `build.py --installer` (Inno Setup) laufen lassen.
2. SHA-256 des Installers bilden — sie landet als Zeile `SHA256: <hex>` in den
   Release-Notizen. Der Client verweigert die Installation, wenn sie nicht passt.
3. Release `v<APP_VERSION>` im OEFFENTLICHEN Releases-Repository anlegen und die
   Setup-Datei als Asset hochladen (`gh`).

Zwei Repositories, mit Absicht: der Quellcode (`FynnXland/fleech`) bleibt privat,
die Installationsdateien liegen in `FynnXland/fleech-releases`. Nur so kommt die
Update-Pruefung ohne Zugriffstoken aus — und ein Token in einer ausgelieferten EXE
waere ohnehin auslesbar. Wer Fleech benutzen darf, entscheidet stattdessen der
Lizenzschluessel (`fleech/licensing.py`, ausgestellt mit `packaging/issue_key.py`).

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

from fleech.ui.updates import GITHUB_REPO as RELEASE_REPO   # noqa: E402
from fleech.version import APP_VERSION                      # noqa: E402


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


def changelog_abschnitt(version: str = APP_VERSION) -> str:
    """Den Abschnitt dieser Version aus CHANGELOG.md holen (ohne Ueberschrift).

    Damit steht im GitHub-Release das, was der Empfaenger wissen will, statt nur
    Dateigroesse und Pruefsumme. Der Changelog ist die eine Quelle — eine zweite
    Liste in den Release-Notizen zu pflegen hiesse, dass sie irgendwann abweicht.

    Leer, wenn es keinen Eintrag gibt: Ein Release ohne Notizen ist unschoen, aber
    besser als eines, das den Text der Vorversion behauptet.
    """
    datei = ROOT / "CHANGELOG.md"
    if not datei.is_file():
        return ""
    zeilen = datei.read_text(encoding="utf-8").splitlines()
    start = None
    for i, zeile in enumerate(zeilen):
        if zeile.startswith("## ") and zeile[3:].strip().startswith(version):
            start = i + 1
            break
    if start is None:
        return ""
    ende = start
    while ende < len(zeilen) and not zeilen[ende].startswith("## "):
        ende += 1
    # Der Trenner „---" gehoert zum Seitenaufbau, nicht zum Abschnitt.
    text = "\n".join(zeilen[start:ende]).strip()
    return text.removesuffix("---").strip()


def notizen(hash_hex: str, datei: Path) -> str:
    mb = datei.stat().st_size / (1024 * 1024)
    was_neu = changelog_abschnitt()
    kopf = f"Fleech {APP_VERSION}\n\n"
    if was_neu:
        kopf += f"{was_neu}\n\n---\n\n"
    return (
        f"{kopf}"
        f"Installation: `{datei.name}` herunterladen und ausführen (per-user, kein "
        f"Administrator nötig). Ein laufendes Fleech bitte vorher beenden.\n\n"
        f"Größe: {mb:.0f} MB\n"
        f"SHA256: {hash_hex}\n\n"
        f"Die App prüft diese Summe vor jeder Installation — stimmt sie nicht, wird "
        f"die Datei verworfen."
    )


def ist_patch_version() -> bool:
    """Dritte Stelle > 0 = Kleinigkeit (4.3.1, 4.3.2 …).

    Fuer die wird bewusst NICHT veroeffentlicht: Installer bauen und 1 GB
    hochladen dauert rund zehn Minuten — so lange wie die Aenderung selbst. Ein
    Release lohnt sich erst, wenn genug zusammengekommen ist (neue Minor- oder
    Major-Version). Wer es doch braucht: --force.
    """
    teile = APP_VERSION.split(".")
    return len(teile) > 2 and teile[2].isdigit() and int(teile[2]) > 0


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if ist_patch_version() and "--force" not in sys.argv and not dry_run:
        print(f"[release] {APP_VERSION} ist eine Patch-Version — kein Release.")
        print("[release] Kleinigkeiten sammeln und mit der naechsten Minor-Version")
        print("[release] veroeffentlichen (oder --force, wenn es wirklich raus muss).")
        return 0
    fehlt = pruefe_werkzeuge(dry_run)
    if fehlt:
        print("[release] Abbruch — Voraussetzungen fehlen:")
        for zeile in fehlt:
            print("  •", zeile)
        return 1

    python = sys.executable
    # --no-build: nutzt die vorhandene Setup-Datei. Fuer den zweiten Versuch, wenn
    # nur der Upload gescheitert ist — ein 2-GB-Build dafuer erneut zu fahren waere
    # eine Viertelstunde fuer nichts.
    if "--no-build" not in sys.argv:
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
    # Veroeffentlicht wird ins RELEASES-Repository, nicht ins Quellcode-Repository:
    # dort liegen nur die Setup-Dateien, deshalb darf es oeffentlich sein und die
    # Update-Pruefung braucht keinen Zugriffstoken.
    cmd = ["gh", "release", "create", tag, str(setup),
           "--repo", RELEASE_REPO,
           "--title", f"Fleech {APP_VERSION}",
           "--notes", notizen(hash_hex, setup)]
    # Bewusst ohne Sonderzeichen: die Windows-Konsole faehrt cp1252, ein Pfeil
    # wuerde den Lauf mit UnicodeEncodeError abbrechen (real passiert).
    print(f"[release] gh release create {tag} in {RELEASE_REPO}")
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        print("[release] Release-Erstellung fehlgeschlagen (Tag schon vorhanden?).")
        return 1
    print(f"[release] Fertig: {tag} veröffentlicht.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
