"""Anwendungen: welches Profil greift in welchem Programm.

Drei Spalten — Programme, Zuordnung, Detail. Die Seite fuehrt bewusst Buch
darueber, wann ein zugewiesenes Programm zuletzt gesehen wurde: Ein Tippfehler im
Prozessnamen faellt sonst nie auf, weil das Profil einfach stumm nie greift.
"""

from __future__ import annotations

import logging
import time as _time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from ...history import HistoryStore
from ...usersettings import UserSettings
from ..theme import (
    ACCENT, BORDER_HAIRLINE, CARD, MUTED, NAV_ACTIVE_BG, PAGE_MARGINS,
    PAGE_SPACING, ROW_HOVER, SIDEBAR, TEXT, TRACK, page_title_qss, style_button,
)
from ..widgets import _card, _no_hscroll, _passt, _suchfeld

log = logging.getLogger(__name__)


# Ab wie vielen Tagen ohne Sichtung ein zugewiesener Prozess als verdaechtig gilt.
# Bewusst grosszuegig: eine App, die man nur monatlich braucht, soll nicht sofort
# als Fehler markiert werden — es geht um Tippfehler und umbenannte Programme.
_STALE_APP_DAYS = 30


class AppsPage(QWidget):
    """Zuordnung App → Profil, von der APP aus gedacht.

    Auf der Profilseite stand dieselbe Beziehung andersherum („welche Apps gehoeren
    zu diesem Profil?") — und damit an der falschen Stelle: Ein Profil beantwortet
    seit den Ausgabeformaten die Frage „was wird aus dem Diktat", nicht „wo".
    Gefragt wird im Alltag aber „was soll Fleech in DIESEM Programm tun?" — genau
    das ist diese Seite.

    Die Daten bleiben unveraendert: zugewiesen wird weiterhin in `profil["apps"]`,
    nur die Blickrichtung dreht sich. Keine Migration.
    """

    KEIN_PROFIL = "— kein Profil (Standard)"

    def __init__(self, settings: UserSettings, store: HistoryStore, on_changed=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_changed = on_changed or (lambda section: None)
        self._loading = False

        from PySide6.QtWidgets import QComboBox, QLineEdit

        from ..chevron import apply_chevrons

        layout = QVBoxLayout(self)
        # Dieselben Masse wie Home, Insights und Profile — siehe theme.PAGE_MARGINS.
        # Diese Seite war herausgewachsen (Rand 28/24/28/20, Titel 17 pt), und beim
        # Umschalten sprang dadurch sichtbar das ganze Layout.
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(PAGE_SPACING)
        titel = QLabel("Apps")
        titel.setStyleSheet(page_title_qss())
        layout.addWidget(titel)
        unter = QLabel("Anwendung links wählen. In der Mitte, welches Profil "
                       "Fleech dort automatisch nimmt — rechts, zwischen welchen "
                       "der Profil-Hotkey dort wechselt. Ohne Zuordnung gilt das "
                       "Standardprofil oder das, was du von Hand gewählt hast.")
        unter.setWordWrap(True)
        unter.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        layout.addWidget(unter)

        body = QHBoxLayout()
        body.setSpacing(PAGE_SPACING)   # 12 wie Home, Insights und Profile (war 14)
        layout.addLayout(body, 1)

        list_style = (
            f"QListWidget {{ background: transparent; border: none; outline: none;"
            f"  color: {TEXT}; font-size: 9.5pt; }}"
            f"QListWidget::item {{ padding: 7px 10px; border-radius: 8px; }}"
            f"QListWidget::item:hover {{ background: {ROW_HOVER}; }}"
            f"QListWidget::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
        )
        links, links_box = _card("Anwendungen")
        self._app_suche = _suchfeld("Anwendung suchen …")
        self._app_suche.textChanged.connect(lambda _t: self._filter_apps())
        links_box.addWidget(self._app_suche)
        self._apps = QListWidget()
        self._apps.setStyleSheet(list_style)
        _no_hscroll(self._apps)
        self._apps.currentRowChanged.connect(lambda _r: self._refresh_detail())
        links_box.addWidget(self._apps, 1)
        body.addWidget(links, 5)

        rechts, rechts_box = _card("Zuordnung")
        self._app_titel = QLabel("")
        self._app_titel.setStyleSheet(
            f"color: {TEXT}; font-size: 11pt; font-weight: 600;")
        rechts_box.addWidget(self._app_titel)

        hinweis = QLabel("Profil für diese Anwendung")
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        rechts_box.addWidget(hinweis)
        self._profil_combo = QComboBox()
        self._profil_combo.setStyleSheet(apply_chevrons(
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ width: 11px; height: 11px;"
            f"  margin-right: 6px; image: url(__CHEV_DOWN__); }}"
            f"QComboBox QAbstractItemView {{ background: {SIDEBAR}; color: {TEXT};"
            f"  border: 1px solid {TRACK}; outline: none; padding: 4px;"
            f"  selection-background-color: {NAV_ACTIVE_BG};"
            f"  selection-color: {ACCENT}; }}"))
        self._profil_combo.currentIndexChanged.connect(self._on_profil_gewaehlt)
        rechts_box.addWidget(self._profil_combo)

        # Eigene, DRITTE Spalte: acht Profile in die Zuordnungs-Karte gequetscht
        # zeigten drei Zeilen mit Scrollbalken — man sah nicht einmal, welche
        # angehakt sind. Und es ist ohnehin eine andere Frage: „welches Profil gilt
        # hier" (Mitte) gegen „zwischen welchen kann ich hier wechseln" (rechts).
        dritte, dritte_box = _card("Schnellwechsel")
        self._app_titel2 = QLabel("")
        self._app_titel2.setStyleSheet(
            f"color: {TEXT}; font-size: 11pt; font-weight: 600;")
        dritte_box.addWidget(self._app_titel2)
        schnell_hinweis = QLabel(
            "Was der Profil-Hotkey in dieser Anwendung durchtippt — und beim "
            "Halten zur Auswahl stellt. Alles angehakt = keine Einschränkung.")
        schnell_hinweis.setWordWrap(True)
        schnell_hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        dritte_box.addWidget(schnell_hinweis)
        self._schnell = QListWidget()
        # Ankreuz-Kaestchen im Design-System (15px, Radius 4, Akzent-Fuellung mit
        # generiertem Haken) — der Windows-Standardindikator sass hier als einziges
        # helles Element in einer dunklen Karte.
        self._schnell.setStyleSheet(apply_chevrons(
            list_style
            + f"QListWidget::indicator {{ width: 15px; height: 15px;"
              f"  border-radius: 4px; border: 1.5px solid {TRACK};"
              f"  background: transparent; margin-right: 4px; }}"
              f"QListWidget::indicator:hover {{ border-color: {MUTED}; }}"
              f"QListWidget::indicator:checked {{ background: {ACCENT};"
              f"  border-color: {ACCENT}; image: url(__CHEV_CHECK__); }}"))
        _no_hscroll(self._schnell)
        self._schnell.itemChanged.connect(self._schnell_geaendert)
        dritte_box.addWidget(self._schnell, 1)

        rechts_box.addSpacing(8)
        regel_hinweis = QLabel(
            "Ausnahmen nach Fenstertitel — derselbe Prozess trägt oft sehr "
            "verschiedene Kontexte (ein Editor mit Code, einer mit Notizen). "
            "Eine Ausnahme gewinnt gegen das Profil oben. Doppelklick entfernt sie.")
        regel_hinweis.setWordWrap(True)
        regel_hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        rechts_box.addWidget(regel_hinweis)
        self._regeln = QListWidget()
        self._regeln.setStyleSheet(list_style)
        _no_hscroll(self._regeln)
        self._regeln.setMinimumHeight(60)
        self._regeln.itemDoubleClicked.connect(self._regel_entfernen)
        rechts_box.addWidget(self._regeln, 1)

        neu_row = QHBoxLayout()
        neu_row.setSpacing(6)
        self._regel_titel = QLineEdit()
        self._regel_titel.setPlaceholderText("Titel …")
        self._regel_titel.setStyleSheet(
            f"QLineEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; font-size: 9.5pt; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT}; }}")
        self._regel_titel.returnPressed.connect(self._regel_hinzufuegen)
        neu_row.addWidget(self._regel_titel, 3)
        self._regel_profil = QComboBox()
        self._regel_profil.setStyleSheet(self._profil_combo.styleSheet())
        neu_row.addWidget(self._regel_profil, 2)
        plus = style_button(QPushButton("Hinzufügen"), "ghost")
        plus.clicked.connect(self._regel_hinzufuegen)
        neu_row.addWidget(plus)
        rechts_box.addLayout(neu_row)
        body.addWidget(rechts, 5)
        body.addWidget(dritte, 4)

    # -- Daten ---------------------------------------------------------------------

    def _items(self) -> list:
        return [i for i in (self.settings.profiles.items or []) if isinstance(i, dict)]

    def _aktuelle_app(self) -> str:
        item = self._apps.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def refresh(self) -> None:
        from ...profiles import parse_app_rule
        from ..windowsfocus import list_visible_window_processes

        vorher = self._aktuelle_app()
        self._loading = True
        self._apps.clear()
        gesehen: set = set()
        self._erhoben: list = []      # [(app, zusatz)] — Quelle fuer die Anzeige
        try:
            laufend = list_visible_window_processes()
        except Exception:
            log.debug("Fensterliste nicht abrufbar.", exc_info=True)
            laufend = []
        for app in laufend:
            gesehen.add(app.lower())
            self._eintrag(app, "läuft")
        try:
            haeufig = self.store.stats().app_usage or []
        except Exception:
            haeufig = []
        for app, words, _share in haeufig:
            if app.lower() not in gesehen:
                gesehen.add(app.lower())
                self._eintrag(app, f"{words} Wörter diktiert")
        # Zugewiesene Apps, die gerade weder laufen noch im Verlauf stehen: sonst
        # verschwindet eine bestehende Regel aus der Sicht und wirkt geloescht.
        # Der „nie gesehen"-Hinweis ist wichtig — ein vertippter Prozessname
        # faellt sonst NIE auf, weil das Profil einfach stumm nie greift.
        stale = self._stale_apps()
        for profil in self._items():
            for eintrag in profil.get("apps", []):
                prozess = parse_app_rule(eintrag)[0]
                if prozess and prozess.lower() not in gesehen:
                    gesehen.add(prozess.lower())
                    tage = stale.get(prozess.lower())
                    if tage is None:
                        zusatz = "zugewiesen"
                    elif tage:
                        zusatz = f"seit {tage} Tagen nicht gesehen"
                    else:
                        zusatz = "noch nie gesehen"
                    self._eintrag(prozess, zusatz)
        self._loading = False
        self._zeige_apps(vorher)

    def _stale_apps(self) -> dict:
        """{prozess_klein: tage_seit_letztem_diktat} fuer Prozesse, die weder gerade
        laufen noch in den letzten 30 Tagen als Diktat-Ziel auftauchten.

        None-Wert gibt es nicht — 0 bedeutet „noch nie gesehen"."""
        try:
            from ..windowsfocus import list_visible_window_processes

            running = {a.lower() for a in list_visible_window_processes()}
        except Exception:
            running = set()
        try:
            seen = self.store.last_seen_apps()
        except Exception:
            seen = {}
        import time as _time

        now = _time.time()
        stale = {}
        for profile in self.settings.profiles.items or []:
            if not isinstance(profile, dict) or profile.get("default"):
                continue
            for entry in profile.get("apps", []):
                from ...profiles import parse_app_rule

                process = parse_app_rule(entry)[0].lower()
                if not process or process in running or process in stale:
                    continue
                ts = seen.get(process)
                if ts is None:
                    stale[process] = 0
                    continue
                days = int((now - ts) // 86400)
                if days >= _STALE_APP_DAYS:
                    stale[process] = days
        return stale

    def _eintrag(self, app: str, zusatz: str) -> None:
        from ...profiles import parse_app_rule

        # Nur die ALLGEMEINE Regel (ohne Titel-Bedingung) anzeigen — sonst stuende
        # links ein Profil, das nur in einem einzigen Fenster gilt, und der Pfeil
        # loege ueber den Normalfall. Titel-Ausnahmen bekommen ein eigenes Zeichen.
        profil, ausnahmen = "", 0
        for p in self._items():
            for eintrag in p.get("apps", []):
                prozess, titel = parse_app_rule(eintrag)
                if prozess.lower() != app.lower():
                    continue
                if titel:
                    ausnahmen += 1
                elif not profil:
                    profil = str(p.get("name", ""))
        text = f"{app}   ·  {zusatz}"
        if profil:
            text += f"   →  {profil}"
        if ausnahmen:
            text += f"   (+{ausnahmen} nach Titel)"
        self._erhoben.append((app, zusatz, text))

    def _refresh_detail(self) -> None:
        from ...profiles import parse_app_rule

        app = self._aktuelle_app()
        self._loading = True
        self._regeln.clear()
        self._profil_combo.clear()
        self._regel_profil.clear()
        self._profil_combo.addItem(self.KEIN_PROFIL, "")
        for p in self._items():
            if not p.get("default"):
                name = str(p.get("name", ""))
                self._profil_combo.addItem(name, name)
                self._regel_profil.addItem(name, name)
        self._app_titel.setText(app or "Keine Anwendung gewählt")
        self._app_titel2.setText(app or "—")
        self._profil_combo.setEnabled(bool(app))
        for w in (self._regel_titel, self._regel_profil):
            w.setEnabled(bool(app) and self._regel_profil.count() > 0)
        self._fuelle_schnellwechsel(app)
        if not app:
            self._loading = False
            return

        gewaehlt = ""
        for p in self._items():
            for eintrag in p.get("apps", []):
                prozess, titel = parse_app_rule(eintrag)
                if prozess.lower() != app.lower():
                    continue
                if titel:
                    zeile = QListWidgetItem(
                        f"Titel enthält „{titel}“   →  {p.get('name', '')}")
                    zeile.setData(Qt.UserRole, (str(p.get("name", "")), eintrag))
                    self._regeln.addItem(zeile)
                else:
                    gewaehlt = str(p.get("name", ""))
        index = self._profil_combo.findData(gewaehlt)
        self._profil_combo.setCurrentIndex(max(0, index))
        self._loading = False

    # -- Aenderungen ----------------------------------------------------------------

    def _on_profil_gewaehlt(self, _index: int) -> None:
        if self._loading:
            return
        app = self._aktuelle_app()
        if not app:
            return
        from ...profiles import parse_app_rule

        ziel = str(self._profil_combo.currentData() or "")
        # Erst ueberall entfernen (nur die Regel OHNE Titel), dann neu setzen: Eine
        # App gehoert nie zu zwei Profilen, sonst entscheidet die Listenreihenfolge
        # und niemand kann nachvollziehen, warum welches gewinnt.
        for p in self._items():
            p["apps"] = [e for e in p.get("apps", [])
                         if not (parse_app_rule(e)[0].lower() == app.lower()
                                 and not parse_app_rule(e)[1])]
        if ziel:
            for p in self._items():
                if str(p.get("name", "")) == ziel:
                    p.setdefault("apps", []).append(app)
                    break
        self.settings.save()
        self._on_changed("profiles")
        log.info("App %s → Profil %s", app, ziel or "(keins)")
        self.refresh()

    # -- Schnellwechsel je App ------------------------------------------------------

    def _app_quick(self) -> dict:
        vorhanden = getattr(self.settings.profiles, "app_quick", None)
        if not isinstance(vorhanden, dict):
            vorhanden = {}
            self.settings.profiles.app_quick = vorhanden
        return vorhanden

    def _fuelle_schnellwechsel(self, app: str) -> None:
        """Ankreuzliste der global freigegebenen Profile, Haken je App.

        Angeboten werden nur Profile, die global im Schnellwechsel stehen — was
        dort ausgeblendet ist, kann eine App nicht zurueckholen. Sonst gaebe es
        zwei Schalter fuer dieselbe Frage, und der eine wuerde den anderen
        stillschweigend uebersteuern.
        """
        from ...profiles import quickswitch_profiles

        self._schnell.clear()
        namen = quickswitch_profiles(self._items())
        erlaubt = {str(n).lower()
                   for n in (self._app_quick().get((app or "").lower()) or [])}
        for name in namen:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Ohne Eintrag ist ALLES erlaubt — dann alle Haken setzen, sonst saehe
            # eine unkonfigurierte App aus, als waere der Schnellwechsel dort leer.
            item.setCheckState(Qt.Checked if not erlaubt or name.lower() in erlaubt
                               else Qt.Unchecked)
            item.setData(Qt.UserRole, name)
            self._schnell.addItem(item)
        self._schnell.setEnabled(bool(app) and bool(namen))

    def _schnell_geaendert(self, _item) -> None:
        if self._loading:
            return
        app = self._aktuelle_app()
        if not app:
            return
        angehakt = [str(self._schnell.item(i).data(Qt.UserRole))
                    for i in range(self._schnell.count())
                    if self._schnell.item(i).checkState() == Qt.Checked]
        speicher = self._app_quick()
        schluessel = app.lower()
        # Alle angehakt = kein Sonderfall → Eintrag entfernen statt die Vollmenge
        # zu speichern. Sonst friert die App auf dem heutigen Profilstand ein: ein
        # spaeter angelegtes Profil taucht dort nie auf, ohne dass man ahnt, warum.
        if len(angehakt) == self._schnell.count():
            speicher.pop(schluessel, None)
        else:
            # Leere Auswahl NICHT speichern — sie hiesse „hier gar kein Profil"
            # und liesse sich per Hotkey nicht mehr verlassen.
            speicher[schluessel] = angehakt or None
            if not angehakt:
                speicher.pop(schluessel, None)
        self.settings.save()
        self._on_changed("profiles")
        log.info("Schnellwechsel fuer %s: %s", app,
                 ", ".join(angehakt) if angehakt else "(alle)")

    def _zeige_apps(self, auswahl: str = "") -> None:
        """Gemerkte Eintraege anzeigen, gefiltert nach dem Suchfeld.

        Getrennt von `refresh()`, weil dort die teuren Quellen stecken (Fensterliste
        per EnumWindows, Verlaufs-Statistik). Beides bei jedem Tastendruck im
        Suchfeld abzufragen waere spuerbar traege.
        """
        suche = self._app_suche.text()
        self._loading = True
        self._apps.clear()
        for app, zusatz, text in getattr(self, "_erhoben", []):
            # Gesucht wird ueber die GANZE Zeile, nicht nur den Prozessnamen — so
            # findet „stichpunkte" auch die Apps, die auf dieses Profil zeigen.
            if not _passt(text, suche):
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, app)
            self._apps.addItem(item)
        self._loading = False
        if self._apps.count():
            treffer = [i for i in range(self._apps.count())
                       if str(self._apps.item(i).data(Qt.UserRole)) == auswahl]
            self._apps.setCurrentRow(treffer[0] if treffer else 0)
        self._refresh_detail()

    def _filter_apps(self) -> None:
        self._zeige_apps(self._aktuelle_app())

    def _regel_hinzufuegen(self) -> None:
        app = self._aktuelle_app()
        titel = self._regel_titel.text().strip()
        ziel = str(self._regel_profil.currentData() or "")
        if not app or not titel or not ziel:
            return
        from ...profiles import format_app_rule, parse_app_rule

        # Dieselbe Titel-Bedingung nie zweimal: sonst haengt dieselbe App an zwei
        # Profilen und die Reihenfolge in der Liste entscheidet.
        for p in self._items():
            p["apps"] = [e for e in p.get("apps", [])
                         if not (parse_app_rule(e)[0].lower() == app.lower()
                                 and parse_app_rule(e)[1].lower() == titel.lower())]
        for p in self._items():
            if str(p.get("name", "")) == ziel:
                p.setdefault("apps", []).append(format_app_rule(app, titel))
                break
        self.settings.save()
        self._on_changed("profiles")
        log.info("App %s (Titel %r) → Profil %s", app, titel, ziel)
        self._regel_titel.clear()
        self.refresh()

    def _regel_entfernen(self, item) -> None:
        daten = item.data(Qt.UserRole)
        if not daten:
            return
        profilname, eintrag = daten
        for p in self._items():
            if str(p.get("name", "")) == profilname:
                p["apps"] = [e for e in p.get("apps", []) if e != eintrag]
                break
        self.settings.save()
        self._on_changed("profiles")
        self.refresh()
