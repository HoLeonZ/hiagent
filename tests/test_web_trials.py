"""trial 账本：append-only，且 **preview 也要记**（§5）。"""
from __future__ import annotations

import json

import pytest

from web.trials import (
    append_trial,
    count_trials,
    distinct_manual_configs,
    recent_runs,
)


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    return tmp_path


def test_append_returns_a_monotonic_trial_number(home):
    a = append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    b = append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.10}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    assert (a, b) == (1, 2)


def test_preview_runs_are_also_recorded(home):
    """§5 管的是“试过多少配置”，与用什么窗口无关。

    漏记 preview 等于开了一个不提记账的调参后门。
    """
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2025-01-01", end="2025-03-01",
                 mode="preview")
    assert count_trials("short_reversal", "v50_slope") == 1


def test_the_ledger_is_append_only_jsonl(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    lines = (home / "trials.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "两条记录不能互相覆盖"
    assert all(json.loads(l)["run_id"] for l in lines)


def test_a_plain_reproduction_is_not_a_trial(home):
    """不带覆盖的运行只是复现一个已声明的 preset，不是一次迭代（§5）。"""
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert count_trials("short_reversal", "v50_slope") == 1                 # 审计条数
    assert distinct_manual_configs("short_reversal", "v50_slope") == 0      # 试验数


def test_the_same_overrides_twice_count_once(home):
    """同一组覆盖跑两次是同一个配置，只计一次。"""
    for rid in ("r1", "r2"):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    assert count_trials("short_reversal", "v50_slope") == 2
    assert distinct_manual_configs("short_reversal", "v50_slope") == 1


def test_different_overrides_count_separately(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.10}, start="2024-01-01", end="2025-01-01", mode="full")
    assert distinct_manual_configs("short_reversal", "v50_slope") == 2


def test_count_is_per_engine_and_preset(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="chase_up", preset="v19",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert count_trials("short_reversal", "v50_slope") == 1
    assert count_trials("chase_up", "v19") == 1
    assert count_trials("short_reversal", "v44_ratio02_buf07") == 0


def test_recent_runs_returns_newest_first_and_honours_the_limit(home):
    """`recent_runs` 是"历史/对比"面板的数据源：**倒序**，且 `limit` 只截尾部。

    它是 `web.trials` 的公开 API，却一度没有任何测试——改坏了没人知道。
    账本是 append-only，故"最近"就是文件尾部；倒序错了面板会把最老的运行
    当成"最近一次"，`limit` 失效则会把整部账本倒给前端。
    """
    for rid in ("r1", "r2", "r3"):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert [r["run_id"] for r in recent_runs()] == ["r3", "r2", "r1"], "必须是倒序"
    assert [r["run_id"] for r in recent_runs(limit=2)] == ["r3", "r2"], "limit 取最近的 N 条"
