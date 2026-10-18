"""四引擎适配器：统一返回形状、窗口计算、以及在窗口太短时给出**具名**错误。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from web.runners import PREVIEW_DAYS, RunResult, WindowTooShortError, effective_window, run

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


def test_preview_window_is_the_last_n_days():
    start, end = effective_window("preview", "2020-01-01", "2026-06-30")
    assert end == "2026-06-30"
    assert start == "2026-04-01"  # 90 天


def test_preview_window_never_goes_earlier_than_the_requested_start():
    start, _ = effective_window("preview", "2026-06-01", "2026-06-30")
    assert start == "2026-06-01"


def test_full_window_is_returned_unchanged():
    assert effective_window("full", "2020-01-01", "2026-06-30") == ("2020-01-01", "2026-06-30")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_run_returns_the_uniform_shape_for_short_reversal():
    """full 模式用引擎默认 min_bars；窗口足够宽，不应触发 F-01。"""
    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    assert isinstance(got, RunResult)
    assert got.engine == "short_reversal" and got.preset == "v50_slope"
    assert isinstance(got.trades, list)
    assert isinstance(got.metrics, dict)
    assert "trades_count" in got.metrics


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_window_too_short_raises_a_named_error_not_a_bare_valueerror():
    """F-01 守卫在面板跨度过小时抛 ValueError。

    平台必须把它转成**具名**错误，好让 API 回 400 而不是 500——
    否则用户看到的是"服务器错误"，而不是"窗口太短"。
    """
    with pytest.raises(WindowTooShortError, match="min_bars"):
        run("short_reversal", "v50_slope", "2026-01-05", "2026-01-20")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_overrides_are_applied_and_visible_in_the_run():
    """改了 tp_pct 必须真的进到这次运行里（不能静默忽略）。"""
    base = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    changed = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12",
                  overrides={"tp_pct": 0.30})
    assert changed.metrics["trades_count"] != base.metrics["trades_count"] or \
           changed.metrics["final_capital"] != base.metrics["final_capital"], \
        "覆盖 tp_pct 后结果必须变化——否则参数没有真的传进去"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_short_reversal_accepts_a_params_dict_not_just_a_name():
    """平台必须能传入被覆盖的参数。

    `run_backtest_v3(preset: str)` 内部 `cfg = dict(get_preset(preset))`，
    于是平台侧改的 params 会被**静默丢弃**——用户改了 tp_pct 却拿到原 preset 的结果。
    另三个引擎的入口都收 `str | dict`，此处与它们对齐。
    """
    from short_reversal.engine import run_backtest_v3
    from web.catalog import all_presets

    db = _db()
    params = dict(all_presets()["short_reversal"]["v50_slope"])
    by_name = run_backtest_v3("v50_slope", "2025-09-12", "2026-09-12", db)

    params["tp_pct"] = 0.30
    by_dict = run_backtest_v3(params, "2025-09-12", "2026-09-12", db)

    assert by_dict["trades_count"] != by_name["trades_count"] or \
           by_dict["final_capital"] != by_name["final_capital"], \
        "传入 dict 时覆盖必须生效——否则参数被静默丢弃"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_passing_a_name_still_behaves_identically():
    """向后兼容：传字符串的行为必须逐个字节不变。"""
    from short_reversal.engine import run_backtest_v3

    db = _db()
    m = run_backtest_v3("v50_slope", "2025-09-12", "2026-09-12", db)
    assert m["trades_count"] == 74, "v50_slope 在 golden 窗口上仍是 74 笔"
