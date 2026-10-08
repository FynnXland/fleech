"""Erkennungsmodelle kommen nur von der Platte (`fleech/stt/lokal.py`).

Bis 6.2.0 fragte faster-whisper bei JEDEM Laden des Modells bei Hugging Face
nach, ob es eine neue Fassung gibt — bei jedem Start. Diese Tests laufen ohne
Netz: Der Cache wird im Temp-Ordner nachgebaut, und jeder Verbindungsversuch
laesst den Test scheitern.
"""

import ast
import socket
import threading
import types
from pathlib import Path

import pytest

from fleech.stt.lokal import ModellFehlt, lade_whisper, modellordner

ROOT = Path(__file__).resolve().parent.parent
KOMMIT = "0123456789abcdef0123456789abcdef01234567"
TURBO_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


@pytest.fixture
def kein_netz(monkeypatch):
    """Jeder Verbindungsaufbau ist ein Fehler — auch einer, den die Bibliothek
    selbst abfangen und still „offline" weitermachen wuerde."""
    versuche = []

    def verboten(self, adresse):
        versuche.append(adresse)
        raise AssertionError(f"Netzzugriff beim Modell-Laden: {adresse}")

    monkeypatch.setattr(socket.socket, "connect", verboten)
    monkeypatch.setattr(socket.socket, "connect_ex", verboten)
    monkeypatch.setattr(socket, "create_connection",
                        lambda adresse, *a, **k: verboten(None, adresse))
    return versuche


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Leerer HF-Cache im Temp-Ordner; `lege_an` legt ein Modell hinein."""
    from huggingface_hub import constants

    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))

    def lege_an(repo=TURBO_REPO, dateien=("config.json", "model.bin", "tokenizer.json")):
        ordner = tmp_path / ("models--" + repo.replace("/", "--"))
        (ordner / "refs").mkdir(parents=True)
        (ordner / "refs" / "main").write_text(KOMMIT)
        snap = ordner / "snapshots" / KOMMIT
        snap.mkdir(parents=True)
        for name in dateien:
            (snap / name).write_bytes(b"x")
        return snap

    return lege_an


# -- Aufloesen: Name → Ordner, ohne Netz ----------------------------------------


def test_vorhandenes_modell_wird_ohne_netz_gefunden(cache, kein_netz):
    snap = cache()
    assert Path(modellordner("large-v3-turbo")) == snap
    assert kein_netz == []


def test_hub_id_des_deutsch_modells_wird_ohne_netz_gefunden(cache, kein_netz):
    from fleech.stt.modellwahl import DEUTSCH

    snap = cache(repo=DEUTSCH)
    assert Path(modellordner(DEUTSCH)) == snap
    assert kein_netz == []


def test_fehlendes_modell_meldet_modell_fehlt(cache, kein_netz):
    with pytest.raises(ModellFehlt) as info:
        modellordner("large-v3-turbo")
    assert info.value.modell == "large-v3-turbo"
    assert kein_netz == []


def test_halb_geladenes_modell_zaehlt_als_fehlend(cache, kein_netz):
    """Abgebrochener Download: die kleinen Dateien da, `model.bin` nicht.
    Frueher reparierte die Nachfrage beim Laden das still."""
    cache(dateien=("config.json", "tokenizer.json"))
    with pytest.raises(ModellFehlt):
        modellordner("large-v3-turbo")


def test_unbekannter_name_ist_kein_fehlendes_modell(cache):
    """Ein Tippfehler in config.yaml soll nicht als „bitte herunterladen" enden."""
    with pytest.raises(ValueError):
        modellordner("gibt-es-nicht")


def test_ordnerpfad_wird_direkt_genommen(tmp_path, monkeypatch):
    import faster_whisper.utils as fw

    monkeypatch.setattr(fw, "download_model",
                        lambda *a, **k: pytest.fail("Ordner braucht keinen Cache"))
    assert modellordner(str(tmp_path)) == str(tmp_path)


def test_modell_fehlt_ist_kein_cuda_fehler():
    """`transcribe` faellt bei RuntimeErrors mit „cuda" im Text auf den Prozessor
    zurueck — ein fehlendes Modell darf da nicht hineinpassen."""
    text = str(ModellFehlt("large-v3-turbo")).lower()
    assert not any(s in text for s in ("cublas", "cudnn", "cuda"))


# -- Laden: faster-whisper bekommt nur noch den Ordner ---------------------------


