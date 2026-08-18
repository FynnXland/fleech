"""Text-Injection ins fokussierte Feld: Zwischenablage + simuliertes Strg+V."""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

# Injections laufen in Pipeline-Worker-Threads. Ueberlappen zwei Diktate zeitlich
# (Diktat 2 beginnt, waehrend Diktat 1 noch pastet), wuerde die Sicherung/Wieder-
# herstellung der Zwischenablage sich gegenseitig zerstoeren — deshalb global
# serialisieren (die Paste-Sequenz dauert ohnehin nur ~0,2 s).
_INJECT_LOCK = threading.Lock()

# Aktive Verifikation statt fester Wartezeit: frueher wurde nach dem Schreiben pauschal
# 50 ms gewartet und dann Strg+V gesendet. Electron-Apps (VS Code, Discord, Slack),
# VMs und Remote-Desktop brauchen deutlich laenger und variabler — unter Last (z. B.
# waehrend die GPU transkribiert) kam der Tastendruck dort VOR dem Clipboard-Update
# an und fuegte den ALTEN Inhalt ein. Jetzt wird zurueckgelesen, bis der Text
# bestaetigt ist; das ist im Normalfall sogar schneller als 50 ms.
_CLIPBOARD_POLL_S = 0.02      # Abstand zwischen zwei Lesungen
_CLIPBOARD_TIMEOUT_S = 0.40   # Deckel — danach wird trotzdem gepastet (Fail-Open)
_CLIPBOARD_SETTLE_S = 0.05    # Zwischenablage nicht lesbar → wie frueher kurz warten


