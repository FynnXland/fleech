"""Hotkeys: Einzeltasten UND Kombinationen (z. B. Ctrl+Shift+Space).

Kanonisches Serialisierungsformat: modifier-tokens (feste Reihenfolge) + Haupttaste,
mit "+" verbunden, komplett kleingeschrieben — z. B. "f9", "ctrl+shift+space",
"ctrl+alt+d". Altbestand ("f9", "f10") ist bereits gueltig und wird automatisch
migriert.

Zwei Nutzungen:
- parse_key()/keys_equal(): Einzeltasten-Vergleich (Legacy, CLI-Modus).
- HotkeySpec + HotkeyManager: Kombinationen mit Modifier-Tracking (Desktop-App).
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

from pynput import keyboard

log = logging.getLogger(__name__)

MODIFIER_TOKENS = ("ctrl", "alt", "shift", "win")

# Maustasten als Haupttaste (nur Desktop-App). Links/rechts sind bewusst NICHT
# bindbar — das wuerde die normale Mausnutzung zerstoeren.
MOUSE_TOKENS = ("mouse_middle", "mouse4", "mouse5")
# Windows nennt die Zusatztasten x1/x2, X11 (pynput/Linux) button8/button9.
_PYNPUT_MOUSE = {
    "middle": "mouse_middle",
    "x1": "mouse4", "x2": "mouse5",
    "button8": "mouse4", "button9": "mouse5",
}

# Win32-Mausnachrichten (fuer Filter/Unterdrueckung im HotkeyManager)
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208
_WM_XBUTTONDOWN, _WM_XBUTTONUP = 0x020B, 0x020C
_MOUSE_DOWN_MSGS = (_WM_MBUTTONDOWN, _WM_XBUTTONDOWN)
_MOUSE_BUTTON_MSGS = (_WM_MBUTTONDOWN, _WM_MBUTTONUP, _WM_XBUTTONDOWN, _WM_XBUTTONUP)


def pynput_mouse_token(button) -> str | None:
    """pynput-Maus-Button → Token; None = nicht bindbar (links/rechts/Scroll)."""
    return _PYNPUT_MOUSE.get(getattr(button, "name", None))


def is_mouse_token(token: str) -> bool:
    return token in MOUSE_TOKENS


def mouse_msg_token(msg: int, mouse_data: int) -> str | None:
    """Win32-Hook-Nachricht → Token (fuer den Event-Filter)."""
    if msg in (_WM_MBUTTONDOWN, _WM_MBUTTONUP):
        return "mouse_middle"
    if msg in (_WM_XBUTTONDOWN, _WM_XBUTTONUP):
        xbutton = (mouse_data >> 16) & 0xFFFF
        return {1: "mouse4", 2: "mouse5"}.get(xbutton)
    return None

# pynput-Key-Namen → kanonisches Token (Modifier-Varianten zusammenfassen).
_NORMALIZE_NAMED = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift_l": "shift", "shift_r": "shift",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
}

_DISPLAY = {
    "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win",
    "space": "Space", "enter": "Enter", "tab": "Tab", "esc": "Esc",
    "page_up": "Page Up", "page_down": "Page Down", "print_screen": "Print",
    "scroll_lock": "Scroll Lock", "caps_lock": "Caps Lock", "num_lock": "Num Lock",
    "mouse_middle": "Mittlere Maustaste", "mouse4": "Maustaste 4", "mouse5": "Maustaste 5",
}


def pynput_token(key) -> str:
    """pynput-Event → kanonisches Token, robust auch bei gehaltenem Ctrl (nutzt vk)."""
    if isinstance(key, keyboard.Key):
        name = key.name
        return _NORMALIZE_NAMED.get(name, name)
    # KeyCode: vk ist layout-/modifier-stabil (char waere bei Ctrl ein Steuerzeichen).
    vk = getattr(key, "vk", None)
    if vk is not None:
        if 0x41 <= vk <= 0x5A:       # A–Z
            return chr(vk).lower()
        if 0x30 <= vk <= 0x39:       # 0–9 (Hauptreihe)
            return chr(vk)
        if 0x60 <= vk <= 0x69:       # Numpad 0–9
            return f"num{vk - 0x60}"
        if 0x70 <= vk <= 0x87:       # F1–F24: F21+ kennt pynput nicht als Key-Enum.
            # Gaming-Tastaturen (Corsair G-Tasten via iCUE, Logitech via G HUB)
            # senden ihre Zusatztasten typischerweise als F13–F24.
            return f"f{vk - 0x70 + 1}"
    ch = getattr(key, "char", None)
    if ch:
        return ch.lower()
    # Unbekannte Taste: vk-Token ist voll bindbar (Recorder + Manager nutzen
    # dieselbe Normalisierung) — faengt exotische Zusatztasten ab.
    return f"vk{vk}" if vk is not None else "unknown"


def is_modifier_token(token: str) -> bool:
    return token in MODIFIER_TOKENS


# -- Schonfrist gegen Auto-Repeat (Befund B-5) ------------------------------------------

_SPI_GETKEYBOARDDELAY = 0x0016
# Aufschlag auf die Systemverzoegerung: Der Hook sieht das erste Wiederholungs-
# ereignis nicht exakt zum eingestellten Zeitpunkt (Nachrichtenschleife, Last).
_GRACE_AUFSCHLAG_S = 0.3
# Untergrenze: schuetzt gegen eine absurd kurz eingestellte Verzoegerung.
_GRACE_MIN_S = 0.6
# Ohne Auskunft (Linux, gesperrte API): ueber der groesstmoeglichen Windows-
# Verzoegerung (1000 ms) — lieber eine Heilung zu spaet als jeden Halte-Druck doppelt.
_GRACE_OHNE_AUSKUNFT_S = 1.1


def system_repeat_delay_s():
    """Windows-Verzoegerung bis zur ERSTEN Auto-Wiederholung, in Sekunden.

    `SystemParametersInfo(SPI_GETKEYBOARDDELAY)` liefert 0–3 = 250/500/750/1000 ms.
    None = keine Auskunft (andere Plattform oder Aufruf fehlgeschlagen).
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        wert = ctypes.c_uint()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETKEYBOARDDELAY, 0, ctypes.byref(wert), 0
        )
        if not ok:
            return None
        stufe = int(wert.value)
    except Exception:
        log.debug("Tastatur-Wiederholverzoegerung nicht abfragbar.", exc_info=True)
        return None
    if not 0 <= stufe <= 3:
        return None
    return 0.25 + stufe * 0.25


