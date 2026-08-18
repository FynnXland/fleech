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

_CF_UNICODETEXT = 13   # Win32-Standardformat "Unicode-Text"


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


def has_text() -> bool:
    """Liegt ueberhaupt TEXT in der Zwischenablage?

    Befund B-10: Gesichert und zurueckgeschrieben wird nur Text. Lag ein Bild oder
    eine kopierte Datei darin, lieferte `paste_text()` einen leeren String — und
    nach dem Diktat schrieb Fleech genau diesen leeren String zurueck. Der eben
    kopierte Screenshot war damit weg. Ist kein Text da, wird nach dem Einfuegen
    nichts wiederhergestellt: Der Diktat-Text bleibt in der Ablage, das Bild ist
    ohnehin schon vom System verdraengt worden — aber es wird nicht zusaetzlich
    ein leerer Text darueber geschrieben.

    Windows fragt `IsClipboardFormatAvailable(CF_UNICODETEXT)`; das ist die einzige
    Auskunft, die ohne Oeffnen der Ablage funktioniert. Keine Auskunft moeglich →
    True, also wie bisher verfahren (fail-open).
    """
    if sys.platform != "win32":
        return bool(paste_text())
    try:
        import ctypes

        return bool(ctypes.windll.user32.IsClipboardFormatAvailable(_CF_UNICODETEXT))
    except Exception:
        log.debug("Zwischenablage-Format nicht abfragbar.", exc_info=True)
        return True


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
