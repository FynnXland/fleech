"""Insights: Kennzahlen aus der eigenen Historie — alles lokal gerechnet.

Woerter je Minute, Korrekturen, Gesamtwoerter, App-Nutzung, Serien-Kalender und
die drei handlungsfaehigen Hinweise. Die Konstanten oben stehen hier und nicht in
`widgets`, weil sie nur diese Seite betreffen.
"""

from __future__ import annotations

import logging
import time as _time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...history import HistoryStore
from ...milestones import word_milestone
from ..dialogs import WordDetailDialog
from ..theme import (
    ACCENT, MUTED, PAGE_MARGINS, PAGE_SPACING, TEXT, page_title_qss,
    style_button,
)
from ..widgets import (
    StreakCalendar, WpmGauge, _card, _diktierzeit_text, _link_button, _metric,
    _rebuild_ranked_list, enable_card_hiding,
)

log = logging.getLogger(__name__)


def _processing_summary(stats) -> str:
    """Text der "Verarbeitung"-Karte: Ø Latenzen, Routing-Verteilung, Fallback-Quote."""
    if not stats.avg_stt_ms and not (stats.tier_shares or {}):
        return "Noch keine Daten — Latenzen werden ab dem nächsten Diktat erfasst."
    lines = []
    if stats.avg_stt_ms or stats.avg_llm_ms:
        total_s = (stats.avg_stt_ms + stats.avg_llm_ms) / 1000
        lines.append(
            f"Ø Verarbeitung: {total_s:.1f} s — davon {stats.avg_stt_ms / 1000:.1f} s "
            f"Erkennung · {stats.avg_llm_ms / 1000:.1f} s KI-Bereinigung"
        )
    shares = stats.tier_shares or {}
    if shares:
        tier_names = (("trivial", "ohne KI"), ("simple", "schnelles Modell"),
                      ("complex", "großes Modell"))
        parts = [f"{round(shares[key] * 100)} % {label}"
                 for key, label in tier_names if key in shares]
        lines.append("Routing: " + " · ".join(parts))
    lines.append(f"Fallback-Quote: {round(stats.fallback_rate * 100)} % "
                 f"(Diktate, die auf das Roh-Transkript zurückfielen)")
    return "\n".join(lines)


# Vorschlaege: wie viele gleichzeitig gezeigt werden und wie viele dafuer geprueft
# werden (Puffer fuer uebernommene/ignorierte, damit Nachruecker sichtbar werden).
_ADVICE_SHOWN = 3


_ADVICE_SCAN = 12


def _latency_trend_line(store) -> str:
    """Kurzer Verlauf der KI-Latenz — macht Modell-Kaltstarts sichtbar (ein einzelner
    Ausreisser nach oben ist fast immer ein Kaltstart, kein langsameres Modell)."""
    try:
        days = store.latency_by_day(days=14)
    except Exception:
        return ""
    if len(days) < 2:
        return ""
    values = [ms for _day, ms in days]
    best, worst = min(values), max(values)
    if worst <= 0:
        return ""
    line = f"\nKI-Latenz der letzten {len(values)} Tage: {values[-1] / 1000:.1f} s zuletzt"
    if worst >= best * 2 and worst - best > 2000:
        line += (f" · Spanne {best / 1000:.1f}–{worst / 1000:.1f} s "
                 f"(Ausreisser = Modell-Kaltstart)")
    return line


# Anzeigetexte fuer history.Stats.productive_daypart ("Deine Muster"-Karte).
_DAYPART_LABELS = {
    "morgens": "morgens (5–11 Uhr)",
    "mittags": "mittags (11–14 Uhr)",
    "nachmittags": "nachmittags (14–18 Uhr)",
    "abends": "abends (18–23 Uhr)",
    "nachts": "nachts (23–5 Uhr)",
}


# Zeitraeume der Insights: (Schluessel, Beschriftung, Tage | None fuer „alles").
# Bewusst kurz gehalten — vier Knoepfe passen in die Kopfzeile, sieben nicht.
INSIGHT_RANGES = (("day", "Heute"), ("week", "7 Tage"),
                  ("month", "30 Tage"), ("all", "Alle"))


