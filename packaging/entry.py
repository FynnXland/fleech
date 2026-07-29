"""PyInstaller-Einstiegspunkt der gepackten App.

Routet durch fleech.__main__.main(), damit alle Flags (--gui default, --audio-selftest,
--cli, --cwd) auch in der EXE funktionieren. Ohne Argumente startet die Desktop-App.
"""

import multiprocessing
import sys

from fleech.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # verhindert Prozess-Bomben bei gepacktem Code
    sys.exit(main())
