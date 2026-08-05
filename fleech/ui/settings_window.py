"""Einstellungs-Panel: Kategorien-Navigation, sofortiges Speichern, ruhige Optik.

Einbettbares QWidget (Seite im MainWindow). Jede Aenderung wird direkt in
settings.json persistiert und — wo moeglich — live angewandt (on_changed(section)
informiert die DesktopApp).

Layout-Prinzip: Bezeichnung links(-buendig), Steuerelement rechts, JEDE Einstellung
mit einem „?"-Badge, dessen Hover-Tooltip die Bedeutung in EINEM kurzen Satz erklaert.
Nur die einzeilige Seiten-Einordnung oben bleibt sichtbar.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from ..usersettings import (
    OVERLAY_COMPACTNESS, TOAST_LEVELS, UserSettings, apply_overlay_compactness,
    apply_toast_level, overlay_compactness, toast_level,
)
from . import autostart
from .theme import (
    ACCENT, ACCENT_DIM, BORDER_HAIRLINE, CARD, MUTED, NAV_ACTIVE_BG, ROW_HOVER,
    SIDEBAR, TEXT, TRACK, button_qss, style_button,
)
from .widgets import HelpBadge, WortListe

log = logging.getLogger(__name__)

# Dunkles Panel-Styling nach Design-System-Token. Nur Leaf-Controls per Typ-Selektor
# stylen — ein Selektor auf Container (QFrame, nacktes background:) kaskadiert auf alle
# Kind-Widgets (QLabel erbt von QFrame) und malt Pillen hinter Labels.
_PANEL_QSS = f"""
QListWidget {{
    background: transparent; border: none; outline: none;
    color: {MUTED}; font-size: 9.5pt; font-weight: 500;
}}
QListWidget::item {{ padding: 6px 10px; border-radius: 8px; margin: 1px 6px; }}
QListWidget::item:hover {{ background: {CARD}; color: {TEXT}; }}
QListWidget::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLineEdit, QComboBox, QPlainTextEdit {{
    background: {CARD}; color: {TEXT};
    border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px; padding: 5px 10px;
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT_DIM}; }}
QComboBox:hover {{ background: {ROW_HOVER}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    width: 11px; height: 11px; margin-right: 6px; image: url(__CHEV_DOWN__);
}}
QComboBox QAbstractItemView {{
    background: {SIDEBAR}; color: {TEXT}; border: 1px solid {TRACK};
    outline: none; padding: 4px;
    selection-background-color: {NAV_ACTIVE_BG}; selection-color: {ACCENT};
}}
QComboBox QAbstractItemView::item {{
    min-height: 24px; padding: 4px 8px; border-radius: 5px;
}}
{button_qss("default")}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1.5px solid {TRACK}; background: transparent;
}}
QCheckBox::indicator:hover {{ border-color: {MUTED}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url(__CHEV_CHECK__);
}}
QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 13px; height: 13px; margin: -5px 0; border-radius: 6px; background: {TEXT};
}}
"""

_INTERVENTION_HELP = {
    "minimal": "Fast Rohtext, keine KI — am schnellsten.",
    "standard": "Füllwörter weg, saubere Zeichensetzung. (Empfohlen)",
    "strong": "Stärkere Glättung mit Absätzen und Aufzählungen.",
}
_MATH_LEVEL_HELP = {
    "auto": "Gesprochene Formeln werden im Fließtext erkannt und als LaTeX "
            "geschrieben — vollständig auf diesem Rechner, ohne Umschalten. "
            "Mehrdeutige Ausdrücke werden nach den üblichen Vorrangregeln "
            "übersetzt und in der Vorschau als „geraten“ markiert; sprich "
            "„Klammer auf … Klammer zu“ mit, wenn es eindeutig sein soll.",
    "off": "Keine Formel-Erkennung. Alles wird als normaler Text behandelt.",
}


def _hint(text: str) -> QLabel:
    """Einzeilige Seiten-Einordnung oben — der einzige dauerhaft sichtbare Hinweis."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #808088; font-size: 8pt;")
    return label


