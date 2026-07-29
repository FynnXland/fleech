"""Linux: PortAudio-Aufloesung fuer sounddevice absichern.

Die sounddevice-Wheels bundeln libportaudio nur fuer Windows/macOS; unter Linux
verlaesst sich sounddevice auf ctypes.util.find_library("portaudio") — und das
kennt nur den ldconfig-Cache. Fehlt das Systempaket (libportaudio2) und ist kein
sudo verfuegbar, waere Audio tot.

Loesung: Ist "portaudio" systemweit nicht auffindbar, suchen wir eine lokal
abgelegte libportaudio.so.2 (Bundle der gepackten App bzw. ~/.local/lib/fleech,
extrahiert aus dem offiziellen Ubuntu-Paket) und lassen find_library fuer genau
diesen einen Namen den vollen Pfad liefern. Mit installiertem Systempaket ist
das hier ein No-op.

Muss VOR dem ersten "import sounddevice" laufen → Aufruf in fleech/__init__.py.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_local_portaudio() -> Path | None:
    roots = []
    if getattr(sys, "frozen", False):  # PyInstaller: Lib liegt im Bundle
        roots.append(Path(sys.executable).parent / "_internal")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    roots.append(Path.home() / ".local" / "lib" / "fleech")
    for root in roots:
        if not root.is_dir():
            continue
        for lib in sorted(root.glob("libportaudio.so*")):
            if lib.is_file():
                return lib
    return None


def ensure_portaudio() -> None:
    if not sys.platform.startswith("linux"):
        return
    import ctypes.util

    if ctypes.util.find_library("portaudio"):
        return  # Systempaket vorhanden — nichts zu tun
    lib = _find_local_portaudio()
    if lib is None:
        return  # sounddevice liefert dann seine normale, klare Fehlermeldung
    original = ctypes.util.find_library

    def find_library(name):  # noqa: ANN001 — stdlib-Signatur
        if name == "portaudio":
            return str(lib)
        return original(name)

    ctypes.util.find_library = find_library
