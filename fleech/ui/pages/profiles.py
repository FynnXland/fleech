"""Profile: Ausgabeformat, Stil, Sprache und Zuordnung je Profil.

Die breiteste Seite der App — drei Spalten, in denen fast jede Einstellung eines
Profils erreichbar ist. Den System-Prompt dahinter zeigt und aendert der
`PromptDialog`.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from ...history import HistoryStore
from ...usersettings import PROFILE_FORMATS, UserSettings
from ..dialogs import PromptDialog
from ..theme import (
    ACCENT, BORDER_HAIRLINE, CARD, MUTED, NAV_ACTIVE_BG, ROW_HOVER, SIDEBAR, TEXT,
    TRACK, style_button,
)
from ..widgets import HelpBadge, _card, _no_hscroll, _passt, _suchfeld

log = logging.getLogger(__name__)


class ProfilesPage(QWidget):
    """App-Profile: pro Ziel-App automatisch Eingriffsgrad + Stil-Tags fahren.

    Drei Spalten: laufende/haeufige Apps (links) → Doppelklick weist sie dem
    gewaehlten Profil (Mitte) zu; rechts das Detail mit Eingriffsgrad, Stil-Tags
    und zugewiesenen Apps (Doppelklick entfernt). Das Standardprofil ("Alle")
    ist der Fallback fuer alle nicht zugewiesenen Apps. Der grosse Toggle rechts
    neben der Ueberschrift schaltet Profile global — aus = alles ausgegraut.
    """

    _INTERVENTION_LABELS = [("", "Wie Einstellungen (Ausgabe)"),
                            ("minimal", "Minimal (kein LLM-Eingriff)"),
                            ("standard", "Standard"),
                            ("strong", "Strong (starke Glättung)")]

    def __init__(self, settings: UserSettings, store: HistoryStore, on_changed=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_changed = on_changed or (lambda section: None)
        self._loading = False
        from ...usersettings import ensure_default_profile

        ensure_default_profile(self.settings.profiles.items)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        head = QHBoxLayout()
        title = QLabel("Profile")
        title.setStyleSheet(f"color: {TEXT}; font-size: 12pt; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        from PySide6.QtWidgets import QCheckBox

        # Grosser globaler Toggle, rechtsbuendig in der Titelzeile.
        self._global_cb = QCheckBox()
        self._global_cb.setChecked(settings.profiles.enabled)
        self._global_cb.setToolTip("App-Profile global aktivieren/deaktivieren")
        self._global_cb.setCursor(Qt.PointingHandCursor)
        from ..chevron import apply_chevrons

        self._global_cb.setStyleSheet(apply_chevrons(
            f"QCheckBox::indicator {{ width: 22px; height: 22px; border-radius: 6px;"
            f"  border: 1.5px solid {TRACK}; background: transparent; }}"
            f"QCheckBox::indicator:hover {{ border-color: {MUTED}; }}"
            f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};"
            f"  image: url(__CHEV_CHECK__); }}"
        ))
        self._global_cb.toggled.connect(self._on_global_toggled)
        head.addWidget(self._global_cb)
        outer.addLayout(head)
        hint = QLabel("Ein Profil bestimmt, was aus dem Diktat wird. Welche App "
                      "welches Profil bekommt, steht auf der Seite „Apps“ — hier "
                      "gilt „Alle“ als Standard.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        outer.addSpacing(6)

        # Alles unterhalb des Kopfes lebt in einem Container, der bei global-aus
        # komplett deaktiviert (ausgegraut, nicht klickbar) wird.
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        outer.addWidget(self._body, 1)

        # Design-System: Zeilen 7/10-Padding, Radius 8; Hover eine Flaechenstufe heller.
        list_style = (
            f"QListWidget {{ background: transparent; border: none; outline: none;"
            f"  color: {TEXT}; font-size: 9.5pt; }}"
            f"QListWidget::item {{ padding: 7px 10px; border-radius: 8px; }}"
            f"QListWidget::item:hover {{ background: {ROW_HOVER}; }}"
            f"QListWidget::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
        )
        # Checkbox im Design-System: 15px, Radius 4, TRACK-Rahmen → Akzent-Fuellung
        # mit dunklem Haken (generiertes Icon, QSS kann keinen Haken zeichnen).
        cb_style = (
            f"QCheckBox {{ color: {TEXT}; font-size: 9.5pt; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;"
            f"  border: 1.5px solid {TRACK}; background: transparent; }}"
            f"QCheckBox::indicator:hover {{ border-color: {MUTED}; }}"
            f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};"
            f"  image: url(__CHEV_CHECK__); }}"
            f"QCheckBox:disabled {{ color: {MUTED}; }}"
        )
        # Combobox im dunklen Karten-Kontext: geschlossenes Feld UND aufgeklappte Liste
        # in Brand-Farben, damit das Dropdown nicht im Windows-Hell-Stil aufpoppt.
        combo_style = (
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE};"
            f"  border-radius: 8px; padding: 5px 10px; font-size: 9.5pt; }}"
            f"QComboBox:hover {{ background: {ROW_HOVER}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ width: 11px; height: 11px; margin-right: 6px;"
            f"  image: url(__CHEV_DOWN__); }}"
            f"QComboBox QAbstractItemView {{ background: {SIDEBAR}; color: {TEXT};"
            f"  border: 1px solid {TRACK}; outline: none; padding: 4px;"
            f"  selection-background-color: {NAV_ACTIVE_BG}; selection-color: {ACCENT}; }}"
            f"QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 4px 8px;"
            f"  border-radius: 5px; }}"
        )

        # Kleine Abschnitts-Ueberschrift + „?"-Badge — ersetzt die frueheren
        # dauerhaft sichtbaren Erklaertexte (konsistent mit den Einstellungen).
        def _section(text: str, tip: str) -> QWidget:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 4, 0, 0)
            lay.setSpacing(6)
            lab = QLabel(text)
            lab.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; font-weight: 600;")
            lay.addWidget(lab)
            lay.addWidget(HelpBadge(tip))
            lay.addStretch(1)
            return w

        # Links: Profil-Liste (Klick = Auswahl) + Funktions-Schalter darunter.
        # Die frueher hier stehende App-Spalte ist mit v4.7.0 auf die eigene
        # Seite „Apps" gewandert: Ein Profil beantwortet „was wird aus dem
        # Diktat", die Frage „wo gilt das" gehoert zur App, nicht zum Profil.
        profiles_frame, profiles_box = _card("Profile")
        self._profil_suche = _suchfeld("Profil suchen …")
        self._profil_suche.textChanged.connect(lambda _t: self._refresh_profiles(keep_row=True))
        profiles_box.addWidget(self._profil_suche)
        self._profiles_list = QListWidget()
        self._profiles_list.setStyleSheet(list_style)
        _no_hscroll(self._profiles_list)
        self._profiles_list.currentRowChanged.connect(lambda _r: self._refresh_detail())
        profiles_box.addWidget(self._profiles_list, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        add_btn = style_button(QPushButton("Hinzufügen"))
        add_btn.clicked.connect(self._add_profile)
        del_btn = style_button(QPushButton("Löschen"), "ghost")
        del_btn.clicked.connect(self._delete_profile)
        row.addWidget(add_btn, 1)
        row.addWidget(del_btn)
        profiles_box.addLayout(row)
        body.addWidget(profiles_frame, 1)

        # Rechts: Detail des gewaehlten Profils.
        detail_frame, detail_box = _card("Details")
        from PySide6.QtWidgets import QComboBox, QLineEdit

        # Titel = editierbares Feld: Klick hinein → Profil umbenennen (Enter/Fokusverlust
        # uebernimmt). Sieht wie eine Ueberschrift aus, verhaelt sich wie ein Eingabefeld.
        self._detail_title = QLineEdit("")
        self._detail_title.setFrame(False)
        self._detail_title.setStyleSheet(
            f"QLineEdit {{ color: {TEXT}; font-size: 11pt; font-weight: 600;"
            f"  background: transparent; border: none; padding: 0; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {ACCENT}; }}"
        )
        self._detail_title.setToolTip("Zum Umbenennen anklicken, Enter übernimmt")
        self._detail_title.editingFinished.connect(self._on_rename_profile)
        title_row = QWidget()
        trow = QHBoxLayout(title_row)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(6)
        trow.addWidget(self._detail_title, 1)
        trow.addWidget(HelpBadge("Name anklicken und tippen — Enter benennt das Profil um."))
        detail_box.addWidget(title_row)

        from ..chevron import apply_chevrons

        # Ausgabeformat: die Einstellung, die aus einem Profil mehr macht als eine
        # Glaettungsstufe. Der frueher entfernte „Modus-Slot" ist damit zurueck —
        # diesmal mit einem Zweck, den man beim Diktieren sofort merkt.
        detail_box.addWidget(_section(
            "Ausgabeformat", "Was aus dem Diktat wird. „Diktat“ = bereinigter Text "
            "wie gesprochen. „E-Mail“ und „KI-Prompt“ formulieren um: Anrede und "
            "Absätze bzw. knappe Stichpunkte für eine KI.",
        ))
        self._profile_format_combo = QComboBox()
        self._profile_format_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in PROFILE_FORMATS:
            self._profile_format_combo.addItem(label, value)
        self._profile_format_combo.currentIndexChanged.connect(
            self._on_profile_format_changed
        )
        detail_box.addWidget(self._profile_format_combo)
        # Der Prompt hinter dem Format — sichtbar und aenderbar. Bis 5.1.0 war er
        # eine Blackbox: Man sah, DASS ein Profil anders formuliert, aber nie warum.
        self._prompt_btn = style_button(QPushButton("Prompt ansehen …"), "ghost")
        self._prompt_btn.clicked.connect(self._prompt_bearbeiten)
        detail_box.addWidget(self._prompt_btn)

        self._quick_cb = QCheckBox("Im Schnellwechsel zeigen")
        self._quick_cb.setCursor(Qt.PointingHandCursor)
        self._quick_cb.setStyleSheet(apply_chevrons(cb_style))
        self._quick_cb.setToolTip(
            "Punkt in der Pille, Profil-Hotkey und Auswahlliste gehen nur durch "
            "diese Profile. Wer viele pflegt, aber im Alltag zwischen zweien "
            "wechselt, blendet den Rest hier aus."
        )
        self._quick_cb.toggled.connect(self._on_quick_toggled)
        detail_box.addWidget(self._quick_cb)

        # Ab hier: alles, was der Normalfall NICHT braucht. Der Umschalter unten
        # blendet diesen Block aus — ein Profil besteht dann aus Name, Ausgabeformat
        # und Schnellwechsel. Die App-Zuweisung steckt bewusst hier drin: Profile
        # sind seit den Ausgabeformaten in erster Linie eine Wahl beim Sprechen,
        # nicht eine Automatik nach Prozessnamen.
        self._advanced_box = QWidget()
        adv = QVBoxLayout(self._advanced_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(detail_box.spacing())
        detail_box.addWidget(self._advanced_box, 1)
        detail_box = adv

        detail_box.addWidget(_section(
            "Eingriff", "Wie stark die KI das Diktat glättet. „Wie Einstellungen“ = "
            "globaler Wert aus Einstellungen → Ausgabe.",
        ))
        self._intervention_combo = QComboBox()
        self._intervention_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in self._INTERVENTION_LABELS:
            self._intervention_combo.addItem(label, value)
        self._intervention_combo.currentIndexChanged.connect(self._on_intervention_changed)
        detail_box.addWidget(self._intervention_combo)

        # Gesprochenes Safe-Word je Profil: im Meeting/Grossraum unpassend und
        # zufaellig ausloesbar. Der »-Knopf in der Pille bleibt immer verfuegbar.
        detail_box.addWidget(_section(
            "Safe-Word (gesprochen)", "Ob in diesen Apps ein gesprochenes Safe-Word "
            "Befehle auslöst. Der »-Knopf in der Pille funktioniert immer.",
        ))
        self._profile_command_combo = QComboBox()
        self._profile_command_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in (("", "Wie Einstellungen (Ausgabe)"),
                             ("on", "An — gesprochenes Safe-Word erlaubt"),
                             ("off", "Aus — nur über den »-Knopf")):
            self._profile_command_combo.addItem(label, value)
        self._profile_command_combo.currentIndexChanged.connect(
            self._on_profile_command_changed
        )
        detail_box.addWidget(self._profile_command_combo)

        # Der Stil-Tag-Editor ist mit v3.7.2 entfallen. Die Profilseite beantwortet
        # jetzt genau eine Frage — „in welcher App wie stark eingreifen" — statt
        # nebenbei noch Stilvorgaben und Modus-Slots anzubieten, die in der Praxis
        # leer blieben. Das Feld `tags` bleibt in den Settings erhalten (alte
        # settings.json laden unveraendert) und wirkt weiter, falls jemand es dort
        # von Hand pflegt; die Pipeline nimmt es unveraendert entgegen.

        detail_box.addWidget(_section(
            "Nachricht absenden", "Nach dem Einfügen zusätzlich Enter drücken — "
            "praktisch in KI-Chats, gefährlich in E-Mails.",
        ))
        self._autosend_cb = QCheckBox("Diktat direkt abschicken")
        self._autosend_cb.setStyleSheet(apply_chevrons(cb_style))
        self._autosend_cb.setCursor(Qt.PointingHandCursor)
        self._autosend_cb.setToolTip(
            "Gilt nur für die diesem Profil zugewiesenen Apps und nur bei einem "
            "normalen Diktat — nach einem Befehl oder einem Rohtext-Rückfall wird "
            "nie automatisch gesendet."
        )
        self._autosend_cb.toggled.connect(self._on_autosend_toggled)
        detail_box.addWidget(self._autosend_cb)

        # Ohne diesen Dehnungs-Platzhalter verteilt Qt den freien Platz GLEICHMAESSIG
        # zwischen allen Zeilen, sobald der erweiterte Block (mit der App-Liste, die
        # den Raum bisher aufgefangen hat) versteckt ist: Beschriftungen standen dann
        # weit von ihren Bedienelementen entfernt und die Karte sah leer aus.
        # WICHTIG in die AEUSSERE Karte — `detail_box` zeigt hier laengst auf den
        # erweiterten Container, dort waere der Platzhalter mit versteckt.
        detail_frame.layout().addStretch(1)

        self._advanced_cb = QCheckBox("Erweiterte Einstellungen")
        self._advanced_cb.setCursor(Qt.PointingHandCursor)
        self._advanced_cb.setStyleSheet(apply_chevrons(cb_style))
        self._advanced_cb.setToolTip(
            "Zeigt Eingriffsgrad, Safe-Word und automatisches Absenden. Ohne "
            "das besteht ein Profil aus Name, Ausgabeformat und Schnellwechsel "
            "— für die meisten genug. Welche App welches Profil bekommt, steht "
            "auf der Seite „Apps“."
        )
        self._advanced_cb.setChecked(bool(self.settings.interface.profiles_advanced))
        self._advanced_cb.toggled.connect(self._on_advanced_toggled)
        detail_frame.layout().addWidget(self._advanced_cb)
        self._advanced_box.setVisible(self._advanced_cb.isChecked())
        body.addWidget(detail_frame, 1)

        # Der Funktions-Balken (Mathe-Funktion) ist mit v3.7.4 entfallen: Er
        # schaltete dasselbe Feld wie die Formel-Erkennung in den Einstellungen —
        # zwei Schalter fuer einen Wert, an zwei weit auseinanderliegenden Orten.
        # Auf der Profilseite hatte er ohnehin nichts zu suchen: Er galt global,
        # unabhaengig von jedem Profil.

        self._apply_body_enabled(settings.profiles.enabled)

    # -- Datenzugriff -----------------------------------------------------------------

    def _items(self) -> list:
        return self.settings.profiles.items

    def _current_index(self) -> int:
        """Index in `items` — aus dem Item, NICHT aus der Zeilennummer.

        Mit dem Suchfeld sind das zwei verschiedene Dinge: Zeile 0 einer gefilterten
        Liste kann Profil 5 sein. Wer hier die Zeilennummer nimmt, benennt oder
        loescht stillschweigend das falsche Profil.
        """
        item = self._profiles_list.currentItem()
        if item is None:
            return -1
        wert = item.data(Qt.UserRole)
        return int(wert) if isinstance(wert, int) else -1

    def _current_profile(self) -> dict | None:
        index = self._current_index()
        items = self._items()
        return items[index] if 0 <= index < len(items) else None

    def _save(self) -> None:
        self.settings.save()

    # -- Aufbau/Refresh ------------------------------------------------------------------

    def refresh(self) -> None:
        from ...usersettings import ensure_default_profile

        ensure_default_profile(self._items())
        self._refresh_profiles(keep_row=True)

    # BEWUSST OHNE die Brand-Akzentfarbe (#35C0D8): die steht im ganzen Programm
    # fuer „ausgewaehlt". Als Kategoriefarbe gelesen wirkte der E-Mail-Punkt wie
    # eine Markierung — genau so wurde es gemeldet.
    _MODE_DOT_COLORS = {"math": "#AA78F0", "prompt": "#E8A13C",
                        "email": "#6E86C8", "summary": "#7FD1A6"}
    # Kurzform des Ausgabeformats hinter dem Namen. Beantwortet die Frage „was macht
    # dieses Profil?" in der LISTE — vorher musste man jedes Profil anklicken.
    _MODE_KURZ = {"email": "E-Mail", "prompt": "KI-Prompt", "math": "Formeln",
                  "summary": "Stichpunkte"}

    @staticmethod
    def _mode_dot_icon(color: str) -> QIcon:
        """Kleiner gefuellter Punkt in der Modus-Farbe — dieselbe Sprache wie der
        Status-Punkt im Overlay (violett = Mathe, amber = KI-Prompting)."""
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(8, 8), 4, 4)
        p.end()
        return QIcon(pm)

    def _refresh_profiles(self, keep_row: bool = False) -> None:
        from ...usersettings import profile_in_quickswitch, profile_mode

        previous = self._current_index() if keep_row else 0
        suche = self._profil_suche.text()
        self._loading = True
        self._profiles_list.clear()
        for index, profile in enumerate(self._items()):
            name = profile.get("name", "Profil")
            if profile.get("default"):
                name += "  („Alle“)"
            kurz = self._MODE_KURZ.get(profile_mode(profile), "")
            # „E-Mail · E-Mail" ist keine Zusatzinfo, sondern Laerm: Die
            # Standardprofile heissen wie ihr Format. Nur anhaengen, wenn der
            # Name das Format NICHT schon sagt.
            if kurz and kurz.lower() not in name.lower():
                name += f"   ·  {kurz}"
            if not profile_in_quickswitch(profile):
                # Ausgeblendete Profile bleiben sichtbar, aber erkennbar: sonst
                # sucht man spaeter, warum der Schnellwechsel eines auslaesst.
                name += "   (nicht im Schnellwechsel)"
            if not _passt(name, suche):
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, index)
            # Modus-Slot direkt in der Liste sichtbar machen (Design-System):
            # farbiger Punkt in der Modus-Farbe vor dem Namen.
            mode = profile_mode(profile)
            if mode in self._MODE_DOT_COLORS:
                item.setIcon(self._mode_dot_icon(self._MODE_DOT_COLORS[mode]))
            self._profiles_list.addItem(item)
        self._loading = False
        if self._profiles_list.count():
            zeilen = [i for i in range(self._profiles_list.count())
                      if self._profiles_list.item(i).data(Qt.UserRole) == previous]
            self._profiles_list.setCurrentRow(zeilen[0] if zeilen else 0)
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        profile = self._current_profile()
        self._loading = True
        if profile is None:
            self._detail_title.setText("")
            self._detail_title.setEnabled(False)
            self._profile_command_combo.setCurrentIndex(0)
            self._loading = False
            return
        self._detail_title.setEnabled(True)
        self._detail_title.setText(profile.get("name", "Profil"))
        from ...usersettings import profile_mode

        from ...usersettings import profile_command_mode

        self._profile_command_combo.setCurrentIndex(
            ["", "on", "off"].index(profile_command_mode(profile))
        )
        self._autosend_cb.setChecked(bool(profile.get("auto_send", False)))
        values = [v for v, _l in self._INTERVENTION_LABELS]
        current = profile.get("intervention", "")
        self._intervention_combo.setCurrentIndex(
            values.index(current) if current in values else 0
        )
        from ...usersettings import profile_mode

        formate = [v for v, _l in PROFILE_FORMATS]
        fmt = profile_mode(profile)
        self._profile_format_combo.setCurrentIndex(
            formate.index(fmt) if fmt in formate else 0
        )
        self._aktualisiere_prompt_knopf(fmt)
        from ...usersettings import profile_in_quickswitch

        self._quick_cb.setChecked(profile_in_quickswitch(profile))
        self._loading = False

    # -- Interaktionen ---------------------------------------------------------------------

    def _apply_body_enabled(self, on: bool) -> None:
        """Bei global-aus den GESAMTEN Bereich unter dem Kopf klar sichtbar ausgrauen:
        nicht nur deaktivieren (Qt graut nur dezent), sondern zusaetzlich per
        Opacity-Effekt deutlich abdunkeln. Effekt nur im Aus-Zustand setzen — im
        Normalbetrieb kein Effekt (verhindert Render-Eigenheiten beim Scrollen)."""
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        self._body.setEnabled(on)
        if on:
            self._body.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self._body)
            effect.setOpacity(0.30)
            self._body.setGraphicsEffect(effect)

    def _on_global_toggled(self, on: bool) -> None:
        self.settings.profiles.enabled = on
        self._apply_body_enabled(on)
        self._save()


    def _on_autosend_toggled(self, on: bool) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["auto_send"] = bool(on)
            self._save()

    def _on_profile_command_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["command"] = self._profile_command_combo.currentData()
            self._save()


    # -- Prompt hinter dem Ausgabeformat (F4a) -----------------------------------------

    # Format → Prompt-Datei. „Formeln" fehlt bewusst: Der Formel-Parser arbeitet
    # deterministisch ohne Modell, es gibt dort keinen Prompt zum Ansehen.
    _FORMAT_PROMPTS = {"": "cleanup", "summary": "summary", "email": "email",
                       "prompt": "prompt_engineer"}

    def _aktualisiere_prompt_knopf(self, fmt: str) -> None:
        datei = self._FORMAT_PROMPTS.get(fmt or "")
        self._prompt_btn.setEnabled(bool(datei))
        if not datei:
            self._prompt_btn.setText("Kein Prompt (Formeln laufen ohne Modell)")
            return
        from ...prompts import user_prompt_path

        eigen = user_prompt_path(datei).is_file()
        self._prompt_btn.setText(
            "Prompt bearbeiten  ·  eigene Fassung" if eigen else "Prompt ansehen …")

    def _prompt_bearbeiten(self) -> None:
        from ...usersettings import profile_mode

        profile = self._current_profile()
        if profile is None:
            return
        datei = self._FORMAT_PROMPTS.get(profile_mode(profile) or "")
        if not datei:
            return
        # Referenz halten, sonst raeumt der GC den Dialog sofort wieder ab.
        self._prompt_dialog = PromptDialog(datei, self)
        self._prompt_dialog.gespeichert.connect(
            lambda: (self._aktualisiere_prompt_knopf(profile_mode(profile)),
                     self._on_changed("prompts")))
        self._prompt_dialog.show()

    def _on_rename_profile(self) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        name = self._detail_title.text().strip()
        if profile is None or not name or name == profile.get("name"):
            return
        profile["name"] = name
        self._save()
        self._refresh_profiles(keep_row=True)

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_box.setVisible(bool(checked))
        if self._loading:
            return
        self.settings.interface.profiles_advanced = bool(checked)
        self.settings.save()

    def _on_quick_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["quick"] = bool(checked)
            self._save()
            self._refresh_profiles(keep_row=True)

    def _on_profile_format_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["mode"] = self._profile_format_combo.currentData()
            self._save()

    def _on_intervention_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["intervention"] = self._intervention_combo.currentData()
            self._save()

    def _add_profile(self) -> None:
        items = self._items()
        items.append({"name": f"Profil {len(items)}", "intervention": "standard",
                      "tags": [], "apps": []})
        self._save()
        # Suche leeren: Sonst legt man bei aktivem Filter ein Profil an, das die
        # Suche nicht trifft — es waere sofort unsichtbar und wirkte wie ein
        # fehlgeschlagener Klick.
        if self._profil_suche.text():
            self._loading = True
            self._profil_suche.clear()
            self._loading = False
        self._refresh_profiles()
        self._profiles_list.setCurrentRow(self._profiles_list.count() - 1)

    def _delete_profile(self) -> None:
        row = self._current_index()
        items = self._items()
        if 0 <= row < len(items) and not items[row].get("default"):
            del items[row]   # das Standardprofil ist nicht loeschbar
            self._save()
            self._refresh_profiles()
