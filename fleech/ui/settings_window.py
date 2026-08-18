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

from ..usersettings import UserSettings
from . import autostart
from .theme import (
    ACCENT, ACCENT_DIM, BORDER_HAIRLINE, CARD, MUTED, NAV_ACTIVE_BG, ROW_HOVER,
    SIDEBAR, TEXT, TRACK, button_qss, style_button,
)
from .settings.wortprobe import WortprobeMixin
from .widgets import HelpBadge

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

class SettingsPanel(WortprobeMixin, QWidget):
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
        from ..dictionary import parse_dictionary, primed_terms

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
    # „Mathe-Umschalt" stand hier bis 5.10.2 mit drin, obwohl es das Feld und den
    # Modus seit v3.0.0 nicht mehr gibt — ein Eintrag, der nur die Erinnerung an
    # eine Bedienung wachhielt, die ins Leere geht.
    _HOTKEY_FRIENDLY = {"dictate": "Diktat",
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
        """Die neun Seiten aufbauen — je Seite ein Modul in `ui/settings/`.

        Stand 5.4.0 war das EINE Funktion mit 674 Zeilen, danach neun Methoden in
        dieser Datei. Beides liess sich sauber trennen, weil jede Seite mit
        `self._page()` neu anfaengt und keine lokale Variable ueber eine
        Seitengrenze hinweg lebt.
        """
        from . import settings as seiten

        self._hotkey_fields = {}
        seiten.build_all(self)




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
