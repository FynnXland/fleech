#!/usr/bin/env bash
# Linux-Dev-Umgebung für Fleech aufsetzen (Kubuntu/X11).
#
# Das venv liegt bewusst AUSSERHALB des Projekts (~/.venvs/fleech), weil das
# Projekt auf einem NTFS-Mount liegt. Fehlt python3-venv/pip systemweit, wird
# pip per get-pip.py gebootstrapt (kein sudo nötig).
#
# Aufruf:  bash packaging/setup-linux.sh
set -euo pipefail

VENV="${FLEECH_VENV:-$HOME/.venvs/fleech}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$VENV/bin/python" ]; then
    echo "[setup] Lege venv an: $VENV"
    python3 -m venv "$VENV" 2>/dev/null || {
        python3 -m venv --without-pip "$VENV"
        curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python"
    }
fi

echo "[setup] Installiere Requirements …"
# requirements-dev.txt zieht requirements.txt nach und ergänzt pytest, Pillow
# und PyInstaller (Tests + Build).
"$VENV/bin/pip" install -r "$ROOT/requirements-dev.txt"

# pynput OHNE Abhängigkeiten: das X11-Backend braucht nur python-xlib (oben
# installiert); die deklarierte evdev-Abhängigkeit (Wayland/uinput) hat keine
# Binary-Wheels und würde ohne python3-dev-Header am Source-Build scheitern.
echo "[setup] Installiere pynput (ohne evdev) …"
"$VENV/bin/pip" install --no-deps "pynput>=1.7.7"

echo "[setup] Fertig. Tests:  $VENV/bin/python -m pytest -q"
echo "[setup]         Build:  $VENV/bin/python packaging/build.py"
