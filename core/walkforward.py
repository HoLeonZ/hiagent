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

import logging

logger = logging.getLogger(__name__)

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


def window_coverage(windows: list[WalkForwardWindow]) -> tuple[list[int], list[int]]:
    """相邻 test 窗的**重叠月数**与**空档月数**(纯函数,便于单测)。

    返回 `(overlaps, gaps)`,长度都是 `len(windows) - 1`(没有相邻对时为空)。

    为什么需要它:`roll_months < test_months` ⇒ 相邻 **test 窗重叠**(同一段行情被
    多个窗口重复计入);`roll_months > test_months` ⇒ 中间**留空档**(那段行情没人看)。
    两者都不报错、也不提示,而已有的一条 OOS 测试的 docstring 写着"无 sample overlap"
    —— 那句话**只在窗口内**成立(train_end < test_start),跨窗口并不成立:
    实测默认参数(train 12 / test 12 / roll 6)下两个 test 窗**重叠 6 个月(50%)**。

    重叠本身可以是一种选择(更多折),**但必须被说出来**:聚合层(跨窗均值/中位数、
    DSR)会把"N 个窗"当成 N 份独立证据,而重叠时并不独立。
    """
    def month_index(d: date) -> int:
        return d.year * 12 + d.month

    overlaps: list[int] = []
    gaps: list[int] = []
    for prev, nxt in zip(windows, windows[1:]):
        # 以**月序号**为准(而不是天数差):delta = 下一窗开始的月份 - 本窗结束的月份。
        #   delta <= 0 ⇒ 有重叠,共享 (1 - delta) 个**日历月**;
        #   delta == 1 ⇒ 首尾相接(不重不漏);
        #   delta >  1 ⇒ 中间空档 (delta - 1) 个月。
        # 注意口径:共享月数按**日历月**计 —— 默认参数(roll 6 / test 12)下
        # 2025-01..2025-12 与 2025-07..2026-06 共享 7..12 共 **6** 个月。
        # (我第一版写成 `-delta`,把 6 报成 5 —— 差一个月,报告里的数就不能用了。)
        delta = month_index(nxt.test_start) - month_index(prev.test_end)
        if delta <= 0:
            overlaps.append(1 - delta)
        elif delta > 1:
            gaps.append(delta - 1)
    return overlaps, gaps


def window_trading_days(panel: pd.DataFrame, start: str, end: str) -> int:
    """面板里**属于 `[start, end]` 窗口**的交易日数(CLAUDE.md §5 单源)。

    **为什么需要它**(附八十一 实测):各引擎的 `load_panel()` 都会把起点往前推
    一个暖机缓冲(`WARMUP_DAYS = 400`,chase / uptrend / short_reversal 同构),
    所以 `panel` **不是**窗口,而是 `[start − 400 天, end]`。于是
    `panel["date"].nunique()` 量的是**面板**长度,不是**窗口**长度 —— 而这个名字
    长得像窗口统计量,极容易被当成窗口用。

    它被用错的地方会同时污染两个量(实测 T 高估 **2.10 倍**):
      * CAGR 的年化分母 ⇒ 短窗口 CAGR 被系统性压低;
      * DSR 的 `n_returns` ⇒ T 高估 ⇒ DSR **偏乐观**。

    早先多处写成 `int(panel["date"].nunique())`,其中至少一处(附六十)还是**为了
    "把猜的常数换成实测值"**才这么写的 —— 一次意在提高诚实度的修复,反而把指标推得
    更宽松。故此处单源,并在窗口为空时 fail-fast(不许退化成面板长度)。
    """
    days = int(
        panel.loc[
            (panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end)),
            "date",
        ].nunique()
    )
    if days == 0:
        raise ValueError(
            f"§5: 窗口 {start}..{end} 在面板里一个交易日都没有 —— "
            f"年化与 DSR 的分母无从谈起(不许退化成面板长度 {int(panel['date'].nunique())})"
        )
    return days


def walkforward_windows(
    start: date,
    end: date,
    train_months: int = 12,
    test_months: int = 12,
    roll_months: int = 6,
) -> list[WalkForwardWindow]:
    """生成 train/test split WFV 窗口 (cycle_price_action 风格).

    每个窗口: train_months 训练 + test_months 测试, 然后向前 roll_months。
    train_end < test_start 强制 (OOS testing) —— 这是**窗口内**的 OOS。

    ## 跨窗口的语义(附七十五 写清)

    `roll_months` 与 `test_months` 的关系决定相邻 **test 窗**的关系:

    | 关系 | 后果 |
    |---|---|
    | `roll < test` | test 窗**重叠**(默认 6 < 12 ⇒ 相邻窗重叠 50%)—— 同一段行情被多个窗口重复计入 |
    | `roll == test` | test 窗首尾相接,不重不漏 |
    | `roll > test` | 中间**留空档**,那段行情没人评估 |

    重叠/空档都不报错(它们是选择,不是 bug),但本函数会**告警**并给出具体月数 ——
    聚合层(跨窗均值/中位数、DSR)若无此信息,会把"N 个窗"当成 N 份**独立**证据。
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

    overlaps, gaps = window_coverage(windows)
    if overlaps:
        logger.warning(
            "§5 WFV: 相邻 test 窗**重叠** %s 个月(roll_months=%d < test_months=%d)"
            " —— %d 个窗并非 %d 份独立证据;聚合均值/中位数与 DSR 的 T 口径要把这一点说清。",
            overlaps, roll_months, test_months, len(windows), len(windows),
        )
    if gaps:
        logger.warning(
            "§5 WFV: 相邻 test 窗之间**留空档** %s 个月(roll_months=%d > test_months=%d)"
            " —— 这些月份没有被评估。",
            gaps, roll_months, test_months,
        )
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