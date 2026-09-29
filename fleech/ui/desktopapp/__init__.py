"""Die Teilgebiete von `DesktopApp` — je Thema ein Modul.

`desktop.py` war mit 1979 Zeilen und einer Klasse mit 89 Methoden das groesste
Einzelstueck im Projekt. Uebrig bleibt dort der Kern: Aufbau der App, der
Aufnahme-Lebenszyklus (`_on_record_start`/`_process_locked`), die Hotkeys und die
Verdrahtung mit Tray, Overlay und Einstellungen. Alles, was ein eigenes Thema mit
eigenem Zustand ist, liegt hier.

**Warum Mixins und keine Controller-Objekte.** Ein `ProfileController(app)` waere
das sauberere Muster, haette aber zwei konkrete Kosten in genau diesem Projekt:
Erstens legt jedes zusaetzliche Objekt neue Referenzen in den Qt-Objektgraphen —
die dokumentierte Ursache der wandernden „access violation"-Abstuerze (siehe
CLAUDE.md). Zweitens pruefen die Tests diese Methoden bewusst ungebunden gegen
einen Fake (`DesktopApp._app_profile_overrides(fake)`), um sie ohne echte Widgets
durchzurechnen; ein Controller haette diesen Zugang zerschnitten. Der Zustand
bleibt deshalb auf EINEM Objekt, nur die Definition zieht um.
"""

from __future__ import annotations

from .anstupsen import AnstupsenMixin
from .freihand import FreihandMixin
from .keinton import KeinTonMixin
from .lebenszyklus import LebenszyklusMixin
from .lizenz import LizenzUpdateMixin
from .modelle import ModelleMixin
from .nachbereitung import NachbereitungMixin
from .profil import ProfilMixin
from .wachhund import WachhundMixin

__all__ = [
    "AnstupsenMixin", "FreihandMixin", "KeinTonMixin", "LebenszyklusMixin", "LizenzUpdateMixin",
    "ModelleMixin", "NachbereitungMixin", "ProfilMixin", "WachhundMixin",
]
