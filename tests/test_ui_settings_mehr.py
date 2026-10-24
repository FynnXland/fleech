"""Sechs Seiten mit „Mehr Optionen" (6.5.0): oben nur das Noetige, der Rest zugeklappt.

Wacht darueber, dass die Seiten schlank bleiben. Kommt eine neue Einstellung dazu,
gehoert sie im Zweifel unter „Mehr Optionen" — die Obergrenze unten soll genau
diese Frage erzwingen, statt still wieder auf 80 sichtbare Zeilen zu wachsen.
"""

import pytest

pytest.importorskip("PySide6")

# Sichtbare Zeilen (mit Bezeichnung) aller sechs Seiten zusammen, bei Vorgaben.
# Stand 6.5.0: 24 (dazu 47 unter „Mehr Optionen“). Vorher waren es rund 80 auf einen Blick.
OBERGRENZE_SICHTBAR = 30


@pytest.fixture
def panel(qapp, tmp_path, monkeypatch):
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.ui.settings_window import SettingsPanel
    from fleech.usersettings import UserSettings

    return SettingsPanel(UserSettings(), lambda s: None, lambda: ["Mikrofon A"])


def _formulare(seite):
    """(oberes Formular, Mehr-Formular) einer Seite."""
    from PySide6.QtWidgets import QFormLayout, QWidget

    oben = mehr = None
    for w in seite.widget().findChildren(QWidget):
        lay = w.layout()
        if not isinstance(lay, QFormLayout):
            continue
        if w.objectName() == "mehrBereich":
            mehr = lay
        elif oben is None:
            oben = lay
    return oben, mehr


def _beschriftete_zeilen(form) -> list:
    """Bezeichnungen der Zeilen, die ohne Zutun zu sehen sind (keine Hinweiszeilen)."""
    from PySide6.QtWidgets import QFormLayout, QLabel

    namen = []
    for zeile in range(form.rowCount()):
        feld = form.itemAt(zeile, QFormLayout.FieldRole)
        label = form.itemAt(zeile, QFormLayout.LabelRole)
        if feld is None or feld.widget() is None or feld.widget().isHidden():
            continue
        w = label.widget() if label is not None else None
        texte = [w.text()] if isinstance(w, QLabel) else [
            l.text() for l in (w.findChildren(QLabel) if w is not None else [])]
        text = " ".join(t for t in texte if t).strip()
        if text:
            namen.append(text)
    return namen


def test_sechs_seiten(panel):
    assert panel.PAGES == ["Allgemein", "KI & Text", "Wörterbuch", "Pille & Töne",
                           "Ruhe", "Datenschutz"]


def test_jede_seite_hat_einen_zugeklappten_bereich(panel):
    from PySide6.QtWidgets import QPushButton

    from fleech.ui.settings.mehr import AUF, ZU, ist_zugeklappt

    for i, name in enumerate(panel.PAGES):
        seite = panel._pages.widget(i)
        oben, mehr = _formulare(seite)
        assert oben is not None and mehr is not None, f"{name}: kein Mehr-Bereich"
        assert ist_zugeklappt(mehr), f"{name}: Mehr Optionen sind nicht zugeklappt"
        assert _beschriftete_zeilen(mehr), f"{name}: Mehr Optionen sind leer"
        knopf = [b for b in seite.findChildren(QPushButton)
                 if b.objectName() == "mehrOptionen"][0]
        assert knopf.text() == ZU
        knopf.click()
        assert not ist_zugeklappt(mehr) and knopf.text() == AUF
        knopf.click()
        assert ist_zugeklappt(mehr) and knopf.text() == ZU


def test_oben_steht_nur_das_noetige(panel):
    sichtbar = {}
    for i, name in enumerate(panel.PAGES):
        oben, _ = _formulare(panel._pages.widget(i))
        sichtbar[name] = _beschriftete_zeilen(oben)
    gesamt = sum(len(z) for z in sichtbar.values())
    assert gesamt <= OBERGRENZE_SICHTBAR, (
        f"{gesamt} sichtbare Zeilen (Grenze {OBERGRENZE_SICHTBAR}) — gehört die "
        f"neue Einstellung nicht unter „Mehr Optionen“?\n{sichtbar}")
    # Was man zum Diktieren braucht, darf nie hinter einem Klick verschwinden.
    for name, zeile in (("Allgemein", "Diktat-Hotkey"), ("Allgemein", "Mikrofon"),
                        ("Allgemein", "Sprache"), ("KI & Text", "Anbieter"),
                        ("Wörterbuch", "Wörterbuch"), ("Datenschutz", "Verlauf löschen")):
        treffer = [z for z in sichtbar[name] if zeile.split()[0] in z]
        assert treffer, f"„{zeile}“ fehlt oben auf „{name}“: {sichtbar[name]}"


def test_spalten_fluchten_zwischen_oben_und_mehr(panel):
    """Die Steuerelement-Spalte darf beim Aufklappen nicht springen."""
    from PySide6.QtWidgets import QFormLayout

    for i, name in enumerate(panel.PAGES):
        oben, mehr = _formulare(panel._pages.widget(i))
        breiten = set()
        for form in (oben, mehr):
            for zeile in range(form.rowCount()):
                item = form.itemAt(zeile, QFormLayout.LabelRole)
                if item is not None and item.widget() is not None:
                    breiten.add(item.widget().minimumWidth())
        assert len(breiten) == 1, f"{name}: unterschiedliche Spaltenbreiten {breiten}"
        assert oben.contentsMargins().left() == mehr.contentsMargins().left(), name


def test_bedingte_zeilen_folgen_weiter_ihrer_wahl(panel):
    """Sprechpause nur bei „Anstupsen" — auch nach dem Umbau im richtigen Formular."""
    from PySide6.QtWidgets import QComboBox

    seite = panel._pages.widget(panel.PAGES.index("Allgemein"))
    oben, _ = _formulare(seite)
    assert oben.isRowVisible(panel._sprechpause_box) is False
    modus = [c for c in seite.findChildren(QComboBox) if c.findData("nudge") >= 0][0]
    modus.setCurrentIndex(modus.findData("nudge"))
    assert oben.isRowVisible(panel._sprechpause_box) is True
