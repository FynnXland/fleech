"""Profile: welches gilt gerade, was aendert es, wie wechselt man.

Zwei Wege fuehren zu einem Profil — die Zuordnung zur fokussierten App
(`_app_profile_overrides`, ueber Prozessname und optionale Titel-Bedingung)
und die Wahl von Hand (Profil-Hotkey, Pillen-Punkt, Auswahlliste). Der
Hotkey unterscheidet Tippen (durchschalten) von Halten (Liste oeffnen);
deshalb liegen Tastendruck und -loslassen hier und nicht bei den Hotkeys.

Mixin statt eigener Klasse: Der Zustand (settings, overlay, pipeline, recorder)
liegt weiter auf EINEM Objekt. Ein eigenes Controller-Objekt haette neue
Referenzen in den Qt-Objektgraphen gelegt — genau die Konstellation, die in
diesem Projekt schon zu GC-Reihenfolge-Abstuerzen gefuehrt hat.
"""

from __future__ import annotations

import logging
from PySide6.QtCore import QTimer
from ...profiles import APP_STANDARD
from ...protokolltext import inhalt


log = logging.getLogger(__name__)
# Ab dieser Haltedauer gilt der Profil-Hotkey als „gehalten" und oeffnet die
# Auswahlliste. 350 ms: lang genug, dass ein zuegiger Tipp nie versehentlich die
# Liste oeffnet, kurz genug, dass Halten sich nicht wie Warten anfuehlt.
_PROFIL_HALTEN_MS = 350


def overrides_from(item: dict):
    """Profil-Eintrag → ProfileOverrides.

    Modul-Funktion statt Methode: die Umwandlung braucht kein App-Objekt, und die
    Profil-Tests bauen die App als schlankes Fake nach — eine Methode mehr waere
    dort jedes Mal eine Zeile Attrappe.
    """
    from ...profiles import (
        ProfileOverrides,
        profile_command_mode,
        profile_mode,
        profile_sprache,
    )

    mode = str(item.get("intervention", "")).lower()
    tags = [str(t).strip() for t in item.get("tags", []) if str(t).strip()]
    return ProfileOverrides(
        name=str(item.get("name", "") or ""),
        intervention=mode if mode in ("minimal", "standard", "strong") else None,
        style_hints=tags or None,
        mode_slot=profile_mode(item),
        command=profile_command_mode(item),
        auto_send=bool(item.get("auto_send", False)),
        sprache=profile_sprache(item),
    )


