# PyInstaller-Spec fuer Fleech (onedir, windowed, kein Konsolenfenster).
# Aufruf ueber packaging/build.py — nicht direkt, damit build.txt/version_info stimmen.
# Plattformfaehig: Windows (Fleech.exe) und Linux (Fleech-Binary, gleiche Struktur).

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # packaging/ -> Projekt-Root
ASSETS = ROOT / "assets"
IS_WIN = sys.platform == "win32"

datas = [
    (str(ROOT / "prompts"), "prompts"),
    (str(ASSETS), "assets"),
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
hiddenimports = ["fleech", "fleech.ui.desktop"]

# Pakete mit nativen Teilen / Datendateien vollstaendig einsammeln.
collect_pkgs = ["faster_whisper", "ctranslate2", "av", "sounddevice", "numpy"]
if IS_WIN:
    collect_pkgs += ["pycaw", "comtypes"]
else:
    # pulsectl ist pures Python (laedt libpulse aus dem System), copykitten hat
    # eine native Extension — beide explizit einsammeln.
    collect_pkgs += ["pulsectl", "copykitten"]
for pkg in collect_pkgs:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Linux: libportaudio mitbundeln (sounddevice-Wheels enthalten sie dort nicht;
# fleech.portaudio_bootstrap findet sie im Bundle). Quelle auf dem Build-Rechner:
# Systembibliothek oder ~/.local/lib/fleech (aus dem Ubuntu-Paket extrahiert).
if not IS_WIN:
    import ctypes.util

    _pa = ctypes.util.find_library("portaudio")
    if not _pa:
        _local = sorted((Path.home() / ".local" / "lib" / "fleech").glob("libportaudio.so*"))
        _pa = str(_local[0]) if _local else None
    if _pa:
        binaries.append((_pa, "."))
    else:
        print("[spec] WARNUNG: libportaudio nicht gefunden — Audio wird im Bundle fehlen.")

# Cloud-Anbieter (6.1.0) laufen ueber urllib — kein SDK. Die API-Schluessel liegen
# im Schluesselbund des Systems: `keyring` findet seine Backends ueber
# Paket-Metadaten (entry points). Ohne die Metadaten im Bundle meldet es „kein
# Backend" und Fleech koennte keinen Schluessel speichern.
hiddenimports += collect_submodules("keyring")
datas += copy_metadata("keyring")
if IS_WIN:
    hiddenimports += collect_submodules("win32ctypes")

# Build-Stamp (vom Build-Skript geschrieben) mitbundeln, falls vorhanden.
build_stamp = ROOT / "build.txt"
if build_stamp.is_file():
    datas.append((str(build_stamp), "."))

# Optional GPU: nvidia cuBLAS/cuDNN nur bundeln, wenn FLEECH_GPU gesetzt ist
# (macht das Paket ~1 GB groesser; ohne greift der CPU/int8-Fallback zur Laufzeit).
if os.environ.get("FLEECH_GPU"):
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception as exc:  # noqa: BLE001
            print(f"[spec] GPU-Paket {pkg} nicht gefunden: {exc}")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib", "PySide6.QtWebEngineCore",
              "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Icon/Versions-Ressource sind Windows-PE-Features; unter Linux kommt das Icon
# ueber die .desktop-Datei (packaging/build.py --install).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fleech",
    console=False,                       # kein Terminalfenster
    icon=str(ASSETS / "fleech.ico") if IS_WIN else None,
    version=str(ROOT / "packaging" / "version_info.txt") if IS_WIN else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Fleech")
