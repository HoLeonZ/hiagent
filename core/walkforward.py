"""共用 Walk-Forward Validation 窗口生成器 (CLAUDE.md §5).

4 engine 共用同一份代码 — chase_up / uptrend_pullback / short_reversal /
cycle_price_action / dna_stats 全部从此 import, 不重复实现。

提供 3 个窗口生成函数 (不同 WFV 形态):
  - `walkforward_windows()`: train/test split 窗口 (cycle_price_action 风格)
  - `monthly_windows()`: 月级滚动单窗口 (chase_up + uptrend_pullback 同构)
  - `yearly_windows()`: 逐年窗口 (uptrend_pullback 风格)

CLAUDE.md §5 铁律: 简单 grid-search 找 max Sharpe 是 banned, 必须 WFV。
`walkforward_windows()` 强制 train_end < test_start (out-of-sample)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    """单个 WFV 窗口: train 段 + test 段 (out-of-sample).

    train_end < test_start 强制 — 防 look-ahead bias。
    """

    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __getitem__(self, key: str) -> date:
        return getattr(self, key)


def walkforward_windows(
    start: date,
    end: date,
    train_months: int = 12,
    test_months: int = 12,
    roll_months: int = 6,
) -> list[WalkForwardWindow]:
    """生成 train/test split WFV 窗口 (cycle_price_action 风格).

    每个窗口: train_months 训练 + test_months 测试, 然后向前 roll_months。
    train_end < test_start 强制 (OOS testing)。
    """
    if (end.year - start.year) * 12 + (end.month - start.month) < train_months + test_months:
        raise ValueError("horizon too short for train+test windows")

    windows: list[WalkForwardWindow] = []
    train_start = pd.Timestamp(start).normalize()
    while True:
        train_end = _add_months(train_start, train_months) - pd.tseries.offsets.BDay(1)
        test_start = _add_months(train_start, train_months)
        test_end = _add_months(test_start, test_months) - pd.tseries.offsets.BDay(1)
        if test_end.date() > end:
            break
        windows.append(
            WalkForwardWindow(
                train_start=train_start.date(),
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
            )
        )
        train_start = _add_months(train_start, roll_months)
    return windows


def monthly_windows(
    start_month: str,
    end_month: str,
    window_months: int = 2,
    step_months: int = 0,
) -> list[tuple[str, str]]:
    """生成 [start_month, end_month) 内的月级滚动窗口 (chase_up + uptrend_pullback 同构).

    start_month / end_month 格式 'YYYY-MM', 窗口左闭右开。
    step_months = 0 时退化为不重叠 (= window_months)。
    返回 (start_date, end_date) 列表, 日期形如 'YYYY-MM-DD'。
    """
    step = step_months if step_months > 0 else window_months
    sy, sm = map(int, start_month.split("-"))
    ey, em = map(int, end_month.split("-"))
    cur_y, cur_m = sy, sm
    out: list[tuple[str, str]] = []
    while True:
        end_y, end_m = cur_y, cur_m + window_months
        while end_m > 12:
            end_m -= 12
            end_y += 1
        if (end_y, end_m) > (ey, em):
            break
        out.append((f"{cur_y:04d}-{cur_m:02d}-01", f"{end_y:04d}-{end_m:02d}-01"))
        cur_m += step
        while cur_m > 12:
            cur_m -= 12
            cur_y += 1
    return out


def yearly_windows(first_year: int, last_year: int, month_day: str = "09-08") -> list[tuple[str, str]]:
    """生成 [first_year..last_year] 的逐年窗口 (uptrend_pullback 风格).

    起止日对齐 month_day (默认 '09-08')。
    """
    return [
        (f"{y}-{month_day}", f"{y + 1}-{month_day}")
        for y in range(first_year, last_year)
    ]


def _add_months(d: date, n: int) -> pd.Timestamp:
    return (pd.Timestamp(d) + pd.DateOffset(months=n)).normalize()