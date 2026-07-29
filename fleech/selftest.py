"""Audio-Selbsttest:  python -m fleech --audio-selftest

Ablauf:
1. Zeigt Input-Geraet, Fokus-Modus und das Guard-Ergebnis an.
2. Spielt ein Test-Stoergeraeusch ueber den Standard-Output ab (Sinus-Sweep) — bei
   aktivem Ducking hoert man es weich absinken.
3. Nimmt parallel NUR vom Mikrofon auf. Der Nutzer spricht die Testformel.
4. Transkribiert die Aufnahme und zeigt das Ergebnis: Enthaelt es nur die Sprache
   (und nicht etwa Audio anderer Apps), ist der Capture-Pfad sauber.

Hinweis Physik: Ueber LAUTSPRECHER abgespieltes Audio kann akustisch ins Mikrofon
einkoppeln — das ist kein Software-Loopback und nur per Headset vermeidbar. Der Test
macht genau das sichtbar.
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger(__name__)

TEST_FORMULA = "x hoch zwei plus eins, das Ganze durch zwei"
DURATION = 8.0


def _test_noise(samplerate: int = 16000, seconds: float = DURATION) -> np.ndarray:
    """Leiser Sinus-Sweep als eindeutig nicht-sprachliches Stoergeraeusch."""
    t = np.linspace(0, seconds, int(seconds * samplerate), endpoint=False)
    freq = 300 + 500 * (t / seconds)
    return (0.15 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run_audio_selftest(config) -> int:
    import sounddevice as sd

    from .audio import Recorder
    from .app import DictationApp
    from .stt import create_stt

    focus = DictationApp._build_focus_controller(config)
    print("=== Fleech Audio-Selbsttest ===")
    print(f"Status:      {focus.status_line()}")
    print(f"Device-Guard: {'OK' if focus.device_check.ok else 'PROBLEM — ' + focus.device_check.reason}")
    print()
    print(f"Gleich startet eine {DURATION:.0f}-Sekunden-Aufnahme. Parallel laeuft ein Testton")
    print(f"ueber die Lautsprecher. Sprich waehrenddessen ins Mikrofon:")
    print(f'    "{TEST_FORMULA}"')
    print()
    time.sleep(2)

    recorder = Recorder(config.audio.samplerate, config.audio.device)
    focus.on_recording_start()
    try:
        recorder.start()
        sd.play(_test_noise(16000), 16000)  # Standard-Output; blockiert nicht
        print("[REC] Aufnahme laeuft -- jetzt sprechen ...")
        time.sleep(DURATION)
        sd.stop()
        audio = recorder.stop()
    finally:
        focus.on_recording_stop()

    print("[STOP] Aufnahme beendet, transkribiere ...")
    stt = create_stt(config.stt)
    text = stt.transcribe(audio, config.audio.samplerate)
    print()
    print(f"TRANSKRIPT: {text or '<leer>'}")
    print()
    print("Bewertung:")
    print(" - Enthaelt das Transkript nur deine gesprochene Formel -> Capture-Pfad sauber.")
    print(" - Der Testton darf nicht als Text auftauchen (er ist kein Sprachsignal).")
    print(" - Hoertest du den Ton waehrend der Aufnahme leiser werden -> Ducking aktiv.")
    print(" - Tauchen Inhalte aus anderen Apps auf (Musik-Lyrics, Video-Ton): Das ist")
    print("   akustisches Uebersprechen Lautsprecher->Mikrofon -- Headset verwenden.")
    return 0
