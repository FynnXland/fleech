"""Bedienlogik Hold / Toggle / Anstupsen — UI-unabhaengig und damit testbar.

Hold:      Taste druecken = Aufnahme laeuft, loslassen = stoppen & verarbeiten.
Toggle:    erster Druck = starten, zweiter Druck = stoppen & verarbeiten.
           (Auto-Repeat beim Gedrueckthalten wird ueber den Key-Down-Zustand entprellt.)
Anstupsen: ein Druck = starten, die SPRECHPAUSE beendet — kein zweiter Griff zur
           Tastatur. Der zweite Druck bleibt trotzdem moeglich, um vorzeitig zu
           beenden; hier verhaelt es sich also wie Toggle mit Abschaltautomatik.

Das Beenden per Stille steht bewusst NICHT hier: Dieses Modul kennt kein Audio.
Wer die Automatik fuettert, ist der Aufrufer (`ui/desktop.py`) mit Hilfe von
`stillewache.Stillewache` — er ruft dann schlicht `stop_if_active()`.

„Anstupsen" ist der Nachfolger des Freihand-Startworts. Der Wunsch dahinter war
nie „mit der Stimme starten", sondern „am Ende nicht wieder zur Tastatur greifen
muessen" — und genau diese Haelfte laesst sich zuverlaessig bauen. Die andere
nicht: Ein dauerhaft offenes Mikrofon in einem Raum, in dem auch mal ein Video
laeuft, loest frueher oder spaeter falsch aus, und jeder Fehlstart tippt Text in
das gerade fokussierte Fenster.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MODES = ("hold", "toggle", "nudge")

# Modi, in denen der Druck startet und ein zweiter Druck vorzeitig beendet.
_DRUCK_MODI = ("toggle", "nudge")


class RecordingController:
    def __init__(self, mode: str, on_start, on_stop):
        """on_start(kind) / on_stop(kind) mit kind in {"dictate", "math"}."""
        self.mode = mode if mode in MODES else "hold"
        self.on_start = on_start
        self.on_stop = on_stop
        self._active_kind: str | None = None
        self._key_down: set[str] = set()  # entprellt Auto-Repeat

    @property
    def active(self) -> bool:
        return self._active_kind is not None

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            log.warning("Unbekannter Bedienmodus %r — behalte %s.", mode, self.mode)
            return
        # Laufende Aufnahme sauber beenden, bevor die Semantik wechselt.
        if self._active_kind is not None:
            self._stop()
        self.mode = mode

    def press(self, kind: str) -> None:
        if kind in self._key_down:  # Auto-Repeat des gehaltenen Keys
            return
        self._key_down.add(kind)
        if self.mode == "hold":
            if self._active_kind is None:
                self._start(kind)
        else:  # toggle | nudge — Anstupsen endet zusaetzlich von selbst
            if self._active_kind is None:
                self._start(kind)
            elif self._active_kind == kind:
                self._stop()
            # Druck des ANDEREN Hotkeys waehrend aktiver Aufnahme: ignorieren —
            # kein versehentliches Moduswechsel-Chaos mitten im Satz.

    def release(self, kind: str) -> None:
        self._key_down.discard(kind)
        if self.mode == "hold" and self._active_kind == kind:
            self._stop()

    def stop_if_active(self) -> None:
        """Fuer Tray-Menue ("Aufnahme stoppen"), Overlay-Haken und Moduswechsel."""
        if self._active_kind is not None:
            self._stop()

    def cancel(self) -> str | None:
        """Aufnahme abbrechen OHNE Verarbeitung (Overlay-X). Gibt die abgebrochene
        Art zurueck, oder None wenn gerade nichts laeuft. on_stop wird bewusst NICHT
        gerufen — der Aufrufer verwirft das Audio selbst."""
        kind, self._active_kind = self._active_kind, None
        return kind

    def start_via_ui(self, kind: str = "dictate") -> None:
        """Fuer Tray-Menue ("Aufnahme starten") — verhaelt sich wie Toggle."""
        if self._active_kind is None:
            self._start(kind)
        else:
            self._stop()

    def _start(self, kind: str) -> None:
        self._active_kind = kind
        self.on_start(kind)

    def _stop(self) -> None:
        kind, self._active_kind = self._active_kind, None
        self.on_stop(kind)
