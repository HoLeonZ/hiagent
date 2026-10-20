"""状态目录必须落在仓库外（CLAUDE.md §7）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from web.state import assert_outside_repo, run_dir, state_home

#: ⚠️ **仓库根由本文件的位置推出，不用 `git rev-parse`。**
#:
#: 用 `git rev-parse` 是**从启动目录问"仓库在哪"**——那正是 `web/state.py` 里
#: 已被修掉的脆弱判据（cwd 在仓库外时它失败，而失败被当成"不在仓库内"）。
#: 测试自己若还用那一招，就会出现两种坏结果：
#:   · 从仓库外跑 pytest → `subprocess.CalledProcessError`，测试**报 error**（§6 要求 skip 而非 error）；
#:   · 更坏的是，若 cwd 恰好在**另一个** git 仓库里，测试会拿那个仓库的根去断言，
#:     **而它通过了**——一条"验证闸能拦住仓库内路径"的测试，验证的却是别的仓库。
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_state_home_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path / "plat"))
    assert state_home() == tmp_path / "plat"


def test_state_home_defaults_to_dot_hiagent_platform(monkeypatch):
    monkeypatch.delenv("HIAGENT_PLATFORM_HOME", raising=False)
    assert state_home() == Path.home() / ".hiagent_platform"


def test_assert_outside_repo_rejects_a_path_inside_the_repo():
    """运行产物写进仓库会违反 §7。这个断言必须真的会拒绝。"""
    with pytest.raises(RuntimeError, match="inside the git repository"):
        assert_outside_repo(REPO_ROOT / "results")


def test_assert_outside_repo_accepts_a_path_outside(tmp_path):
    assert_outside_repo(tmp_path)  # 不抛即通过


def test_the_gate_fires_for_every_write_path_not_just_run_dir(monkeypatch):
    """**闸必须覆盖全部写盘路径，而不是只覆盖 run_dir。**

    原先 `assert_outside_repo` 只在 `run_dir()` 里调用，于是
    `trials.py` / `configs.py` 直接拼路径**绕过了它**——把 HOME 指到仓库内时，
    账本与配置会**静默写进仓库**（§7 违规），要等到某次提交作业触发 `run_dir()` 才报错。
    这条测试断言：**每一条**写路径都会在写之前抛错。
    """
    repo_root = REPO_ROOT
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
    from web import state as state_mod
    from web.trials import append_trial

    repo = REPO_ROOT
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


def test_a_relative_state_home_cannot_sneak_inside_the_repo(monkeypatch, tmp_path):
    """**相对路径的 `HIAGENT_PLATFORM_HOME` 不许因为换了 cwd 就绕过闸。**

    闸把"已验证过的路径"缓存起来（每个进程每个路径只验一次）。原实现的**缓存键是
    未解析的字符串**，而相对路径在不同 cwd 下解析到**不同目录** —— 于是同一个字符串
    先在一个 cwd 下被判"在仓库外"并缓存，随后 chdir 到仓库根，它解析**进**仓库里，
    **却因缓存命中而放行**。

    实测（2026-10-19）：`HIAGENT_PLATFORM_HOME=hiagent_evil`，
    先 cwd=/tmp → 放行；再 chdir 到仓库根 → 解析到 `<repo>/hiagent_evil`（**仓库内**）
    → 缓存命中 → **放行**，产物就落进仓库了。

    判据是"**解析后**的路径是否在仓库内"，缓存键就必须是解析后的路径；
    否则缓存的是**输入**，而输入在这里恰恰是**会随环境变的那一半**。
    """
    from web import state as state_mod

    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", "hiagent_evil")
    state_mod._ASSERTED.clear()

    # 仓库外：解析到 tmp_path/hiagent_evil，确实在仓库外 → 放行（并写进缓存）
    monkeypatch.chdir(tmp_path)
    state_mod.assert_state_writable()

    # **同一个 HOME 字符串**，现在解析进仓库里 → 必须重新判定并拒绝
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(RuntimeError, match="inside the git repository"):
        state_mod.assert_state_writable()


def test_a_run_id_cannot_escape_the_runs_directory(monkeypatch, tmp_path):
    """**拼接后的路径必须在 `runs/` 底下** —— 闸不能只检查 `state_home()` 本身。

    实测（2026-10-19）：`run_artifact("../../../../../../etc/hostname", "x")`
    在加守卫前解析到 `/private/etc/hostname/x` —— **状态目录之外**。

    **今天经 HTTP 到不了**（FastAPI/Starlette 在路由层就拒掉带 `/` 的路径参数，
    三种编码写法实测都是 404）—— 所以这不是一个可利用的漏洞，我不夸大它。
    但 `list_runs()` 会拿**账本行里的 run_id** 来调它，而账本可以被手改或损坏；
    **"靠调用方凑巧安全"** 正是这个仓库我已经修过四次的形状。

    判据取"解析后仍在 `runs/` 之下"，而不是"`run_id` 长得像不像 id"：
    后者会把测试里那些可读的 id（`r1`/`abc123`）一并拒掉，却不提供更多保证。
    """
    from web.state import run_artifact, run_dir

    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    from web import state as state_mod
    state_mod._ASSERTED.clear()

    for evil in ("..", "../..", "../../../../../../etc/hostname", "/etc/passwd",
                 "runs/../../escape"):
        with pytest.raises(RuntimeError, match="escapes the runs directory"):
            run_artifact(evil, "run.log")
        with pytest.raises(RuntimeError, match="escapes the runs directory"):
            run_dir(evil)

    # 正常 id（含带子目录的——它仍在 runs/ 之下）照常
    assert run_artifact("r1", "run.log").name == "run.log"
    assert str(run_artifact("a/b", "x")).endswith("runs/a/b/x")
    d = run_dir("abc123")
    assert d.is_dir()
