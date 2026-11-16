"""Welches Vollbild ist ein Spiel? (`windowsfocus.kein_spiel_grund`)

Die Faelle stammen aus echten Fenstern (Klasse, Prozess, Stil am 2026-11-03
ausgelesen) und aus dem Log: 492 Entladungen vom 09.10. bis 03.11.2026, davon
nur 22 durch ein Spiel."""

import sys

import pytest

from fleech.ui.windowsfocus import FocusContext, FocusProbe, kein_spiel_grund

FLOWSHARE_EXSTIL = 0x00000108  # Aufnahme-Overlay je Monitor: topmost, kein Werkzeugfenster
ALT_TAB_EXSTIL = 0x00200088  # XamlExplorerHostIslandWindow: topmost + Werkzeugfenster


@pytest.mark.parametrize("klasse, prozess", [
    ("UnrealWindow", "VALORANT-Win64-Shipping.exe"),  # randloses Vollbild
    ("GLFW30", "javaw.exe"),                          # Minecraft
    ("UnityWndClass", "Gromopoli.exe"),
])
def test_spiele_zaehlen(klasse, prozess):
    assert kein_spiel_grund(klasse, prozess, False, 0) == ""


@pytest.mark.parametrize("klasse, prozess, maximiert, exstil, grund", [
    # YouTube-Vollbild im Browser (272 Entladungen), Discord-Stream, Claude
    ("Chrome_WidgetWin_1", "comet.exe", False, 0, "Browser/Electron"),
    ("Chrome_WidgetWin_1", "Discord.exe", False, 0, "Browser/Electron"),
    ("Chrome_WidgetWin_1", "claude.exe", False, 0, "Browser/Electron"),
    # FlowShare ist Electron; Alt+Tab ein Werkzeugfenster ohne Taskleisten-Knopf
    ("Chrome_WidgetWin_1", "FlowShare.exe", False, FLOWSHARE_EXSTIL, "Browser/Electron"),
    ("XamlExplorerHostIslandWindow", "explorer.exe", False, ALT_TAB_EXSTIL, "Overlay"),
    # Windows-Oberflaeche und Remotedesktop
    ("Windows.UI.Core.CoreWindow", "LockApp.exe", False, 0, "kein Spielprozess"),
    ("TscShellContainerClass", "mstsc.exe", False, 0, "kein Spielprozess"),
    ("CabinetWClass", "explorer.exe", False, 0, "kein Spielprozess"),
    ("MozillaWindowClass", "firefox.exe", False, 0, "kein Spielprozess"),
    # Maximiert mit Titelleiste bei automatisch ausgeblendeter Taskleiste:
    # deckt den Monitor ab (die Probe uebergibt maximiert=True nur MIT Titelleiste;
    # comet im Video-Vollbild ist "maximiert" ohne und faellt auf die Klasse)
    ("UnityWndClass", "irgendwas.exe", True, 0, "maximiertes Fenster"),
])
def test_kein_spiel(klasse, prozess, maximiert, exstil, grund):
    assert kein_spiel_grund(klasse, prozess, maximiert, exstil) == grund


def test_vorgabe_ist_kein_spielvollbild():
    """Wer den Kontext ohne Fensterabfrage baut, entlaedt nichts."""
    assert FocusContext(fullscreen=True).spiel_vollbild is False


@pytest.mark.skipif(sys.platform != "win32", reason="echte Win32-Abfrage")
def test_echte_abfrage_liefert_das_spielsignal():
    ctx = FocusProbe().query()
    assert isinstance(ctx.spiel_vollbild, bool)
    assert not (ctx.spiel_vollbild and not ctx.fullscreen)