def repeat_grace_s(delay_fn=system_repeat_delay_s) -> float:
    """Schonfrist, nach der ein erneuter Druck als NEUER Druck zaehlt.

    Befund B-5: Die feste Zahl (0,4 s) lag UNTER der Windows-Wiederholverzoegerung
    (auf diesem Rechner 500 ms). Das erste Wiederholungsereignis einer gehaltenen
    Taste wurde dadurch als „Release fehlte" gedeutet — im Protokoll 53-mal — und
    loeste Pause, KI-Prompting oder Profilwechsel ein zweites Mal aus.
    """
    try:
        delay = delay_fn()
    except Exception:
        delay = None
    if delay is None:
        return _GRACE_OHNE_AUSKUNFT_S
    return max(_GRACE_MIN_S, delay + _GRACE_AUFSCHLAG_S)


def _pretty(token: str) -> str:
    if token in _DISPLAY:
        return _DISPLAY[token]
    if len(token) == 1:
        return token.upper()
    if token.startswith("f") and token[1:].isdigit():
        return token.upper()
    if token.startswith("vk") and token[2:].isdigit():
        return f"Sondertaste ({token[2:]})"  # z. B. G-Taste/Makrotaste ohne Standard-Namen
    return token.replace("_", " ").title()


@dataclass(frozen=True)
class HotkeySpec:
    key: str
    modifiers: frozenset = field(default_factory=frozenset)

    def serialize(self) -> str:
        mods = [m for m in MODIFIER_TOKENS if m in self.modifiers]
        return "+".join(mods + [self.key])

    def display(self) -> str:
        parts = [m for m in MODIFIER_TOKENS if m in self.modifiers] + [self.key]
        return " + ".join(_pretty(p) for p in parts)

    @classmethod
    def parse(cls, text: str) -> "HotkeySpec":
        raw = [t.strip().lower() for t in str(text).split("+") if t.strip()]
        if not raw:
            raise ValueError("Leerer Hotkey.")
        raw = [_NORMALIZE_NAMED.get(t, t) for t in raw]
        mods = frozenset(t for t in raw if t in MODIFIER_TOKENS)
        keys = [t for t in raw if t not in MODIFIER_TOKENS]
        if len(keys) != 1:
            raise ValueError(f"Hotkey braucht genau eine Haupttaste: {text!r}")
        return cls(key=keys[0], modifiers=mods)


