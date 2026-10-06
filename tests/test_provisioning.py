"""Kaltstart-Einrichtung: Stand erheben, Schritte abarbeiten, ehrlich scheitern."""

from dataclasses import dataclass

from fleech import ollama_setup, provisioning


@dataclass
class FakeEndpoint:
    model: str
    base_url: str = "http://127.0.0.1:11434"


# -- ollama_setup ------------------------------------------------------------------


def test_status_ready_when_service_answers(monkeypatch):
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: True)
    assert ollama_setup.status() == "ready"


def test_status_unterscheidet_installiert_und_fehlend(monkeypatch):
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: False)
    monkeypatch.setattr(ollama_setup, "binary_present", lambda: True)
    assert ollama_setup.status() == "installed"
    monkeypatch.setattr(ollama_setup, "binary_present", lambda: False)
    assert ollama_setup.status() == "missing"


def test_install_ohne_winget_tut_nichts(monkeypatch):
    """Kein winget = keine Installation. Nie ein Fehler, nie ein Versuch."""
    monkeypatch.setattr(ollama_setup, "install_available", lambda: False)
    aufgerufen = []
    monkeypatch.setattr(ollama_setup.subprocess, "run",
                        lambda *a, **k: aufgerufen.append(a))
    assert ollama_setup.install() is False
    assert aufgerufen == []


def test_install_ruft_winget_mit_zustimmungen(monkeypatch):
    """Ohne --accept-*-Flags fragt winget interaktiv und haengt in einer GUI."""
    monkeypatch.setattr(ollama_setup, "install_available", lambda: True)
    gesehen = {}

    class Ergebnis:
        returncode = 0
        stdout = stderr = ""

    def fake_run(cmd, **kwargs):
        gesehen["cmd"] = cmd
        return Ergebnis()

    monkeypatch.setattr(ollama_setup.subprocess, "run", fake_run)
    meldungen = []
    assert ollama_setup.install(on_progress=meldungen.append) is True
    assert gesehen["cmd"][:4] == ["winget", "install", "--id", "Ollama.Ollama"]
    assert "--accept-package-agreements" in gesehen["cmd"]
    assert "--accept-source-agreements" in gesehen["cmd"]
    assert meldungen and any("installiert" in m for m in meldungen)


def test_install_fehler_wird_gemeldet_nicht_geworfen(monkeypatch):
    monkeypatch.setattr(ollama_setup, "install_available", lambda: True)

    class Ergebnis:
        returncode = 1
        stdout = "kaputt"
        stderr = ""

    monkeypatch.setattr(ollama_setup.subprocess, "run", lambda *a, **k: Ergebnis())
    meldungen = []
    assert ollama_setup.install(on_progress=meldungen.append) is False
    assert any("Hand" in m for m in meldungen)


def test_manual_hint_nennt_immer_einen_weg():
    assert ollama_setup.manual_hint().strip()


# -- build_steps -------------------------------------------------------------------


def _fake_lage(monkeypatch, lage="ready", modelle=(), whisper=True, winget=True):
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: whisper)
    monkeypatch.setattr(ollama_setup, "status", lambda *a, **k: lage)
    monkeypatch.setattr(ollama_setup, "install_available", lambda: winget)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set(modelle))


def test_build_steps_alles_da(monkeypatch):
    _fake_lage(monkeypatch, modelle={"gemma3:4b"})
    schritte = provisioning.build_steps([FakeEndpoint("gemma3:4b")], "large-v3-turbo",
                                        "http://127.0.0.1:11434")
    assert [s.key for s in schritte] == ["ollama", "llm:gemma3:4b", "stt"]
    assert all(s.state == "done" for s in schritte)


def test_build_steps_frischer_rechner(monkeypatch):
    _fake_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    schritte = provisioning.build_steps([FakeEndpoint("gemma3:4b")], "large-v3-turbo",
                                        "http://127.0.0.1:11434")
    assert [s.state for s in schritte] == ["pending", "pending", "pending"]
    # Groesse im Text: 5 GB Download muessen vorher benannt sein.
    assert "1,6" in schritte[-1].note


def test_build_steps_ohne_winget_verlangt_handarbeit(monkeypatch):
    _fake_lage(monkeypatch, lage="missing", winget=False, whisper=False)
    schritte = provisioning.build_steps([], "large-v3-turbo", "http://127.0.0.1:11434")
    ollama = schritte[0]
    assert ollama.state == "manual"
    assert ollama.manual.strip()


def test_build_steps_dedupliziert_modelle(monkeypatch):
    _fake_lage(monkeypatch, modelle=set())
    schritte = provisioning.build_steps(
        [FakeEndpoint("gemma3:4b"), FakeEndpoint("gemma3:4b")],
        "large-v3-turbo", "http://127.0.0.1:11434",
    )
    assert [s.key for s in schritte].count("llm:gemma3:4b") == 1


# -- SetupRunner -------------------------------------------------------------------


def _runner(monkeypatch, **kw):
    zustaende, fortschritte = [], []
    runner = provisioning.SetupRunner(
        endpoints=kw.pop("endpoints", [FakeEndpoint("gemma3:4b")]),
        stt_model="large-v3-turbo",
        on_state=lambda k, s, n: zustaende.append((k, s)),
        on_progress=lambda k, t, p: fortschritte.append((k, t, p)),
        **kw,
    )
    return runner, zustaende, fortschritte


def test_runner_alles_vorhanden(monkeypatch):
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: True)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: True)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: {"gemma3:4b"})
    runner, zustaende, _ = _runner(monkeypatch)
    assert runner.run() is True
    assert zustaende == [("ollama", "done"), ("llm:gemma3:4b", "done"), ("stt", "done")]


