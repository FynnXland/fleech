"""Persistierte GPU/CPU-Build-Praeferenz (packaging/build.py) — kein Env-Var-Gefrickel."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("fleech_build", PACKAGING / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_isoliert(tmp_path, monkeypatch):
    """build.py ohne Blick auf echte Dateien: eigene Wahl im tmp-Ordner, und kein
    Rueckgriff auf die build.local.json des Haupt-Checkouts — sonst saehe ein
    Testlauf im Worktree dessen {"gpu": true}."""
    build = _load_build_module()
    monkeypatch.setattr(build, "BUILD_LOCAL_CONFIG", tmp_path / "build.local.json")
    monkeypatch.setattr(build, "haupt_checkout_config", lambda: None)
    return build


def test_flags_persist_across_calls(tmp_path, monkeypatch):
    build = _build_isoliert(tmp_path, monkeypatch)
    monkeypatch.delenv("FLEECH_GPU", raising=False)

    assert build.resolve_gpu_flag([]) is False  # kein Flag, keine Datei → Default CPU

    assert build.resolve_gpu_flag(["build.py", "--gpu"]) is True
    assert build.BUILD_LOCAL_CONFIG.is_file()
    # Naechster Aufruf OHNE Flag erinnert sich weiterhin an GPU:
    assert build.resolve_gpu_flag(["build.py"]) is True

    assert build.resolve_gpu_flag(["build.py", "--cpu"]) is False
    assert build.resolve_gpu_flag(["build.py"]) is False


def test_env_var_overrides_persisted_cpu_choice(tmp_path, monkeypatch):
    build = _build_isoliert(tmp_path, monkeypatch)
    build.write_gpu_preference(False)
    monkeypatch.setenv("FLEECH_GPU", "1")
    assert build.resolve_gpu_flag(["build.py"]) is True


def test_explicit_flag_wins_over_env_var(tmp_path, monkeypatch):
    build = _build_isoliert(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEECH_GPU", "1")
    assert build.resolve_gpu_flag(["build.py", "--cpu"]) is False
    assert build.read_gpu_preference() is False


# -- Worktree: GPU-Wahl des Haupt-Checkouts ------------------------------------------

def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def haupt_und_worktree(tmp_path):
    """Echtes git: Haupt-Checkout mit build.local.json, daneben ein Worktree ohne."""
    if shutil.which("git") is None:
        pytest.skip("git nicht installiert")
    haupt = tmp_path / "haupt"
    (haupt / "packaging").mkdir(parents=True)
    _git("init", "-q", cwd=haupt)
    _git("commit", "-q", "--allow-empty", "-m", "start", cwd=haupt)
    worktree = haupt / ".claude" / "worktrees" / "wt"
    _git("worktree", "add", "-q", "--detach", str(worktree), cwd=haupt)
    (worktree / "packaging").mkdir()
    return haupt, worktree


def _bauen_in(build, monkeypatch, checkout):
    monkeypatch.setattr(build, "ROOT", checkout)
    monkeypatch.setattr(build, "BUILD_LOCAL_CONFIG", checkout / "packaging" / "build.local.json")
    monkeypatch.delenv("FLEECH_GPU", raising=False)


def test_worktree_uebernimmt_gpu_wahl_des_haupt_checkouts(haupt_und_worktree, monkeypatch):
    """2026-10-08: Im Claude-Worktree fehlte die gitignorierte Datei, `build.py`
    baute still einen CPU-Build — installiert lief die Erkennung auf dem Prozessor."""
    haupt, worktree = haupt_und_worktree
    (haupt / "packaging" / "build.local.json").write_text('{"gpu": true}', encoding="utf-8")
    build = _load_build_module()
    _bauen_in(build, monkeypatch, worktree)

    assert build.haupt_checkout_config() == (haupt / "packaging" / "build.local.json").resolve()
    assert build.resolve_gpu_flag(["build.py"]) is True


def test_eigene_wahl_im_worktree_gewinnt(haupt_und_worktree, monkeypatch):
    haupt, worktree = haupt_und_worktree
    (haupt / "packaging" / "build.local.json").write_text('{"gpu": true}', encoding="utf-8")
    (worktree / "packaging" / "build.local.json").write_text('{"gpu": false}', encoding="utf-8")
    build = _load_build_module()
    _bauen_in(build, monkeypatch, worktree)

    assert build.resolve_gpu_flag(["build.py"]) is False


def test_haupt_checkout_verweist_nicht_auf_sich_selbst(haupt_und_worktree, monkeypatch):
    """Im Haupt-Checkout liefert git ein relatives „.git" — das darf nicht als
    fremde Datei gelten."""
    haupt, _ = haupt_und_worktree
    build = _load_build_module()
    _bauen_in(build, monkeypatch, haupt)

    assert build.haupt_checkout_config() is None


def test_ohne_jede_wahl_warnt_der_build_laut(tmp_path, monkeypatch, capsys):
    build = _build_isoliert(tmp_path, monkeypatch)
    monkeypatch.delenv("FLEECH_GPU", raising=False)

    assert build.resolve_gpu_flag(["build.py"]) is False
    ausgabe = capsys.readouterr().out
    assert "ACHTUNG" in ausgabe and "--gpu" in ausgabe


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
