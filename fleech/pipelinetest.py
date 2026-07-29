"""Pipeline-Selbsttest: alle drei Modi (Cleanup, Redax-Befehl, Formel) gegen echte
Provider durchlaufen lassen — mit denselben Assets/Prompts/Config, die die Desktop-
App auch nutzt. Gedacht, um eine INSTALLIERTE EXE end-to-end zu pruefen, ohne
Mikrofon/GUI-Automatisierung: die Audio-Fixtures kommen von der Kommandozeile,
die Config/Prompts/`.env` werden exakt so aufgeloest wie im echten Betrieb
(fleech/resources.py, fleech/config.py — Benutzerpfad %APPDATA%/Fleech zuerst).

Aufruf (auch aus der gepackten EXE heraus):
    Fleech.exe --pipeline-selftest "<pfad>\\tests\\fixtures"

Erwartet in diesem Ordner (jede Datei optional — fehlende werden uebersprungen):
    diktat_de.wav         → Cleanup-Pfad
    command_safeword.wav  → Safe-Word-Befehl
    math_quadratisch.wav  → Formel-Modus (Math-Hotkey)
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from .pipeline_factory import build_pipeline
from .usersettings import UserSettings

log = logging.getLogger(__name__)


class _CaptureInjector:
    """Fuer den Selbsttest: zeichnet auf statt real ins Textfeld einzufuegen."""

    def __init__(self):
        self.log: list[tuple] = []

    def inject(self, text: str) -> None:
        self.log.append(("inject", text))

    def replace_tail(self, delete_chars: int, text: str) -> None:
        self.log.append(("replace_tail", delete_chars, text))


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0, wav.getframerate()


_CASES = (
    ("Cleanup", "diktat_de.wav", False),
    ("Command (Safe-Word)", "command_safeword.wav", False),
    ("Formel (Math-Hotkey)", "math_quadratisch.wav", True),
)


def run_pipeline_selftest(config, fixtures_dir: str) -> int:
    fixtures = Path(fixtures_dir)
    settings = UserSettings.load()
    settings.apply_to(config)

    injector = _CaptureInjector()
    pipeline = build_pipeline(config, settings, injector=injector)

    print("=== Fleech Pipeline-Selbsttest ===")
    print(f"Cleanup-LLM: {config.llm_cleanup.model} @ {config.llm_cleanup.base_url}")
    print(f"Schnelles Modell: {config.llm_cleanup_fast.model}")
    print("Formeln: lokaler Parser (kein Modell, keine Cloud)")
    print(f"Fixtures-Ordner: {fixtures}\n")

    all_ok = True
    ran_any = False
    for label, filename, _unused in _CASES:
        path = fixtures / filename
        if not path.is_file():
            print(f"[{label}] uebersprungen — Fixture fehlt: {path}")
            continue
        ran_any = True
        audio, samplerate = _load_wav(path)
        injector.log.clear()
        try:
            result = pipeline.process(audio, samplerate)
        except Exception as exc:
            log.exception("Pipeline-Fehler bei %s", label)
            print(f"[{label}] FEHLER: {exc}")
            all_ok = False
            continue
        print(f"[{label}] Ergebnis: {result}")
        for entry in injector.log:
            print(f"    {entry}")
        if result not in ("ok", "fallback"):
            all_ok = False

    print()
    if not ran_any:
        print("GESAMT: keine Fixtures gefunden — nichts getestet.")
        return 1
    print("GESAMT:", "OK" if all_ok else "PROBLEME (siehe oben)")
    return 0 if all_ok else 1
