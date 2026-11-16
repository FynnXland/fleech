"""Insights: Kennzahlen aus der eigenen Historie — alles lokal gerechnet.

Woerter je Minute, Korrekturen, Gesamtwoerter, App-Nutzung, Serien-Kalender und
die drei handlungsfaehigen Hinweise. Die Konstanten oben stehen hier und nicht in
`widgets`, weil sie nur diese Seite betreffen.
"""

from __future__ import annotations

import logging
import random
import time as _time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...history import HistoryStore
from ...i18n import N_, dezimal, tr
from ...milestones import word_milestone
from ..dialogs import WordDetailDialog
from .anzeigetext import ganzzahl
from ..theme import (
    ACCENT, MUTED, PAGE_MARGINS, PAGE_SPACING, TEXT, page_title_qss,
    style_button,
)
from ..widgets import (
    StreakCalendar, WpmGauge, _card, _diktierzeit_text, _link_button, _metric,
    _rebuild_ranked_list, enable_card_hiding,
)

log = logging.getLogger(__name__)


def _ganzzahl(n: int) -> str:
    """Deutsche Tausendertrennung fuer Stueckzahlen. `:n` folgt der C-Locale und
    liefert ohne `locale.setlocale()` (kommt im Projekt nirgends vor) gar keinen
    Trenner (F-9/Befund 9) — `milestones._zahl` haengt bei Werten < 10 eine
    Nachkommastelle an (fuer Faktoren gedacht), das waere fuer eine Stueckzahl
    falsch, deshalb dieser einfachere Zwilling."""
    return ganzzahl(n)


def _tier_names() -> tuple:
    """Beschriftung der Routing-Stufen fuer die "Verarbeitung"-Karte.

    A-2/E-10: „schnelles Modell / großes Modell" behauptet ein zweites, kleineres
    Modell, das es seit v3.5.0 nicht mehr gibt (cleanup_fast ist BEWUSST dasselbe
    Modell wie cleanup, siehe config.yaml). Solange das so ist, heissen die Stufen
    ehrlich „kurzer Weg" (weniger Pruefung) und „voller Weg" — taucht kuenftig ein
    wirklich anderes, schnelleres Modell auf, tragen sie wieder die alten Namen.
    """
    gleich = True
    try:
        from ...config import load_config

        cfg = load_config()
        gleich = cfg.llm_cleanup.model == cfg.llm_cleanup_fast.model
    except Exception:
        log.debug("Konfiguration fuer Routing-Beschriftung nicht lesbar.", exc_info=True)
    if gleich:
        return (("trivial", tr("ohne KI")), ("simple", tr("kurzer Weg")),
                ("complex", tr("voller Weg")))
    return (("trivial", tr("ohne KI")), ("simple", tr("schnelles Modell")),
            ("complex", tr("großes Modell")))


def _gruende_zeile(gruende_zaehler) -> str:
    """„Rückfälle: 2× Ollama · 1× Sinnumkehr" ("" = nichts zu melden).

    Die Fallback-Quote sagt WIE OFT, nie WARUM (H-2). Kurzform statt vollem Satz:
    In einer Aufzaehlung zaehlt die Unterscheidbarkeit, den ganzen Grund zeigt der
    Detail-Dialog des Eintrags."""
    from collections import Counter

    from ...gruende import kurzform

    kurz: Counter = Counter()
    for grund, anzahl in (gruende_zaehler or {}).items():
        kurz[kurzform(grund)] += anzahl
    if not kurz:
        return ""
    # `kurzform` liefert das Etikett schon in der Sprache der Oberfläche.
    teile = [f"{anzahl}× {name}" for name, anzahl in kurz.most_common(4)]
    return "\n" + tr("Rückfälle: {liste}", liste=" · ".join(teile))


