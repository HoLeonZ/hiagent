"""回归测试:render_html_report.build_trade_dates 必须正确反推 entry_date / exit_date。

历史 bug (2026-09-20):
    renderer 的 docstring 声称会校验 exit_price ∈ [low, high] of exit bar,
    但实现没真做校验。结果当 entry_price 同时匹配多根 bar 的 open 时,
    renderer 任意挑第一根, 把错误的 entry_date / exit_date 写到 HTML,
    导致 exit_price 看起来比 exit_date 当天 low 还低 (实际是 exit_date 错了)。

正确行为(本文件钉住):
    1. 候选 entry bar 必须满足 open ≈ entry_price (容差 ±0.001)
    2. 候选 entry bar 之后的第 hold_days 个 BDay 上, exit_price 必须 ∈ [low, high]
       (SL gap-up 是例外: sl_p < low 是合法的 backtrader 约定, 不是 bug)
    3. 若存在多个候选 → 选**能通过校验**的那一个(而不是日期最早的那个)
    4. 若所有候选都不通过校验 → 必须标 **unverified** (而不是任意挑一个错的)

## 2026-10-17 重写(原版是"守卫依赖已消失的产物")

原版三条例用**真实回测产物**(`short_reversal/results/v33_*.json`)驱动,
而那两个 preset(`v33_mainboard_tp2_sl05_dneg` / `v33_mainboard_tp6_sl005_mh5_realistic`)
**已被裁剪出 PRESETS** ⇒ 产物再也无法重生成 ⇒ 三条用例**永远 skip**(实测 3 条 skip,
理由还写着"需用 --save-trades 重跑 <已不存在的 preset>",是一条**不可能执行的指引**)。
另外原版把 DB 与 results 路径**硬编码**成别人的检出
(`/Users/holeon/code/hiagent/short_reversal/results`)—— 与审计在
`_regen_chase_baselines.py` 修过的"硬编码绝对路径会读/写别的检出"是同一类。

现改为**合成夹具**:不依赖任何产物、不需要 DB,于是**任何检出里都能跑**,
而上面四条不变量全部仍被钉住。
"""
from __future__ import annotations

import pandas as pd
import pytest

from short_reversal.render_html_report import build_trade_dates


def _bar(date: str, o: float, h: float, lo: float, c: float) -> dict:
    return {"date": pd.Timestamp(date), "open": o, "high": h, "low": lo, "close": c}


def _trade(**kw) -> dict:
    base = {"thscode": "X", "entry_price": 10.0, "exit_price": 11.4,
             "hold_days": 1, "exit_reason": "TP"}
    base.update(kw)
    return base


_WINDOW = ("2026-01-01", "2026-01-31")


def test_ambiguous_entry_price_picks_the_candidate_that_validates() -> None:
    """**历史 bug 本体**:两根 bar 的 open 都 ≈ entry_price ⇒ 必须选能过校验的那根。

    下例中 01-05 与 01-06 的 open 都是 10.0;只有 01-06 之后的 exit bar
    (01-07,xp=11.4 ∈ [10.0, 11.5])能通过校验。旧实现"任意挑第一根"会选 01-05,
    于是 01-06 才是 exit bar,而 11.4 不在其 [9.8, 10.3] 内 ⇒ 报告里出现
    "exit_price 比当日 high 还高"这类错。本断言直接钉住"选能验证的那根"。
    """
    klines = {"X": pd.DataFrame([
        _bar("2026-01-05", 10.0, 10.2, 9.9, 10.1),
        _bar("2026-01-06", 10.0, 10.3, 9.8, 10.0),
        _bar("2026-01-07", 10.1, 11.5, 10.0, 11.4),
    ])}
    out = build_trade_dates([_trade()], klines, *_WINDOW)
    assert out[0]["_entry_date"] == "2026-01-06", (
        "选了 2026-01-05(最早候选)而不是能通过 exit_price 校验的那根 —— 历史 bug 回归"
    )
    assert out[0]["_exit_date"] == "2026-01-07"
    assert out[0]["_date_status"] == "verified"


def test_sl_gap_up_is_legitimate_not_a_mismatch() -> None:
    """SL 且 xp < low(gap-up 跳过止损)是**合法**约定,应判 verified。"""
    klines = {"X": pd.DataFrame([
        _bar("2026-01-05", 10.0, 10.2, 9.9, 10.1),
        _bar("2026-01-06", 9.2, 9.3, 9.0, 9.1),   # exit bar:low=9.0 ⇒ xp=9.0 < low 合法
    ])}
    trade = _trade(exit_price=8.5, exit_reason="SL", hold_days=1)
    out = build_trade_dates([trade], klines, *_WINDOW)
    assert out[0]["_date_status"] == "verified", (
        "SL gap-up(xp < low)被当成 mismatch —— 会把合法成交报成渲染错误"
    )


def test_no_validating_candidate_is_marked_unverified() -> None:
    """**要求 4**:所有候选都通不过校验 ⇒ 状态必须是 `unverified`,不得默认可信。

    实现里此前**从来没有** "unverified" 这个词(它只出现在本文件的 docstring 里):
    代码退化取最早候选,还**凭空推**一个 exit_date(`entry + BDay(hd)`),
    那个 bar 可能根本不存在 —— 报告里于是出现一个"看起来正常、实际是编的"日期。
    本断言钉住:状态随行发布,且回退路径不得自称 verified。
    """
    klines = {"X": pd.DataFrame([
        _bar("2026-01-05", 10.0, 10.2, 9.9, 10.1),
        _bar("2026-01-06", 10.5, 10.6, 10.4, 10.5),  # xp=11.4 不落在任何一根的 [low, high]
    ])}
    out = build_trade_dates([_trade()], klines, *_WINDOW)
    assert out[0]["_date_status"] == "unverified", (
        f"回退路径自称 {out[0]['_date_status']!r} —— 声明(要求 4)与实现不符"
    )


def test_missing_kline_is_marked_no_kline_match() -> None:
    """该股在 klines 里没有数据 ⇒ `no_kline_match`(日期是按 index 推的,不可当真)。"""
    out = build_trade_dates([_trade(thscode="NOPE")], {}, *_WINDOW)
    assert out[0]["_date_status"] == "no_kline_match"


def test_every_row_carries_a_status() -> None:
    """任何一行都必须带状态 —— 默认值是 `unknown`(fail-safe),绝不默认 `verified`。"""
    klines = {"X": pd.DataFrame([_bar("2026-01-05", 10.0, 11.0, 9.5, 10.5)])}
    out = build_trade_dates([_trade(), _trade(thscode="NOPE")], klines, *_WINDOW)
    assert all("_date_status" in r for r in out)
    assert all(r["_date_status"] != "unknown" for r in out), (
        "有行走到了未覆盖的路径(状态仍是 unknown)—— 说明新增分支没设状态"
    )
