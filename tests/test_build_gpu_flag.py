"""Persistierte GPU/CPU-Build-Praeferenz (packaging/build.py) — kein Env-Var-Gefrickel."""

import importlib.util
import sys
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
