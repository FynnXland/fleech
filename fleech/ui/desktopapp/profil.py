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
        from ...profiles import (
            ProfileOverrides,
            app_rule_matches,
            parse_app_rule,
            profile_command_mode,
            profile_mode,
        )

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
            self._set_profile("")
        app = getattr(self, "_record_app", "") or ""
        title = getattr(self, "_record_title", "") or ""

        # Zwei Durchlaeufe nach Spezifitaet: Eintraege MIT Titel-Bedingung gewinnen
        # immer gegen den blossen Prozessnamen. Sonst haenge die Zuordnung an der
        # Reihenfolge der Profile — „Code.exe" in einem Profil wuerde
        # „Code.exe :: Fleech" in einem anderen je nach Listenposition verdecken,
        # und der Nutzer haette keine Handhabe, das zu steuern.
        chosen = None
        default_item = None
        candidates = []
        for item in prof.items or []:
            if not isinstance(item, dict):
                continue
            if item.get("default"):
                default_item = item
                continue
            candidates.append(item)

        for want_title in (True, False):
            paare = [(item, entry) for item in candidates
                     for entry in item.get("apps", [])
                     if bool(parse_app_rule(entry)[1]) == want_title]
            # Innerhalb des Titel-Durchgangs entschied bisher die Reihenfolge der
            # Profile (Befund G-B7): „chrome.exe :: Gmail" fing „chrome.exe ::
            # Gmail - Entwurf" ab, wenn es weiter oben stand — die feinere Regel
            # griff nie. Genauer schlaegt allgemeiner, also die laengere Bedingung
            # zuerst. Gleich lange Bedingungen behalten ihre Reihenfolge (stabil).
            if want_title:
                paare.sort(key=lambda p: len(parse_app_rule(p[1])[1]), reverse=True)
            for item, entry in paare:
                if app and app_rule_matches(entry, app, title):
                    chosen = item
                    # Befund G-B9: Die AUTOMATISCHE Auflösung protokollierte bisher
                    # nichts — ob eine Regel griff und welche, war nach dem Diktat
                    # nicht mehr feststellbar, auch nicht im Log.
                    log.info("Profil %s ueber Regel %r fuer %s / %r",
                             item.get("name", ""), entry, app, title)
                    break
            if chosen is not None:
                break

        if chosen is None:
            chosen = default_item
        if chosen is None:
            return ProfileOverrides()
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

    def active_profile_name(self) -> str:
        """Profil, das fuer das naechste Diktat gilt — gewaehlt oder automatisch."""
        gewaehlt = getattr(self.settings.profiles, "active", "")
        if gewaehlt:
            return gewaehlt
        for item in self.settings.profiles.items or []:
            if isinstance(item, dict) and item.get("default"):
                return str(item.get("name", "Standard"))
        return "Standard"

    def cycle_profile(self) -> None:
        """Naechstes Profil waehlen; hinter dem letzten wieder „App-Standard".

        Die Wahl bleibt bestehen, bis sie geaendert wird — auch ueber Diktate
        hinweg. Waehrend einer laufenden Aufnahme gilt sie fuer GENAU dieses
        Diktat (die Aufloesung passiert erst beim Verarbeiten).
        """
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

    def _set_profile(self, name: str) -> None:
        """Profil festlegen, merken und kurz anzeigen. "" = automatisch nach App."""
        self.settings.profiles.active = name
        self.settings.save()
        anzeige = name or f"{APP_STANDARD} ({self.active_profile_name()})"
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
