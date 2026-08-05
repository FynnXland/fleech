"""Die Teile der Aufnahme-Pille — je Thema ein Modul.

`overlay_qt.py` war mit 1409 Zeilen die groesste Datei im Projekt; `OverlayWindow`
allein hatte 862 Zeilen und 50 Methoden. Uebrig bleibt dort das Fenster selbst:
Aufbau, Hintergrund zeichnen, Qt-Ereignisse. Alles, was ein eigenes Thema ist,
liegt hier:

- `konstanten`    — Masse, Farben, Zeiten. Zuerst, weil alle anderen sie brauchen.
- `bausteine`     — eigenstaendige Widgets (Waveform, Status-Punkt, Textblase).
- `geometrie`     — wo die Pille steht: Presets, Ziehen, Einrasten, Monitorwechsel.
- `einblendungen` — was kurz erscheint: Transkript, Formeln, Fortschritt, Live-Text.
- `zustand`       — was dauerhaft angezeigt wird: Aufnahme, Modus, Profil, Pause.

**Warum Mixins.** Der Zustand bleibt auf EINEM Widget. Eigene Objekte haetten neue
Referenzen in den Qt-Objektgraphen gelegt — und genau das Overlay ist das Widget,
an dem die dokumentierten GC-Reihenfolge-Abstuerze auftraten (CLAUDE.md,
Referenzzyklus-Crash). Die Bausteine sind dagegen echte Klassen: Sie haengen nicht
am Fenster, sondern werden hineingelegt.
"""

from __future__ import annotations

from .bausteine import TranscriptCaption, WaveformWidget
from .einblendungen import EinblendungenMixin
from .geometrie import GeometrieMixin, preset_position
from .zustand import ZustandMixin

__all__ = [
    "EinblendungenMixin", "GeometrieMixin", "TranscriptCaption", "WaveformWidget",
    "ZustandMixin", "preset_position",
]