_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}


class InsightsPage(QWidget):
    def __init__(self, store: HistoryStore, on_add_rule=None, settings=None,
                 on_ignored=None):
        """on_add_rule: Callable(falsch, richtig) — uebernimmt einen erkannten
        Korrektur-Fehler als Woerterbuch-Regel (Ein-Klick aus der Vorschlags-Karte).
        settings: UserSettings — fuer bereits vorhandene Regeln und die Ignorier-
        Liste (None = alle Vorschlaege zeigen, z. B. in Tests).
        on_ignored: Callable() — nach einem „Ignorieren"-Klick, damit der Editor
        der Ignorier-Liste in den Einstellungen nachzieht."""
        self._on_add_rule = on_add_rule
        self._settings = settings
        self._on_ignored = on_ignored
        self._init_page(store)

    def _init_page(self, store: HistoryStore):
        super().__init__()
        self.store = store

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*PAGE_MARGINS)
        outer.setSpacing(PAGE_SPACING)   # Karten-Grid-Gap, siehe theme.py
        # Kopfzeile: Titel links, Zeitraum rechts. Der Zeitraum ist der Grund, warum
        # die Seite ueberhaupt lebendig wirkt — ohne ihn rechnet jede Zahl ueber die
        # gesamte Historie, und nach ein paar hundert Diktaten bewegt sich nichts mehr.
        head = QHBoxLayout()
        title = QLabel("Insights")
        title.setStyleSheet(page_title_qss())
        head.addWidget(title)
        head.addStretch(1)
        self._range_buttons: dict[str, QPushButton] = {}
        for key, label in INSIGHT_RANGES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("range_key", key)   # KEIN Lambda mit self — Referenzzyklus
            btn.clicked.connect(self._on_range_clicked)
            self._range_buttons[key] = btn
            head.addWidget(btn)
        outer.addLayout(head)
        self._range = self._stored_range()
        self._apply_range_styles()

        # Reihe 1 — drei KPI-Karten (Titel im Header, grosse Kennzahl darunter).
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        outer.addLayout(row1)

        self._wpm_frame, wpm_box = _card("WPM")
        gauge_row = QHBoxLayout()
        self._gauge = WpmGauge()
        gauge_row.addStretch(1)
        gauge_row.addWidget(self._gauge)
        gauge_row.addStretch(1)  # Gauge mittig in der Karte (Design)
        wpm_box.addLayout(gauge_row)
        # Echte Sprechzeit aus `audio_seconds` der Historie — NICHT aus Woertern
        # geteilt durch WPM gerechnet. Das waere ein Zirkelschluss (WPM stammt aus
        # denselben zwei Zahlen) und haette Pausen, Verwerfungen und abgebrochene
        # Aufnahmen unterschlagen.
        self._time_label = QLabel("")
        self._time_label.setWordWrap(True)
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setStyleSheet(
            f"color: {MUTED}; font-size: 8.5pt; border: none;")
        wpm_box.addWidget(self._time_label)
        wpm_box.addStretch(1)

        self._fix_frame, fix_box, self._fix_value = _metric("Korrekturen von Fleech")
        self._fix_detail = QLabel("")
        self._fix_detail.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        fix_box.addWidget(self._fix_detail)
        fix_box.addStretch(1)

        self._words_frame, words_box, self._words_value = _metric("Wörter diktiert")
        # Hier stand bisher der Lokal-Anteil („Desktop · 100 % lokal"). Seit v3.6.0
        # gibt es ueberhaupt keinen Cloud-Pfad mehr — die Zeile konnte gar nichts
        # anderes mehr sagen und war damit tote Flaeche. Jetzt steht dort ein
        # Groessenvergleich mit einem bekannten Buch: „74.245" sagt niemandem etwas,
        # „etwa das 1,2-Fache von Momo" schon.
        self._local_label = QLabel("")
        self._local_label.setWordWrap(True)
        self._local_label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        words_box.addWidget(self._local_label)
        words_box.addStretch(1)

        row1.addWidget(self._wpm_frame, 1)
        row1.addWidget(self._fix_frame, 1)
        row1.addWidget(self._words_frame, 1)

        # Reihe 2 — App-Nutzung und Serie, gleich breit (Design).
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        outer.addLayout(row2)
        self._usage_frame, self._usage_box = _card("App-Nutzung")
        # Befehle — welche Art Anweisung nutzt du wirklich? Gleiche Rangliste wie
        # die App-Nutzung; Karte bleibt weg, solange es keine Befehle gab.
        self._commands_frame, self._commands_box = _card("Befehle")
        self._commands_rows: list[QWidget] = []
        self._streak_frame, streak_box = _card("Serie")
        self._calendar = StreakCalendar()
        streak_box.addWidget(self._calendar)
        self._streak_label = QLabel("")
        self._streak_label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        streak_box.addWidget(self._streak_label)
        row2.addWidget(self._usage_frame, 1)
        row2.addWidget(self._commands_frame, 1)
        row2.addWidget(self._streak_frame, 1)

        # Reihe 3 — Haeufigste Woerter · Deine Muster · Verarbeitung, je ein Drittel.
        row3 = QHBoxLayout()
        row3.setSpacing(12)
        outer.addLayout(row3)

        # Haeufigste Woerter — Rangliste wie App-Nutzung, Fuellwoerter ausgeblendet
        # (STOPWORDS_DE); die erste Zeile ist damit implizit das "Lieblingswort".
        # "Alle anzeigen" oeffnet die vollstaendige Liste (nicht nur die Top 5).
        show_all_words = _link_button("Alle anzeigen")
        show_all_words.clicked.connect(self._open_word_detail)
        self._words_freq_frame, self._words_freq_box = _card(
            "Häufigste Wörter", header_action=show_all_words
        )
        row3.addWidget(self._words_freq_frame, 1)

        # Deine Muster — kurze Einordnung aus Tageszeit/Wochentag der Diktate.
        self._pattern_frame, pattern_box = _card("Deine Muster")
        self._pattern_label = QLabel("")
        self._pattern_label.setWordWrap(True)
        self._pattern_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        pattern_box.addWidget(self._pattern_label)
        pattern_box.addStretch(1)
        row3.addWidget(self._pattern_frame, 1)

        # Verarbeitung — lokale Latenz-Telemetrie + Routing-/Fallback-Bild.
        # Vorschlags-Karte: aus Zahlen wird eine Handlung. Wird nur eingeblendet,
        # wenn es tatsaechlich etwas vorzuschlagen gibt (sonst leerer Platz).
        self._advice_frame, self._advice_box = _card("Vorschläge")
        self._advice_rows: list[QWidget] = []
        outer.addWidget(self._advice_frame)

        self._processing_frame, processing_box = _card("Verarbeitung")
        self._processing_label = QLabel("")
        self._processing_label.setWordWrap(True)
        self._processing_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        processing_box.addWidget(self._processing_label)
        processing_box.addStretch(1)
        row3.addWidget(self._processing_frame, 1)

        outer.addStretch(1)
        self._usage_rows: list[QWidget] = []
        self._words_freq_rows: list[QWidget] = []
        self._advice_allowed = True
        self._commands_allowed = True

    # -- Vorschlaege ------------------------------------------------------------------

    def _advice_text(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        self._advice_box.addWidget(label)
        return label

    def _correction_row(self, wrong: str, right: str, count: int) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        label = QLabel(f"„{wrong}“ wurde {count}× zu „{right}“ korrigiert")
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        button = style_button(QPushButton("Als Regel übernehmen"))
        # Daten am Button statt in einem Lambda: ein Lambda, das `self` faengt und in
        # einem Kind-Widget haengt, erzeugt einen Referenzzyklus (real: sporadische
        # Access Violations). Eine gebundene Methode + sender()-Property ist sicher.
        button.setProperty("rule_wrong", wrong)
        button.setProperty("rule_right", right)
        button.clicked.connect(self._on_take_rule)
        ignore = style_button(QPushButton("Ignorieren"))
        ignore.setToolTip(
            "Schlägt dieses Paar nicht mehr vor. Die Liste der ignorierten Paare "
            "steht unter Einstellungen → Wörterbuch — dort löschen holt den "
            "Vorschlag zurück."
        )
        ignore.setProperty("rule_wrong", wrong)
        ignore.setProperty("rule_right", right)
        ignore.clicked.connect(self._on_ignore_rule)
        h.addWidget(label, 1)
        h.addWidget(button)
        h.addWidget(ignore)
        self._advice_box.addWidget(row)
        return row

    @staticmethod
    def _advice_key(wrong: str, right: str) -> str:
        return f"{wrong} => {right}".lower()

    def _on_take_rule(self) -> None:
        button = self.sender()
        if button is None or self._on_add_rule is None:
            return
        wrong = button.property("rule_wrong")
        right = button.property("rule_right")
        if not wrong or not right:
            return
        self._on_add_rule(str(wrong), str(right))
        # Kein zusaetzlicher Merkposten noetig: `_refresh_advice` blendet Paare aus,
        # fuer die bereits eine Woerterbuch-Regel existiert. Loescht man die Regel
        # spaeter wieder, taucht der Vorschlag zu Recht erneut auf.
        self._refresh_advice()

    def _on_ignore_rule(self) -> None:
        """„Ignorieren": Paar dauerhaft in die sichtbare Ignorier-Liste.

        Dieselbe Liste, die auch abgelehnte Woerterbuch-Rueckfragen traegt — sie
        steht als Editor unter Einstellungen → Woerterbuch. Dauerhaft ist hier
        vertretbar, WEIL sie sichtbar ist: Ein Fehlklick laesst sich dort per
        Zeile-loeschen zuruecknehmen."""
        button = self.sender()
        settings = self._settings
        if button is None or settings is None:
            return
        wrong = button.property("rule_wrong")
        right = button.property("rule_right")
        if not wrong or not right:
            return
        key = self._advice_key(str(wrong), str(right))
        ignores = settings.output.dictionary_ignores
        if not any(str(i).strip().lower() == key for i in ignores):
            ignores.append(key)
            settings.save()
        if self._on_ignored is not None:
            self._on_ignored()
        self._refresh_advice()

    def _advice_suppressed(self, wrong: str, right: str) -> bool:
        """Vorschlag ausblenden — weil die Regel schon existiert oder das Paar auf
        der Ignorier-Liste steht."""
        settings = self._settings
        if settings is None:
            return False
        line = f"{wrong} => {right}".strip().lower()
        for existing in settings.output.dictionary or []:
            if str(existing).strip().lower() == line:
                return True
        key = self._advice_key(wrong, right)
        return any(str(i).strip().lower() == key
                   for i in settings.output.dictionary_ignores or [])

    def _update_advice_visibility(self) -> None:
        self._advice_frame.setVisible(self._advice_allowed and bool(self._advice_rows))

    def _refresh_advice(self) -> None:
        """Beobachtungen, aus denen eine Handlung folgt. Nichts zu sagen → Karte weg."""
        for row in self._advice_rows:
            self._advice_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._advice_rows = []

        try:
            # Mehr holen als angezeigt wird: Sonst bliebe die Karte leer, sobald die
            # drei staerksten Paare uebernommen oder weggeklickt sind — obwohl es
            # dahinter weitere echte Funde gibt.
            corrections = self.store.top_corrections(limit=_ADVICE_SCAN)
        except Exception:
            corrections = []
        shown = 0
        for wrong, right, count in corrections:
            if shown >= _ADVICE_SHOWN:
                break
            if self._advice_suppressed(wrong, right):
                continue
            shown += 1
            if self._on_add_rule is None:
                self._advice_rows.append(self._advice_text(
                    f"„{wrong}“ wurde {count}× zu „{right}“ korrigiert."))
            else:
                self._advice_rows.append(self._correction_row(wrong, right, count))

        try:
            recent, previous, seen = self.store.fallback_trend()
        except Exception:
            recent, previous, seen = 0.0, 0.0, 0
        # Nur melden, wenn es genug Diktate gab UND der Anstieg deutlich ist —
        # sonst ist jede Schwankung ein Fehlalarm.
        if seen >= 5 and recent >= 0.25 and recent > previous * 1.5:
            self._advice_rows.append(self._advice_text(
                f"Die Fallback-Quote liegt zuletzt bei {round(recent * 100)} % (davor "
                f"{round(previous * 100)} %) — läuft Ollama noch, und stimmt das "
                f"Modell in der Konfiguration?"
            ))
        self._update_advice_visibility()

    def apply_interface(self, ui) -> None:
        """Bausteine gemaess InterfaceSettings ein-/ausblenden."""
        self._wpm_frame.setVisible(ui.insights_show_wpm)
        self._fix_frame.setVisible(ui.insights_show_corrections)
        self._words_frame.setVisible(ui.insights_show_words)
        self._usage_frame.setVisible(ui.insights_show_app_usage)
        self._streak_frame.setVisible(ui.insights_show_streak)
        self._words_freq_frame.setVisible(ui.insights_show_top_words)
        self._pattern_frame.setVisible(ui.insights_show_patterns)
        self._processing_frame.setVisible(ui.insights_show_processing)
        self._advice_allowed = getattr(ui, "insights_show_advice", True)
        self._update_advice_visibility()
        # Die Befehls-Karte kennt zwei Gruende, weg zu sein: abgeschaltet ODER es
        # gab noch keine Befehle. Der Sichtbarkeits-Stand aus refresh() darf hier
        # nicht ueberschrieben werden — deshalb nur die Erlaubnis merken und die
        # tatsaechliche Sichtbarkeit dem naechsten refresh() ueberlassen.
        self._commands_allowed = getattr(ui, "insights_show_commands", True)
        if not self._commands_allowed:
            self._commands_frame.setVisible(False)

    def enable_hiding(self, settings, on_changed) -> None:
        """Jede Karte per Rechtsklick ausblendbar machen (statt Checkbox-Liste)."""
        for frame, title, attr in (
            (self._wpm_frame, "Wörter/Minute", "insights_show_wpm"),
            (self._fix_frame, "Korrekturen", "insights_show_corrections"),
            (self._words_frame, "Wörter diktiert", "insights_show_words"),
            (self._usage_frame, "App-Nutzung", "insights_show_app_usage"),
            (self._commands_frame, "Befehle", "insights_show_commands"),
            (self._streak_frame, "Serie", "insights_show_streak"),
            (self._words_freq_frame, "Häufigste Wörter", "insights_show_top_words"),
            (self._pattern_frame, "Deine Muster", "insights_show_patterns"),
            (self._processing_frame, "Verarbeitung", "insights_show_processing"),
            (self._advice_frame, "Vorschläge", "insights_show_advice"),
        ):
            enable_card_hiding(frame, title, attr, settings, on_changed)

    def _open_word_detail(self) -> None:
        WordDetailDialog(self.store, self).exec()

    def _stored_range(self) -> str:
        gemerkt = getattr(getattr(self._settings, "interface", None),
                          "insights_range", "all")
        return gemerkt if gemerkt in _RANGE_DAYS else "all"

    def _on_range_clicked(self) -> None:
        """Zeitraum umgeschaltet. Der Schluessel haengt am Button (setProperty),
        NICHT in einem Lambda — ein Lambda mit `self` in einem Kind-Widget baut
        einen Referenzzyklus, an dem Qt schon einmal sporadisch abgestuerzt ist."""
        sender = self.sender()
        key = sender.property("range_key") if sender is not None else None
        if key not in _RANGE_DAYS:
            return
        self._range = key
        if self._settings is not None:
            try:
                self._settings.interface.insights_range = key
                self._settings.save()
            except Exception:
                log.debug("Zeitraum konnte nicht gespeichert werden.", exc_info=True)
        self._apply_range_styles()
        self.refresh()

    def _apply_range_styles(self) -> None:
        for key, btn in self._range_buttons.items():
            aktiv = key == self._range
            btn.setChecked(aktiv)
            btn.setStyleSheet(
                f"QPushButton {{ background: {'#16333a' if aktiv else 'transparent'};"
                f"  color: {ACCENT if aktiv else MUTED}; border: none;"
                f"  border-radius: 7px; padding: 4px 11px; font-size: 8.5pt;"
                f"  font-weight: {'600' if aktiv else '500'}; }}"
                f"QPushButton:hover {{ color: {TEXT}; }}"
            )

    def _range_since(self) -> float | None:
        tage = _RANGE_DAYS.get(self._range)
        return None if not tage else _time.time() - tage * 86400

    def refresh(self) -> None:
        stats = self.store.stats(since=self._range_since())
        self._gauge.set_wpm(stats.wpm)  # Kennzahl steht IM Gauge (Design)
        self._time_label.setText(_diktierzeit_text(stats))
        self._fix_value.setText(f"{stats.corrected_words:n}")
        per_dictation = (stats.corrected_words / stats.total_dictations
                         if stats.total_dictations else 0.0)
        self._fix_detail.setText(
            f"Wörter korrigiert oder entfernt\n"
            f"aus {stats.total_dictations:n} Diktaten · Ø {per_dictation:.1f} je Diktat"
        )
        self._words_value.setText(f"{stats.total_words:n}")
        self._streak_label.setText(
            f"Aktuell {stats.streak} Tage · längste Serie {stats.longest_streak} Tage"
        )
        self._calendar.set_data(stats.daily_counts or {})

        usage_entries = [
            (app.removesuffix(".exe"), share, f"{round(share * 100)} %")
            for app, _words, share in (stats.app_usage or [])[:5]
        ]
        self._usage_rows = _rebuild_ranked_list(
            self._usage_box, self._usage_rows, usage_entries, "Noch keine Daten."
        )

        try:
            kinds = self.store.command_kinds()
        except Exception:
            kinds = []
        kind_total = sum(count for _name, count in kinds)
        command_entries = [
            (name, (count / kind_total) if kind_total else 0.0, f"{count}×")
            for name, count in kinds
        ]
        self._commands_rows = _rebuild_ranked_list(
            self._commands_box, self._commands_rows, command_entries,
            "Noch keine Befehle genutzt."
        )
        self._commands_frame.setVisible(self._commands_allowed and bool(kinds))

        # Groessenvergleich statt nackter Zahl. Bewusst NICHT bei jedem Neuzeichnen
        # neu gewuerfelt, sondern einmal je Aufbau der Seite — sonst wechselte der
        # Titel bei jedem Repaint und die Karte flackerte.
        self._local_label.setText(word_milestone(int(stats.total_words or 0)))

        word_entries = [
            (word, share, f"{count}×")
            for word, count, share in (stats.top_words or [])[:5]
        ]
        self._words_freq_rows = _rebuild_ranked_list(
            self._words_freq_box, self._words_freq_rows, word_entries, "Noch keine Daten."
        )

        if stats.productive_daypart and stats.productive_weekday:
            self._pattern_label.setText(
                f"Du diktierst am meisten {_DAYPART_LABELS.get(stats.productive_daypart, stats.productive_daypart)}. "
                f"Dein aktivster Wochentag ist {stats.productive_weekday}."
            )
        else:
            self._pattern_label.setText(
                "Noch nicht genug Diktate für eine Auswertung — nach ein paar Tagen "
                "zeigen wir dir hier, wann du am produktivsten bist."
            )

        self._processing_label.setText(
            _processing_summary(stats) + _latency_trend_line(self.store)
        )
        self._refresh_advice()
