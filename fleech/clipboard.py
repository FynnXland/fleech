"""Zwischenablage plattformuebergreifend — EINE Nahtstelle fuer die Injection.

Windows: pyperclip (Bestand, stabil, keine Zusatztools).
Linux:   copykitten (arboard-basiert) — funktioniert auf X11 UND Wayland ohne
         xclip/xsel-Systemabhaengigkeit. pyperclip bleibt Fallback (greift z. B.,
         wenn ein Clipboard-Manager wie Klipper via qdbus erreichbar ist).

Alle Funktionen sind Best-Effort: Lesen liefert None statt Exception, Schreiben
wirft nur, wenn KEIN Backend funktioniert (dann waere die Injection wirkungslos
und der Fehler muss sichtbar werden).
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


def _use_copykitten() -> bool:
    return sys.platform != "win32"


def paste_text() -> str | None:
    """Aktueller Text-Inhalt der Zwischenablage; None = leer/nicht lesbar."""
    if _use_copykitten():
        try:
            import copykitten

            return copykitten.paste()
        except Exception:
            # Leer, Nicht-Text-Inhalt oder Backend-Problem → pyperclip probieren.
            pass
    try:
        import pyperclip

        return pyperclip.paste()
    except Exception:
        return None


def copy_text(text: str) -> None:
    if _use_copykitten():
        try:
            import copykitten

            copykitten.copy(text)
            return
        except Exception:
            log.debug("copykitten.copy fehlgeschlagen — versuche pyperclip.", exc_info=True)
    import pyperclip

    pyperclip.copy(text)
