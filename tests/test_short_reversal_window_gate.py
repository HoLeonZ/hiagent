"""§1 窗口边界显式约束守卫（审计 P1-C，2026-10-15）。

背景：short_reversal 的面板按 180 天前 / 60 天后扩 buffer，而 `feed_bt.py`
明确不设 `fromdate/todate`。实测「无窗口前入场」成立 —— 但那是靠指标暖机的
NaN gate **偶然**保证的：策略里从来没有窗口检查，改指标周期 / `min_bars` /
buffer 常量即可静默失守，而当时的守卫用例因 harness 分叉常年 ERROR（零覆盖）。

本文件锁定三件事：
  1. 策略暴露 `window_start` / `window_end` 参数，未提供时 `_in_window` 放行
     （仅为不关心窗口的单测保留；策略侧会打 warn，不静默）。
  2. `_in_window` 的边界语义正确（含端点），且**只约束入场**。
  3. **生产入口 `engine.py` 必须传真实窗口** —— 这条是防止重蹈
     「修复做成可选开关、默认仍是违规值」的关键（同 §3
     `signal_price_domain` 默认 `raw` 的教训）。
"""
from __future__ import annotations

import datetime as dt
import inspect

from pathlib import Path

import pytest

from short_reversal import engine as sr_engine
from short_reversal.replay_strategy_v3 import Phase3V3Strategy

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1) 参数存在且默认为 None（不启用）
# ---------------------------------------------------------------------------


def test_window_params_exist_and_default_disabled() -> None:
    # backtrader 的 params 是 ParamsBase 子类，用 _getitems() 取 (name, default)
    params = dict(Phase3V3Strategy.params._getitems())
    assert "window_start" in params, "策略缺少 window_start 参数（§1 窗口约束）"
    assert "window_end" in params, "策略缺少 window_end 参数（§1 窗口约束）"
    assert params["window_start"] is None and params["window_end"] is None, (
        "默认应为 None（不启用）；启用状态由生产入口显式传入"
    )


# ---------------------------------------------------------------------------
# 2) _in_window 边界语义
# ---------------------------------------------------------------------------


class _FakeData:
    """最小替身：_in_window 只读 d.datetime[0]（backtrader 的 datetime line）。"""

    def __init__(self, day: dt.date) -> None:
        import backtrader as bt

        self._num = bt.date2num(day)

        class _Line:
            def __init__(self, num: float) -> None:
                self._num = num

            def __getitem__(self, _idx: int) -> float:
                return self._num

        self.datetime = _Line(self._num)


def _mk(win_start, win_end):
    class _Gate:
        _in_window = Phase3V3Strategy._in_window

        def __init__(self, s, e):
            self._win_start, self._win_end = s, e

    return _Gate(win_start, win_end)


def test_in_window_disabled_passes_everything() -> None:
    gate = _mk(None, None)
    assert gate._in_window(_FakeData(dt.date(2020, 1, 1))) is True


def test_in_window_bounds_are_inclusive() -> None:
    start = dt.date(2025, 9, 12)
    end = dt.date(2026, 9, 12)
    gate = _mk(start, end)
    assert gate._in_window(_FakeData(start)) is True, "窗口首日必须允许入场"
    assert gate._in_window(_FakeData(end)) is True, "窗口末日必须允许入场"
    assert gate._in_window(_FakeData(dt.date(2025, 9, 11))) is False, "窗口前一日必须拒绝"
    assert gate._in_window(_FakeData(dt.date(2026, 9, 13))) is False, "窗口后一日必须拒绝"


# ---------------------------------------------------------------------------
# 3) 生产入口必须传窗口（防止「可选开关」式的假修复）
# ---------------------------------------------------------------------------


def test_production_entrypoint_passes_window_bounds() -> None:
    """engine.py 的 addstrategy 必须显式传 window_start/window_end。

    否则生产路径会退回到"无窗口约束"，而单测仍然全绿 —— 正是 §3
    `signal_price_domain` 默认 `raw` 那类"修复不可达"的失败模式。
    """
    src = inspect.getsource(sr_engine.run_backtest_v3)
    assert "window_start=start" in src, "engine.py 未把窗口起点下发给策略"
    assert "window_end=end" in src, "engine.py 未把窗口终点下发给策略"


def test_entry_queue_is_window_gated() -> None:
    """入场排队处必须经过 _in_window（而非只写在文档里）。"""
    src = inspect.getsource(Phase3V3Strategy.next)
    assert "_in_window(" in src, (
        "next() 的入场排队未经过 _in_window —— 窗口约束不可达"
    )