class TextInjector:
    def __init__(self, restore_clipboard: bool = True, paste_delay_ms: int = 150,
                 focus_restorer=None):
        self.restore_clipboard = restore_clipboard
        self.paste_delay_ms = paste_delay_ms
        # Callable(target)->bool | None: holt vor dem Paste das Ziel-Feld vom
        # Aufnahme-Start zurueck (Fenster nach vorn + Caret-Ruecklick). Plattform-
        # abhaengig injiziert (fleech.ui.focusrestore.restore_focus_target), damit
        # dieses Modul portabel bleibt.
        self.focus_restorer = focus_restorer
        self._focus_target = None  # FocusTarget | None, pro Aufnahme gesetzt

    def set_focus_target(self, target) -> None:
        """Ziel-Feld, in das der naechste inject() zurueckschreiben soll.

        None = keine Wiederherstellung (Text geht an den aktuellen Fokus).
        Wird von der DesktopApp beim Aufnahme-Start gesetzt, wenn die Option aktiv ist."""
        self._focus_target = target

    # -- testbare Nahtstellen (in Tests gestubbt, damit keine echten Tastendruecke/
    #    Clipboard-Zugriffe passieren) --------------------------------------------------

    def _get_clipboard(self):
        from .clipboard import paste_text

        return paste_text()

    def _clipboard_has_text(self) -> bool:
        from .clipboard import has_text

        return has_text()

    def _set_clipboard(self, text: str) -> None:
        from .clipboard import copy_text

        copy_text(text)

    def _paste_keystroke(self) -> None:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")

    def _restore_focus(self) -> None:
        """Falls ein Ziel-Feld gemerkt wurde: es vor dem Paste zurueckholen."""
        target = self._focus_target
        if target is None or self.focus_restorer is None:
            return
        try:
            if self.focus_restorer(target):
                log.debug("Fokus vor Paste auf Startfeld zurueckgesetzt.")
        except Exception:
            log.debug("Fokus-Wiederherstellung fehlgeschlagen.", exc_info=True)

    # -- Injection --------------------------------------------------------------------

    def inject(self, text: str) -> None:
        if not text:
            return
        with _INJECT_LOCK:
            self._inject_locked(text)

    def _await_clipboard(self, text: str) -> bool:
        """Wartet, bis die Zwischenablage den geschriebenen Text wirklich fuehrt.

        True = bestaetigt. False = nicht bestaetigt (Timeout oder nicht lesbar); es
        wird trotzdem gepastet — lieber ein Versuch als gar kein Text (Fail-Open).
        """
        deadline = time.monotonic() + _CLIPBOARD_TIMEOUT_S
        while True:
            try:
                current = self._get_clipboard()
            except Exception:
                current = None
            if current == text:
                return True
            if current is None:
                # Nicht lesbar (Backend/Rechte) → Verifikation unmoeglich. Wie frueher
                # kurz warten und weitermachen, statt in den Timeout zu laufen.
                time.sleep(_CLIPBOARD_SETTLE_S)
                return False
            if time.monotonic() >= deadline:
                log.warning(
                    "Zwischenablage hat den Text nach %.0f ms nicht bestaetigt — "
                    "fuege trotzdem ein (langsame Ziel-App/VM?).",
                    _CLIPBOARD_TIMEOUT_S * 1000,
                )
                return False
            time.sleep(_CLIPBOARD_POLL_S)

    def _inject_locked(self, text: str) -> None:
        # Nur sichern, wenn wirklich TEXT in der Ablage liegt (Befund B-10). Bei
        # einem kopierten Bild lieferte das Lesen frueher "" — und nach dem Diktat
        # wurde genau dieser leere String zurueckgeschrieben, das Bild war weg.
        previous = None
        if self.restore_clipboard and self._clipboard_has_text():
            previous = self._get_clipboard()

        self._set_clipboard(text)
        self._await_clipboard(text)  # statt blinder Wartezeit (siehe Modul-Kopf)

        # Fokus-Wiederherstellung unmittelbar vor dem Tastendruck: hat der Nutzer nach
        # dem Diktatstart weggeklickt, bringt das das urspruengliche Feld zurueck,
        # sodass Strg+V dort landet (No-op, wenn der Fokus ohnehin noch stimmt).
        self._restore_focus()
        self._paste_keystroke()

        # Erst nach dem Paste die alte Zwischenablage wiederherstellen.
        time.sleep(self.paste_delay_ms / 1000)
        if self.restore_clipboard and previous is not None:
            try:
                self._set_clipboard(previous)
            except Exception:
                pass

    def replace_tail(self, delete_chars: int, text: str) -> None:
        """Loescht die letzten N Zeichen (Backspaces) und fuegt dann text ein.

        Funktioniert nur, wenn der Cursor direkt hinter dem zu ersetzenden Text steht —
        also unmittelbar nach eigenem Diktat, ohne dass der Nutzer geklickt hat.
        """
        with _INJECT_LOCK:  # Backspaces + Paste als atomare Sequenz
            if delete_chars > 0:
                from pynput.keyboard import Controller, Key

                kb = Controller()
                for _ in range(delete_chars):
                    kb.press(Key.backspace)
                    kb.release(Key.backspace)
                    time.sleep(0.004)
            if text:
                self._inject_locked(text)

    def send_enter(self) -> None:
        """Enter druecken — schickt die eben eingefuegte Nachricht ab.

        Nur fuer Profile, in denen das ausdruecklich eingeschaltet ist (KI-Chats).
        Laeuft unter demselben Lock wie das Einfuegen: Sonst koennte zwischen Text
        und Enter ein zweites Diktat dazwischenrutschen und eine halbe Nachricht
        abschicken.
        """
        with _INJECT_LOCK:
            from pynput.keyboard import Controller, Key

            kb = Controller()
            # Kurz warten: Manche Oberflaechen (Web-Chats) brauchen einen Moment,
            # bis der eingefuegte Text im Eingabefeld verarbeitet ist. Wird Enter
            # zu frueh gesendet, geht eine leere Nachricht raus.
            time.sleep(0.12)
            kb.press(Key.enter)
            kb.release(Key.enter)
