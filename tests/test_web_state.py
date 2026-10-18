"""状态目录必须落在仓库外（CLAUDE.md §7）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from web.state import assert_outside_repo, run_dir, state_home


def test_state_home_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path / "plat"))
    assert state_home() == tmp_path / "plat"


def test_state_home_defaults_to_dot_hiagent_platform(monkeypatch):
    monkeypatch.delenv("HIAGENT_PLATFORM_HOME", raising=False)
    assert state_home() == Path.home() / ".hiagent_platform"


def test_assert_outside_repo_rejects_a_path_inside_the_repo():
    """运行产物写进仓库会违反 §7。这个断言必须真的会拒绝。"""
    repo_root = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip())
    with pytest.raises(RuntimeError, match="inside the git repository"):
        assert_outside_repo(repo_root / "results")


def test_assert_outside_repo_accepts_a_path_outside(tmp_path):
    assert_outside_repo(tmp_path)  # 不抛即通过


def test_the_gate_fires_for_every_write_path_not_just_run_dir(monkeypatch):
    """**闸必须覆盖全部写盘路径，而不是只覆盖 run_dir。**

    原先 `assert_outside_repo` 只在 `run_dir()` 里调用，于是
    `trials.py` / `configs.py` 直接拼路径**绕过了它**——把 HOME 指到仓库内时，
    账本与配置会**静默写进仓库**（§7 违规），要等到某次提交作业触发 `run_dir()` 才报错。
    这条测试断言：**每一条**写路径都会在写之前抛错。
    """
    import subprocess
    from pathlib import Path as _P

    repo_root = _P(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True, check=True).stdout.strip())
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(repo_root / "would_be_in_repo"))

    from web import state as state_mod
    from web.trials import append_trial

    state_mod._ASSERTED.clear()                       # 清掉缓存，否则进程内已验过
    with pytest.raises(RuntimeError, match="inside the git repository"):
        append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                     param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert not (repo_root / "would_be_in_repo" / "trials.jsonl").exists(), \
        "闸没拦住——账本写进仓库了"


def test_the_gate_does_not_depend_on_the_current_working_directory(monkeypatch):
    """**闸的判据不能依赖调用者从哪启动。**

    原实现在目标路径不存在时用 `Path.cwd()` 跑 `git rev-parse`；平台若从仓库外启动
    （`cwd=/` 是一例），`git rev-parse` 失败 → 被当成"不在仓库内" → **静默放行**，
    账本照样写进仓库。这条测试就是要把它钉死：**cwd 在仓库外时，闸仍然要拦。**
    """
    import subprocess
    from pathlib import Path as _P

    from web import state as state_mod
    from web.trials import append_trial

    repo = _P(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip())
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(repo / "would_be_in_repo"))
    monkeypatch.chdir("/")                 # ← 关键：cwd 在仓库外
    state_mod._ASSERTED.clear()

    with pytest.raises(RuntimeError, match="inside the git repository"):
        append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                     param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert not (repo / "would_be_in_repo" / "trials.jsonl").exists(), \
        "闸没拦住——账本写进仓库了"


def test_run_dir_is_created_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    d = run_dir("abc123")
    assert d == tmp_path / "runs" / "abc123"
    assert d.is_dir()