def _processing_summary(stats, gruende_zaehler=None) -> str:
    """Text der "Verarbeitung"-Karte: Median/p90-Latenzen, Routing-Verteilung,
    Fallback-Quote — plus die Gruende-Zeile.

    Median/p90 statt Mittelwert (F-B4): Ein Mittelwert ueberzeichnet den Normalfall
    durch seltene Kaltstart-Ausreisser nach oben UND wird durch Diktate ohne
    Modelllauf (`llm_ms=0`, "trivial") nach unten verzerrt — zwei Fehler, die sich
    gegenseitig verwischen. Die KI-Zeile filtert deshalb eigenstaendig auf
    `llm_ms > 0`, nicht auf `stt_ms > 0` wie die Erkennung.

    `gruende_zaehler`: {Grund: Anzahl} aus `HistoryStore.reasons(since)` — None
    laesst die Gruende-Zeile weg (Aufrufer ohne Verlauf, z. B. Tests)."""
    if not stats.stt_median_ms and not (stats.tier_shares or {}):
        return tr("Noch keine Daten — Latenzen werden ab dem nächsten Diktat erfasst.")
    lines = []
    if stats.stt_median_ms or stats.llm_median_ms:
        median_s = (stats.stt_median_ms + stats.llm_median_ms) / 1000
        p90_s = (stats.stt_p90_ms + stats.llm_p90_ms) / 1000
        lines.append(tr(
            "Verarbeitung: die Hälfte deiner Diktate war nach {median} s da, "
            "neun von zehn nach {p90} s", median=dezimal(median_s), p90=dezimal(p90_s)))
        detail = tr("davon {s} s Erkennung (Median)",
                    s=dezimal(stats.stt_median_ms / 1000))
        if stats.llm_median_ms:
            detail += " · " + tr("{s} s KI-Bereinigung (Median)",
                                 s=dezimal(stats.llm_median_ms / 1000))
        lines.append(detail)
    shares = stats.tier_shares or {}
    if shares:
        parts = [f"{round(shares[key] * 100)} % {label}"
                 for key, label in _tier_names() if key in shares]
        lines.append(tr("Routing: {teile}", teile=" · ".join(parts)))
    lines.append(tr("Fallback-Quote: {n} % (Diktate, die auf das Roh-Transkript "
                    "zurückfielen)", n=round(stats.fallback_rate * 100)))
    return "\n".join(lines) + _gruende_zeile(gruende_zaehler)


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
    line = "\n" + tr("KI-Latenz der letzten {n} Tage: {s} s zuletzt",
                     n=len(values), s=dezimal(values[-1] / 1000))
    if worst >= best * 2 and worst - best > 2000:
        line += " · " + tr("Spanne {von}–{bis} s (Ausreisser = Modell-Kaltstart)",
                           von=dezimal(best / 1000), bis=dezimal(worst / 1000))
    return line


# Anzeigetexte fuer history.Stats.productive_daypart ("Deine Muster"-Karte).
_DAYPART_LABELS = {
    "morgens": N_("morgens (5–11 Uhr)"),
    "mittags": N_("mittags (11–14 Uhr)"),
    "nachmittags": N_("nachmittags (14–18 Uhr)"),
    "abends": N_("abends (18–23 Uhr)"),
    "nachts": N_("nachts (23–5 Uhr)"),
}

# `history.Stats.productive_weekday` liefert den deutschen Namen — übersetzt wird
# beim Anzeigen. Die Liste markiert die Namen für den Sprachkatalog.
_WOCHENTAGE = (N_("Montag"), N_("Dienstag"), N_("Mittwoch"), N_("Donnerstag"),
               N_("Freitag"), N_("Samstag"), N_("Sonntag"))


# Zeitraeume der Insights: (Schluessel, Beschriftung, Tage | None fuer „alles").
# Bewusst kurz gehalten — vier Knoepfe passen in die Kopfzeile, sieben nicht.
INSIGHT_RANGES = (("day", N_("Heute")), ("week", N_("7 Tage")),
                  ("month", N_("30 Tage")), ("all", N_("Alle")))


_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}


