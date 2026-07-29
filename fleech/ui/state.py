"""Zentrales State-Modell der Desktop-App.

Zustaende:      idle → listening → processing → idle
                                       └→ error → idle (nach kurzer Anzeige)
Uebergaenge laufen ueber den StateBus (Qt-Signale) — Worker-Threads emittieren,
UI-Elemente (Tray, Overlay) konsumieren via Queued Connection thread-sicher.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal


class AppState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    ERROR = "error"


class StateBus(QObject):
    state_changed = Signal(object)   # AppState
    feedback = Signal(str)           # kurzer Fortschritts-/Feedbacktext
    preview_text = Signal(str)       # rohe Streaming-Hypothese (M4)
    history_changed = Signal()       # neues Diktat aufgezeichnet (Home/Insights)
    transcript_ready = Signal(str)   # fertiger, eingefuegter Text (Overlay-Einblendung)
    injection_fallback = Signal()    # Text kam als ROHTEXT (Modell weg/Ausgabe verworfen)
    # Laengerer Zwischenschritt waehrend der Verarbeitung ("Modell wird geladen …").
    # Bewusst KEIN eigener AppState: der Zustand bleibt "verarbeitend", nur die
    # Begruendung wird sichtbar — sonst muesste jede UI-Stelle neue Zustaende kennen.
    progress = Signal(str)
    # [(latex, war_geraten)] — Formel-Vorschau vor dem Einfuegen. Geratene
    # Ausdruecke werden hervorgehoben, damit man sie pruefen kann, statt sie
    # ungeprueft im Dokument zu haben.
    formula_preview = Signal(list)
    # Als Halluzination verworfener Transkript-Schwanz. Anders als die Formel-
    # Vorschau ist das eine LOESCHUNG — sie wird immer gemeldet, auch wenn die
    # Transkript-Blase aus ist.
    tail_dropped = Signal(str)
    dictionary_suggestion = Signal(str, str, str)  # (erkannt, gemeint, satz) — Rueckfrage
    command_armed = Signal(bool)     # Befehls-Aufnahme laeuft (Trigger-Button) → Pille armen

    def __init__(self):
        super().__init__()
        self.state = AppState.IDLE

    def set_state(self, state: AppState, feedback: str = "") -> None:
        self.state = state
        self.state_changed.emit(state)
        if feedback:
            self.feedback.emit(feedback)