class HotkeyManager:
    """pynput-Listener mit Modifier-Tracking; feuert on_activate/on_deactivate je Binding.

    Debounced: Auto-Repeat beim Halten erzeugt keine zweite Aktivierung. Ein Combo
    endet, sobald die Haupttaste ODER ein benoetigter Modifier losgelassen wird.

    Selbstheilend gegen fehlende Release-Events: Makro-/G-Tasten (iCUE, G HUB)
    senden je nach Zuweisung nur ein KeyDOWN ohne KeyUP. Ohne Gegenmassnahme bliebe
    das Binding dauerhaft „aktiv" und JEDER weitere Druck wuerde still als
    Auto-Repeat verschluckt (real aufgetreten: F14-G-Taste nach dem ersten Druck
    tot). Deshalb gilt ein erneuter Druck eines aktiven Bindings nach einer kurzen
    Schonfrist als NEUER Druck — echtes Auto-Repeat (~30 ms Abstand) faellt in die
    Schonfrist und bleibt unterdrueckt.
    """

    # Massgeblich ist die VERZOEGERUNG bis zur ersten Wiederholung (250–1000 ms,
    # Systemeinstellung), nicht der ~30-ms-Takt danach — siehe repeat_grace_s().
    REPEAT_GRACE_S = repeat_grace_s()

    # Alle Manager mit laufendem Listener. Gebraucht fuer genau einen Fall: Bricht
    # der App-Start ab, NACHDEM der Listener lief, haengt ein Low-Level-Tastatur-
    # Hook in einem halbtoten Prozess. Er schluckt und verdoppelt dann Tasten —
    # gemeldet als „komische Tastatureingaben beim Starten". Der Aufraeumer in
    # `ui/desktop.run_desktop` kommt sonst an keine Instanz heran: Die Exception
    # fliegt mitten in `DesktopApp.__init__`, es gibt also kein fertiges Objekt.
    _lebende: list = []

    def __init__(self, on_activate, on_deactivate):
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self._bindings: dict[str, HotkeySpec] = {}
        self._active: dict[str, str] = {}   # name -> ausloesendes Haupttasten-Token
        self._last_press: dict[str, float] = {}  # name -> Zeit des letzten Drucks
        self._mods: set[str] = set()
        self._listener = None
        self._mouse_listener = None
        self._clock = None  # Test-Injektion; None = time.monotonic

    def set_bindings(self, bindings: dict[str, HotkeySpec]) -> None:
        self._bindings = dict(bindings)
        # Aktive Bindings, die es nicht mehr gibt, sauber beenden.
        for name in list(self._active):
            if name not in self._bindings:
                del self._active[name]
                self.on_deactivate(name)
        # Maus-Hook live nachziehen (Bindings koennen sich zur Laufzeit aendern).
        if self._listener is not None:
            self._sync_mouse_listener()

    def _needs_mouse_listener(self) -> bool:
        return any(is_mouse_token(spec.key) for spec in self._bindings.values())

    def _sync_mouse_listener(self) -> None:
        """Maus-Listener nur betreiben, wenn wirklich eine Maustaste gebunden ist.

        Ein Low-Level-Maus-Hook ruft den Python-Filter fuer JEDES Maus-Event auf —
        inklusive jeder Bewegung (hunderte Events/s). Ohne Maus-Binding ist das
        reine Hintergrundlast, also Hook gar nicht erst installieren.
        """
        needed = self._needs_mouse_listener()
        if needed and self._mouse_listener is None:
            from pynput import mouse

            if sys.platform == "win32":
                # Verarbeitung UND Unterdrueckung laufen komplett im
                # win32_event_filter — eine gebundene Maustaste (z. B. Maustaste 5
                # als Push-to-talk) darf ihre normale Funktion in der Ziel-App
                # (Browser: "Vorwaerts"!) nicht mehr ausloesen. Nicht gebundene
                # Kombinationen werden unveraendert durchgereicht.
                self._mouse_listener = mouse.Listener(
                    win32_event_filter=self._win32_mouse_filter
                )
            else:
                # X11/Wayland: Klicks kommen als on_click-Events. Eine Unter-
                # drueckung der Original-Funktion ist hier ohne globalen Pointer-
                # Grab nicht moeglich (und ein Grab wuerde die Maus fuer andere
                # Apps blockieren) — die gebundene Taste loest ihre normale
                # Funktion in der Ziel-App also zusaetzlich aus.
                self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()
        elif not needed and self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None

    def start(self) -> None:
        self.stop()
        self._mods.clear()
        self._active.clear()
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()
        self._sync_mouse_listener()
        if self not in HotkeyManager._lebende:
            HotkeyManager._lebende.append(self)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        try:
            HotkeyManager._lebende.remove(self)
        except ValueError:
            pass

    @classmethod
    def stop_all(cls) -> int:
        """Jeden laufenden Listener abraeumen. Rueckgabe: wie viele es waren.

        Nur fuer den Notfall gedacht (abgebrochener App-Start) — im normalen
        Betrieb raeumt jeder Manager sich selbst ueber `stop()` ab.
        """
        anzahl = 0
        for manager in list(cls._lebende):
            try:
                manager.stop()
                anzahl += 1
            except Exception:
                log.debug("Hotkey-Listener liess sich nicht schliessen.", exc_info=True)
        cls._lebende.clear()
        return anzahl

    # -- Gemeinsame Token-Logik (Tastatur + Maus) -------------------------------------

    def _now(self) -> float:
        import time

        return (self._clock or time.monotonic)()

    def _press_token(self, token: str) -> bool:
        """True = mindestens ein Binding aktiviert (→ Maus-Event unterdruecken)."""
        now = self._now()
        current_mods = frozenset(self._mods)
        matched = False
        for name, spec in self._bindings.items():
            if name in self._active:
                if self._active[name] == token:
                    matched = True
                    # Auto-Repeat (gehaltene Taste, Druecke im ~30-ms-Takt) weiter
                    # unterdruecken. Liegt der letzte Druck aber laenger zurueck,
                    # fehlte das Release (Makro-Taste sendet nur DOWN) → als neuen
                    # Druck werten, sonst waere das Binding dauerhaft verkeilt.
                    if now - self._last_press.get(name, 0.0) > self.REPEAT_GRACE_S:
                        log.info("Hotkey %s: Release fehlte (Makro-Taste?) — "
                                 "Druck zaehlt als neuer Druck.", name)
                        # Erst das fehlende Loslassen nachholen (Befund B-4/D-1):
                        # `RecordingController.press` verwirft jeden Druck, dessen
                        # Taste noch als gedrueckt gilt — die Heilung endete damit
                        # ausgerechnet beim Diktat-Hotkey im Entprell-Schutz, und
                        # die Taste blieb tot. `release()` raeumt `_key_down` auf,
                        # danach wirkt der Druck wie ein echter zweiter.
                        self.on_deactivate(name)
                        self.on_activate(name)
                    self._last_press[name] = now
                continue
            if spec.key == token and spec.modifiers == current_mods:
                self._active[name] = token
                self._last_press[name] = now
                matched = True
                self.on_activate(name)
        return matched

    def _release_token(self, token: str) -> bool:
        matched = False
        for name in list(self._active):
            if self._active[name] == token:
                del self._active[name]
                matched = True
                self.on_deactivate(name)
        return matched

    # -- Tastatur-Callbacks -------------------------------------------------------------

    def _on_press(self, key) -> None:
        token = pynput_token(key)
        if is_modifier_token(token):
            self._mods.add(token)
            return
        self._press_token(token)

    def _on_release(self, key) -> None:
        token = pynput_token(key)
        if is_modifier_token(token):
            self._mods.discard(token)
            for name in list(self._active):
                if token in self._bindings[name].modifiers:
                    del self._active[name]
                    self.on_deactivate(name)
            return
        self._release_token(token)

    # -- Maus (Linux/X11: on_click-Callback) ----------------------------------------------

    def _on_click(self, _x, _y, button, pressed) -> None:
        token = pynput_mouse_token(button)
        if token is None:
            return  # links/rechts/Scroll: nie anfassen
        if pressed:
            self._press_token(token)
        else:
            self._release_token(token)

    # -- Maus (Win32-Hook-Filter) ---------------------------------------------------------

    def _suppress_mouse_event(self) -> None:
        self._mouse_listener.suppress_event()  # separat, damit Tests es stubben koennen

    def _win32_mouse_filter(self, msg, data) -> bool:
        """Laeuft fuer jedes Maus-Event im Hook — muss schnell sein und darf nur
        gebundene Button-Events anfassen. Rueckgabe True = Event normal weiterreichen.
        """
        try:
            token = mouse_msg_token(msg, getattr(data, "mouseData", 0))
        except Exception:
            return True
        if token is None:
            return True  # Bewegung/Raeder/links/rechts: nie anfassen
        if msg in _MOUSE_DOWN_MSGS:
            matched = self._press_token(token)
        else:
            matched = self._release_token(token)
        if matched:
            # WICHTIG: suppress_event() signalisiert per Exception — NICHT fangen.
            self._suppress_mouse_event()
        return True


