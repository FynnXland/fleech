"""Verfolgt, was Fleech in das aktuelle Ziel-Feld diktiert hat.

Fremde Felder koennen wir nicht lesen — dieser Tracker ist die einzige Quelle fuer
den KONTEXT von Prompt 2 und fuer die Aufloesung der Ersetzungs-Scopes. Er modelliert
exakt die Zeichen, die wir selbst eingefuegt haben.

Session-Kontext: Pro Fenster bleibt der
Diktat-Verlauf erhalten — wer kurz in den Browser schaut und zurueckkehrt, hat den
Kontext wieder (Befehle mit Bezug funktionieren). Aber: **Kontext lesen und Text
ersetzen sind nicht gleich gefaehrlich.** Ersetzungen laufen ueber blinde Backspaces
und setzen voraus, dass der Cursor unmittelbar hinter dem eigenen Text steht; nach
einer Rueckkehr ist die Cursor-Position unbekannt — Backspaces wuerden fremden Text
loeschen, und dagegen gibt es keinen moeglichen Guard (die 2701-Zeichen-Fehlerklasse).
Deshalb traegt jede Session ein `dirty`-Flag: nach einer Rueckkehr liefert
`resolve_scope` None (= Ersetzung wird wie bisher sauber abgefangen), erst die
naechste EIGENE Injection macht Ersetzungen wieder moeglich.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time

log = logging.getLogger(__name__)

# Satzende: .!? optional gefolgt von schliessendem Zeichen, dann Whitespace.
_SENTENCE_END = re.compile(r"[.!?][\"'“”)\]]?\s+")

# Session-Grenzen: Erinnerung ist RAM-only und beschreibt den Live-Zustand fremder
# Felder — grosszuegig genug fuer echte Arbeit, klein genug, um nie ins Gewicht zu
# fallen. Timeout fest (keine Einstellung): je aelter der Kontext, desto eher hat
# der Nutzer den Text laengst von Hand umgebaut — ein Bezug darauf fuehrt das
# Befehls-Modell dann in die Irre statt es zu stuetzen.
SESSION_TIMEOUT_S = 15 * 60
_MAX_SESSIONS = 8
_MAX_SESSION_CHARS = 8000
_MAX_CHUNKS = 10


class _Session:
    __slots__ = ("text", "chunks", "last_chunk", "last_activity", "dirty")

    def __init__(self):
        self.text = ""
        self.chunks: list[str] = []
        self.last_chunk = ""
        self.last_activity = time.monotonic()
        self.dirty = False


class DocumentTracker:
    """Thread-sicher: Der Qt-Signal-Bus serialisiert nur UI-Ereignisse, NICHT den
    Zugriff mehrerer Worker auf gemeinsame Daten. Auf diesen Puffer greifen der
    Verarbeitungs-Thread (Anhaengen/Ersetzen) und ggf. ein noch laufender Vorgaenger
    zu — deshalb ein eigener RLock um Lese- UND Schreibpfade (verschachtelte Aufrufe
    wie resolve_scope innerhalb einer Ersetzung bleiben so moeglich)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict = {}
        self._window = None

    @staticmethod
    def _foreground_window():
        if sys.platform != "win32":
            return None
        import ctypes

        return ctypes.windll.user32.GetForegroundWindow()

    @staticmethod
    def _window_alive(hwnd) -> bool:
        if hwnd is None or sys.platform != "win32":
            return True
        try:
            import ctypes

            return bool(ctypes.windll.user32.IsWindow(hwnd))
        except Exception:
            return True  # im Zweifel behalten — der Deckel raeumt ohnehin auf

    # -- Session-Verwaltung -----------------------------------------------------------

    def _current(self) -> _Session:
        """Session des aktiven Fensters (legt bei Bedarf eine leere an).
        Nur unter self._lock aufrufen."""
        session = self._sessions.get(self._window)
        if session is None:
            session = _Session()
            self._sessions[self._window] = session
        return session

    def _expired(self, session: _Session) -> bool:
        return (time.monotonic() - session.last_activity) > SESSION_TIMEOUT_S

    def _prune(self) -> None:
        """Tote Fenster und abgelaufene Sessions entsorgen, Deckel durchsetzen.
        Nur unter self._lock aufrufen."""
        for hwnd in list(self._sessions):
            if hwnd == self._window:
                continue
            session = self._sessions[hwnd]
            if self._expired(session) or not self._window_alive(hwnd):
                del self._sessions[hwnd]
        while len(self._sessions) > _MAX_SESSIONS:
            # Aelteste fremde Session fliegt zuerst; die aktive nie.
            oldest = min(
                (h for h in self._sessions if h != self._window),
                key=lambda h: self._sessions[h].last_activity,
                default=None,
            )
            if oldest is None:
                break
            del self._sessions[oldest]

    def sync_window(self) -> None:
        """Vor jeder Verarbeitung aufrufen: aktive Session dem Fokus nachfuehren.

        Frueher wurde der Puffer beim Wechsel VERWORFEN; jetzt wird er gemerkt und
        bei Rueckkehr reaktiviert — als reiner Lese-Kontext (dirty), bis die
        naechste eigene Injection die Cursor-Annahme wieder herstellt."""
        hwnd = self._foreground_window()
        with self._lock:
            if hwnd == self._window:
                return
            self._window = hwnd
            session = self._sessions.get(hwnd)
            if session is not None:
                if self._expired(session):
                    del self._sessions[hwnd]
                    log.info("Diktat-Kontext des Fensters verfallen (Timeout).")
                elif session.text:
                    # Rueckkehr: Kontext lesen ja, Ersetzen nein (siehe Modul-Kopf).
                    session.dirty = True
                    log.info("Fenster gewechselt — gemerkter Diktat-Kontext "
                             "reaktiviert (%d Bloecke, nur Lese-Kontext).",
                             len(session.chunks))
            # Aktive Session VOR dem Aufraeumen anlegen, damit der Deckel sie
            # mitzaehlt (sonst entsteht sie erst beim Diktat — eine ueber Limit).
            self._current()
            self._prune()

    def session_info(self):
        """(Anzahl Bloecke, Minuten seit letztem Diktat) fuer das AKTUELLE Fenster —
        None, wenn dort kein Kontext gemerkt ist. Fuer den Session-Punkt der Pille."""
        hwnd = self._foreground_window()
        with self._lock:
            session = self._sessions.get(hwnd)
            if session is None or not session.text:
                return None
            if self._expired(session):
                del self._sessions[hwnd]
                return None
            minutes = int((time.monotonic() - session.last_activity) // 60)
            # Drittes Feld `dirty`: Nach einem Fensterwechsel ist der Kontext nur
            # noch LESBAR — Ersetzen verweigert `resolve_scope`, weil die Cursor-
            # Position unbekannt ist. Bisher erfuhr man das erst, wenn ein Befehl
            # ins Leere lief; die Pille kann es jetzt vorher zeigen.
            return len(session.chunks), minutes, session.dirty

    # -- Lese-/Schreibpfade (Signatur wie bisher) ---------------------------------------

    @property
    def text(self) -> str:
        with self._lock:
            return self._current().text

    def context_tail(self, max_chars: int = 600) -> str:
        """Die letzten Saetze fuer den KONTEXT-Block von Prompt 2 — liefert auch
        nach einer Fenster-Rueckkehr (genau dafuer gibt es die Sessions)."""
        with self._lock:
            return self._current().text[-max_chars:]

    def separator(self) -> str:
        """Leerzeichen zwischen aufeinanderfolgenden Diktat-Segmenten."""
        with self._lock:
            text = self._current().text
            if not text or text[-1] in " \n\t":
                return ""
            return " "

    def record_append(self, injected: str) -> None:
        with self._lock:
            session = self._current()
            session.text += injected
            if len(session.text) > _MAX_SESSION_CHARS:
                session.text = session.text[-_MAX_SESSION_CHARS:]
            session.chunks.append(injected)
            del session.chunks[:-_MAX_CHUNKS]
            session.last_chunk = injected
            session.last_activity = time.monotonic()
            # Eigene Injection: der Cursor steht wieder garantiert hinter unserem
            # Text — Ersetzungen sind ab jetzt wieder erlaubt.
            session.dirty = False

    def record_replace(self, deleted_chars: int, replacement: str) -> None:
        with self._lock:
            session = self._current()
            session.text = session.text[: len(session.text) - deleted_chars] + replacement
            if session.chunks:
                session.chunks[-1] = replacement
            else:
                session.chunks.append(replacement)
            session.last_chunk = replacement
            session.last_activity = time.monotonic()
            session.dirty = False

    def resolve_scope(self, scope: str) -> str | None:
        """Exakter Puffer-Endabschnitt, den der Scope bezeichnet — None, wenn nicht
        aufloesbar. Nach einer Fenster-Rueckkehr (dirty) IMMER None: Ersetzungen
        setzen die bekannte Cursor-Position voraus, und die gibt es dann nicht."""
        with self._lock:
            session = self._current()
            if not session.text or session.dirty:
                return None
            text = session.text
            if scope == "dictated":
                return session.last_chunk or None
            if scope == "whole_document":
                return text
            if scope == "last_paragraph":
                idx = text.rstrip().rfind("\n")
                return text[idx + 1 :] if idx >= 0 else text
            if scope == "last_sentence":
                end = len(text.rstrip())
                start = 0
                for m in _SENTENCE_END.finditer(text):
                    if m.end() < end:  # nur Satzenden, nach denen noch Text kommt
                        start = m.end()
                return text[start:]
            return None  # as_described & Unbekanntes: ohne Feld-Zugriff nicht lokalisierbar