def test_lade_whisper_gibt_faster_whisper_nur_den_ordner(cache, kein_netz, monkeypatch):
    import faster_whisper

    snap = cache()
    gebaut = {}

    class FakeModel:
        def __init__(self, modell, **optionen):
            gebaut["modell"], gebaut["optionen"] = modell, optionen

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    lade_whisper("large-v3-turbo", device="cuda", compute_type="int8_float16")
    # Ein Ordner statt eines Namens: Dann laesst faster-whisper huggingface_hub
    # gar nicht erst an — es gibt nichts nachzufragen.
    assert Path(gebaut["modell"]) == snap
    assert gebaut["optionen"] == {"device": "cuda", "compute_type": "int8_float16"}
    assert kein_netz == []


def test_lade_whisper_baut_bei_fehlendem_modell_nichts(cache, monkeypatch):
    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel",
                        lambda *a, **k: pytest.fail("darf nicht gebaut werden"))
    with pytest.raises(ModellFehlt):
        lade_whisper("large-v3-turbo", device="cpu")


def _stt(monkeypatch, lader):
    import fleech.stt.faster_whisper_stt as fws

    monkeypatch.setattr(fws, "_register_cuda_dlls", lambda: None)
    monkeypatch.setattr(fws, "lade_whisper", lader)
    cfg = types.SimpleNamespace(model_size="large-v3-turbo", device="cuda",
                                compute_type="int8_float16", language="de",
                                vad_filter=True)
    return fws.FasterWhisperSTT(cfg)


def test_fehlendes_modell_faellt_nicht_auf_den_prozessor_zurueck(monkeypatch):
    aufrufe = []

    def lader(modell, **optionen):
        aufrufe.append(optionen["device"])
        raise ModellFehlt(modell)

    stt = _stt(monkeypatch, lader)
    with pytest.raises(ModellFehlt):
        stt._ensure_model()
    assert aufrufe == ["cuda"]               # kein zweiter Versuch auf der CPU
    assert stt._on_cpu is False


def test_gpu_fehler_faellt_weiter_auf_den_prozessor_zurueck(monkeypatch):
    aufrufe = []

    def lader(modell, **optionen):
        aufrufe.append(optionen["device"])
        if optionen["device"] == "cuda":
            raise RuntimeError("CUDA failed with error out of memory")
        return "cpu-modell"

    stt = _stt(monkeypatch, lader)
    stt._ensure_model()
    assert aufrufe == ["cuda", "cpu"]
    assert stt._model == "cpu-modell" and stt._on_cpu is True


def test_vorschaumodell_faellt_bei_fehlendem_modell_nicht_auf_den_prozessor(monkeypatch):
    import fleech.stt.faster_whisper_stt as fws
    import fleech.stt.lokal as lokal
    from fleech.overlay import PreviewModel

    aufrufe = []

    def lader(modell, **optionen):
        aufrufe.append(optionen["device"])
        raise ModellFehlt(modell)

    monkeypatch.setattr(fws, "_register_cuda_dlls", lambda: None)
    monkeypatch.setattr(lokal, "lade_whisper", lader)
    with pytest.raises(ModellFehlt):
        PreviewModel(model_size="small").load()
    assert aufrufe == ["auto"]


# -- Einrichtung: dieselbe Pruefung --------------------------------------------


def test_einrichtung_sieht_halbes_modell_als_fehlend(cache, kein_netz):
    from fleech import provisioning

    cache(dateien=("config.json",))
    assert provisioning.whisper_present("large-v3-turbo") is False


def test_einrichtung_sieht_vorhandenes_modell_ohne_netz(cache, kein_netz):
    from fleech import provisioning

    cache()
    assert provisioning.whisper_present("large-v3-turbo") is True
    assert kein_netz == []


# -- Waechter: niemand laedt am Offline-Weg vorbei -------------------------------


