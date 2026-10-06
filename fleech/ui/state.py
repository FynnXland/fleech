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
    # Text liegt nur in der Zwischenablage (spaet fertig, Nutzer woanders) —
    # die Pille zeigt es als Blase, unabhaengig von Benachrichtigungen.
    in_ablage = Signal(str)
    # Wichtiger Hinweis ohne Bezug zu einem Diktat (z. B. KI auf dem Prozessor) —
    # als Blase an der Pille, unabhaengig von Benachrichtigungs-Einstellungen.
    hinweis = Signal(str)
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
    # Pause an/aus. Der Pause-Hotkey kommt ebenfalls aus dem pynput-Thread; die
    # Pille direkt von dort umzufaerben ist derselbe Thread-Fehler wie oben, nur
    # leiser — er crasht sporadisch statt sofort.
    paused_changed = Signal(bool)
    # KI-Prompting fuer DIESES Diktat an/aus. Der Hotkey kommt aus dem
    # pynput-Thread, und die Pille faerbte sich bis 5.10.3 direkt von dort um
    # (`overlay.set_prompt_latched` → Widget-Operationen im falschen Thread,
    # Befund D-6) — derselbe Fehler wie oben, nur ohne Ausnahme, die ihn zeigt.
    prompt_latch_changed = Signal(bool)
    # Das gewaehlte Profil gibt es nicht mehr → zurueck auf „automatisch".
    # Bemerkt wird das beim Aufloesen im VERARBEITUNGS-Thread (Befund D-7); das
    # Aufraeumen selbst speichert die Einstellungen und faerbt die Pille, gehoert
    # also in den GUI-Thread.
    profil_zuruecksetzen = Signal()
    # Eine Aufnahme hat begonnen — Ring (und bei einem Wechsel die Namens-Kapsel)
    # an der Pille nachziehen. Vorher folgte der Ring nur der Wahl von Hand und
    # war blind fuer die App-Zuordnung (Befund G-B4). Der Aufnahmestart laeuft im
    # pynput-Thread, deshalb ueber den Bus statt direkt an die Pille.
    profil_pruefen = Signal()
    # Rohtranskript, sobald die Erkennung fertig ist (~0,8 s) — also LANGE bevor
    # die Bereinigung durch ist (~4 s). Wer schon lesen kann, waehrend das Modell
    # arbeitet, wartet gefuehlt nicht mehr. Wird spaeter von `transcript_ready`
    # (der fertigen Fassung) abgeloest.
    raw_ready = Signal(str)
    # Ergebnis einer Nachbearbeitung (Text, Formatname, Grund des Scheiterns). Der
    # Lauf haengt am LLM und gehoert deshalb in einen Worker-Thread — das Ergebnis
    # muss ueber ein Signal zurueck, sonst faende die Zwischenablage im falschen
    # Thread statt. Der dritte Wert ist leer, wenn es geklappt hat; sonst traegt er
    # den Grund. Ohne ihn koennte das Fortschritts-Fenster nur „fehlgeschlagen"
    # sagen — und „ein Diktat laeuft noch" ist etwas ganz anderes als „das Modell
    # hat nichts geliefert".
    reprocessed = Signal(str, str, str)
    # Freihand-Ereignis (Name des Ereignisses). Kommt aus dem AUDIO-Thread — dort
    # darf nichts mit Qt passieren, deshalb der Umweg ueber dieses Signal.
    freihand_ereignis = Signal(str)
    # Lauschzustand fuer die Pille ("aus" | "lauscht" | "aufnahme").
    freihand_zustand = Signal(str)
    # Freihand liess sich NICHT starten (Grund als Text). Eigenes Signal, weil der
    # Aufbau in einem Hintergrund-Thread laeuft — von dort darf nichts direkt an
    # Qt. Ohne diese Meldung blieb der Fehlschlag unsichtbar: Der Schalter stand
    # auf an, es passierte nichts, und man sucht den Fehler beim Startwort.
    freihand_fehler = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = AppState.IDLE

    def set_state(self, state: AppState, feedback: str = "") -> None:
        self.state = state
        self.state_changed.emit(state)
        if feedback:
            self.feedback.emit(feedback)