class ProfilMixin:
    def _app_profile_overrides(self):
        """App-Profil der Ziel-App aufloesen → ProfileOverrides.

        Kein zugewiesenes Profil → Standardprofil ("Alle") als Fallback; Profile
        global aus → leere Overrides = Verhalten wie in den Einstellungen."""
        from ...profiles import ProfileOverrides, profil_fuer_app

        prof = self.settings.profiles
        if not prof.enabled:
            return ProfileOverrides()
        # Von Hand gewaehltes Profil (Punkt in der Pille) sticht die App-Zuordnung.
        # Ob dieses Diktat eine Mail wird, weiss nur der Sprecher — keine Regel
        # ueber Prozessnamen kann das wissen.
        gewaehlt = getattr(self.settings.profiles, "active", "")
        if gewaehlt:
            for item in prof.items or []:
                if isinstance(item, dict) and item.get("name") == gewaehlt:
                    return overrides_from(item)
            log.info("Gewaehltes Profil %r gibt es nicht mehr — zurueck auf automatisch.",
                     gewaehlt)
            # Befund D-7: Hier stand `self._set_profile("")` — und diese Methode
            # laeuft im VERARBEITUNGS-Thread. `_set_profile` schreibt die
            # Einstellungen (ungeschuetztes settings.save() aus dem Worker) und
            # fasst zwei Mal die Pille an (Qt-Widgets im falschen Thread). Das
            # Aufraeumen geht deshalb ueber den Bus in den GUI-Thread; dieses eine
            # Diktat laeuft ohne Profil-Overrides.
            self.bus.profil_zuruecksetzen.emit()
            return ProfileOverrides()
        app = getattr(self, "_record_app", "") or ""
        title = getattr(self, "_record_title", "") or ""

        # Die Aufloesung selbst steht in `profiles.profil_fuer_app` — sie wird auch
        # von `active_profile_name()` (Ring an der Pille) und von der Apps-Seite
        # gebraucht, und drei Kopien derselben Schleife waeren drei Antworten.
        chosen, regel = profil_fuer_app(prof.items, app, title)
        if chosen is None:
            return ProfileOverrides()
        if regel:
            # Befund G-B9: Die AUTOMATISCHE Aufloesung protokollierte bisher
            # nichts — ob eine Regel griff und welche, war nach dem Diktat nicht
            # mehr feststellbar, auch nicht im Log.
            log.info("Profil %s ueber Regel %r fuer %s / %s",
                     chosen.get("name", ""), regel, app, inhalt(title))
        return overrides_from(chosen)

    def current_app(self) -> str:
        """Prozessname der App, in die gerade diktiert wird bzw. wuerde.

        Waehrend einer Aufnahme der beim Start festgehaltene Wert — sonst waere die
        Auswahlliste eine andere als die, fuer die das Diktat gilt (der Fokus kann
        zwischendurch wandern). Sonst der laufende Fokus-Poll.
        """
        if getattr(self, "recorder", None) is not None and self.recorder.recording:
            gemerkt = getattr(self, "_record_app", "")
            if gemerkt:
                return gemerkt
        # Ausserhalb der Aufnahme: frisch abfragen. Der 3-s-Poll haette hier
        # dieselbe Verzoegerung wie oben — die Auswahlliste zeigte dann die
        # Profile der App, aus der man gerade gekommen ist.
        from ..windowsfocus import foreground_now

        prozess = foreground_now()[0]
        if prozess:
            return prozess
        try:
            return self.notifier.context.foreground_process or ""
        except Exception:
            return ""

    def profile_names(self) -> list:
        """Profile fuer den Schnellwechsel (Punkt, Hotkey, Liste).

        Nicht alle Profile: Wer viele pflegt, schaltet im Alltag nur zwischen
        zweien um — der Rest laesst sich auf der Profilseite global ausblenden,
        und auf der Apps-Seite je Anwendung noch einmal enger fassen. In Claude
        will man zwischen „KI-Prompt" und „Stichpunkte" wechseln, nicht durch
        „E-Mail" und „Formeln" hindurchtippen.
        """
        from ...profiles import quickswitch_for_app

        return quickswitch_for_app(
            self.settings.profiles.items,
            getattr(self.settings.profiles, "app_quick", {}) or {},
            self.current_app(),
        )

    def ziel_app_und_titel(self) -> tuple[str, str]:
        """(Prozessname, Fenstertitel) der App, fuer die das naechste Diktat gilt.

        Waehrend einer Aufnahme die beim Start festgehaltenen Werte — dort landet
        der Text, und danach richtet sich das Profil. Sonst der frische
        Vordergrund; der 3-s-Poll waere hier zu traege (siehe `foreground_now`).
        """
        recorder = getattr(self, "recorder", None)
        if recorder is not None and getattr(recorder, "recording", False):
            return (getattr(self, "_record_app", "") or "",
                    getattr(self, "_record_title", "") or "")
        prozess, titel = "", ""
        try:
            from ..windowsfocus import foreground_now

            prozess, titel = foreground_now()
        except Exception:
            log.debug("Vordergrund nicht abfragbar.", exc_info=True)
        if not prozess:
            try:
                kontext = self.notifier.context
                prozess = getattr(kontext, "foreground_process", "") or ""
                titel = titel or getattr(kontext, "foreground_title", "") or ""
            except Exception:
                pass
        return prozess or "", titel or ""

    def active_profile_name(self) -> str:
        """Profil, das fuer das naechste Diktat gilt — gewaehlt oder automatisch.

        Befund G-B4: Ohne Wahl von Hand nannte diese Methode immer das
        Standardprofil und war damit blind fuer die App-Zuordnung — der Ring an
        der Pille (ihr einziger Dauer-Anzeiger) zeigte in Outlook dieselbe Farbe
        wie im Editor. Jetzt loest sie fuer die aktuelle Ziel-App auf, genau wie
        die Verarbeitung es spaeter tut.
        """
        gewaehlt = getattr(self.settings.profiles, "active", "")
        if gewaehlt:
            return gewaehlt
        from ...profiles import profil_fuer_app

        app, titel = self.ziel_app_und_titel()
        treffer, _regel = profil_fuer_app(self.settings.profiles.items, app, titel)
        if treffer is not None:
            return str(treffer.get("name", "") or "Standard")
        return "Standard"

    def _on_profil_pruefen(self) -> None:
        """GUI-Thread: Eine Aufnahme hat begonnen — welches Profil gilt JETZT?

        Der Aufnahmestart laeuft im pynput-Thread; von dort darf nichts direkt an
        Qt (dieselbe Regel wie bei `prompt_latch_changed`), deshalb der Umweg
        ueber den Bus.

        Der Ring wird immer nachgezogen, die Namens-Kapsel nur bei einem
        Wechsel: Sie bei jedem Diktat zu zeigen waere nach drei Tagen Tapete —
        interessant ist der Moment, in dem eine andere App ein anderes Profil
        mitbringt.
        """
        self._melde_profilfarbe()
        if not getattr(self.settings.profiles, "enabled", True):
            return
        try:
            aktiv = self.active_profile_name()
        except Exception:
            log.debug("Aktives Profil nicht ermittelbar.", exc_info=True)
            return
        if aktiv == getattr(self, "_zuletzt_gemeldetes_profil", None):
            return
        self._zuletzt_gemeldetes_profil = aktiv
        try:
            self.overlay.show_profile(aktiv)
        except Exception:
            log.debug("Profil-Anzeige fehlgeschlagen.", exc_info=True)

    def cycle_profile(self) -> None:
        """Naechstes Profil waehlen; hinter dem letzten wieder „App-Standard".

        Die Wahl bleibt bestehen, bis sie geaendert wird — auch ueber Diktate
        hinweg. Waehrend einer laufenden Aufnahme gilt sie fuer GENAU dieses
        Diktat (die Aufloesung passiert erst beim Verarbeiten).
        """
        if not self._profile_aktiv():
            return
        namen = self.profile_names()
        if not namen:
            return
        stationen = namen + [""]        # "" = automatisch (App-Zuordnung)
        jetzt = getattr(self.settings.profiles, "active", "")
        try:
            naechste = stationen[(stationen.index(jetzt) + 1) % len(stationen)]
        except ValueError:
            naechste = stationen[0]
        self._set_profile(naechste)

    def _on_profil_zuruecksetzen(self) -> None:
        """GUI-Thread: das gewaehlte Profil ist verschwunden — auf „automatisch".

        Gegenstueck zum Signal aus `_app_profile_overrides` (Befund D-7). Eigene
        Methode statt Lambda: eine gebundene Methode legt keine zusaetzliche
        Referenz in den Qt-Objektgraphen.
        """
        self._set_profile("")

    def _profile_aktiv(self) -> bool:
        """Sind Profile global eingeschaltet? Wenn nicht, sagt die Kapsel das.

        Befund G-B11: Punkt und Auswahlliste wechselten weiter munter das Profil,
        die Kapsel nannte einen Namen — und gewirkt hat nichts, weil
        `_app_profile_overrides` bei `enabled=False` sofort leere Overrides
        liefert. Ein Widerspruch genau an der Stelle, die Vertrauen schaffen soll.
        """
        if getattr(self.settings.profiles, "enabled", True):
            return True
        log.info("Profilwechsel abgelehnt — Profile sind global ausgeschaltet.")
        try:
            self.overlay.show_profile("Profile sind ausgeschaltet")
        except Exception:
            log.debug("Profil-Anzeige fehlgeschlagen.", exc_info=True)
        return False

    def _set_profile(self, name: str) -> None:
        """Profil festlegen, merken und kurz anzeigen. "" = automatisch nach App."""
        if not self._profile_aktiv():
            return
        self.settings.profiles.active = name
        self.settings.save()
        aktiv = self.active_profile_name()
        anzeige = name or f"{APP_STANDARD} ({aktiv})"
        # Merken, was zuletzt zu sehen war: Sonst zeigte der naechste
        # Aufnahmestart dieselbe Kapsel gleich noch einmal.
        self._zuletzt_gemeldetes_profil = aktiv
        log.info("Profil gewaehlt: %s", anzeige)
        try:
            self.overlay.show_profile(anzeige)
        except Exception:
            log.debug("Profil-Anzeige fehlgeschlagen.", exc_info=True)
        self._melde_profilfarbe()

    def _melde_profilfarbe(self) -> None:
        """Farbe des aktiven Profils an den Punkt der Pille geben.

        Defensiv gekapselt: Der Punkt ist reine Anzeige. Ginge hier etwas schief,
        duerfte das niemals das Diktieren aufhalten — der Aufruf haengt an
        Profilwechsel und Einstellungsaenderung, also an Wegen, die mitten im
        Arbeiten laufen."""
        try:
            from ...profiles import profile_color

            aktiv = self.active_profile_name()
            treffer = next(
                (i for i in (self.settings.profiles.items or [])
                 if isinstance(i, dict) and str(i.get("name", "")) == aktiv),
                None,
            )
            # Profile global aus = kein bunter Ring: Er wuerde etwas anzeigen,
            # das gerade gar nicht greift.
            farbe = (profile_color(treffer)
                     if treffer is not None and self.settings.profiles.enabled else "")
            self.overlay.set_profile_color(farbe)
        except Exception:
            log.debug("Profilfarbe konnte nicht gesetzt werden.", exc_info=True)

    def _on_profile_key(self, gedrueckt: bool) -> None:
        """UI-Thread: Profil-Taste gedrueckt (True) bzw. losgelassen (False)."""
        if gedrueckt:
            self._on_profile_key_down()
        else:
            self._on_profile_key_up()

    def _on_profile_key_down(self) -> None:
        """Taste gedrueckt: Timer starten. Ob Tippen oder Halten, entscheidet sich
        erst beim Loslassen — deshalb passiert hier bewusst noch nichts."""
        self._profile_key_held = True
        QTimer.singleShot(_PROFIL_HALTEN_MS, self._maybe_open_profile_picker)

    def _maybe_open_profile_picker(self) -> None:
        if not getattr(self, "_profile_key_held", False):
            return                      # war ein Tipp — schon losgelassen
        self._profile_picker_open = True
        self.show_profile_picker()

    def _on_profile_key_up(self) -> None:
        war_gehalten = getattr(self, "_profile_picker_open", False)
        self._profile_key_held = False
        self._profile_picker_open = False
        if not war_gehalten:
            self.cycle_profile()        # kurzer Tipp → naechstes Profil

    def show_profile_picker(self) -> None:
        """Auswahlliste am Mauszeiger (Hotkey halten)."""
        from ..profilepicker import ProfilePicker

        picker = getattr(self, "_profile_picker", None)
        if picker is None:
            picker = self._profile_picker = ProfilePicker()
            picker.chosen.connect(self._set_profile)
        picker.show_at_cursor(self.profile_names(),
                              getattr(self.settings.profiles, "active", ""))
