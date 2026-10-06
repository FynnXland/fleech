"""Persistierte GPU/CPU-Build-Praeferenz (packaging/build.py) — kein Env-Var-Gefrickel."""

import importlib.util
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("fleech_build", PACKAGING / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_flags_persist_across_calls(tmp_path, monkeypatch):
    build = _load_build_module()
    monkeypatch.setattr(build, "BUILD_LOCAL_CONFIG", tmp_path / "build.local.json")
    monkeypatch.delenv("FLEECH_GPU", raising=False)

    assert build.resolve_gpu_flag([]) is False  # kein Flag, keine Datei → Default CPU

    assert build.resolve_gpu_flag(["build.py", "--gpu"]) is True
    assert build.BUILD_LOCAL_CONFIG.is_file()
    # Naechster Aufruf OHNE Flag erinnert sich weiterhin an GPU:
    assert build.resolve_gpu_flag(["build.py"]) is True

    assert build.resolve_gpu_flag(["build.py", "--cpu"]) is False
    assert build.resolve_gpu_flag(["build.py"]) is False


def test_env_var_overrides_persisted_cpu_choice(tmp_path, monkeypatch):
    build = _load_build_module()
    monkeypatch.setattr(build, "BUILD_LOCAL_CONFIG", tmp_path / "build.local.json")
    build.write_gpu_preference(False)
    monkeypatch.setenv("FLEECH_GPU", "1")
    assert build.resolve_gpu_flag(["build.py"]) is True


def test_explicit_flag_wins_over_env_var(tmp_path, monkeypatch):
    build = _load_build_module()
    monkeypatch.setattr(build, "BUILD_LOCAL_CONFIG", tmp_path / "build.local.json")
    monkeypatch.setenv("FLEECH_GPU", "1")
    assert build.resolve_gpu_flag(["build.py", "--cpu"]) is False
    assert build.read_gpu_preference() is False


# -- Installer-Zusagen fuer den Update-Weg -------------------------------------------

def _iss() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "packaging" /
            "fleech.iss").read_text(encoding="utf-8", errors="replace")


def test_installer_schliesst_laufendes_fleech():
    """Ohne AppMutex/CloseApplications endet ein Update in „Datei in Verwendung"
    — der Mutex-Name MUSS zu fleech/singleinstance.py passen."""
    from fleech.singleinstance import MUTEX_NAME

    text = _iss()
    assert f"AppMutex={MUTEX_NAME}" in text
    assert "CloseApplications=yes" in text


def test_installer_startet_fleech_nach_stillem_update_wieder():
    """Der stille Lauf ist das Update aus der App heraus. Ohne diesen Eintrag wäre
    Fleech nach dem Update beendet — der Knopf verspricht aber einen Neustart."""
    assert "skipifnotsilent" in _iss()


def test_installer_loescht_keine_nutzerdaten():
    """settings.json und history.db muessen ein Update ueberleben."""
    text = _iss()
    assert "settings.json" not in text
    assert "history.db" not in text
