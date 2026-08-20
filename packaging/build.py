"""Reproduzierbarer Build: Icons → Build-Stamp → EXE-Metadaten → PyInstaller.

Aufruf:
    .venv\\Scripts\\python packaging/build.py             # nutzt die zuletzt gewaehlte
                                                          # GPU/CPU-Praeferenz (Default CPU)
    .venv\\Scripts\\python packaging/build.py --gpu        # GPU-Build, PERSISTIERT die Wahl
    .venv\\Scripts\\python packaging/build.py --cpu        # CPU-Build, persistiert ebenso
    .venv\\Scripts\\python packaging/build.py --gpu --installer

Die GPU/CPU-Wahl wird in packaging/build.local.json gespeichert — kein
"$env:FLEECH_GPU jedes Mal neu setzen" noetig; einmal --gpu reicht, jeder
spaetere Build (auch ohne Flag) bleibt dabei. FLEECH_GPU als Env-Var wird
weiterhin als zusaetzlicher Override unterstuetzt (z. B. fuer CI).

Ergebnis: dist/Fleech/Fleech.exe (onedir, kein Konsolenfenster).

Linux (venv z. B. ~/.venvs/fleech):
    python packaging/build.py                # dist/Fleech/Fleech (onedir)
    python packaging/build.py --gpu
    python packaging/build.py --install      # Sync nach ~/.local/opt/Fleech
                                             # + fleech.desktop + Icon (Startmenue)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fleech.version import APP_VERSION  # noqa: E402

BUILD_LOCAL_CONFIG = ROOT / "packaging" / "build.local.json"


def read_gpu_preference() -> bool:
    if BUILD_LOCAL_CONFIG.is_file():
        try:
            return bool(json.loads(BUILD_LOCAL_CONFIG.read_text(encoding="utf-8")).get("gpu", False))
        except Exception:
            pass
    return False


def write_gpu_preference(value: bool) -> None:
    BUILD_LOCAL_CONFIG.write_text(json.dumps({"gpu": value}, indent=2), encoding="utf-8")
    print(f"[build] GPU-Praeferenz gespeichert: {value} ({BUILD_LOCAL_CONFIG})")


def resolve_gpu_flag(argv: list[str]) -> bool:
    """Prioritaet: --gpu/--cpu (persistiert) > FLEECH_GPU-Env > zuletzt gespeicherter Wert."""
    if "--gpu" in argv:
        write_gpu_preference(True)
        return True
    if "--cpu" in argv:
        write_gpu_preference(False)
        return False
    if os.environ.get("FLEECH_GPU"):
        return True
    return read_gpu_preference()


def write_build_stamp() -> str:
    stamp = _dt.datetime.now().strftime("%Y%m%d")
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        stamp = f"{stamp}.{commit}"
    except Exception:
        pass
    (ROOT / "build.txt").write_text(stamp, encoding="utf-8")
    print(f"[build] Build-Stamp: {stamp}")
    return stamp


def write_version_info() -> None:
    parts = (APP_VERSION.split(".") + ["0", "0", "0", "0"])[:4]
    v = ", ".join(parts)
    content = f"""# Auto-generiert von packaging/build.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}), prodvers=({v}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040704b0', [
      StringStruct('CompanyName', 'Fleech'),
      StringStruct('FileDescription', 'Fleech — Diktat-App'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', 'Fleech'),
      StringStruct('OriginalFilename', 'Fleech.exe'),
      StringStruct('ProductName', 'Fleech'),
      StringStruct('ProductVersion', '{APP_VERSION}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ]
)
"""
    (ROOT / "packaging" / "version_info.txt").write_text(content, encoding="utf-8")
    print(f"[build] EXE-Metadaten: Version {APP_VERSION}")


_ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def find_iscc() -> Path | None:
    for p in _ISCC_CANDIDATES:
        if p.is_file():
            return p
    return None


def build_installer() -> int:
    iscc = find_iscc()
    if iscc is None:
        print("[installer] ISCC.exe nicht gefunden — Inno Setup 6 installieren "
              "(winget install JRSoftware.InnoSetup).")
        return 1
    cmd = [str(iscc), f"/DAppVersion={APP_VERSION}", str(ROOT / "packaging" / "fleech.iss")]
    print("[installer] ISCC:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)
    setup = ROOT / "dist" / f"FleechSetup-{APP_VERSION}.exe"
    print(f"[installer] Fertig: {setup}  (existiert: {setup.is_file()})")
    return 0 if setup.is_file() else 1


def _desktop_entry(exec_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Fleech\n"
        "Comment=Lokale Diktat-App\n"
        f"Exec=\"{exec_path}\" --gui\n"
        "Icon=fleech\n"
        "Terminal=false\n"
        "Categories=Utility;Accessibility;\n"
        "StartupNotify=false\n"
    )


def install_linux() -> int:
    """Robocopy-Aequivalent: dist/Fleech → ~/.local/opt/Fleech + Menue-Eintrag.

    Wie unter Windows gilt: eine laufende Fleech-Instanz vorher beenden, sonst
    ersetzt der Sync Binaries unter einem laufenden Prozess (unter Linux kein
    Kopierfehler, aber ein inkonsistenter Prozess-Zustand).
    """
    import shutil

    home = Path.home()
    src = ROOT / "dist" / "linux" / "Fleech"
    target = home / ".local" / "opt" / "Fleech"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)

    icon_src = ROOT / "assets" / "logo_256.png"
    icon_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_src, icon_dir / "fleech.png")

    apps_dir = home / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop = apps_dir / "fleech.desktop"
    desktop.write_text(_desktop_entry(target / "Fleech"), encoding="utf-8")

    print(f"[install] App:     {target}")
    print(f"[install] Menue:   {desktop}")
    print(f"[install] Icon:    {icon_dir / 'fleech.png'}")
    return 0


def sichere_einstellungen() -> None:
    """Die eigenen Einstellungen wegsichern, bevor der Build laeuft.

    Anlass: Am 2026-08-20 hat ein Testlauf `settings.json` mit den Vorgabewerten
    ueberschrieben — Hotkeys, Mikrofon, Woerterbuch und der Lizenzschluessel waren
    weg, und es gab nichts zum Zurueckholen. Die Ursache ist behoben, aber wer
    baut, aendert Code, und Code kann wieder etwas anfassen, das ihm nicht gehoert.
    Zwei Zeilen Vorsicht vor einem Vorgang, der ohnehin eine Minute dauert.
    """
    from fleech.einstellungssicherung import sichere
    from fleech.usersettings import SETTINGS_PATH

    ziel = sichere(SETTINGS_PATH, "build")
    if ziel is not None:
        print(f"[build] Einstellungen gesichert: {ziel}")


def main() -> int:
    sichere_einstellungen()
    gpu = resolve_gpu_flag(sys.argv)
    is_win = sys.platform == "win32"
    # Getrennte Ausgabepfade: dist/Fleech (Windows, historisch — robocopy und
    # fleech.iss zeigen darauf) vs. dist/linux/Fleech. So ueberschreiben sich die
    # Builds auf dem geteilten NTFS-Laufwerk nicht gegenseitig.
    dist_dir = ROOT / "dist" if is_win else ROOT / "dist" / "linux"
    print(f"[build] Fleech {APP_VERSION}  ({'Windows' if is_win else 'Linux'}, "
          f"GPU={'ja' if gpu else 'nein'})")
    subprocess.check_call([sys.executable, str(ROOT / "assets" / "make_icons.py")])
    write_build_stamp()
    write_version_info()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(dist_dir),
        "--workpath", str(ROOT / "build"),
        str(ROOT / "packaging" / "fleech.spec"),
    ]
    env = dict(os.environ)
    if gpu:
        env["FLEECH_GPU"] = "1"
    else:
        env.pop("FLEECH_GPU", None)
    print("[build] PyInstaller:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT, env=env)

    exe = dist_dir / "Fleech" / ("Fleech.exe" if is_win else "Fleech")
    print(f"[build] Binary: {exe}  (existiert: {exe.is_file()})")
    if not exe.is_file():
        return 1

    if "--installer" in sys.argv:
        if not is_win:
            print("[installer] Inno Setup gibt es nur unter Windows — unter Linux "
                  "stattdessen: build.py --install (Sync nach ~/.local/opt/Fleech).")
            return 1
        return build_installer()
    if "--install" in sys.argv:
        if is_win:
            print("[install] --install ist der Linux-Sync; unter Windows weiterhin "
                  "robocopy nach %LOCALAPPDATA%\\Programs\\Fleech nutzen.")
            return 1
        return install_linux()
    return 0


if __name__ == "__main__":
    sys.exit(main())