class InsightsPage(QWidget):
    def __init__(self, store: HistoryStore, on_add_rule=None, settings=None,
                 on_ignored=None, kontext_fn=None):
        """on_add_rule: Callable(falsch, richtig) — uebernimmt einen erkannten
        Korrektur-Fehler als Woerterbuch-Regel (Ein-Klick aus der Vorschlags-Karte).
        settings: UserSettings — fuer bereits vorhandene Regeln und die Ignorier-
        Liste (None = alle Vorschlaege zeigen, z. B. in Tests).
        on_ignored: Callable() — nach einem „Ignorieren"-Klick, damit der Editor
        der Ignorier-Liste in den Einstellungen nachzieht.
        kontext_fn: Callable() -> KontextSpeicher|None — zweite Quelle der
        Schreibvarianten-Frage (V-14). Gereicht statt selbst geoeffnet, damit die
        Seite nicht ungefragt an die Datei des Nutzers geht (Tests, Fixtures)."""
        self._on_add_rule = on_add_rule
        self._settings = settings
        self._on_ignored = on_ignored
        self._kontext_fn = kontext_fn
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
        title = QLabel(tr("Insights"))
        title.setStyleSheet(page_title_qss())
        head.addWidget(title)
        head.addStretch(1)
        self._range_buttons: dict[str, QPushButton] = {}
        for key, label in INSIGHT_RANGES:
            btn = QPushButton(tr(label))
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

        self._wpm_frame, wpm_box = _card(tr("WPM"))
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

        self._fix_frame, fix_box, self._fix_value = _metric(tr("Korrekturen von Fleech"))
        self._fix_detail = QLabel("")
        self._fix_detail.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        fix_box.addWidget(self._fix_detail)
        fix_box.addStretch(1)

        self._words_frame, words_box, self._words_value = _metric(tr("Wörter diktiert"))
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

        # Reihe 2 — App-Nutzung und Serie, gleich breit (Design). Die fruehere
        # "Befehle"-Karte ist entfallen (Bahn F/Bahn I: 8 Befehle in 1399 Diktaten
        # belegten ein Drittel der Reihe und ignorierten den Zeitraum) — ihr Inhalt
        # steht jetzt als eine Zeile in "Deine Muster", siehe `_commands_line`.
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        outer.addLayout(row2)
        self._usage_frame, self._usage_box = _card(tr("App-Nutzung"))
        self._streak_frame, streak_box = _card(tr("Serie"))
        self._calendar = StreakCalendar()
        streak_box.addWidget(self._calendar)
        self._streak_label = QLabel("")
        self._streak_label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        streak_box.addWidget(self._streak_label)
        row2.addWidget(self._usage_frame, 1)
        row2.addWidget(self._streak_frame, 1)

        # Reihe 3 — Haeufigste Woerter · Deine Muster · Verarbeitung, je ein Drittel.
        row3 = QHBoxLayout()
        row3.setSpacing(12)
        outer.addLayout(row3)

        # Haeufigste Woerter — Rangliste wie App-Nutzung, Fuellwoerter ausgeblendet
        # (STOPWORDS_DE); die erste Zeile ist damit implizit das "Lieblingswort".
        # "Alle anzeigen" oeffnet die vollstaendige Liste (nicht nur die Top 5).
        show_all_words = _link_button(tr("Alle anzeigen"))
        show_all_words.clicked.connect(self._open_word_detail)
        self._words_freq_frame, self._words_freq_box = _card(
            tr("Häufigste Wörter"), header_action=show_all_words
        )
        row3.addWidget(self._words_freq_frame, 1)

        # Deine Muster — kurze Einordnung aus Tageszeit/Wochentag der Diktate.
        self._pattern_frame, pattern_box = _card(tr("Deine Muster"))
        self._pattern_label = QLabel("")
        self._pattern_label.setWordWrap(True)
        self._pattern_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        pattern_box.addWidget(self._pattern_label)
        pattern_box.addStretch(1)
        row3.addWidget(self._pattern_frame, 1)

        # Verarbeitung — lokale Latenz-Telemetrie + Routing-/Fallback-Bild.
        # Vorschlags-Karte: aus Zahlen wird eine Handlung. Wird nur eingeblendet,
        # wenn es tatsaechlich etwas vorzuschlagen gibt (sonst leerer Platz).
        self._advice_frame, self._advice_box = _card(tr("Vorschläge"))
        self._advice_rows: list[QWidget] = []
        outer.addWidget(self._advice_frame)

        self._processing_frame, processing_box = _card(tr("Verarbeitung"))
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
        # F-1: sagen, was der Klick TUT (nicht nur, was bisher passiert ist) —
        # "Als Regel übernehmen" wirkt global, wortgrenzenbasiert, in jedem
        # künftigen Diktat, nicht nur an dieser einen Stelle.
        label = QLabel(tr(
            "„{falsch}“ wurde {n}× zu „{richtig}“ korrigiert — die Regel ersetzt "
            "„{falsch}“ künftig überall durch „{richtig}“.",
            falsch=wrong, richtig=right, n=count))
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        button = style_button(QPushButton(tr("Als Regel übernehmen")))
        # Daten am Button statt in einem Lambda: ein Lambda, das `self` faengt und in
        # einem Kind-Widget haengt, erzeugt einen Referenzzyklus (real: sporadische
        # Access Violations). Eine gebundene Methode + sender()-Property ist sicher.
        button.setProperty("rule_wrong", wrong)
        button.setProperty("rule_right", right)
        button.clicked.connect(self._on_take_rule)
        ignore = style_button(QPushButton(tr("Ignorieren")))
        ignore.setToolTip(tr(
            "Schlägt dieses Paar nicht mehr vor. Die Liste der ignorierten Paare "
            "steht unter Einstellungen → Wörterbuch → Mehr Optionen — dort löschen holt den "
            "Vorschlag zurück."
        ))
        ignore.setProperty("rule_wrong", wrong)
        ignore.setProperty("rule_right", right)
        ignore.clicked.connect(self._on_ignore_rule)
        h.addWidget(label, 1)
        h.addWidget(button)
        h.addWidget(ignore)
        self._advice_box.addWidget(row)
        return row

    def _varianten_row(self, frage) -> QWidget:
        """Zwei Schreibweisen desselben Begriffs — als FRAGE, nie als Behauptung.

        V-14/Befund H-B3: Der haeufigere Begriff ist hier ausdruecklich nicht der
        richtige („Cloud-Code" 18× gegen „Claude Code" 10×), und ein Cluster kann
        auch zwei echte Woerter zusammenziehen („Matrize"/„Matrix"). Deshalb zwei
        gleichwertige Knoepfe und ein „Ignorieren" — keine Vorauswahl.
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        label = QLabel(tr(
            "„{a}“ {n_a}× · „{b}“ {n_b}× — welche Schreibweise stimmt?",
            a=frage.haeufig, n_a=frage.haeufig_anzahl,
            b=frage.selten, n_b=frage.selten_anzahl))
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        h.addWidget(label, 1)
        # Jede Seite ein Knopf „diese ist richtig": die ANDERE wird zur Regel
        # „falsch => richtig" und wirkt damit in beide Richtungen (Priming vor der
        # Erkennung, Ersetzung danach).
        for richtig, falsch in ((frage.haeufig, frage.selten),
                                (frage.selten, frage.haeufig)):
            btn = style_button(QPushButton(tr("„{richtig}“ ist richtig", richtig=richtig)))
            btn.setToolTip(tr(
                "Ersetzt künftig jedes „{falsch}“ durch „{richtig}“ — überall, "
                "in jedem Diktat — und vergisst „{falsch}“ im Gedächtnis.",
                falsch=falsch, richtig=richtig))
            btn.setProperty("rule_wrong", falsch)
            btn.setProperty("rule_right", richtig)
            btn.clicked.connect(self._on_take_rule)
            h.addWidget(btn)
        ignore = style_button(QPushButton(tr("Ignorieren")))
        ignore.setToolTip(tr(
            "Fragt nie wieder nach diesem Paar — z. B. weil es zwei verschiedene "
            "Wörter sind. Zurücknehmen: Einstellungen → Wörterbuch → Mehr Optionen → Ignoriert."
        ))
        ignore.setProperty("rule_wrong", frage.haeufig)
        ignore.setProperty("rule_right", frage.selten)
        ignore.clicked.connect(self._on_ignore_rule)
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
        steht als Editor unter Einstellungen → Textersetzung. Dauerhaft ist hier
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

    def _variante_unterdrueckt(self, a: str, b: str) -> bool:
        """Frage ausblenden — in BEIDE Richtungen.

        Anders als bei einer Korrektur steht bei einer Variantenfrage nicht fest,
        welche Seite die falsche ist. Wer „Claude Code ist richtig" geklickt hat,
        hat die Regel `Cloud-Code => Claude Code` angelegt; die Frage darf danach
        genauso wenig wiederkommen wie nach einem „Ignorieren" der Gegenrichtung.
        """
        settings = self._settings
        if settings is None:
            return False
        paare = {self._advice_key(a, b), self._advice_key(b, a)}
        zeilen = list(settings.output.dictionary or []) \
            + list(settings.output.dictionary_ignores or [])
        return any(str(zeile).strip().lower() in paare for zeile in zeilen)

    def _varianten_fragen(self) -> list:
        """Die Schreibvarianten-Fragen holen — Fehler kosten hier einen Vorschlag,
        nicht ein Diktat, deshalb still auf „nichts zu fragen"."""
        from ...varianten import vorschlaege

        gedaechtnis = None
        if callable(self._kontext_fn):
            try:
                gedaechtnis = self._kontext_fn()
            except Exception:
                log.debug("Gedaechtnis fuer Varianten nicht lesbar.", exc_info=True)
        try:
            return vorschlaege(self.store, gedaechtnis, limit=_ADVICE_SHOWN)
        except Exception:
            log.debug("Schreibvarianten-Auswertung fehlgeschlagen.", exc_info=True)
            return []

    def _update_advice_visibility(self) -> None:
        self._advice_frame.setVisible(self._advice_allowed and bool(self._advice_rows))

    def _refresh_advice(self) -> None:
        """Beobachtungen, aus denen eine Handlung folgt. Nichts zu sagen → Karte weg."""
        for row in self._advice_rows:
            self._advice_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._advice_rows = []

        shown = 0
        # Schreibvarianten ZUERST (V-14): Sie sind die Frage, die das Woerterbuch
        # wirklich fuellt. Der Roh-gegen-Bereinigt-Diff darunter findet Grammatik;
        # Eigennamen zeigen sich erst im Vergleich MEHRERER Diktate — „Cloud-Code"
        # 18× gegen „Claude Code" 10× ist nach 1399 Diktaten der wichtigste
        # Fachbegriff des Nutzers, und er steht in keinem einzigen Diff.
        if self._on_add_rule is not None:
            for frage in self._varianten_fragen():
                if shown >= _ADVICE_SHOWN - 1:
                    break
                if self._variante_unterdrueckt(frage.haeufig, frage.selten):
                    continue
                shown += 1
                self._advice_rows.append(self._varianten_row(frage))

        try:
            # Mehr holen als angezeigt wird: Sonst bliebe die Karte leer, sobald die
            # drei staerksten Paare uebernommen oder weggeklickt sind — obwohl es
            # dahinter weitere echte Funde gibt.
            corrections = self.store.top_corrections(limit=_ADVICE_SCAN)
        except Exception:
            corrections = []
        for wrong, right, count in corrections:
            if shown >= _ADVICE_SHOWN:
                break
            if self._advice_suppressed(wrong, right):
                continue
            shown += 1
            if self._on_add_rule is None:
                self._advice_rows.append(self._advice_text(tr(
                    "„{falsch}“ wurde {n}× zu „{richtig}“ korrigiert.",
                    falsch=wrong, richtig=right, n=count)))
            else:
                self._advice_rows.append(self._correction_row(wrong, right, count))

        try:
            recent, previous, seen = self.store.fallback_trend()
        except Exception:
            recent, previous, seen = 0.0, 0.0, 0
        # Nur melden, wenn es genug Diktate gab UND der Anstieg deutlich ist —
        # sonst ist jede Schwankung ein Fehlalarm.
        if seen >= 5 and recent >= 0.25 and recent > previous * 1.5:
            self._advice_rows.append(self._advice_text(tr(
                "Die Fallback-Quote liegt zuletzt bei {jetzt} % (davor {davor} %) — "
                "läuft Ollama noch, und stimmt das Modell in der Konfiguration?",
                jetzt=round(recent * 100), davor=round(previous * 100))))
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

    def enable_hiding(self, settings, on_changed) -> None:
        """Jede Karte per Rechtsklick ausblendbar machen (statt Checkbox-Liste)."""
        for frame, title, attr in (
            (self._wpm_frame, tr("Wörter/Minute"), "insights_show_wpm"),
            (self._fix_frame, tr("Korrekturen"), "insights_show_corrections"),
            (self._words_frame, tr("Wörter diktiert"), "insights_show_words"),
            (self._usage_frame, tr("App-Nutzung"), "insights_show_app_usage"),
            (self._streak_frame, tr("Serie"), "insights_show_streak"),
            (self._words_freq_frame, tr("Häufigste Wörter"), "insights_show_top_words"),
            (self._pattern_frame, tr("Deine Muster"), "insights_show_patterns"),
            (self._processing_frame, tr("Verarbeitung"), "insights_show_processing"),
            (self._advice_frame, tr("Vorschläge"), "insights_show_advice"),
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

    def _range_days(self) -> int | None:
        """Laenge des gewaehlten Zeitraums in Tagen — None = "Alle" (gesamter
        Verlauf, NICHT "kurz"). Steuert, ab wann ein Muster-Satz ueberhaupt eine
        Aussage ist (F-B7): Ein Wochentag-Satz auf "Heute" waere Tautologie."""
        return _RANGE_DAYS.get(self._range)

    def _commands_line(self) -> str:
        """Eine Zeile fuer "Deine Muster": welche Befehlsart wird benutzt, im
        gewaehlten Zeitraum. Ersetzt die fruehere eigene "Befehle"-Karte (Bahn F/I:
        8 Befehle in 1399 Diktaten belegten dort ein Drittel einer Reihe und
        ignorierten obendrein den Zeitraum)."""
        try:
            kinds = self.store.command_kinds(since=self._range_since())
        except Exception:
            kinds = []
        if not kinds:
            return ""
        # Die Befehlsarten stammen aus `commands.classify_command` (deutsch).
        teile = " · ".join(f"{tr(name)} {count}×" for name, count in kinds)
        return "\n" + tr("Befehle: {teile}", teile=teile)

    def refresh(self) -> None:
        seit = self._range_since()
        stats = self.store.stats(since=seit)
        self._gauge.set_wpm(stats.wpm)  # Kennzahl steht IM Gauge (Design)
        self._time_label.setText(_diktierzeit_text(stats))
        self._fix_value.setText(_ganzzahl(stats.corrected_words))
        # NUR mode='cleanup' (F-B11) — Diktate mit umformulierenden Modi (prompt/
        # command/email/math) zaehlen separat, nicht in den Korrektur-Schnitt hinein.
        cleanup_dictations = stats.total_dictations - stats.non_cleanup_dictations
        per_dictation = (stats.corrected_words / cleanup_dictations
                         if cleanup_dictations else 0.0)
        fix_detail = tr(
            "Wörter korrigiert oder entfernt\naus {n} Diktaten · Ø {schnitt} je Diktat",
            n=_ganzzahl(cleanup_dictations), schnitt=dezimal(per_dictation))
        if stats.non_cleanup_dictations:
            fix_detail += "\n" + tr("{n} Diktate umformuliert",
                                    n=_ganzzahl(stats.non_cleanup_dictations))
        self._fix_detail.setText(fix_detail)
        self._words_value.setText(_ganzzahl(stats.total_words))
        self._streak_label.setText(tr(
            "Aktuell {n} Tage · längste Serie {laengste} Tage",
            n=stats.streak, laengste=stats.longest_streak))
        self._calendar.set_data(stats.daily_counts or {})

        usage_entries = [
            (app.removesuffix(".exe"), share, f"{round(share * 100)} %")
            for app, _words, share in (stats.app_usage or [])[:5]
        ]
        self._usage_rows = _rebuild_ranked_list(
            self._usage_box, self._usage_rows, usage_entries, tr("Noch keine Daten.")
        )

        # Deterministisch aus der (ungefilterten) LEBENSZEIT-Wortzahl gewuerfelt,
        # nicht aus der Zeitraum-Zahl (F-B2) — sonst behauptet die Karte auf
        # "Heute" faelschlich, kaum etwas erreicht zu sein. Der feste Seed
        # (`lifetime // 1000`) sorgt dafuer, dass der Titel nur wechselt, wenn
        # wirklich 1000 Woerter dazugekommen sind — `refresh()` laeuft bei jedem
        # Diktat, solange die Seite offen ist, und wuerfelte vorher jedes Mal neu
        # (F-B3).
        lifetime = int(stats.lifetime_words or 0)
        self._local_label.setText(
            word_milestone(lifetime, rng=random.Random(lifetime // 1000))
        )

        word_entries = [
            (word, share, f"{count}×")
            for word, count, share in (stats.top_words or [])[:5]
        ]
        self._words_freq_rows = _rebuild_ranked_list(
            self._words_freq_box, self._words_freq_rows, word_entries,
            tr("Noch keine Daten.")
        )

        # Wochentag-/Tageszeit-Satz erst ab einem Zeitraum, der ueberhaupt eine
        # Aussage zulaesst (F-B7): "Heute" hat nur einen Wochentag — die Aussage
        # waere eine Tautologie, kein Muster.
        range_days = self._range_days()
        zeigt_tageszeit = bool(stats.productive_daypart) and \
            (range_days is None or range_days >= 2)
        zeigt_wochentag = bool(stats.productive_weekday) and \
            (range_days is None or range_days >= 7)
        if zeigt_tageszeit or zeigt_wochentag:
            saetze = []
            if zeigt_tageszeit:
                zeit = _DAYPART_LABELS.get(stats.productive_daypart,
                                           stats.productive_daypart)
                saetze.append(tr("Du diktierst am meisten {zeit}.", zeit=tr(zeit)))
            if zeigt_wochentag:
                saetze.append(tr("Dein aktivster Wochentag ist {tag}.",
                                 tag=tr(stats.productive_weekday)))
            pattern_text = " ".join(saetze)
        elif stats.productive_daypart or stats.productive_weekday:
            # Genug Diktate insgesamt fuer ein Muster, aber der gewaehlte Zeitraum
            # ist zu kurz dafuer — ein anderer Grund als "noch nicht genug Diktate".
            pattern_text = tr("Für diesen Zeitraum noch kein verlässliches Muster — "
                              "ein längerer Zeitraum zeigt mehr.")
        else:
            pattern_text = tr(
                "Noch nicht genug Diktate für eine Auswertung — nach ein paar Tagen "
                "zeigen wir dir hier, wann du am produktivsten bist."
            )
        self._pattern_label.setText(pattern_text + self._commands_line())

        # Gruende aus DEMSELBEN Zeitraum wie die Quote darueber — eine Zeile, die
        # anders rechnet als die Zahl direkt ueber ihr, wuerde nur verwirren.
        self._processing_label.setText(
            _processing_summary(stats, self.store.reasons(since=seit))
            + _latency_trend_line(self.store)
        )
        self._refresh_advice()
