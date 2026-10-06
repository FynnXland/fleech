"""Single-Instance-Lock: verhindert, dass zwei Fleech-GUI-Prozesse parallel laufen.

Motivation (real beobachtet): Zombie-Instanzen nach Rebuild-/Kill-Zyklen fuehrten zu
vervielfachtem Injection-Output (jede Instanz verarbeitet denselben Hotkey) und zu
Request-Bursts beim Formel-Provider (jede Instanz faehrt ihren eigenen 429-Backoff).
Der Lock verhindert diese Bug-Klasse an der Wurzel.

Mechanismus:
- Windows: benannter Mutex (sessionlokal). Der Handle wird fuer die Prozess-
  Lebensdauer gehalten; Windows raeumt ihn bei JEDEM Prozessende auf — auch nach
  Crash oder taskkill. Kein Stale-Lock-Problem wie bei Lock-Dateien.
- Linux: fcntl.flock auf eine Datei in $XDG_RUNTIME_DIR (tmpfs, benutzerlokal).
  Der Kernel gibt das Lock bei JEDEM Prozessende frei (auch kill -9) — dieselbe
  Garantie wie der Windows-Mutex, ebenfalls kein Stale-Lock-Problem.

Gilt nur fuer den GUI-Modus. --cli, --audio-selftest und --pipeline-selftest sind
kurzlebige Diagnose-/Sondermodi und bleiben bewusst unbeschraenkt.
"""

from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)

MUTEX_NAME = "Fleech.SingleInstance"
_ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    def __init__(self, name: str = MUTEX_NAME):
        self.name = name
        self._handle = None

    def acquire(self, retries: int = 3, delay: float = 0.7) -> bool:
        """True = wir sind die einzige Instanz. Mehrere Versuche decken das
        "Neu laden"-Fenster ab: der alte Prozess gibt den Mutex erst beim Exit frei.
        """
        for attempt in range(retries + 1):
            if self._try_acquire():
                return True
            if attempt < retries:
                time.sleep(delay)
        return False

    def _try_acquire(self) -> bool:
        if sys.platform == "win32":
            return self._try_acquire_mutex()
        if sys.platform.startswith("linux"):
            return self._try_acquire_flock()
        return True  # andere Plattformen: kein Locking

    def _try_acquire_flock(self) -> bool:
        import fcntl
        import os
        import tempfile
        from pathlib import Path

        run_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
        lock_path = run_dir / f"{self.name}.{os.getuid()}.lock"
        try:
            handle = open(lock_path, "w")
        except OSError:
            log.warning("Lock-Datei %s nicht anlegbar — starte ohne Instance-Lock.", lock_path)
            return True  # lieber ungeschuetzt starten als faelschlich blockieren
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def _try_acquire_mutex(self) -> bool:
        import ctypes
        import ctypes.wintypes as wt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p  # HANDLE — nie c_int (64-bit!)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, ctypes.c_wchar_p]

        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            log.warning("CreateMutexW fehlgeschlagen — starte ohne Instance-Lock.")
            return True  # lieber ungeschuetzt starten als faelschlich blockieren
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.CloseHandle(ctypes.c_void_p(self._handle))
        else:
            try:
                self._handle.close()  # schliesst die Lock-Datei → flock wird frei
            except Exception:
                pass
        self._handle = None
