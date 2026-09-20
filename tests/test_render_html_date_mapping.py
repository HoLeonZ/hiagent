"""回归测试：render_html_report.build_trade_dates 必须正确反推 entry_date / exit_date。

历史 bug (2026-09-20):
    renderer 的 docstring 声称会校验 exit_price ∈ [low, high] of exit bar,
    但实现没真做校验。结果当 entry_price 同时匹配多根 bar 的 open 时,
    renderer 任意挑第一根, 把错误的 entry_date / exit_date 写到 HTML,
    导致 exit_price 看起来比 exit_date 当天 low 还低 (实际是 exit_date 错了)。

正确行为:
    1. 候选 entry bar 必须满足 open ≈ entry_price (容差 ±0.001)
    2. 候选 entry bar 之后的第 hold_days 个 BDay 上, exit_price 必须 ∈ [low, high]
       (SL gap-up 是例外: sl_p < low 是合法的 backtrader 约定, 不是 bug)
    3. 若存在多个候选, 优先选 in_window (回测窗口 + 60d) 的; 同窗口内选最近的日期
    4. 若所有候选都不通过校验, 必须报 "unverified" (而不是任意挑一个错的)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from short_reversal.render_html_report import build_trade_dates, fetch_klines

DB_PATH = Path("/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb")
RESULTS = Path("/Users/holeon/code/hiagent/short_reversal/results")


def _load_trades(preset: str) -> list[dict]:
    path = RESULTS / f"{preset}.json"
    if not path.exists():
        pytest.skip(f"{path} 不存在 — 回测结果已清空,需用 --save-trades 重跑 {preset} 才能跑此测试")
    with open(path) as f:
        data = json.load(f)
    return data["trades"], data["start"], data["end"]


def _verify_date_mapping(trade: dict, entry_date: pd.Timestamp, exit_date: pd.Timestamp,
                          klines: dict) -> str:
    """Verify renderer's date mapping is correct.

    Returns:
        'match' if xp ∈ [low, high] of exit_date's bar
        'sl_gap_up' if reason='SL' and xp < low of exit_date's bar (legitimate)
        'mismatch' otherwise
    """
    code = trade["thscode"]
    df = klines.get(code)
    if df is None or df.empty:
        return "no_kline"
    bar = df[df["date"] == exit_date]
    if bar.empty:
        return "no_exit_bar"
    low = float(bar["low"].iloc[0])
    high = float(bar["high"].iloc[0])
    xp = trade["exit_price"]
    if low <= xp <= high:
        return "match"
    # SL: xp = sl_p (engine convention). gap-up 场景 xp < low 是合法的
    if trade["exit_reason"] == "SL" and xp < low:
        return "sl_gap_up"
    return "mismatch"


def test_tp2_preset_all_dates_correct():
    """tp2 preset: 567 trades, every renderer's mapping must be either
    match (xp in [low,high]) or sl_gap_up (legitimate)."""
    trades, start, end = _load_trades("v33_mainboard_tp2_sl05_dneg")
    codes = list({t["thscode"] for t in trades})
    klines = fetch_klines(codes, start, end, pad_days=60)

    mapped = build_trade_dates(trades, klines, start, end)
    statuses = {"match": 0, "sl_gap_up": 0, "mismatch": 0, "no_kline": 0, "no_exit_bar": 0}
    mismatches = []
    for t, m in zip(trades, mapped):
        entry_date = pd.Timestamp(m["_entry_date"])
        exit_date = pd.Timestamp(m["_exit_date"])
        s = _verify_date_mapping(t, entry_date, exit_date, klines)
        statuses[s] += 1
        if s == "mismatch":
            mismatches.append((t["thscode"], t["entry_price"], t["exit_price"],
                               t["hold_days"], t["exit_reason"], entry_date, exit_date))
    assert statuses["mismatch"] == 0, (
        f"{statuses['mismatch']} trades have mismatched date mapping. "
        f"First 5: {mismatches[:5]}\n"
        f"Total: {statuses}"
    )


def test_tp6_preset_all_dates_correct():
    """tp6 preset: same invariant."""
    trades, start, end = _load_trades("v33_mainboard_tp6_sl005_mh5_realistic")
    codes = list({t["thscode"] for t in trades})
    klines = fetch_klines(codes, start, end, pad_days=60)

    mapped = build_trade_dates(trades, klines, start, end)
    statuses = {"match": 0, "sl_gap_up": 0, "mismatch": 0, "no_kline": 0, "no_exit_bar": 0}
    for t, m in zip(trades, mapped):
        entry_date = pd.Timestamp(m["_entry_date"])
        exit_date = pd.Timestamp(m["_exit_date"])
        s = _verify_date_mapping(t, entry_date, exit_date, klines)
        statuses[s] += 1
    assert statuses["mismatch"] == 0, (
        f"tp6 preset has {statuses['mismatch']} mismatched trades. Total: {statuses}"
    )


def test_renderer_does_not_pick_first_arbitrary_match():
    """When entry_price matches multiple bars' open, renderer must pick the one
    whose next-bar range contains exit_price (NOT just the first)."""
    # trade[91] 605228.SH ep=13.4 xp=13.467 hd=1 reason=SL
    # Multiple bars in window have open in [13.35, 13.45]
    # The CORRECT entry is 2026-02-05 (open=13.35) because 2026-02-06 has
    # low=13.05 high=13.53, so xp=13.467 ∈ [low, high]
    # Renderer must NOT pick 2025-07-29 (open=13.43) which fails validation.
    trades, start, end = _load_trades("v33_mainboard_tp2_sl05_dneg")
    target = next(t for i, t in enumerate(trades) if t["thscode"] == "605228.SH")
    codes = [target["thscode"]]
    klines = fetch_klines(codes, start, end, pad_days=60)
    mapped = build_trade_dates([target], klines, start, end)
    m = mapped[0]
    entry_date = pd.Timestamp(m["_entry_date"])
    exit_date = pd.Timestamp(m["_exit_date"])
    s = _verify_date_mapping(target, entry_date, exit_date, klines)
    assert s == "match", f"trade[91] 605228.SH mapped to wrong dates: entry={entry_date} exit={exit_date}, status={s}"