# -- Legacy: Einzeltasten (CLI-Modus) --------------------------------------------------


def parse_key(name: str):
    """"f9", "ctrl_r", "scroll_lock", einzelne Zeichen wie "§" … (nur Einzeltaste)."""
    name = name.strip().lower()
    if not name:
        raise ValueError("Leerer Hotkey-Name.")
    if "+" in name:  # Kombination → nur die Haupttaste (CLI kann keine Combos)
        name = HotkeySpec.parse(name).key
    if is_mouse_token(name):
        raise ValueError(
            f"Maustasten-Hotkeys ({name!r}) unterstuetzt nur die Desktop-App, "
            f"nicht der --cli-Modus."
        )
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        raise ValueError(
            f"Unbekannter Hotkey: {name!r}. Gueltig sind pynput-Key-Namen "
            f"(f1–f20, ctrl_r, alt_gr, scroll_lock, pause, …) oder ein einzelnes Zeichen."
        ) from None


def keys_equal(pressed, configured) -> bool:
    """Vergleicht ein Listener-Event mit dem konfigurierten Key (robust fuer KeyCode)."""
    if pressed == configured:
        return True
    p_char = getattr(pressed, "char", None)
    c_char = getattr(configured, "char", None)
    return p_char is not None and c_char is not None and p_char.lower() == c_char.lower()