def _aufrufe(name: str):
    """(Datei, Zeile, Aufruf) fuer jeden Aufruf von `name` im Paket."""
    for datei in sorted((ROOT / "fleech").rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for k in ast.walk(baum):
            if not isinstance(k, ast.Call):
                continue
            f = k.func
            gerufen = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if gerufen == name:
                yield datei.relative_to(ROOT).as_posix(), k.lineno, k


def test_nur_lokal_py_baut_ein_whisper_modell():
    """Jedes andere `WhisperModel(…)` fragt beim Laden wieder bei Hugging Face
    nach — genau der Fehler, den `stt/lokal.py` behebt."""
    fremde = [f"{d}:{z}" for d, z, _ in _aufrufe("WhisperModel")
              if d != "fleech/stt/lokal.py"]
    assert fremde == [], f"WhisperModel ausserhalb von stt/lokal.py: {fremde}"


def test_herunterladen_nur_in_der_einrichtung():
    """`download_model` ohne `local_files_only=True` ist ein Download — den darf
    nur `provisioning.ensure_whisper` ausloesen."""
    online = []
    for datei, zeile, aufruf in _aufrufe("download_model"):
        offline = any(kw.arg == "local_files_only"
                      and isinstance(kw.value, ast.Constant) and kw.value.value is True
                      for kw in aufruf.keywords)
        if not offline:
            online.append(f"{datei}:{zeile}")
    assert len(online) == 1 and online[0].startswith("fleech/provisioning.py:"), online


# -- App: fehlendes Modell → Einrichtung ----------------------------------------


def _app(monkeypatch, onboarding_done=True, laden_ok=True, danach_da=True):
    import fleech.provisioning as prov
    from fleech.ui.desktopapp.modelle import ModelleMixin

    geladen, hinweise, warm = [], [], []
    monkeypatch.setattr(prov, "ensure_whisper",
                        lambda m, on_progress=None: geladen.append(m) or laden_ok)
    monkeypatch.setattr(prov, "whisper_present", lambda m: danach_da)

    def transcribe(audio, sr):
        raise ModellFehlt("large-v3-turbo")

    app = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            general=types.SimpleNamespace(onboarding_done=onboarding_done)),
        pipeline=types.SimpleNamespace(stt=types.SimpleNamespace(transcribe=transcribe)),
        bus=types.SimpleNamespace(hinweis=types.SimpleNamespace(emit=hinweise.append),
                                  progress=types.SimpleNamespace(emit=lambda t: None)),
        _stt_nachladen=threading.Lock(),
        _warm_up_stt=lambda: warm.append(1),
        _report_model_download=lambda t: None,
    )
    app._stt_modell_fehlt = lambda m: ModelleMixin._stt_modell_fehlt(app, m)
    return app, geladen, hinweise, warm


def test_fehlendes_modell_wird_nach_der_einfuehrung_nachgeladen(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, geladen, hinweise, warm = _app(monkeypatch)
    ModelleMixin._warm_up(app)
    assert geladen == ["large-v3-turbo"]
    assert warm == [1]
    assert hinweise[-1].startswith("Spracherkennung bereit")


def test_vor_der_einfuehrung_laedt_deren_einrichtung(monkeypatch):
    """Die Einrichtungsseite laedt das Modell selbst und waermt danach auf —
    ein zweiter Download daneben waere doppelt."""
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, geladen, hinweise, warm = _app(monkeypatch, onboarding_done=False)
    ModelleMixin._warm_up(app)
    assert geladen == [] and warm == [] and hinweise == []


def test_gescheitertes_nachladen_sagt_es(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, geladen, hinweise, warm = _app(monkeypatch, laden_ok=False)
    ModelleMixin._warm_up(app)
    assert geladen == ["large-v3-turbo"] and warm == []
    assert "Internetverbindung" in hinweise[-1]


def test_kein_bereit_wenn_das_modell_danach_noch_fehlt(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, _, hinweise, warm = _app(monkeypatch, danach_da=False)
    ModelleMixin._warm_up(app)
    assert warm == [] and not hinweise[-1].startswith("Spracherkennung bereit")


def test_laufendes_nachladen_wird_nicht_verdoppelt(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, geladen, _, _ = _app(monkeypatch)
    app._stt_nachladen.acquire()             # ein anderer Thread laedt schon
    ModelleMixin._warm_up(app)
    assert geladen == []


def test_vorschau_holt_ihr_fehlendes_modell(monkeypatch):
    """Die Live-Vorschau hat ein eigenes Modell, das die Einrichtung nicht laedt;
    wer sie einschaltet, bekommt es einmal geholt."""
    import fleech.overlay as overlay_mod
    import fleech.provisioning as prov
    from fleech.config import AppConfig
    from fleech.ui.desktopapp.modelle import ModelleMixin
    from fleech.usersettings import UserSettings

    geladen, versuche = [], []

    class FakeVorschau:
        def __init__(self, model_size, language, samplerate):
            self.model_size = model_size

        def load(self):
            versuche.append(1)
            if not geladen:
                raise ModellFehlt(self.model_size)

    monkeypatch.setattr(overlay_mod, "PreviewModel", FakeVorschau)
    monkeypatch.setattr(prov, "ensure_whisper",
                        lambda m, on_progress=None: geladen.append(m) or True)
    app = types.SimpleNamespace(settings=UserSettings(), config=AppConfig(),
                                _preview_model=None)
    app._lade_vorschaumodell = lambda m: ModelleMixin._lade_vorschaumodell(app, m)
    ModelleMixin._ensure_preview_model(app)
    assert geladen == [AppConfig().overlay.model_size]
    assert versuche == [1, 1]                # vor und nach dem Download