def test_runner_installiert_ollama_und_laedt_alles(monkeypatch):
    """Der ganze Kaltstart-Weg: winget → Dienst wartet → Modell → Whisper."""
    zustand = {"laeuft": False}
    monkeypatch.setattr(ollama_setup, "service_running",
                        lambda *a, **k: zustand["laeuft"])
    monkeypatch.setattr(ollama_setup, "binary_present", lambda: False)
    monkeypatch.setattr(ollama_setup, "install_available", lambda: True)

    def fake_install(on_progress=None, **k):
        if on_progress:
            on_progress("Ollama wird installiert …")
        zustand["laeuft"] = True          # Dienst startet mit der Installation
        return True

    monkeypatch.setattr(ollama_setup, "install", fake_install)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set())

    def fake_pull(base, modell, on_progress=None, **k):
        on_progress(f"Lade Sprachmodell {modell} … 40 %")
        return True

    monkeypatch.setattr(client, "ollama_pull", fake_pull)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: False)
    monkeypatch.setattr(provisioning, "ensure_whisper",
                        lambda m, on_progress=None, **k: True)

    runner, zustaende, fortschritte = _runner(monkeypatch)
    assert runner.run() is True
    assert ("ollama", "running") in zustaende and ("ollama", "done") in zustaende
    assert ("llm:gemma3:4b", "done") in zustaende
    assert ("stt", "done") in zustaende
    # Prozent aus der Textmeldung ist fuer den Balken herausgeloest.
    assert any(k == "llm:gemma3:4b" and p == 40 for k, _t, p in fortschritte)


def test_runner_ohne_dienst_ueberspringt_modelle_aber_nicht_whisper(monkeypatch):
    """Ohne Ollama sind die Modell-Downloads unmoeglich — das Erkennungsmodell
    laeuft aber ueber HuggingFace und ist davon unabhaengig."""
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: False)
    monkeypatch.setattr(ollama_setup, "binary_present", lambda: False)
    monkeypatch.setattr(ollama_setup, "install_available", lambda: False)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: False)
    geladen = []
    monkeypatch.setattr(provisioning, "ensure_whisper",
                        lambda m, on_progress=None, **k: geladen.append(m) or True)

    runner, zustaende, _ = _runner(monkeypatch)
    assert runner.run() is False
    assert ("ollama", "manual") in zustaende
    assert ("llm:gemma3:4b", "pending") in zustaende
    assert geladen == ["large-v3-turbo"]
    assert ("stt", "done") in zustaende


def test_runner_meldet_gescheiterten_modell_download(monkeypatch):
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: True)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: True)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set())
    monkeypatch.setattr(client, "ollama_pull", lambda *a, **k: False)
    runner, zustaende, _ = _runner(monkeypatch)
    assert runner.run() is False
    assert ("llm:gemma3:4b", "failed") in zustaende


def test_runner_abbruch_stoppt_vor_dem_naechsten_schritt(monkeypatch):
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: True)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set())
    monkeypatch.setattr(client, "ollama_pull", lambda *a, **k: True)
    runner, zustaende, _ = _runner(monkeypatch)
    runner.cancel()
    assert runner.run() is False
    assert ("llm:gemma3:4b", "running") not in zustaende


def test_runner_faengt_kaputten_meldehaken(monkeypatch):
    """Eine kaputte UI-Meldung darf die Einrichtung nicht reissen."""
    monkeypatch.setattr(ollama_setup, "service_running", lambda *a, **k: True)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: True)
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: {"gemma3:4b"})

    def kaputt(*_a):
        raise RuntimeError("Fenster ist weg")

    runner = provisioning.SetupRunner(
        endpoints=[FakeEndpoint("gemma3:4b")], stt_model="large-v3-turbo",
        on_state=kaputt, on_progress=kaputt,
    )
    assert runner.run() is True


# -- Whisper-Cache -----------------------------------------------------------------


def test_whisper_cache_bytes_ohne_ordner_ist_null(monkeypatch, tmp_path):
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path))
    assert provisioning.whisper_cache_bytes("large-v3-turbo") == 0


def test_ensure_whisper_ueberspringt_vorhandenes(monkeypatch):
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: True)
    meldungen = []
    assert provisioning.ensure_whisper("large-v3-turbo",
                                       on_progress=meldungen.append) is True
    assert meldungen == []


def test_ensure_whisper_meldet_fortschritt_und_stoppt_beobachter(monkeypatch):
    """Der MB-Zaehler ist die einzige Fortschrittsquelle — huggingface_hub meldet
    nur ueber tqdm auf stderr, was in der GUI unsichtbar bleibt."""
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: False)
    monkeypatch.setattr(provisioning, "whisper_cache_bytes",
                        lambda _m: 300 * 1024 * 1024)
    import faster_whisper.utils as fw

    monkeypatch.setattr(fw, "download_model", lambda *a, **k: __import__("time").sleep(0.25))
    meldungen = []
    assert provisioning.ensure_whisper("large-v3-turbo", on_progress=meldungen.append,
                                       poll=0.05) is True
    assert any("300 MB" in m for m in meldungen)
    assert any("1,6 GB" in m for m in meldungen)
    import threading

    assert not any(t.name == "stt-download-progress" and t.is_alive()
                   for t in threading.enumerate())


def test_ensure_whisper_scheitert_ohne_ausnahme(monkeypatch):
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: False)
    import faster_whisper.utils as fw

    def kaputt(*_a, **_k):
        raise OSError("kein Netz")

    monkeypatch.setattr(fw, "download_model", kaputt)
    assert provisioning.ensure_whisper("large-v3-turbo", poll=0.05) is False
