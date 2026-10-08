"""Startseite: Begruessung, Verlauf der Diktate, Kurz-Statistik.

Die Seite kennt den Verlauf und die Einstellungen — sonst nichts. Was sie an
Aktionen anbietet (Eintrag loeschen, neu bereinigen), meldet sie per Signal nach
oben, statt selbst zu handeln.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...history import HistoryStore, treffer_als_markdown
from ...usersettings import UserSettings
from ..dialogs import TranscriptDetailDialog
from .verlauffilter import VerlaufFilter
from ..theme import (
    ACCENT, AMBER, MUTED, NAV_ACTIVE_BG, PAGE_MARGINS, PAGE_SPACING, ROW_HOVER,
    SIDEBAR, TEXT, TRACK, page_title_qss,
)
from ..widgets import _ElidedLabel, _card, _x_icon, enable_card_hiding

log = logging.getLogger(__name__)


class HistoryEntryRow(QFrame):
    """Flache Verlaufszeile (Design-System): Uhrzeit · einzeiliger Text · Loeschen.
    Transparent, hebt sich beim Hover an (ROW_HOVER); der Loeschen-Button erscheint
    erst beim Hover. Klick auf die Zeile oeffnet den vollen Text; der Loeschen-Button
    verschluckt seinen Klick (Qt liefert das Event dem Button, nicht dem Parent)."""

    clicked = Signal()
    # Rechtsklick — der Aufrufer haengt daran das Kontextmenue (Nachbearbeitung).
    # Als Signal statt fest verdrahtetem Menue: Die Zeile weiss nichts von Profilen
    # und Pipeline, sie meldet nur, dass jemand rechts geklickt hat.
    context_requested = Signal(object)      # QPoint (global)

    def __init__(self, entry: dict, on_delete):
        super().__init__()
        self.setObjectName("entry")
        self.setStyleSheet(
            f"QFrame#entry {{ background: transparent; border-radius: 8px; }}"
            f"QFrame#entry:hover {{ background: {ROW_HOVER}; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Klicken für den vollen Text")
        self.entry_id = entry["id"]

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)
        time_label = QLabel(_dt.datetime.fromtimestamp(entry["ts"]).strftime("%H:%M"))
        time_label.setStyleSheet(f"color: {MUTED}; font-size: 9pt; background: transparent;")
        time_label.setFixedWidth(44)
        text_label = _ElidedLabel()
        text_label.setStyleSheet(f"color: {TEXT}; font-size: 9.5pt; background: transparent;")
        text_label.setFullText(entry["cleaned"])

        self._del_btn = del_btn = QPushButton()
        del_btn.setIcon(_x_icon(MUTED))
        del_btn.setIconSize(QSize(14, 14))
        del_btn.setFixedSize(24, 24)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("Eintrag löschen")
        del_btn.setFocusPolicy(Qt.NoFocus)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {TRACK}; }}"
        )
        del_btn.clicked.connect(lambda: on_delete(self.entry_id))
        # Erst beim Hover sichtbar — Platz bleibt reserviert (keine Layout-Spruenge).
        sp = del_btn.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        del_btn.setSizePolicy(sp)
        del_btn.hide()
        row.addWidget(time_label)
        row.addWidget(text_label, 1)
        # Amberner Punkt, wenn etwas nicht glatt lief (V-1). Bisher sah ein Diktat,
        # bei dem der Rohtext einsprang oder Woerter wegfielen, im Verlauf aus wie
        # jedes andere — der Grund war nur im Moment des Einfuegens sichtbar.
        # Feste Breite und nur ein Zeichen: kein Layoutbruch in der Zeile.
        grund = str(entry.get("reason", "") or "").strip()
        if grund:
            mark = QLabel("●")
            mark.setStyleSheet(
                f"color: {AMBER}; font-size: 8pt; background: transparent;")
            mark.setFixedWidth(12)
            mark.setToolTip(grund)
            row.addWidget(mark)
            self.setToolTip(f"{grund} — klicken für den vollen Text")
        row.addWidget(del_btn)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.context_requested.emit(event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._del_btn.show()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._del_btn.hide()

    def mouseReleaseEvent(self, event) -> None:
        # Wie ein Button: nur ausloesen, wenn der Klick auch AUF der Karte endet
        # (Press-und-wieder-rausgezogen soll den Dialog nicht oeffnen).
        if event.button() == Qt.LeftButton and \
                self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    def __init__(self, settings: UserSettings, store: HistoryStore, on_change=None,
                 on_reprocess=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_change = on_change  # nach Einzel-Loeschung: Insights mitziehen
        # Nachbearbeitung: callable(rohtext, format, profilname). Die Seite kennt
        # die Pipeline nicht — sie reicht nur weiter, was der Nutzer gewaehlt hat.
        self._on_reprocess = on_reprocess
        self._treffer: list[dict] = []   # was gerade in der Timeline steht (Ausgabe)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*PAGE_MARGINS)
        outer.setSpacing(PAGE_SPACING)
        self._welcome = QLabel("")
        self._welcome.setStyleSheet(page_title_qss())
        outer.addWidget(self._welcome)
        outer.addSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # Verlauf (links) — mit Filterleiste darueber (V-12): suchen, Anwendung,
        # Zeitraum, Treffer ausgeben.
        links = QVBoxLayout()
        links.setSpacing(8)
        self.filter = VerlaufFilter()
        self.filter.geaendert.connect(self.refresh)
        self.filter.export_gewuenscht.connect(self._export_treffer)
        links.addWidget(self.filter)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._timeline_holder = QWidget()
        self._timeline = QVBoxLayout(self._timeline_holder)
        self._timeline.setContentsMargins(0, 8, 8, 8)
        self._timeline.addStretch(1)
        self._scroll.setWidget(self._timeline_holder)
        links.addWidget(self._scroll, 1)
        body.addLayout(links, 1)

        # Kurz-Stats (rechts) — Design-System: grosse Kennzahl + kleines Label,
        # der erste Wert (Woerter gesamt) traegt den Akzent.
        self._stats_frame, stats_box = _card("Kurz-Stats")
        self._stats_frame.setFixedWidth(190)
        stats_box.setSpacing(12)

        def _stat(color: str, caption: str) -> QLabel:
            value = QLabel("")
            value.setStyleSheet(
                f"color: {color}; font-size: 21pt; font-weight: 600; border: none;"
            )
            label = QLabel(caption)
            label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
            holder = QVBoxLayout()
            holder.setSpacing(3)
            holder.addWidget(value)
            holder.addWidget(label)
            stats_box.addLayout(holder)
            return value

        self._stat_words = _stat(ACCENT, "Wörter gesamt")
        self._stat_wpm = _stat(TEXT, "WPM")
        self._stat_streak = _stat(TEXT, "Tage-Serie")
        stats_box.addStretch(1)
        side = QVBoxLayout()
        side.addWidget(self._stats_frame)
        side.addStretch(1)
        body.addLayout(side)

    def apply_interface(self, ui) -> None:
        """Bausteine gemaess InterfaceSettings ein-/ausblenden."""
        self._welcome.setVisible(ui.home_show_welcome)
        self._stats_frame.setVisible(ui.home_show_stats)

    def enable_hiding(self, settings, on_changed) -> None:
        enable_card_hiding(self._stats_frame, "Statistik", "home_show_stats",
                           settings, on_changed)

    def _display_name(self) -> str:
        name = self.settings.general.display_name.strip()
        if not name:
            try:
                name = getpass.getuser().capitalize()
            except Exception:
                name = ""
        return name

    def refresh(self) -> None:
        name = self._display_name()
        self._welcome.setText(f"Willkommen zurück{', ' + name if name else ''}")

        stats = self.store.stats()
        self._stat_words.setText(f"{stats.total_words:n}")
        self._stat_wpm.setText(f"{round(stats.wpm)}")
        self._stat_streak.setText(f"{stats.streak}")

        # Timeline neu aufbauen (gruppiert nach Tag)
        while self._timeline.count() > 1:
            item = self._timeline.takeAt(0)
            w = item.widget()
            if w:
                # sofort verstecken: takeAt entfernt nur aus dem Layout, gemalt
                # wird das Widget sonst bis zum naechsten Event-Loop-Durchlauf
                w.hide()
                w.deleteLater()
        self.filter.setze_apps(self._app_namen())
        entries = self._eintraege()
        self._treffer = entries
        if not entries:
            empty = QLabel(
                "Keine Treffer — anderer Suchbegriff, andere Anwendung oder "
                "größerer Zeitraum." if self.filter.aktiv()
                else "Noch keine Diktate — halte den Hotkey und sprich los."
            )
            empty.setStyleSheet(f"color: {MUTED}; font-size: 10pt;")
            self._timeline.insertWidget(0, empty)
            return
        today = _dt.date.today()
        group = None
        insert_at = 0
        for entry in entries:
            day = _dt.datetime.fromtimestamp(entry["ts"]).date()
            if day != group:
                group = day
                title = ("HEUTE" if day == today else
                         "GESTERN" if day == today - _dt.timedelta(days=1)
                         else day.strftime("%d.%m.%Y"))
                header = QLabel(title)
                header.setStyleSheet(
                    f"color: {MUTED}; font-size: 7.5pt; font-weight: 600;"
                    f" letter-spacing: 1px; margin-top: 10px; padding-left: 8px;"
                )
                self._timeline.insertWidget(insert_at, header)
                insert_at += 1
            self._timeline.insertWidget(insert_at, self._entry_row(entry))
            insert_at += 1

    # -- Suche und Ausgabe (V-12) ------------------------------------------------------

    def _eintraege(self) -> list[dict]:
        """Die Liste, die gerade gezeigt wird: gefiltert oder die letzten 40.

        Solange nichts eingestellt ist, bleibt es beim bisherigen Verhalten —
        die Suche kostet niemanden etwas, der sie nicht benutzt."""
        if not self.filter.aktiv():
            return self.store.recent(limit=40)
        return self.store.search(
            text=self.filter.suchtext(), app=self.filter.app(),
            von=self.filter.von(), limit=200,
        )

    def _app_namen(self) -> list[str]:
        """Anwendungen fuer die Auswahlliste — zuletzt benutzte zuerst."""
        try:
            gesehen = self.store.last_seen_apps()
        except Exception:
            log.debug("App-Liste nicht ermittelbar.", exc_info=True)
            return []
        return [app for app, _ts in sorted(gesehen.items(), key=lambda p: -p[1])]

    def _export_treffer(self) -> None:
        """Die angezeigten Eintraege als Markdown-Datei sichern.

        Bewusst die ANGEZEIGTEN, nicht der ganze Bestand: Ein Abzug von tausend
        Diktaten beantwortet keine Frage. Der Hinweis, dass darin der volle
        Wortlaut unverschluesselt steht, haengt am Knopf (Tooltip)."""
        from PySide6.QtWidgets import QFileDialog

        eintraege = getattr(self, "_treffer", None) or []
        if not eintraege:
            log.info("Nichts zu speichern — die Trefferliste ist leer.")
            return
        vorschlag = f"fleech-verlauf-{_dt.date.today().isoformat()}.md"
        pfad, _filter = QFileDialog.getSaveFileName(
            self, "Treffer als Markdown speichern", vorschlag, "Markdown (*.md)")
        if not pfad:
            return
        self._schreibe_markdown(pfad, eintraege)

    @staticmethod
    def _schreibe_markdown(pfad, eintraege: list[dict]) -> bool:
        """Getrennt vom Dateidialog, damit der Inhalt pruefbar ist, ohne eine
        blockierende Qt-Event-Loop zu starten."""
        from pathlib import Path

        try:
            Path(pfad).write_text(treffer_als_markdown(eintraege), encoding="utf-8")
        except Exception:
            log.exception("Verlauf konnte nicht gespeichert werden: %s", pfad)
            return False
        log.info("Verlauf ausgegeben: %d Einträge nach %s", len(eintraege), pfad)
        return True

    def _entry_row(self, entry: dict) -> QFrame:
        row = HistoryEntryRow(entry, self._delete_entry)
        row.clicked.connect(lambda: self._open_entry(entry))
        # `entry` ist ein reines Dict ohne Qt-Bezug — hier entsteht kein
        # Referenzzyklus (anders als bei einem Lambda, das ein Widget faengt).
        row.context_requested.connect(
            lambda pos, e=entry: self._entry_menu(e, pos))
        return row

    def _entry_menu(self, entry: dict, pos) -> None:
        """Rechtsklick auf einen Verlaufseintrag → Menue bauen und oeffnen."""
        self._baue_eintrag_menue(entry).exec(pos)

    def _baue_eintrag_menue(self, entry: dict):
        """Das Kontextmenue eines Verlaufseintrags — gebaut, aber nicht geoeffnet.

        Getrennt vom Oeffnen, weil `QMenu.exec` eine eigene Event-Loop startet:
        Im Test liesse sich das nur durch Patchen der C++-Methode umgehen, und das
        haengt zuverlaessig. Bauen und Zeigen zu trennen macht den Inhalt pruefbar,
        ohne irgendetwas zu faelschen.

        Der haeufigste Fall dahinter: falsches Profil erwischt. Statt neu zu
        diktieren wird das gespeicherte ROHTRANSKRIPT noch einmal durch die
        Pipeline geschickt — inklusive aller Guards.
        """
        from PySide6.QtWidgets import QMenu

        from ...profiles import PROFILE_FORMATS

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {SIDEBAR}; color: {TEXT};"
            f"  border: 1px solid {TRACK}; border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
            f"QMenu::separator {{ height: 1px; background: {TRACK}; margin: 4px 8px; }}")

        neu_menu = menu.addMenu("Neu bereinigen als …")
        neu_menu.setStyleSheet(menu.styleSheet())
        # Angeboten werden die Ausgabeformate, nicht die Profilnamen: Zwei Profile
        # mit demselben Format ergaeben denselben Text — das waere eine Auswahl
        # ohne Unterschied.
        # (Die Ausnahme fuer „Formeln" ist entfallen — das Format steht seit
        #  Befund E-14 gar nicht mehr in PROFILE_FORMATS.)
        for wert, name in PROFILE_FORMATS:
            aktion = neu_menu.addAction(name)
            aktion.triggered.connect(
                lambda _c=False, w=wert, n=name: self._reprocess(entry, w, n))

        menu.addSeparator()
        kopieren = menu.addAction("Text kopieren")
        kopieren.triggered.connect(lambda: self._kopiere(entry["cleaned"]))
        roh_kopieren = menu.addAction("Rohtext kopieren")
        roh_kopieren.triggered.connect(
            lambda: self._kopiere(self.store.raw_text(entry["id"]) or entry["cleaned"]))
        menu.addSeparator()
        loeschen = menu.addAction("Eintrag löschen")
        loeschen.triggered.connect(lambda: self._delete_entry(entry["id"]))
        return menu

    def _kopiere(self, text: str) -> None:
        if not text:
            return
        from ...clipboard import copy_text   # privat: nicht im Win+V-Verlauf

        copy_text(text)
        log.info("In die Zwischenablage kopiert (%d Zeichen).", len(text))

    def _reprocess(self, entry: dict, fmt: str, name: str) -> None:
        """Rohtranskript neu bereinigen lassen. Das Ergebnis geht in die
        ZWISCHENABLAGE, nicht ins Zielfeld.

        Bewusst so: Wer im Verlauf rechtsklickt, steht im Fleech-Fenster — das
        urspruengliche Zielfeld ist laengst nicht mehr fokussiert, und blind dorthin
        zu schreiben ist genau die Fehlerklasse, aus der die Cursor-Regeln stammen.
        """
        if self._on_reprocess is None:
            return
        roh = self.store.raw_text(entry["id"]) or ""
        if not roh.strip():
            log.info("Kein Rohtranskript zu Eintrag %s — Nachbearbeitung entfaellt.",
                     entry["id"])
            self._zeige_nachbearbeitung(entry["cleaned"], name, entry)
            self.melde_nachbearbeitung(
                "", "Zu diesem Eintrag ist kein Rohtranskript gespeichert — es gibt "
                    "nichts, was sich neu bereinigen liesse. Der Verlauf hebt den "
                    "Rohtext erst seit 5.10.4 auf.")
            return
        self._zeige_nachbearbeitung(roh, name, entry)
        self._on_reprocess(roh, fmt, name)

    def _zeige_nachbearbeitung(self, roh: str, name: str, entry: dict) -> None:
        """Das Fortschritts-Fenster oeffnen — SOFORT, vor dem Anstossen der Arbeit.

        Die Reihenfolge ist der Punkt: Erst das Fenster, dann der Auftrag. Sonst
        koennte eine sehr schnelle Antwort da sein, bevor es jemanden gibt, der sie
        anzeigt. Referenz halten, sonst raeumt der GC das Fenster sofort ab.
        """
        from ..nachbearbeitungdialog import NachbearbeitungDialog

        altes = getattr(self, "_nachbearbeitung_dialog", None)
        if altes is not None:
            altes.close()      # zwei Laeufe gleichzeitig gibt es nicht (Prozess-Lock)
        self._nachbearbeitung_dialog = NachbearbeitungDialog(roh, name, entry, self)
        self._nachbearbeitung_dialog.show()
        self._nachbearbeitung_dialog.raise_()
        self._nachbearbeitung_dialog.activateWindow()

    def melde_nachbearbeitung(self, text: str, grund: str) -> None:
        """Ergebnis (oder Grund des Scheiterns) ins offene Fenster tragen."""
        dialog = getattr(self, "_nachbearbeitung_dialog", None)
        if dialog is None:
            return
        if text:
            dialog.zeige_ergebnis(text)
        else:
            dialog.zeige_fehler(grund or "Es kam kein Text zurück.")

    def _open_entry(self, entry: dict) -> None:
        # Nicht-modal (.show statt .exec) — schliesst bei Klick daneben. Referenz
        # halten, sonst raeumt der GC den Dialog sofort wieder ab.
        self._detail_dialog = TranscriptDetailDialog(
            entry, self, raw=self.store.raw_text(entry["id"])
        )
        self._detail_dialog.show()
        self._detail_dialog.raise_()
        self._detail_dialog.activateWindow()

    def _delete_entry(self, entry_id: int) -> None:
        self.store.delete(entry_id)
        self.refresh()
        if self._on_change:
            self._on_change()  # Insights aktualisieren
