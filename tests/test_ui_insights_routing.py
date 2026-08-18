"""Routing-Beschriftung der "Verarbeitung"-Karte (A-2/E-10).

"schnelles Modell / grosses Modell" behauptet ein zweites, kleineres Modell, das es
seit v3.5.0 nicht mehr gibt (cleanup_fast ist BEWUSST dasselbe Modell wie cleanup,
siehe config.yaml). Die Beschriftung wird deshalb aus der Konfiguration abgeleitet:
sind beide Modelle gleich, heissen die Stufen "kurzer Weg"/"voller Weg", sonst die
alten Namen.
"""

import types

import pytest

pytest.importorskip("PySide6")


def _stats(**kw):
    from fleech.history import Stats

    basis = dict(
        avg_stt_ms=450, avg_llm_ms=1200, tier_shares={"trivial": 0.1, "simple": 0.2,
                                                        "complex": 0.7},
        fallback_rate=0.0,
    )
    basis.update(kw)
    return Stats(**basis)


def test_gleiches_modell_ergibt_ehrliche_beschriftung(monkeypatch):
    """Heutiger Ist-Zustand (config.yaml: cleanup_fast BEWUSST dasselbe Modell)."""
    from fleech.ui.pages import insights

    text = insights._processing_summary(_stats())
    assert "kurzer Weg" in text
    assert "voller Weg" in text
    assert "schnelles Modell" not in text
    assert "großes Modell" not in text


def test_unterschiedliches_modell_behaelt_die_alten_namen(monkeypatch):
    """Taucht kuenftig ein wirklich anderes, schnelleres Modell auf, sollen die
    Stufen wieder unterscheidbar heissen."""
    from fleech.ui.pages import insights

    endpoint_a = types.SimpleNamespace(model="grosses-modell")
    endpoint_b = types.SimpleNamespace(model="kleines-modell")
    cfg = types.SimpleNamespace(llm_cleanup=endpoint_a, llm_cleanup_fast=endpoint_b)
    monkeypatch.setattr("fleech.config.load_config", lambda *a, **k: cfg)

    text = insights._processing_summary(_stats())
    assert "schnelles Modell" in text
    assert "großes Modell" in text
    assert "kurzer Weg" not in text


def test_kaputte_config_faellt_ehrlich_zurueck(monkeypatch):
    """Config nicht lesbar -> im Zweifel die Beschriftung, die nichts behauptet,
    was es nicht gibt."""
    from fleech.ui.pages import insights

    def kaputt(*a, **k):
        raise RuntimeError("kein Zugriff")

    monkeypatch.setattr("fleech.config.load_config", kaputt)
    text = insights._processing_summary(_stats())
    assert "kurzer Weg" in text