class SettingsPanel(QWidget):
    # „Oberfläche" ist entfallen: Die zwölf Sichtbarkeits-Checkboxen sind an die
    # Karten selbst gewandert (Rechtsklick → Ausblenden). Zurueckholen sammelt der
    # Knopf auf der Seite „Allgemein".
    PAGES = ["Allgemein", "Aufnahme", "Audio-Fokus", "Overlay",
             "Sounds", "Benachrichtigungen", "Ausgabe", "Textersetzung",
             "Advanced"]

    def __init__(self, settings: UserSettings, on_changed, list_microphones,
                 test_hooks=None, hotkey_capture_guard=None, on_clear_history=None,
                 overlay_hooks=None, wortprobe_fn=None):
        super().__init__()
        self.settings = settings
        self._on_changed = on_changed          # callback(section: str)
        self._list_microphones = list_microphones
        self._test_hooks = test_hooks or {}  # "toast": fn, "sound": fn
        self._hotkey_capture_guard = hotkey_capture_guard  # (before, after) | None
        self._on_clear_history = on_clear_history
        # "edit_toggle": fn()->bool, "reset": fn(), "apply_preset": fn(key)
        self._overlay_hooks = overlay_hooks or {}
        # fn(begriff, sekunden) -> Probe. None = kein Mikrofonzugriff (Tests,
        # Onboarding) → der Einsprech-Knopf erscheint dann gar nicht erst.
        self._wortprobe_fn = wortprobe_fn
        self._debounced_commits: list = []  # (QTimer, commit_fn) der Zeilen-Editoren
        self._loading = True

        from .chevron import apply_chevrons

        self.setStyleSheet(apply_chevrons(_PANEL_QSS))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 12, 8, 8)
        outer.setSpacing(8)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        self._nav = QListWidget()
        self._nav.addItems(self.PAGES)
        # Breit genug fuer den laengsten Eintrag („Benachrichtigungen") — nie abschneiden.
        self._nav.setFixedWidth(178)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pages = QStackedWidget()
        content.addWidget(self._nav)
        content.addWidget(self._pages, 1)
        outer.addLayout(content, 1)
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)

        # Footer: Speichern-Button + kurzes Bestaetigungs-Feedback. Einstellungen
        # greifen zwar sofort (jede Aenderung wird direkt persistiert) — der Button
        # gibt explizit Gewissheit und committet offene Textfelder verbindlich.
        # Design-System: Hairline-Trenner darueber, Speichern als Primary-Button.
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {BORDER_HAIRLINE}; border: none;")
        outer.addWidget(divider)
        footer = QHBoxLayout()
        footer.setContentsMargins(8, 2, 4, 0)
        hint = QLabel("Änderungen werden sofort übernommen · „?“ erklärt die Einstellung.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 8pt;")
        self._save_status = QLabel("")
        self._save_status.setStyleSheet(f"color: {ACCENT}; font-size: 9pt; font-weight: 600;")
        save_btn = style_button(QPushButton("Speichern"), "primary")
        save_btn.clicked.connect(self._save_now)
        footer.addWidget(hint)
        footer.addStretch(1)
        footer.addWidget(self._save_status)
        footer.addWidget(save_btn)
        outer.addLayout(footer)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self._save_status.setText(""))

        self._build_pages()
        self._nav.setCurrentRow(0)
        self._loading = False

    # ------------------------------------------------------------------ Hilfsbauer --

    def _page(self) -> tuple[QWidget, QFormLayout]:
        # Jede Seite scrollt bei Bedarf — lange Seiten (Benachrichtigungen) bleiben
        # auch in kleinen Fenstern vollstaendig erreichbar.
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        # Nie horizontal scrollen — lange Beschriftungen brechen um, statt eine
        # Links-rechts-Scrollleiste am unteren Rand zu erzeugen.
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(20, 8, 20, 16)
        form_holder = QWidget()
        form = QFormLayout(form_holder)
        # Linksbuendige Bezeichnungen (ruhiger als rechtsbuendig „flatternde" Labels).
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        outer.addWidget(form_holder)
        outer.addStretch(1)
        page.setWidget(holder)
        self._pages.addWidget(page)
        return page, form

    def _row_label(self, text: str, help_text: str = ""):
        """(Label-Widget, Badge-oder-None) fuer eine Formularzeile: Bezeichnung +
        „?"-Badge (Hover-Tooltip). Das Badge wird zurueckgegeben, damit Combos die
        Erklaerung zur gewaehlten Option live nachziehen koennen."""
        if not help_text:
            return text, None
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        label = QLabel(text)
        label.setStyleSheet(f"color: {TEXT};")
        badge = HelpBadge(help_text)
        lay.addWidget(label)
        lay.addWidget(badge)
        lay.addStretch(1)  # linksbuendig
        return w, badge

    def reload_dictionary(self) -> None:
        """Woerterbuch-Seite neu befuellen — noetig, wenn Regeln oder Ignorier-
        Eintraege von aussen dazukamen (Ein-Klick-Uebernahme/„Ignorieren" aus den
        Insights)."""
        editor = getattr(self, "_dictionary_editor", None)
        if editor is None:
            return
        self._loading = True
        try:
            editor.setPlainText("\n".join(str(x) for x in self.settings.output.dictionary))
            ignores = getattr(self, "_ignores_editor", None)
            if ignores is not None:
                ignores.setPlainText(
                    "\n".join(str(x) for x in self.settings.output.dictionary_ignores)
                )
        finally:
            self._loading = False
        self._refresh_priming_hint()

    # -- Projekt-Gedaechtnis (fleech/kontext.py) ---------------------------------------

    def _kontext_speicher(self):
        """Eigene Verbindung fuer die Anzeige — die Pipeline laeuft in einem
        anderen Thread, und SQLite-Verbindungen gehoeren dem, der sie oeffnet."""
        try:
            from ..kontext import KontextSpeicher

            return KontextSpeicher()
        except Exception:
            log.debug("Gedaechtnis nicht lesbar.", exc_info=True)
            return None

    def _on_kontext_toggled(self, an: bool) -> None:
        self.settings.advanced.kontext_lernen = bool(an)
        self._changed("output")
        self._refresh_kontext_zeile()

    def _refresh_kontext_zeile(self) -> None:
        """Was gelernt wurde, in einer Zeile — sonst waere es eine Blackbox und
        man saehe nie, warum ein Wort ploetzlich anders geschrieben wird."""
        label = getattr(self, "_kontext_zeile", None)
        if label is None:
            return
        if not getattr(self.settings.advanced, "kontext_lernen", True):
            label.setText("Aus — es wird nichts gelernt und nichts verwendet.")
            return
        speicher = self._kontext_speicher()
        if speicher is None:
            label.setText("")
            return
        kontexte = speicher.kontexte()
        if not kontexte:
            label.setText("Noch nichts gelernt — das kommt mit den ersten Diktaten.")
            return
        apps = {a for a, _seg, _n in kontexte}
        begriffe = sum(n for _a, seg, n in kontexte if seg == "")
        # Die drei groessten mit Beispielen: abstrakte Zahlen sagen wenig, ein
        # „claude.exe: MCP-Server, Design-System" beantwortet die Frage sofort.
        zeilen = []
        for app in sorted(apps)[:3]:
            beispiele = speicher.priming_begriffe(app, limit=4)
            if beispiele:
                zeilen.append(f"{app}: {', '.join(beispiele)}")
        text = f"{begriffe} Begriffe in {len(apps)} Programmen"
        if zeilen:
            text += " — " + " · ".join(zeilen)
        label.setText(text)

    def _kontext_vergessen(self) -> None:
        speicher = self._kontext_speicher()
        if speicher is None:
            return
        anzahl = speicher.vergiss()
        log.info("Projekt-Gedaechtnis geleert (%d Eintraege).", anzahl)
        self._refresh_kontext_zeile()

    def _refresh_priming_hint(self) -> None:
        """„X von Y Begriffen aktiv geprimt" — nur zeigen, wenn das Limit greift."""
        from ..textutils import parse_dictionary, primed_terms

        label = getattr(self, "_priming_hint", None)
        if label is None:
            return
        try:
            terms, _rules = parse_dictionary(self.settings.output.dictionary)
            active = len(primed_terms(terms, self.settings.output.dictionary_usage))
        except Exception:
            label.setText("")
            return
        if len(terms) <= active:
            label.setText("")
            return
        label.setText(
            f"{active} von {len(terms)} Begriffen werden der Erkennung vorab genannt — "
            f"bevorzugt die, die du tatsächlich benutzt. Ersetzungsregeln "
            f"(„falsch => richtig“) greifen immer, unabhängig davon."
        )

    def _restore_cards(self) -> None:
        """Alle ausgeblendeten Home-/Insights-Karten zurueckholen."""
        from dataclasses import fields

        ui = self.settings.interface
        # NUR Sichtbarkeits-Felder („…_show_…"). Frueher galt jedes falsche Bool als
        # ausgeblendete Karte — mit dem ersten Nicht-Sichtbarkeits-Schalter in dieser
        # Klasse (profiles_advanced) haette der Knopf ihn stillschweigend mitgesetzt.
        hidden = [f.name for f in fields(ui)
                  if "_show_" in f.name and not getattr(ui, f.name)]
        for name in hidden:
            setattr(ui, name, True)
        self.settings.save()
        self._cards_hint.setText(
            f"{len(hidden)} Karte(n) wieder eingeblendet." if hidden
            else "Es war keine Karte ausgeblendet."
        )
        self._on_changed("interface")

    def _open_license(self) -> None:
        hook = (self._test_hooks or {}).get("open_license")
        if hook is not None:
            hook()

    def refresh_license(self) -> None:
        """Lizenzzeile nachziehen (nach dem Eintragen eines Schluessels)."""
        label = getattr(self, "_license_label", None)
        if label is None:
            return
        from .licensedialog import license_summary

        label.setText(license_summary(self.settings))

    def _show_onboarding(self) -> None:
        """„Einfuehrung erneut zeigen": ueber die on_changed-Nahtstelle an die
        DesktopApp — das Panel selbst kennt den Wizard bewusst nicht."""
        self._on_changed("onboarding")

    def _changed(self, section: str) -> None:
        if self._loading:
            return
        self.settings.save()
        if section == "dictionary":
            self._refresh_priming_hint()
        self._on_changed(section)

    def _apply_autostart(self, enabled: bool) -> None:
        """Registry schreiben UND verifizieren, dann ehrlich melden, was gilt.

        Der WUNSCH des Nutzers wird immer gespeichert — auch wenn das Schreiben
        scheitert. Frueher wurde er hier auf den tatsaechlichen Zustand
        zurueckgesetzt; das war ein selbstverstaerkender Fehler: Beim naechsten
        Start sah der Abgleich „Wunsch = aus, Eintrag da" und LOESCHTE den Eintrag
        aktiv. Ein einmal fehlgeschlagener Schreibversuch schaltete den Autostart
        damit dauerhaft ab, ohne dass der Nutzer je etwas abgeschaltet haette.
        """
        self.settings.general.autostart = enabled
        autostart.set_autostart(enabled)
        actual = autostart.is_autostart_enabled()
        if enabled and not actual:
            self._autostart_warn.setText(
                "Eintrag ließ sich nicht schreiben — vermutlich blockiert ein "
                "Antivirus den Windows-Autostart. Die Einstellung bleibt gemerkt; "
                "Fleech versucht es bei jedem Start erneut."
            )
            self._autostart_warn.show()
        elif enabled and autostart.blocked_by_system():
            # Eintrag da, aber im Task-Manager deaktiviert — Windows ignoriert ihn.
            self._autostart_warn.setText(
                "Der Eintrag existiert, ist aber im Task-Manager unter „Autostart“ "
                "deaktiviert — deshalb startet Fleech nicht mit. Dort wieder "
                "aktivieren."
            )
            self._autostart_warn.show()
        else:
            self._autostart_warn.hide()
        self.settings.save()

    def commit(self) -> None:
        """Offene Eingabefelder verbindlich uebernehmen. QLineEdit schreibt seinen
        Wert erst bei editingFinished (Fokusverlust/Enter) — wird das Fenster mit
        Cursor im Feld geschlossen, ginge die Eingabe sonst verloren. clearFocus()
        deckt den Normalfall; das explizite emit() ist der fokusunabhaengige
        Fallback (Setter sind idempotent)."""
        focused = self.focusWidget()
        if focused is not None:
            focused.clearFocus()
        for line_edit in self.findChildren(QLineEdit):
            line_edit.editingFinished.emit()
        # Zeilen-Editoren: noch offene Debounce-Speicherungen sofort ausfuehren.
        for timer, commit in self._debounced_commits:
            if timer.isActive():
                commit()

    def _save_now(self) -> None:
        self.commit()
        # Autostart idempotent nachziehen (falls ein Toggle verschluckt wurde).
        if autostart.is_autostart_enabled() != self.settings.general.autostart:
            self._apply_autostart(self.settings.general.autostart)
        self.settings.save()
        self._save_status.setText("Gespeichert ✓")
        self._save_status.show()
        self._save_timer.start(2500)

    def _combo(self, form, label, values, current, section, setter,
               help_map=None, hint_text=""):
        box = QComboBox()
        for value, text in values:
            box.addItem(text, value)
        box.setCurrentIndex(max(0, [v for v, _ in values].index(current) if current in
                                [v for v, _ in values] else 0))
        # help_map = auswahlabhaengige Erklaerung → Badge-Tooltip wird live aktualisiert.
        initial_tip = hint_text or (help_map.get(current, "") if help_map else "")
        label_w, badge = self._row_label(label, initial_tip)

        def on_change(_index):
            value = box.currentData()
            setter(value)
            if badge is not None and help_map is not None:
                badge.set_tip(help_map.get(value, ""))
            self._changed(section)

        box.currentIndexChanged.connect(on_change)
        form.addRow(label_w, box)
        return box

    def _check(self, form, label, current, section, setter, hint_text=""):
        cb = QCheckBox()
        cb.setChecked(bool(current))
        cb.toggled.connect(lambda v: (setter(v), self._changed(section)))
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, cb)
        return cb

    def _lines_editor(self, form, label, current_lines, section, setter,
                      placeholder="", hint_text="", height=110):
        """Mehrzeilen-Editor fuer Listen-Settings (eine Regel pro Zeile). Speichert
        debounced (800 ms nach der letzten Eingabe) und beim Panel-commit()."""
        edit = QPlainTextEdit()
        edit.setPlainText("\n".join(str(x) for x in (current_lines or [])))
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(height)
        edit.setTabChangesFocus(True)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(800)

        def commit():
            timer.stop()
            lines = [ln.strip() for ln in edit.toPlainText().splitlines() if ln.strip()]
            setter(lines)
            self._changed(section)

        timer.timeout.connect(commit)
        edit.textChanged.connect(lambda: None if self._loading else timer.start())
        self._debounced_commits.append((timer, commit))
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, edit)
        return edit

    def _text_field(self, form, label, current, section, setter, hint_text=""):
        """Einzeiliges Textfeld. Speichert debounced wie die Listen-Editoren —
        bei jedem Tastendruck zu schreiben waere unnoetiger Plattenzugriff."""
        feld = QLineEdit(str(current or ""))
        feld.setStyleSheet(
            f"QLineEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; font-size: 9.5pt; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT}; }}")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(800)

        def schreiben():
            setter(feld.text().strip())
            self._changed(section)

        timer.timeout.connect(schreiben)
        feld.textChanged.connect(lambda _t: timer.start())
        feld.editingFinished.connect(lambda: (timer.stop(), schreiben()))
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, feld)
        return feld

    def _spin(self, form, label, current, lo, hi, section, setter, hint_text=""):
        """Kommazahl mit Grenzen (Sekunden). Die Grenzen sind hart: Was ausserhalb
        liegt, wuerde die Zustandsmaschine ohnehin zurechtstutzen — dann soll man
        es gar nicht erst eingeben koennen."""
        from PySide6.QtWidgets import QDoubleSpinBox

        from .chevron import apply_chevrons

        box = QDoubleSpinBox()
        box.setRange(float(lo), float(hi))
        box.setSingleStep(0.5)
        box.setDecimals(1)
        box.setSuffix(" s")
        box.setValue(float(current or lo))
        box.setStyleSheet(apply_chevrons(
            f"QDoubleSpinBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 5px 8px; font-size: 9.5pt; }}"
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
            f"  width: 16px; border: none; background: transparent; }}"
            f"QDoubleSpinBox::up-arrow {{ image: url(__CHEV_UP__);"
            f"  width: 9px; height: 9px; }}"
            f"QDoubleSpinBox::down-arrow {{ image: url(__CHEV_DOWN__);"
            f"  width: 9px; height: 9px; }}"))
        box.valueChanged.connect(lambda v: (setter(float(v)), self._changed(section)))
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, box)
        return box

    def _slider(self, form, label, current, section, setter, lo=0, hi=100, hint_text=""):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(current * 100))
        value_label = QLabel(f"{s.value()} %")
        value_label.setFixedWidth(44)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Design-System: Live-Wert in Akzent, semibold (SliderField).
        value_label.setStyleSheet(f"color: {ACCENT}; font-size: 9pt; font-weight: 600;")

        def on_change(v):
            value_label.setText(f"{v} %")
            setter(v / 100)
            self._changed(section)

        s.valueChanged.connect(on_change)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        h.addWidget(s, 1)   # Slider teilt sich die Breite mit dem Wert-Label
        h.addWidget(value_label)
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, row)
        return s

    # Anzeigenamen fuer die Kollisionswarnung („belegt durch …"). JEDER Hotkey
    # braucht hier einen Eintrag — fehlt einer, wirft die Warnung einen KeyError,
    # sobald zwei Felder existieren.
    _HOTKEY_FRIENDLY = {"dictate": "Diktat", "math_toggle": "Mathe-Umschalt",
                        "prompt_toggle": "KI-Prompting", "undo": "Rohtext einsetzen",
                        "pause": "Pause", "profile": "Profil wechseln"}

    def _add_hotkey_field(self, form, label, settings_attr, kind, default, hint_text=""):
        from ..hotkey import HotkeySpec
        from .hotkey_recorder import HotkeyField

        # Der GESPEICHERTE Wert ist die Wahrheit — auch wenn er leer ist. Frueher
        # stand hier `… or default`: Eine bewusst geloeschte Bindung zeigte nach
        # jedem Neustart wieder ihre alte Vorbelegung an, und beim naechsten
        # Speichern waere sie echt zurueckgekehrt. Genau so wurde es gemeldet
        # („bei jedem Update resettet er die Hotkeys"). Der Parameter `default`
        # dient nur noch als Rueckfall fuer einen UNLESBAREN Wert.
        roh = getattr(self.settings.recording, settings_attr)
        if not roh:
            spec = None
        else:
            try:
                spec = HotkeySpec.parse(roh)
            except ValueError:
                log.warning("Ungueltige Bindung %s=%r — nutze Vorgabe.", settings_attr, roh)
                spec = HotkeySpec.parse(default) if default else None

        def others():
            return {
                self._HOTKEY_FRIENDLY[k]: fld.spec()
                for k, fld in self._hotkey_fields.items()
                if k != kind and fld.spec() is not None
            }

        field = HotkeyField(spec, others, capture_guard=self._hotkey_capture_guard)

        def on_change(new_spec):
            setattr(self.settings.recording, settings_attr,
                    new_spec.serialize() if new_spec else "")
            self._changed("hotkeys")
            for k, fld in self._hotkey_fields.items():
                if k != kind:
                    fld._refresh()  # Kollisionshinweis der anderen Felder aktualisieren

        field.changed.connect(on_change)
        self._hotkey_fields[kind] = field
        label_w, _ = self._row_label(label, hint_text)
        form.addRow(label_w, field)

    # ---------------------------------------------------------------------- Seiten --

    def _build_pages(self) -> None:
        """Die neun Seiten der Einstellungen aufbauen — je Seite eine Methode.

        Stand 5.4.0 war das EINE Funktion mit 674 Zeilen. Sie liess sich sauber
        trennen, weil jede Seite mit `self._page()` neu anfaengt und keine lokale
        Variable ueber eine Seitengrenze hinweg lebt.
        """
        self._hotkey_fields = {}
        self._page_allgemein()
        self._page_aufnahme()
        self._page_audiofokus()
        self._page_overlay()
        self._page_sounds()
        self._page_benachrichtigungen()
        self._page_ausgabe()
        self._page_textersetzung()
        self._page_advanced()

    def _page_allgemein(self) -> None:
        """Allgemein — Autostart, Sprache, Name, Verlauf."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Grundlegendes: Start mit Windows, Sprache, dein Name und der lokale Verlauf."
        ))
        self._autostart_cb = auto = self._check(
            form, "Autostart mit Windows", autostart.is_autostart_enabled(), "general",
            lambda v: setattr(s.general, "autostart", v),
            "Startet Fleech automatisch beim Windows-Anmelden.",
        )
        self._autostart_warn = _hint("")
        self._autostart_warn.setStyleSheet("color: #E0574A; font-size: 8pt;")
        self._autostart_warn.hide()
        form.addRow("", self._autostart_warn)
        auto.toggled.connect(self._apply_autostart)
        self._combo(
            form, "Sprache",
            [("de", "Deutsch"), ("en", "Englisch"),
             ("auto", "Automatisch (mehrsprachig)")],
            s.general.language, "general", lambda v: setattr(s.general, "language", v),
            hint_text="Sprache der Erkennung. „Automatisch“ erkennt sie selbst.",
        )
        name = QLineEdit(s.general.display_name)
        name.setPlaceholderText("leer = Windows-Benutzername")
        name.editingFinished.connect(
            lambda: (setattr(s.general, "display_name", name.text().strip()),
                     self._changed("general"))
        )
        label_w, _ = self._row_label(
            "Anzeigename",
            "Name in der Begrüßung auf Home — und die Unterschrift unter Diktaten "
            "im Profil „E-Mail“. Leer heißt: die Mail endet mit der Grußformel, "
            "ohne Namen (ein geratener Name unter einer Mail wäre schlimmer).")
        form.addRow(label_w, name)
        self._check(form, "Diktat-Verlauf speichern", s.general.save_history, "general",
                    lambda v: setattr(s.general, "save_history", v),
                    "Speichert Diktate lokal für Home und Insights — keine Cloud.")
        clear_btn = style_button(QPushButton("Verlauf löschen …"), "danger")
        clear_btn.clicked.connect(lambda: (self._on_clear_history or (lambda: None))())
        label_w, _ = self._row_label(
            "Verlauf", "Löscht alle Diktate endgültig — dazu „Delete“ eintippen.")
        form.addRow(label_w, clear_btn)
        onboarding_btn = style_button(QPushButton("Einführung erneut zeigen"))
        onboarding_btn.clicked.connect(self._show_onboarding)
        label_w, _ = self._row_label(
            "Einführung", "Der Erststart-Rundgang: Mikrofon, Bedienung, Modi.")
        form.addRow(label_w, onboarding_btn)

        lizenz_zeile = QWidget()
        lrow = QHBoxLayout(lizenz_zeile)
        lrow.setContentsMargins(0, 0, 0, 0)
        lizenz_btn = style_button(QPushButton("Schlüssel eintragen …"))
        lizenz_btn.clicked.connect(self._open_license)
        self._license_label = QLabel("")
        self._license_label.setStyleSheet("color: #808088; font-size: 8pt;")
        self._license_label.setWordWrap(True)
        lrow.addWidget(lizenz_btn)
        lrow.addWidget(self._license_label, 1)
        label_w, _ = self._row_label(
            "Lizenz", "Fleech diktiert nur mit gültigem Schlüssel. Er gilt persönlich "
                      "und wird ohne Internet geprüft.")
        form.addRow(label_w, lizenz_zeile)
        self.refresh_license()
        cards_btn = style_button(QPushButton("Alle Karten wieder einblenden"))
        cards_btn.clicked.connect(self._restore_cards)
        label_w, _ = self._row_label(
            "Karten",
            "Karten auf Home und Insights blendest du per Rechtsklick auf die "
            "jeweilige Karte aus. Dieser Knopf holt alle zurück.")
        form.addRow(label_w, cards_btn)
        self._cards_hint = _hint("")
        form.addRow("", self._cards_hint)

        # Aufnahme

    def _page_aufnahme(self) -> None:
        """Aufnahme — Hotkeys, Mikrofon, Freihand."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Wie du das Diktat auslöst — und welches Mikrofon genutzt wird."
        ))
        # Der Sprechpause-Regler gehoert zum Anstupsen-Modus und wird mit ihm
        # ein- und ausgeblendet. Er entsteht aber erst NACH dem Combo (er steht
        # ja darunter) — deshalb der Umweg ueber diese Liste statt eines direkten
        # Zugriffs im Setter.
        #
        # Der Setter faengt BEWUSST nur `s` und diese Liste, NIEMALS `self`: Ein
        # Lambda, das den Qt-Parent faengt und in einem Kind-Widget haengt, baut
        # einen Referenzzyklus. Die Widgets sterben dann per GC in undefinierter
        # Reihenfolge — real aufgetreten als wandernde „access violation", deren
        # Absturzort nichts mit der Ursache zu tun hatte (siehe CLAUDE.md).
        pausen_zeilen: list = []

        def modus_gesetzt(v, _ziel=s.recording, _zeilen=pausen_zeilen):
            _ziel.mode = v
            for layout, box in _zeilen:
                layout.setRowVisible(box, v == "nudge")

        self._combo(
            form, "Bedienmodus",
            [("hold", "Hold-to-talk (halten)"), ("toggle", "Toggle (drücken/drücken)"),
             ("nudge", "Anstupsen (endet von selbst)")],
            s.recording.mode, "recording", modus_gesetzt,
            help_map={
                "hold": "Taste halten = aufnehmen, loslassen = fertig.",
                "toggle": "Einmal drücken = Start, nochmal = fertig.",
                "nudge": "Einmal drücken = Start. Hörst du auf zu reden, ist das "
                         "Diktat fertig — ohne dass du die Taste nochmal anfasst. "
                         "Ein zweiter Druck beendet trotzdem sofort.",
            },
        )
        self._sprechpause_box = self._spin(
            form, "Sprechpause bis Ende", s.freihand.stille_s, 1.0, 4.0, "freihand",
            lambda v: setattr(s.freihand, "stille_s", v),
            hint_text="Nur beim Anstupsen: So lange still = Diktat fertig. Kürzer "
                      "schneidet Denkpausen ab, länger lässt dich warten.",
        )
        pausen_zeilen.append((form, self._sprechpause_box))
        form.setRowVisible(self._sprechpause_box, s.recording.mode == "nudge")
        self._add_hotkey_field(
            form, "Diktat-Hotkey", "hotkey", "dictate", "f9",
            hint_text="„Aufnehmen“ klicken, dann Taste, Kombination oder Maustaste "
                      "4/5/Mitte drücken. Esc = abbrechen.",
        )
        # Das Feld „Mathe-Umschalt" ist mit v3.7.2 entfallen: Den Modus gibt es seit
        # v3.0.0 nicht mehr (Formeln entstehen im lokalen Parser), die Taste war also
        # seit sieben Versionen wirkungslos einstellbar.
        self._add_hotkey_field(
            form, "KI-Prompting", "prompt_toggle_hotkey", "prompt_toggle", "ctrl+alt+p",
            hint_text="Nur WÄHREND einer Aufnahme: dieses Diktat wird als strukturierter "
                      "KI-Prompt formuliert. Dauerhaft umschalten: Punkt in der Pille.",
        )
        self._add_hotkey_field(
            form, "Rohtext einsetzen", "undo_hotkey", "undo", "ctrl+alt+z",
            hint_text="Ersetzt die zuletzt eingefügte Fassung durch das wörtliche "
                      "Transkript — für den Fall, dass die Bereinigung danebengriff. "
                      "Nur direkt danach und solange der Cursor noch dort steht.",
        )
        self._add_hotkey_field(
            form, "Profil wechseln", "profile_hotkey", "profile", "",
            hint_text="Kurz drücken = nächstes Profil. GEDRÜCKT HALTEN = Liste aller "
                      "Profile am Mauszeiger, dort direkt anklicken. Sinnvoll auf "
                      "einer Maus-Zusatztaste (mouse4/mouse5) — deshalb ohne "
                      "Vorbelegung. Esc im Aufnahmefeld löscht eine Bindung.",
        )
        self._add_hotkey_field(
            form, "Pause", "pause_hotkey", "pause", "ctrl+alt+space",
            hint_text="Hält die laufende Aufnahme an — währenddessen wird nichts "
                      "aufgezeichnet, du kannst also frei sprechen. Nochmal drücken "
                      "setzt dasselbe Diktat fort. Auch als Knopf in der Pille.",
        )
        # -- Freihand: diktieren ohne Taste (F1) ---------------------------------
        # Bewusst HIER, direkt unter den Hotkeys: Es ist der zweite Weg, eine
        # Aufnahme zu starten — wer nach „wie beginne ich" sucht, schaut hier.
        f = s.freihand
        form.addRow("", _hint(
            "— Freihand —  Startwort sagen, sprechen, aufhören. Kommt zusätzlich "
            "zum Hotkey, ersetzt ihn nicht.\n"
            "Wenn dir am automatischen Ende gelegen ist: Der Bedienmodus "
            "„Anstupsen“ oben kann das auch — und kann nicht durch ein Video oder "
            "ein Gespräch im Raum ausgelöst werden."
        ))
        self._freihand_cb = self._check(
            form, "Freihand", f.aktiv, "freihand",
            lambda v: setattr(f, "aktiv", v),
            hint_text="Fleech hört dauerhaft auf das Startwort. Ein sparsamer "
                      "Sprach-Erkenner läuft dafür mit (~1 % CPU); Audio wird nie "
                      "gespeichert, erst ab dem Startwort überhaupt gesammelt. "
                      "Wirkt nach einem Neustart von Fleech.",
        )
        # Mehrere Startwörter: Welches Wort die eigene Aussprache zuverlässig
        # trifft, lässt sich nicht vorhersagen — mit zwei oder drei Kandidaten
        # nebeneinander entfällt das Herumprobieren mit einem einzigen.
        from ..freihand import zerlege_woerter

        def startwoerter_gesetzt(woerter, _ziel=f):
            _ziel.startwort = "\n".join(woerter)

        self._startwort_liste = WortListe(
            zerlege_woerter(f.startwort),
            platzhalter="Startwort eintippen, dann Enter",
            on_changed=lambda w: (startwoerter_gesetzt(w), self._changed("freihand")),
        )
        label_w, _ = self._row_label(
            "Startwörter",
            "Ein Wort pro Zeile — Fleech startet bei jedem davon. Mehrsilbig und "
            "im Alltag selten, sonst löst es im Gespräch ständig versehentlich "
            "aus. „Kimono“ hat sich bewährt. Kunstwörter, die wie ein Alltagswort "
            "klingen, sind eine schlechte Wahl: „Fleech“ etwa kommt als „Fleisch“ "
            "an und würde beim Kochrezept auslösen.")
        form.addRow(label_w, self._startwort_liste)
        if self._wortprobe_fn is not None:
            # Ob ein Startwort taugt, hängt an der eigenen Aussprache — das lässt
            # sich nicht vorhersagen, nur ausprobieren. Zehn Sekunden statt eines
            # halben Tages Rätselraten, warum Freihand nicht reagiert.
            self._startwort_probe_btn = style_button(
                QPushButton("Startwort einsprechen …"), "ghost")
            self._startwort_probe_btn.setToolTip(
                "Sprich das Startwort einmal beiläufig ins Mikrofon. Fleech zeigt, "
                "was ankommt und ob Freihand darauf anspringen würde."
            )
            self._startwort_probe_btn.clicked.connect(self._startwort_probe_starten)
            form.addRow("", self._startwort_probe_btn)
        self._combo(
            form, "Genauigkeit", [
                ("diktat", "Wie beim Diktat — empfohlen"),
                ("tiny", "Sparsam (schwache Rechner)"),
                ("base", "Sparsam, etwas genauer"),
                ("small", "Sparsam, am genauesten (langsam)"),
            ],
            getattr(f, "modell", "diktat") or "diktat", "freihand",
            lambda v: setattr(f, "modell", v),
            hint_text="Wie genau auf das Startwort gehört wird. „Wie beim Diktat“ "
                      "nimmt dasselbe Modell, das deine Diktate erkennt — es liegt "
                      "ohnehin auf der Grafikkarte, ist am genauesten und mit 140 ms "
                      "je Prüfung auch am schnellsten. Die sparsamen Varianten "
                      "rechnen stattdessen auf dem Prozessor: für Rechner ohne "
                      "brauchbare Grafikkarte, dafür deutlich schlechter im Hören. "
                      "Wirkt nach einem Neustart von Fleech.",
        )
        self._text_field(
            form, "Abbruchwort", f.abbruchwort, "freihand",
            lambda v: setattr(f, "abbruchwort", v),
            hint_text="Fällt dieses Wort im Diktat, wird verworfen statt eingefügt. "
                      "Es startet bewusst KEINE neue Aufnahme — sonst würde ein "
                      "Versprecher zur Endlosschleife.",
        )
        # „Sprechpause bis Ende" steht jetzt oben beim Bedienmodus: Sie beendet
        # auch den Anstupsen-Modus, und derselbe Wert an zwei Stellen zu regeln
        # wäre eine Einladung, ihn zweimal verschieden einzustellen.
        self._check(
            form, "Fehlersuche", getattr(f, "diagnose", False), "freihand",
            lambda v: setattr(f, "diagnose", v),
            hint_text="NUR zur Fehlersuche: Hebt die geprüften Startwort-Fenster "
                      "als Tondateien auf, damit nachvollziehbar wird, was beim "
                      "Lauschen wirklich ankommt. Es werden zwei Sekunden je "
                      "Prüfung gespeichert, höchstens 60 Stück, in "
                      "%APPDATA%\\Fleech\\freihand-diagnose. Danach bitte wieder "
                      "ausschalten — sonst wird dauerhaft Ton mitgeschrieben. "
                      "Wirkt nach einem Neustart von Fleech.",
        )
        self._lines_editor(
            form, "Nicht lauschen in", f.ausgeschlossene_apps, "freihand",
            lambda lines: setattr(f, "ausgeschlossene_apps", lines),
            placeholder="Teams.exe\nDiscord.exe\ncs2.exe",
            hint_text="Programme, in denen Freihand ruht — ein Prozessname je "
                      "Zeile. Für Spiele und Besprechungen: Dort ist Sprache im "
                      "Raum die Regel, und eine Fehlauslösung fällt mitten hinein.",
            height=80,
        )

        mics = [(None, "Systemstandard")] + [(name, name) for name in self._list_microphones()]
        self._combo(
            form, "Mikrofon", mics, s.recording.microphone, "microphone",
            lambda v: setattr(s.recording, "microphone", v),
            hint_text="Wirkt ab der nächsten Aufnahme.",
        )
        self._lines_editor(
            form, "Gesperrte Geräte", s.recording.blocked_devices, "microphone",
            lambda lines: setattr(s.recording, "blocked_devices", lines),
            placeholder="Stereomix\nCABLE Output\nAufnahmesumme",
            hint_text="Geräte, die nie als Mikrofon gelten sollen — ein Namensteil "
                      "je Zeile. Fleech erkennt die gängigen Loopback-Geräte schon "
                      "selbst; diese Liste ist für die Fälle, die dabei durchrutschen.",
            height=90,
        )

        # Audio-Fokus

    def _page_audiofokus(self) -> None:
        """Audio-Fokus — Ducking und Capture-Guard."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Macht andere Apps (Musik, Videos) während der Aufnahme leiser — für ein "
            "sauberes Mikrofonsignal."
        ))
        self._combo(
            form, "Fokus-Modus",
            [("pure_mic", "Aus (fremde Apps unverändert)"),
             ("soft_duck", "Leiser stellen (empfohlen)"),
             ("hard_focus", "Stark absenken")],
            s.audio_focus.mode, "audio_focus", lambda v: setattr(s.audio_focus, "mode", v),
            help_map={
                "pure_mic": "Andere Apps bleiben unverändert laut.",
                "soft_duck": "Andere Apps werden beim Aufnehmen leiser gestellt.",
                "hard_focus": "Andere Apps werden beim Aufnehmen stark abgesenkt.",
            },
        )
        self._slider(form, "Restlautstärke anderer Apps", s.audio_focus.duck_level,
                     "audio_focus", lambda v: setattr(s.audio_focus, "duck_level", v),
                     lo=0, hi=100,
                     hint_text="Wie laut andere Apps beim Aufnehmen bleiben. 0 % = stumm.")

        # Overlay

    def _page_overlay(self) -> None:
        """Overlay — Groesse, Position, Verhalten der Pille."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Die kleine Pille am Bildschirmrand: Sichtbarkeit, Größe, Ränder und Position."
        ))
        self._combo(
            form, "Sichtbarkeit",
            [("during_activity", "Nur während Aufnahme/Verarbeitung (empfohlen)"),
             ("always", "Immer sichtbar"),
             ("auto_hide", "Automatisch ausblenden"),
             ("off", "Deaktiviert")],
            s.overlay.visibility, "overlay", lambda v: setattr(s.overlay, "visibility", v),
            hint_text="Wann die Pille zu sehen ist.",
        )
        hide_seconds = QDoubleSpinBox()
        hide_seconds.setRange(0.5, 60.0)
        hide_seconds.setValue(s.overlay.auto_hide_seconds)
        hide_seconds.setSuffix(" s")
        hide_seconds.valueChanged.connect(
            lambda v: (setattr(s.overlay, "auto_hide_seconds", v), self._changed("overlay"))
        )
        label_w, _ = self._row_label(
            "Auto-Hide nach", "Nach dieser Zeit blendet sich die Pille aus.")
        form.addRow(label_w, hide_seconds)
        self._combo(
            form, "Größe",
            [("compact", "Kompakt"), ("normal", "Standard"), ("large", "Groß")],
            s.overlay.size, "overlay", lambda v: setattr(s.overlay, "size", v),
            hint_text="Gesamtgröße der Pille.",
        )
        # Frueher vier Spinboxen (links/rechts/oben/unten). Die einzelne Einstellbarkeit
        # hat in der Praxis niemand gebraucht — hier steht EINE Stufe, die alle vier
        # Werte setzt. Wer es genauer will, kann sie in der settings.json weiterhin
        # frei setzen; `overlay_compactness` waehlt dann die naechstliegende Stufe.
        self._combo(
            form, "Pillen-Rand",
            list(OVERLAY_COMPACTNESS),
            overlay_compactness(s.overlay), "overlay",
            lambda v: apply_overlay_compactness(s.overlay, v),
            hint_text="Innenabstand des Pillen-Hintergrunds — enger wirkt kompakter.",
        )
        self._combo(
            form, "Rand-Buttons",
            [(True, "Eigener Hintergrund (getrennte Inseln)"),
             (False, "In einer durchgehenden Pille")],
            s.overlay.separate_islands, "overlay",
            lambda v: setattr(s.overlay, "separate_islands", v),
            help_map={
                True: "Mathe-Punkt und Trigger-Button als eigene Inseln neben der Pille.",
                False: "Alles in einem durchgehenden Hintergrund.",
            },
        )
        self._slider(form, "Transparenz", s.overlay.opacity, "overlay",
                     lambda v: setattr(s.overlay, "opacity", v), lo=20, hi=100,
                     hint_text="Deckkraft der Pille.")
        self._slider(form, "Pegel-Empfindlichkeit", s.overlay.level_gain, "overlay",
                     lambda v: setattr(s.overlay, "level_gain", v), lo=20, hi=300,
                     hint_text="Wie stark die Waveform ausschlägt — rein optisch, hilft "
                               "bei leisen Mikrofonen.")
        self._check(form, "Click-Through", s.overlay.click_through, "overlay",
                    lambda v: setattr(s.overlay, "click_through", v),
                    "Mausklicks gehen durch die Pille hindurch.")
        self._check(form, "Folgt dem Maus-Bildschirm", s.overlay.follow_mouse_screen,
                    "overlay", lambda v: setattr(s.overlay, "follow_mouse_screen", v),
                    "Die Pille erscheint auf dem Monitor des Mauszeigers.")
        self._check(form, "Live-Transkription (experimentell)", s.overlay.live_preview,
                    "overlay", lambda v: setattr(s.overlay, "live_preview", v),
                    "Grobe Echtzeit-Vorschau beim Sprechen (zusätzliches Modell, "
                    "~0,5 GB VRAM).")
        self._check(form, "Erkannten Text über Overlay zeigen", s.overlay.show_transcript,
                    "overlay", lambda v: setattr(s.overlay, "show_transcript", v),
                    "Zeigt den fertigen Text kurz über der Pille.")

        # Position: Presets + Bearbeiten/Reset
        from .overlay_qt import OVERLAY_PRESETS

        preset_row = QWidget()
        prow = QHBoxLayout(preset_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(6)
        for key, label in OVERLAY_PRESETS:
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(
                lambda _=False, k=key: self._overlay_hooks.get("apply_preset",
                                                               lambda _k: None)(k)
            )
            prow.addWidget(b)
        prow.addStretch(1)
        label_w, _ = self._row_label("Position", "Pille am Bildschirmrand ausrichten.")
        form.addRow(label_w, preset_row)

        edit_row = QWidget()
        erow = QHBoxLayout(edit_row)
        erow.setContentsMargins(0, 0, 0, 0)
        erow.setSpacing(6)
        self._overlay_edit_btn = QPushButton("Overlay bearbeiten")
        self._overlay_edit_btn.setCursor(Qt.PointingHandCursor)
        self._overlay_edit_btn.clicked.connect(self._on_overlay_edit_clicked)
        reset_btn = QPushButton("Position zurücksetzen")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(
            lambda: self._overlay_hooks.get("reset", lambda: None)()
        )
        erow.addWidget(self._overlay_edit_btn)
        erow.addWidget(reset_btn)
        erow.addStretch(1)
        label_w, _ = self._row_label(
            "Bearbeiten",
            "Pille dauerhaft anzeigen und mit der Maus an die Wunschposition ziehen.",
        )
        form.addRow(label_w, edit_row)

        # Sounds

    def _page_sounds(self) -> None:
        """Sounds."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Fleechs eigene Töne für Start, Stopp, eingefügten Text und Fehler."
        ))
        self._check(form, "UI-Sounds", s.sounds.enabled, "sounds",
                    lambda v: setattr(s.sounds, "enabled", v),
                    "Alle Töne an/aus.")
        self._slider(form, "Lautstärke", s.sounds.volume, "sounds",
                     lambda v: setattr(s.sounds, "volume", v),
                     hint_text="Lautstärke der Fleech-Töne.")
        self._combo(form, "Preset", [("soft", "Soft (Chimes)"), ("click", "Click (Ticks)")],
                    s.sounds.preset, "sounds", lambda v: setattr(s.sounds, "preset", v),
                    hint_text="Klangstil der Töne.")
        for key, label, tip in (
            ("start", "Start der Aufnahme", "Ton beim Aufnahmestart."),
            ("stop", "Stopp der Aufnahme", "Ton beim Aufnahmestopp."),
            ("commit", "Text eingefügt", "Ton, wenn der Text eingefügt wurde."),
            ("error", "Fehler/Fallback", "Ton bei Fehlern oder Ersatz-Verarbeitung."),
        ):
            self._check(form, label, getattr(s.sounds, key), "sounds",
                        lambda v, k=key: setattr(s.sounds, k, v), tip)

        # Benachrichtigungen (Windows Focus Assist, Toasts, Gaming)

    def _page_benachrichtigungen(self) -> None:
        """Benachrichtigungen — Tray, Toast, Overlay."""
        s = self.settings
        _, form = self._page()
        f = s.focus
        form.addRow("", _hint(
            "Windows-Banner (Toasts) und ruhiges Verhalten bei „Nicht stören“ und im Spiel."
        ))
        self._check(form, "Windows Do Not Disturb respektieren", f.respect_dnd, "focus",
                    lambda v: setattr(f, "respect_dnd", v),
                    "Bei „Nicht stören“: keine unwichtigen Banner.")
        self._check(form, "Sounds bei DND stummschalten", f.dnd_mute_sounds, "focus",
                    lambda v: setattr(f, "dnd_mute_sounds", v),
                    "Bei „Nicht stören“ zusätzlich alle Fleech-Töne stumm.")
        # Frueher fuenf einzelne Toast-Schalter. Die Entscheidung, die man wirklich
        # trifft, ist "wie viel darf mich unterbrechen" — nicht Banner fuer Banner.
        self._combo(
            form, "Windows-Banner",
            list(TOAST_LEVELS),
            toast_level(f), "focus",
            lambda v: apply_toast_level(f, v),
            hint_text="„Wichtiges“ meldet nur Probleme (Fehler, Anbieter-Quota); "
                      "„Alles“ zusätzlich Statusmeldungen wie „läuft im Hintergrund“.",
        )
        self._check(form, "Akzent-Sound bei kritischen Toasts", f.notification_sounds,
                    "focus", lambda v: setattr(f, "notification_sounds", v),
                    "Eigener Ton bei kritischen Bannern.")
        self._check(form, "Gaming-/Fullscreen-Erkennung", f.gaming_detection, "focus",
                    lambda v: setattr(f, "gaming_detection", v),
                    "Erkennt Spiele und Vollbild-Apps automatisch.")
        self._combo(
            form, "Overlay im Gaming-Modus",
            [("activity_only", "Nur bei Aufnahme/Verarbeitung (empfohlen)"),
             ("compact", "Compact"), ("hidden", "Versteckt"),
             ("unchanged", "Unverändert")],
            f.gaming_overlay, "focus", lambda v: setattr(f, "gaming_overlay", v),
            hint_text="Verhalten der Pille, während ein Spiel läuft.",
        )
        self._slider(form, "Fleech-eigene Töne im Spiel", f.gaming_sound_factor,
                     "focus", lambda v: setattr(f, "gaming_sound_factor", v),
                     hint_text="Lautstärke der Fleech-Töne im Spiel. 0 % = stumm.")
        exceptions = QLineEdit(", ".join(f.gaming_exceptions))
        exceptions.editingFinished.connect(lambda: (
            setattr(f, "gaming_exceptions",
                    [e.strip() for e in exceptions.text().split(",") if e.strip()]),
            self._changed("focus"),
        ))
        label_w, _ = self._row_label(
            "Ausnahmen (Prozesse)",
            "Prozesse, die nicht als Spiel gelten — durch Komma getrennt.",
        )
        form.addRow(label_w, exceptions)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        test_toast = QPushButton("Test-Toast")
        test_toast.clicked.connect(lambda: self._test_hooks.get("toast", lambda: None)())
        test_sound = QPushButton("Test-Sound")
        test_sound.clicked.connect(lambda: self._test_hooks.get("sound", lambda: None)())
        row.addWidget(test_toast)
        row.addWidget(test_sound)
        row.addStretch(1)
        label_w, _ = self._row_label("Testen", "Probe-Banner und Probe-Ton abspielen.")
        form.addRow(label_w, buttons)

        # Ausgabe

    def _page_ausgabe(self) -> None:
        """Ausgabe — wie der Text ins Feld kommt."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Wie stark die KI dein Diktat glättet — pro App feiner steuerbar im Tab "
            "„Profile“."
        ))

        # Frueher eine eigene Seite „Mathe" fuer diesen EINEN Regler. Er gehoert
        # hierher: Es geht darum, was im Text landet ($…$ statt „x quadrat").
        from ..usersettings import apply_math_level, math_level

        _math_ref = s.math

        def _set_level(value: str) -> None:
            apply_math_level(_math_ref, value)

        self._combo(
            form, "Formel-Erkennung",
            [("auto", "Automatisch — erkennt Formeln im Fließtext"),
             ("off", "Aus")],
            math_level(s.math), "math", _set_level,
            help_map=_MATH_LEVEL_HELP,
        )
        self._combo(
            form, "Eingriffsgrad",
            [("minimal", "Minimal"), ("standard", "Standard (empfohlen)"), ("strong", "Strong")],
            s.output.intervention, "output", lambda v: setattr(s.output, "intervention", v),
            help_map=_INTERVENTION_HELP,
        )
        self._check(form, "Safe-Word-Befehle aktiv", s.output.command_enabled, "output",
                    lambda v: setattr(s.output, "command_enabled", v),
                    "Befehle per Safe-Word an/aus.")
        self._check(form, "Gesprochene Zeichen schreiben", s.output.spoken_symbols,
                    "output", lambda v: setattr(s.output, "spoken_symbols", v),
                    "„Slash Hunter“ wird zu „/Hunter“. Betrifft nur eindeutige "
                    "Wörter (Slash, Backslash, Hashtag, Raute, Unterstrich, "
                    "Klammeraffe) — „Minus“ und „Plus“ bleiben Text, das sind "
                    "gewöhnliche deutsche Wörter.")
        self._check(form, "Cursor-Rückkehr", s.output.restore_focus, "output",
                    lambda v: setattr(s.output, "restore_focus", v),
                    "Fügt den Text dort ein, wo das Diktat begann — auch wenn du "
                    "zwischendurch woanders hingeklickt hast.")
        trigger = QLineEdit(s.output.trigger_word)
        trigger.setPlaceholderText("leer = Wert aus config.yaml")
        trigger.editingFinished.connect(
            lambda: (setattr(s.output, "trigger_word", trigger.text().strip()),
                     self._changed("output"))
        )
        label_w, _ = self._row_label(
            "Safe-Word (Befehle)",
            "Gesprochenes Auslösewort für Befehle, z. B. „Kimono, mach das formeller“.",
        )
        form.addRow(label_w, trigger)

        # Wörterbuch — Fachbegriffe/Eigennamen fuer Erkennung + Korrektur

    def _page_textersetzung(self) -> None:
        """Textersetzung — Woerterbuch, Bausteine, Kontext."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Eigene Begriffe, die die Spracherkennung kennen soll — eine Zeile pro Eintrag."
        ))
        self._dictionary_editor = self._lines_editor(
            form, "Wörterbuch", s.output.dictionary, "dictionary",
            lambda lines: setattr(s.output, "dictionary", lines),
            placeholder="Fleech\nKimono\ngithub => GitHub\nCosinus => Kosinus",
            hint_text="„Begriff“ = besser erkennen. „falsch => richtig“ = zusätzlich "
                      "automatisch ersetzen.",
            height=220,
        )
        # Einsprech-Test: Man traegt ein Wort ein und weiss nicht, ob es etwas
        # gebracht hat — bis es mitten im Diktat wieder falsch dasteht.
        if self._wortprobe_fn is not None:
            self._probe_btn = style_button(QPushButton("Eintrag einsprechen …"), "ghost")
            self._probe_btn.setToolTip(
                "Markiere im Wörterbuch eine Zeile (oder setz den Cursor hinein) "
                "und sprich das Wort einmal ins Mikrofon. Fleech zeigt, was ankommt."
            )
            self._probe_btn.clicked.connect(self._wortprobe_starten)
            form.addRow("", self._probe_btn)
        # Transparenz zum Priming-Limit: ueber 60 Begriffen kann die Erkennung nicht
        # alle vorab kennen — sichtbar machen, statt still abzuschneiden.
        self._priming_hint = _hint("")
        self._refresh_priming_hint()
        form.addRow("", self._priming_hint)
        # Ignorier-Liste: abgelehnte Rueckfragen + weggeklickte Insights-Vorschlaege.
        # Sichtbar und editierbar, DAMIT „Ignorieren" dauerhaft sein darf — Zeile
        # loeschen holt den Vorschlag bzw. die Rueckfrage zurueck.
        self._ignores_editor = self._lines_editor(
            form, "Ignoriert", s.output.dictionary_ignores, "dictionary",
            lambda lines: setattr(s.output, "dictionary_ignores", lines),
            placeholder="kimano => kimono",
            hint_text="Paare, die nie mehr vorgeschlagen werden — aus abgelehnten "
                      "Rückfragen und „Ignorieren“ in den Insights. Zeile löschen "
                      "holt den Vorschlag zurück.",
            height=90,
        )

        # Projekt-Gedaechtnis: gelerntes Fachvokabular je App/Fenster. Bewusst
        # HIER, direkt unter dem Woerterbuch: Es ist dieselbe Sache, nur
        # automatisch — beides primt die Erkennung. Wer sucht, warum ein Wort
        # anders geschrieben wird, schaut an einer Stelle.
        self._kontext_cb = self._check(
            form, "Gedächtnis", getattr(s.advanced, "kontext_lernen", True),
            "output", self._on_kontext_toggled,
            hint_text="Gelerntes Fachvokabular als Erkennungs-Hinweis. "
                      "Aus = weder lernen noch verwenden.",
        )
        form.addRow("", _hint(
            "Fleech merkt sich je Programm und Fenster die Fachbegriffe, die dort "
            "vorkommen (alles mit Binnenversalien, Ziffern oder Punkten — "
            "„MCP-Server“, „PySide6“, „x_3“), und gibt sie beim nächsten Diktat "
            "als Hinweis an die Erkennung. Nur Schreibweisen: Der Inhalt geht nie "
            "an die KI, das Diktat wird dadurch nicht langsamer."
        ))
        self._kontext_zeile = _hint("")
        form.addRow("", self._kontext_zeile)
        vergessen = style_button(QPushButton("Gelerntes vergessen"), "ghost")
        vergessen.clicked.connect(self._kontext_vergessen)
        form.addRow("", vergessen)
        self._refresh_kontext_zeile()

        # Bausteine — gesprochenes Kuerzel fuegt einen festen Textblock ein.
        # BEWUSST auf derselben Seite wie das Woerterbuch (v3.12.0, aus einem
        # externen Gutachten): Beides sind Text-Ersetzungen — eines wortbasiert,
        # eines kuerzelbasiert. Als zwei getrennte Bereiche musste man raten, wo
        # man sucht.
        form.addRow("", _hint(
            "Feste Textblöcke, die du per Sprache abrufst — z. B. „Baustein Signatur“ "
            "am Ende einer Mail. Der Text wird genau so eingefügt, wie er hier steht: "
            "keine KI schaut ihn an, nichts wird umformuliert."
        ))
        self._snippets_editor = self._lines_editor(
            form, "Bausteine", s.output.snippets, "snippets",
            lambda lines: setattr(s.output, "snippets", lines),
            placeholder=("Signatur => Viele Grüße\\nVorname Nachname\n"
                         "Absage => Vielen Dank für die Anfrage — leider muss ich absagen.\n"
                         "Docstring => \\\"\\\"\\\"\\n\\n\\\"\\\"\\\""),
            hint_text="Eine Zeile pro Baustein: „Kürzel => Text“. „\\n“ im Text "
                      "erzeugt einen Zeilenumbruch.",
            height=220,
        )
        keyword = QLineEdit(s.output.snippet_keyword)
        keyword.setPlaceholderText("leer = „Baustein“")
        keyword.editingFinished.connect(
            lambda: (setattr(s.output, "snippet_keyword", keyword.text().strip()),
                     self._changed("snippets"))
        )
        label_w, _ = self._row_label(
            "Signalwort",
            "Das gesprochene Wort vor dem Kürzel. Bewusst getrennt vom Safe-Word für "
            "Befehle: Bausteine fügen nur ein, Befehle verändern vorhandenen Text.",
        )
        form.addRow(label_w, keyword)
        form.addRow("", _hint(
            "Wird das Signalwort erkannt, aber kein Kürzel getroffen, steht das im "
            "Log — dann hat die Erkennung das Kürzel verhört und ein kürzeres, "
            "deutlicheres Wort hilft."
        ))

        # Advanced

    def _page_advanced(self) -> None:
        """Advanced — Modelle, Warmhaltung, Diagnose."""
        s = self.settings
        _, form = self._page()
        form.addRow("", _hint(
            "Technische Schalter — die Standardwerte passen für die meisten."
        ))
        from ..version import version_string

        version_label = QLabel(f"Fleech {version_string()}")
        version_label.setStyleSheet("font: 600 11pt 'Segoe UI';")
        form.addRow("Version", version_label)

        update_row = QWidget()
        urow = QHBoxLayout(update_row)
        urow.setContentsMargins(0, 0, 0, 0)
        check_btn = QPushButton("Nach Updates suchen")
        self._update_status = QLabel("")
        self._update_status.setStyleSheet("color: #808088; font-size: 8pt;")
        check_btn.clicked.connect(self._check_updates)
        urow.addWidget(check_btn)
        urow.addWidget(self._update_status, 1)
        label_w, _ = self._row_label("Updates", "Manuell nach einer neuen Version suchen.")
        form.addRow(label_w, update_row)

        self._check(form, "Automatisch nach Updates suchen", s.advanced.auto_update_check,
                    "advanced", lambda v: setattr(s.advanced, "auto_update_check", v),
                    "Beim Start und danach täglich. Gefunden wird nur geprüft und "
                    "gemeldet — installiert wird nie ohne Klick.")
        self._check(form, "Updates im Hintergrund laden",
                    s.advanced.auto_update_download, "advanced",
                    lambda v: setattr(s.advanced, "auto_update_download", v),
                    "Lädt die neue Version gleich herunter (mit Prüfsummen-Kontrolle), "
                    "damit die Installation später nur einen Klick braucht.")

        feed = QLineEdit(s.advanced.update_feed_url)
        feed.setPlaceholderText("(leer) GitHub-Releases des Projekts")
        feed.editingFinished.connect(
            lambda: (setattr(s.advanced, "update_feed_url", feed.text().strip()),
                     self._changed("advanced"))
        )
        label_w, _ = self._row_label(
            "Update-Quelle",
            "Leer = GitHub-Releases des Projekts. Eine eigene HTTPS-Adresse muss auf "
            "einen JSON-Feed mit „version\", „url\" und „sha256\" zeigen.")
        form.addRow(label_w, feed)

        token = QLineEdit(s.advanced.update_token)
        token.setEchoMode(QLineEdit.Password)
        token.setPlaceholderText("(nur bei privatem Repository)")
        token.editingFinished.connect(
            lambda: (setattr(s.advanced, "update_token", token.text().strip()),
                     self._changed("advanced"))
        )
        label_w, _ = self._row_label(
            "Zugriffstoken",
            "Nur nötig, wenn die Update-Quelle ein privates Repository ist: ein "
            "GitHub-Token mit Leserecht („Contents: Read-only“). Er wird ausschließlich "
            "an GitHub gesendet und nie ins Log geschrieben. Alternativ die "
            "Umgebungsvariable FLEECH_UPDATE_TOKEN setzen.")
        form.addRow(label_w, token)

        # Wayland ehrlich benennen, statt Funktionen still ausfallen zu lassen.
        from ..platformpaths import WAYLAND_LIMITS, session_kind

        if session_kind() == "wayland":
            limits = "\n".join(f"• {t}" for t in WAYLAND_LIMITS)
            warn = _hint(
                "Wayland erkannt — folgende Funktionen sind hier eingeschränkt:\n"
                f"{limits}\nUnter einer X11-Sitzung laufen sie vollständig."
            )
            warn.setStyleSheet("color: #E8A13C; font-size: 8pt;")
            label_w, _ = self._row_label(
                "Sitzung", "Plattform-Einschränkungen der aktuellen Sitzungsart.")
            form.addRow(label_w, warn)

        self._check(form, "GPU-Beschleunigung bevorzugen (STT)", s.advanced.prefer_gpu,
                    "stt_device", lambda v: setattr(s.advanced, "prefer_gpu", v),
                    "Erkennung auf der Grafikkarte (schneller). Aus = CPU erzwingen.")

        self._combo(
            form, "Modell-Warmhaltung",
            [("smart", "Nach Nutzung (empfohlen)"),
             ("always", "Dauerhaft"),
             ("off", "Aus")],
            s.advanced.llm_keep_warm, "warmhold",
            lambda v: setattr(s.advanced, "llm_keep_warm", v),
            help_map={
                "smart": "KI bleibt nach dem letzten Diktat geladen (Zeit unten "
                         "einstellbar). Danach — oder sobald ein Spiel läuft — wird "
                         "sie sofort entladen (RAM/Grafikspeicher frei).",
                "always": "KI bleibt dauerhaft geladen (~8 GB Speicher) — "
                          "schnellste Antwort, auch beim Zocken belegt.",
                "off": "Kein Warmhalten — maximal freier Speicher, erstes "
                       "Diktat langsamer.",
            },
        )
        self._combo(
            form, "Im Leerlauf entladen nach",
            [(3, "3 Minuten (aggressiv)"),
             (10, "10 Minuten (empfohlen)"),
             (30, "30 Minuten"),
             (45, "45 Minuten")],
            int(s.advanced.llm_idle_unload_minutes), "warmhold",
            lambda v: setattr(s.advanced, "llm_idle_unload_minutes", int(v)),
            help_map={
                3: "Gibt RAM schnell frei. Erstes Diktat nach einer Pause ~8 s "
                   "langsamer (teils vom Parallel-Laden verdeckt).",
                10: "Guter Mittelweg: kurze Arbeitspausen bleiben schnell, danach "
                    "wird RAM frei.",
                30: "Modelle bleiben lange warm — RAM länger belegt.",
                45: "Maximal reaktionsschnell, RAM am längsten belegt.",
            },
        )
        self._check(form, "Adaptive Geschwindigkeit (Cleanup)", s.advanced.adaptive_cleanup,
                    "adaptive", lambda v: setattr(s.advanced, "adaptive_cleanup", v),
                    "Kurze Diktate laufen über ein kleines, schnelleres Modell.")

        from ..usersettings import SETTINGS_DIR

        self._check(form, "Debug-Logging", s.advanced.debug_logging, "advanced",
                    lambda v: setattr(s.advanced, "debug_logging", v),
                    f"Ausführliches Protokoll in {SETTINGS_DIR / 'fleech.log'}.")

    def _on_overlay_edit_clicked(self) -> None:
        toggle = self._overlay_hooks.get("edit_toggle")
        if toggle is None:
            return
        self.set_overlay_editing(toggle())

    def set_overlay_editing(self, editing: bool) -> None:
        """Beschriftung des Bearbeiten-Buttons mit dem Overlay-Zustand synchron halten."""
        self._overlay_edit_btn.setText(
            "Fertig – Position speichern" if editing else "Overlay bearbeiten"
        )

    def _check_updates(self) -> None:
        from .updates import check_for_updates

        self._update_status.setText("Suche …")
        from .updates import update_token

        result = check_for_updates(self.settings.advanced.update_feed_url or None,
                                   token=update_token(self.settings))
        status = result["status"]
        if status == "update_available":
            self._update_status.setText(f"Update {result['latest']} verfügbar.")
            hook = (self._test_hooks or {}).get("open_update")
            if hook is not None:
                hook()                       # Dialog mit Notizen und Download oeffnen
        elif status == "up_to_date":
            self._update_status.setText("Aktuell.")
        elif status == "no_release":
            self._update_status.setText("Noch keine Veröffentlichung vorhanden.")
        elif status == "auth_required":
            self._update_status.setText("Kein Zugriff — Token fehlt oder gilt nicht.")
        else:
            self._update_status.setText(f"Fehlgeschlagen: {result.get('message', '')[:60]}")

    def _wortprobe_begriff(self) -> str:
        """Der Begriff aus der Zeile, in der der Cursor steht.

        Bewusst die AKTUELLE Zeile statt eines eigenen Eingabefelds: Man schreibt
        das Wort gerade, der Cursor steht ohnehin darin — ein zweites Feld waere
        dasselbe Wort ein zweites Mal.
        """
        editor = getattr(self, "_dictionary_editor", None)
        if editor is None:
            return ""
        zeile = editor.textCursor().block().text().strip()
        if not zeile:
            # Cursor in einer Leerzeile: die letzte gefuellte Zeile nehmen.
            gefuellt = [z.strip() for z in editor.toPlainText().splitlines() if z.strip()]
            zeile = gefuellt[-1] if gefuellt else ""
        # „falsch => richtig" — geprueft wird, ob die RICHTIGE Schreibweise ankommt.
        if "=>" in zeile:
            zeile = zeile.split("=>", 1)[1]
        return zeile.strip()

    def _startwort_probe_starten(self) -> None:
        """Das Startwort einsprechen und sehen, ob Freihand darauf anspringen würde.

        Geprüft wird mit dem Erkenner, der im Betrieb LÄUFT — nicht mit dem
        Diktat-Weg. Der hört ungleich besser, und ein Test, der besteht, während
        der Alltag scheitert, ist schlimmer als keiner.
        """
        if self._wortprobe_fn is None:
            return
        liste = getattr(self, "_startwort_liste", None)
        woerter = liste.woerter() if liste is not None else []
        if not woerter:
            self._startwort_probe_btn.setText("Erst ein Startwort eintragen")
            return
        # Bei mehreren wird das ERSTE geprüft: Es ist das, das man im Alltag sagt
        # — die anderen stehen als Rückfalloption da. Alle nacheinander abzufragen
        # wäre ein Testlauf statt einer Probe.
        wort = woerter[0]
        from .dialogs import WortprobeDialog

        WortprobeDialog(wort, self._wortprobe_fn, self, zweck="startwort").exec()
        self._startwort_probe_btn.setText("Startwort einsprechen …")

    def _wortprobe_starten(self) -> None:
        if self._wortprobe_fn is None:
            return
        begriff = self._wortprobe_begriff()
        if not begriff:
            self._probe_btn.setText("Erst eine Zeile ins Wörterbuch schreiben")
            return
        from .dialogs import WortprobeDialog

        dlg = WortprobeDialog(begriff, self._wortprobe_fn, self)
        if dlg.exec() and dlg.vorschlag:
            # „gehört => gemeint" ans Wörterbuch anhängen, damit die falsche
            # Schreibweise kuenftig automatisch ersetzt wird.
            editor = self._dictionary_editor
            zeilen = [z for z in editor.toPlainText().splitlines()]
            if dlg.vorschlag not in zeilen:
                zeilen.append(dlg.vorschlag)
                editor.setPlainText("\n".join(zeilen))
        self._probe_btn.setText("Eintrag einsprechen …")
