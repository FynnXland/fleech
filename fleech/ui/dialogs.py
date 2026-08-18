"""Dialoge des Hauptfensters — jeder eine abgeschlossene Sache.

Vier Stueck, die nichts voneinander wissen: den Prompt eines Formats ansehen und
aendern, ein Transkript im Detail zeigen, ein Wort aus den Insights aufschluesseln,
einen Woerterbuch-Eintrag vorschlagen.

Sie liegen zusammen, weil sie dieselbe Rolle haben, nicht weil sie zusammen
arbeiten — entsprechend darf hier nie einer den anderen aufrufen.
"""

from __future__ import annotations

import datetime as _dt
import logging

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..history import HistoryStore
from .theme import (
    ACCENT, AMBER, BG, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button,
)
from .widgets import _ranked_row

log = logging.getLogger(__name__)


class PromptDialog(QDialog):
    r"""Den System-Prompt hinter einem Ausgabeformat ansehen und aendern.

    Bis 5.1.0 war er eine Blackbox: Man sah, DASS „E-Mail" anders formuliert, aber
    nicht wonach. Wer das Ergebnis verschieben will, musste raten.

    Eigene Fassungen landen in %APPDATA%\Fleech\prompts — NICHT im Programmordner,
    der bei jedem Update gespiegelt wird. Der Werkszustand bleibt daneben liegen und
    ist per Knopf jederzeit wieder herstellbar.
    """

    gespeichert = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name
        self.setWindowTitle(f"Prompt · {name}.md")
        self.resize(680, 620)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        from ..config import load_config
        from ..prompts import prompt_text

        try:
            self._prompts_dir = load_config().prompts_dir
        except Exception:
            log.debug("Config nicht ladbar — Werkspfad geraten.", exc_info=True)
            from pathlib import Path

            self._prompts_dir = Path("prompts")
        text, eigen = prompt_text(self._prompts_dir, name)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(8)

        kopf = QLabel(f"SYSTEM-PROMPT · {name.upper()}.MD"
                      + ("  ·  EIGENE FASSUNG" if eigen else "  ·  WERKSZUSTAND"))
        kopf.setStyleSheet(
            f"color: {ACCENT if eigen else MUTED}; font-size: 9pt;"
            f" font-weight: 600; letter-spacing: 0.5px;")
        outer.addWidget(kopf)

        hinweis = QLabel(
            "Das ist die Anweisung, die das Sprachmodell bei diesem Ausgabeformat "
            "bekommt. Änderungen wirken ab dem nächsten Diktat. Die Sicherheitsregel "
            "zu den Text-Markern ergänzt Fleech notfalls selbst — sie lässt sich "
            "nicht wegkürzen.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        outer.addWidget(hinweis)

        self._edit = QTextEdit()
        self._edit.setPlainText(text)
        self._edit.setStyleSheet(
            f"QTextEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 10px; font-family: Consolas, monospace; font-size: 9.5pt; }}")
        outer.addWidget(self._edit, 1)

        self._meldung = QLabel("")
        self._meldung.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        outer.addWidget(self._meldung)

        knoepfe = QHBoxLayout()
        knoepfe.setSpacing(8)
        zurueck = style_button(QPushButton("Auf Werkszustand zurücksetzen"), "ghost")
        zurueck.setEnabled(eigen)
        zurueck.clicked.connect(self._zuruecksetzen)
        knoepfe.addWidget(zurueck)
        knoepfe.addStretch(1)
        schliessen = style_button(QPushButton("Schließen"), "ghost")
        schliessen.clicked.connect(self.close)
        knoepfe.addWidget(schliessen)
        speichern = style_button(QPushButton("Speichern"), "primary")
        speichern.clicked.connect(self._speichern)
        knoepfe.addWidget(speichern)
        outer.addLayout(knoepfe)
        self._zurueck_btn = zurueck

    def _speichern(self) -> None:
        from ..prompts import save_user_prompt

        text = self._edit.toPlainText()
        if not text.strip():
            self._meldung.setText("Leer speichern geht nicht — nutze „Zurücksetzen“.")
            return
        if save_user_prompt(self._name, text):
            self._meldung.setText("Gespeichert. Gilt ab dem nächsten Diktat.")
            self._zurueck_btn.setEnabled(True)
            self.gespeichert.emit()
        else:
            self._meldung.setText("Konnte nicht gespeichert werden — siehe Protokoll.")

    def _zuruecksetzen(self) -> None:
        from ..prompts import prompt_text, save_user_prompt

        save_user_prompt(self._name, "")
        werk, _eigen = prompt_text(self._prompts_dir, self._name)
        self._edit.setPlainText(werk)
        self._meldung.setText("Werkszustand wiederhergestellt.")
        self._zurueck_btn.setEnabled(False)
        self.gespeichert.emit()


class TranscriptDetailDialog(QDialog):
    """Zeigt einen Verlaufseintrag vollstaendig (nicht abgeschnitten) und laesst den
    Text in die Zwischenablage kopieren — z. B. um ein Diktat nachzuholen, das im
    Zielfeld nicht angekommen ist (Fokus verloren, versehentlich weggeklickt)."""

    def __init__(self, entry: dict, parent=None, raw: str = ""):
        # Bewusst NICHT modal: der Dialog soll sich schliessen, sobald man daneben
        # klickt (siehe event()) — statt den Klick zu blocken (Windows-Fehlerton).
        super().__init__(parent)
        self.setWindowTitle("Transkript")
        self.resize(480, 440)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self._text = entry["cleaned"]
        self._was_activated = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(4)

        ts = _dt.datetime.fromtimestamp(entry["ts"])
        header = QLabel(f"TRANSKRIPT · {ts.strftime('%d.%m.%Y · %H:%M')}")
        header.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;"
        )
        outer.addWidget(header)

        # Der erklaerende Teil (V-1): Bis 5.10.3 stand hier nur der Text — welches
        # Profil galt, in welchem Fenster, und warum es nicht glatt lief, war nach
        # dem Diktat nicht mehr feststellbar. Leere Felder (Altzeilen, glatter
        # Lauf) erzeugen KEINE Zeile, sonst waere jeder Eintrag voller "—".
        for beschriftung, wert, farbe in (
            ("Profil", entry.get("profile", ""), MUTED),
            ("Fenster", entry.get("title", ""), MUTED),
            ("Grund", entry.get("reason", ""), AMBER),
            ("Verworfen (Rohtext-Ende)", entry.get("dropped", ""), AMBER),
        ):
            wert = str(wert or "").strip()
            if not wert:
                continue
            zeile = QLabel(f"{beschriftung}: {wert}")
            zeile.setWordWrap(True)
            zeile.setStyleSheet(f"color: {farbe}; font-size: 8.5pt;")
            outer.addWidget(zeile)
        outer.addSpacing(6)

        def _section(caption: str) -> None:
            lab = QLabel(caption)
            lab.setStyleSheet(
                f"color: {MUTED}; font-size: 7.5pt; font-weight: 500;"
                f" letter-spacing: 1px;"
            )
            outer.addWidget(lab)

        _section("BEREINIGT")
        self._edit = QTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlainText(self._text)
        self._edit.setStyleSheet(
            f"QTextEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE};"
            f"  border-radius: 8px; padding: 8px; font-size: 10pt; }}"
        )
        outer.addWidget(self._edit, 2)

        raw = (raw or "").strip()
        if raw and raw != self._text:
            outer.addSpacing(6)
            _section("ROH")
            raw_edit = QTextEdit()
            raw_edit.setReadOnly(True)
            raw_edit.setPlainText(raw)
            raw_edit.setStyleSheet(
                f"QTextEdit {{ background: {CARD}; color: {MUTED};"
                f"  border: 1px solid {BORDER_HAIRLINE};"
                f"  border-radius: 8px; padding: 8px; font-size: 9.5pt; }}"
            )
            outer.addWidget(raw_edit, 1)
        outer.addSpacing(8)

        buttons = QHBoxLayout()
        meta_parts = []
        app = (entry.get("app") or "").removesuffix(".exe")
        if app:
            meta_parts.append(app)
        meta_parts.append(f"{entry.get('words', len(self._text.split()))} Wörter")
        meta_parts.append("lokal verarbeitet")
        meta = QLabel(" · ".join(meta_parts))
        meta.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        buttons.addWidget(meta)
        buttons.addStretch(1)
        self._copy_btn = style_button(QPushButton("Kopieren"))
        self._copy_btn.clicked.connect(self._copy)
        close_btn = style_button(QPushButton("Schließen"), "ghost")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        buttons.addWidget(self._copy_btn)
        outer.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self._copy_btn.setText("Kopiert ✓")

    def event(self, e) -> bool:
        # Klick ausserhalb / Fensterwechsel → schliessen (nicht nur in den
        # Hintergrund fallen). Der Kopieren-Button klickt INNERHALB, deaktiviert
        # das Fenster also nicht. Der _was_activated-Guard verhindert, dass ein
        # verirrtes Deactivate direkt beim Oeffnen das Fenster sofort schliesst.
        if e.type() == QEvent.WindowActivate:
            self._was_activated = True
        elif e.type() == QEvent.WindowDeactivate and self._was_activated:
            self.close()
        return super().event(e)


