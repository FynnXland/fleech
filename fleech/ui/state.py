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
    # Update-Pruefung/-Download laufen im Worker-Thread; das Ergebnis darf die UI nur
    # ueber dieses Signal erreichen. dict = Ergebnis von check_for_updates(),
    # str = Pfad der geladenen Datei ("" = noch nicht geladen).
    update_ready = Signal(object, str)
    # Profil-Taste (gedrueckt/losgelassen). Der Hotkey kommt aus dem pynput-Thread —
    # dort ist QTimer WIRKUNGSLOS: weder die Halte-Erkennung noch das automatische
    # Ausblenden der Profil-Kapsel liefen, die Kapsel blieb ewig stehen. Ueber dieses
    # Signal landet beides im UI-Thread, wo Timer funktionieren.
    profile_key = Signal(bool)
    # Freischalt-Dialog anfordern. Die Lizenzpruefung sitzt am Aufnahmestart, und
    # der laeuft im pynput-Thread — ein QDialog dort ZU BAUEN haengt die ganze App
    # auf (Qt-Widgets gehoeren dem GUI-Thread, keine Ausnahme). Ueber dieses Signal
    # entsteht der Dialog dort, wo er hingehoert.
    license_needed = Signal()
    # Pause an/aus. Der Pause-Hotkey kommt ebenfalls aus dem pynput-Thread; die
    # Pille direkt von dort umzufaerben ist derselbe Thread-Fehler wie oben, nur
    # leiser — er crasht sporadisch statt sofort.
    paused_changed = Signal(bool)
    # Rohtranskript, sobald die Erkennung fertig ist (~0,8 s) — also LANGE bevor
    # die Bereinigung durch ist (~4 s). Wer schon lesen kann, waehrend das Modell
    # arbeitet, wartet gefuehlt nicht mehr. Wird spaeter von `transcript_ready`
    # (der fertigen Fassung) abgeloest.
    raw_ready = Signal(str)
    # Ergebnis einer Nachbearbeitung (Text, Formatname). Der Lauf haengt am LLM und
    # gehoert deshalb in einen Worker-Thread — das Ergebnis muss ueber ein Signal
    # zurueck, sonst faende die Zwischenablage im falschen Thread statt.
    reprocessed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state = AppState.IDLE

    def set_state(self, state: AppState, feedback: str = "") -> None:
        self.state = state
        self.state_changed.emit(state)
        if feedback:
            self.feedback.emit(feedback)