class WordDetailDialog(QDialog):
    """Vollstaendigere Rangliste der haeufigsten Woerter (Klick auf "Alle anzeigen"
    in der Insights-Karte) — auch die Woerter, die auf den ersten 5 keinen Platz
    mehr fanden."""

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Häufigste Wörter")
        self.resize(420, 520)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        title = QLabel("ALLE WÖRTER")
        title.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;"
        )
        outer.addWidget(title)
        hint = QLabel("Gesamter Verlauf, ohne Füllwörter wie „der“, „die“, „das“.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        outer.addWidget(hint)
        outer.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(4)

        words = store.top_words(limit=50)
        if not words:
            empty = QLabel("Noch keine Daten.")
            empty.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
            box.addWidget(empty)
        else:
            for word, count, share in words:
                box.addWidget(_ranked_row(word, share, f"{count}×"))
        box.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        close_btn = style_button(QPushButton("Schließen"))
        close_btn.clicked.connect(self.accept)
        outer.addWidget(close_btn, 0, Qt.AlignRight)


class DictionarySuggestionDialog(QDialog):
    """Rueckfrage bei wahrscheinlicher Fehlschreibung: „Meintest du ‚X‘?" — mit
    markiertem Satz. Bestaetigen legt automatisch eine Woerterbuch-Regel an
    (selbstlernend); Ablehnen merkt sich das Paar und fragt nie wieder.
    Nicht-modal, schliesst bei Klick daneben."""

    def __init__(self, recognized: str, meant: str, sentence: str,
                 on_learn, on_ignore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wörterbuch")
        self.resize(440, 240)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self._on_learn = on_learn
        self._on_ignore = on_ignore
        self._recognized, self._meant = recognized, meant
        self._was_activated = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        title = QLabel(f"Meintest du „{meant}“?")
        title.setStyleSheet(f"color: {TEXT}; font-size: 12.5pt; font-weight: 600;")
        outer.addWidget(title)
        sub = QLabel(f"Erkannt wurde „{recognized}“ — das liegt nah an deinem "
                     f"Wörterbuch-Begriff „{meant}“.")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        sub.setWordWrap(True)
        outer.addWidget(sub)
        outer.addSpacing(6)

        sentence_label = QLabel()
        sentence_label.setTextFormat(Qt.RichText)
        highlighted = sentence.replace(
            recognized, f'<span style="color:{ACCENT}; font-weight:600;">{recognized}</span>'
        )
        sentence_label.setText(f"„{highlighted}“")
        sentence_label.setWordWrap(True)
        sentence_label.setStyleSheet(
            f"color: {TEXT}; font-size: 10pt; background: {CARD};"
            f" border-radius: 8px; padding: 10px;"
        )
        outer.addWidget(sentence_label, 1)

        buttons = QHBoxLayout()
        learn_btn = style_button(QPushButton(f"Ja — künftig „{meant}“ schreiben"), "primary")
        learn_btn.clicked.connect(self._learn)
        ignore_btn = style_button(QPushButton("Nein, war richtig"), "ghost")
        ignore_btn.clicked.connect(self._ignore)
        buttons.addWidget(learn_btn)
        buttons.addStretch(1)
        buttons.addWidget(ignore_btn)
        outer.addLayout(buttons)

    def _learn(self) -> None:
        self._on_learn(self._recognized, self._meant)
        self.close()

    def _ignore(self) -> None:
        self._on_ignore(self._recognized, self._meant)
        self.close()

    def event(self, e) -> bool:
        if e.type() == QEvent.WindowActivate:
            self._was_activated = True
        elif e.type() == QEvent.WindowDeactivate and self._was_activated:
            self.close()  # Klick daneben = spaeter entscheiden (fragt beim
            # naechsten Vorkommen erneut — nichts wird gelernt/ignoriert)
        return super().event(e)


class WortprobeDialog(QDialog):
    """Einen Wörterbuch-Eintrag einsprechen und sehen, ob die Erkennung ihn trifft.

    Man trägt „PySide6" ein und weiß danach nicht, ob es etwas gebracht hat —
    bis es mitten im Diktat wieder als „Pi Seite 6" dasteht. Hier dauert die
    Antwort zehn Sekunden.

    Der Dialog nimmt selbst nichts auf: `aufnehmen` kommt von aussen und liefert
    die fertige Probe zurück. So hängt die Oberfläche nicht am Audiogerät, und
    der Weg bleibt ohne Mikrofon prüfbar.
    """

    AUFNAHME_S = 3.0

    def __init__(self, begriff: str, aufnehmen, parent=None,
                 zweck: str = "woerterbuch"):
        super().__init__(parent)
        self._begriff = begriff
        self._aufnehmen = aufnehmen          # fn(begriff, sekunden, zweck) -> Probe
        self._zweck = zweck
        self._vorschlag = ""
        self.setWindowTitle(f"„{begriff}“ testen")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        titel = QLabel(f"Sag „{begriff}“")
        titel.setStyleSheet(f"color: {TEXT}; font-size: 13pt; font-weight: 600;")
        lay.addWidget(titel)

        hinweis = QLabel(
            f"Nach dem Klick wird {self.AUFNAHME_S:.0f} Sekunden aufgenommen. "
            + ("Sag es beiläufig, so wie mitten im Reden — nicht betont "
               "deutlich. Genau so muss es später erkannt werden."
               if zweck == "startwort" else
               "Sprich das Wort einmal so, wie du es im Diktat sagen würdest — "
               "nicht betont langsam.")
        )
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(hinweis)

        self._meldung = QLabel("")
        self._meldung.setWordWrap(True)
        self._meldung.setStyleSheet(f"color: {TEXT}; font-size: 10pt;")
        self._meldung.setMinimumHeight(52)
        lay.addWidget(self._meldung)

        knoepfe = QHBoxLayout()
        self._start_btn = style_button(QPushButton("Aufnehmen"), "primary")
        self._start_btn.clicked.connect(self._starten)
        knoepfe.addWidget(self._start_btn)
        # Erscheint erst, wenn es etwas zu übernehmen gibt — ein toter Knopf
        # daneben sähe aus, als wäre etwas kaputt.
        self._uebernehmen_btn = style_button(QPushButton("Als Variante eintragen"))
        self._uebernehmen_btn.clicked.connect(self.accept)
        self._uebernehmen_btn.hide()
        knoepfe.addWidget(self._uebernehmen_btn)
        knoepfe.addStretch(1)
        schliessen = style_button(QPushButton("Schließen"), "ghost")
        schliessen.clicked.connect(self.reject)
        knoepfe.addWidget(schliessen)
        lay.addLayout(knoepfe)

    @property
    def vorschlag(self) -> str:
        """Wörterbuch-Zeile „gehört => gemeint" ("" = keine)."""
        return self._vorschlag

    def _starten(self) -> None:
        self._start_btn.setEnabled(False)
        self._uebernehmen_btn.hide()
        self._vorschlag = ""
        self._meldung.setText("Aufnahme läuft — jetzt sprechen …")
        QApplication.processEvents()          # die Meldung MUSS vor der Aufnahme stehen
        try:
            probe = self._aufnehmen(self._begriff, self.AUFNAHME_S, self._zweck)
        except Exception:
            log.exception("Wortprobe fehlgeschlagen.")
            self._meldung.setText("Aufnahme nicht möglich — läuft gerade ein Diktat?")
            self._start_btn.setEnabled(True)
            self._start_btn.setText("Nochmal")
            return
        self._meldung.setText(probe.als_text())
        self._vorschlag = probe.vorschlag
        if self._vorschlag:
            self._uebernehmen_btn.setText(f"„{self._vorschlag}“ eintragen")
            self._uebernehmen_btn.show()
        self._start_btn.setEnabled(True)
        self._start_btn.setText("Nochmal")
