"""Pure entry-condition evaluator for short_reversal (CLAUDE.md §6).

Single source of truth for the A-K entry gates. The backtrader strategy
collects scalars from its LineBuffers and calls this; the live signal job
collects the same scalars from a DuckDB panel and calls this. Neither may
re-implement any condition.

Transplanted verbatim from Phase3V3Strategy._all_conditions
(short_reversal/replay_strategy_v3.py:975-1125, 2026-10-17). Any change to the
evaluation ORDER or short-circuit semantics alters the trade list and MUST
regenerate tests/golden/sr_*_baseline.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class BarSnapshot:
    open: float
    high: float
    low: float
    close: float
    date: date


@dataclass(frozen=True)
class ConditionResult:
    passed: bool
    failed_at: str | None
    checks: dict[str, bool] = field(default_factory=dict)


# Every key check_conditions reads from `params`. Consumers must build their
# params mapping from THIS tuple — do not reflect over backtrader's AutoInfoClass.
CONDITION_PARAM_KEYS: tuple[str, ...] = (
    "sl_cooldown_days",
    "liq_low", "liq_high",
    "signal_price_domain", "a_condition", "close_ma60_buffer",
    "below_ratio_60", "up_streak_low", "up_streak_high",
    "pct_chg_low", "pct_chg_high", "d_mode",
    "require_ma20_slope_neg", "ma20_slope_threshold",
    "require_weak_1m", "weak_1m_threshold",
    "require_weak_3m", "weak_3m_threshold",
    "require_weak_6m", "weak_6m_threshold",
    "require_amount_dryup", "amount_dryup_threshold",
    "require_rsi_oversold", "rsi_oversold_threshold",
    "require_intraday_reversal", "intraday_reversal_threshold",
    "intraday_reversal_require_close_above_open",
)


def _is_nan(x: float) -> bool:
    return x is None or (isinstance(x, float) and np.isnan(x))


def check_conditions(
    bar: BarSnapshot,
    ind: Mapping[str, float],
    params: Mapping[str, Any],
    last_sl_date: date | None = None,
) -> ConditionResult:
    checks: dict[str, bool] = {}

    def fail(tag: str) -> ConditionResult:
        checks[tag] = False
        return ConditionResult(False, tag, checks)

    def ok(tag: str) -> None:
        checks[tag] = True

    # ---- J: SL cooldown (must stay first — cheapest, and blocks everything)
    if params.get("sl_cooldown_days", 0) > 0 and last_sl_date is not None:
        days_since = (bar.date - last_sl_date).days
        if days_since < params["sl_cooldown_days"]:
            return fail("J")
    if params.get("sl_cooldown_days", 0) > 0:
        ok("J")

    # ---- E: liquidity
    am60 = ind["am60"]
    if _is_nan(am60) or not (params["liq_low"] <= am60 <= params["liq_high"]):
        return fail("E")
    ok("E")

    # ---- A
    ma60_v = ind["ma60"]
    if _is_nan(ma60_v):
        return fail("A")
    close_v = (
        float(ind["signal_close"])
        if params.get("signal_price_domain", "adj") == "adj"
        else float(bar.close)
    )
    if _is_nan(close_v):
        return fail("A")
    if params.get("a_condition", "default") == "cascade_price":
        ma5_v, ma10_v, ma20_v = ind["ma5"], ind["ma10"], ind["ma20"]
        if _is_nan(ma5_v) or _is_nan(ma10_v) or _is_nan(ma20_v):
            return fail("A")
        if not (ma5_v < ma10_v < ma20_v < ma60_v and close_v < ma20_v):
            return fail("A")
    else:
        ratio = ind["below_ma60_ratio_60"]
        if _is_nan(ratio):
            return fail("A")
        if close_v >= ma60_v * (1.0 + params.get("close_ma60_buffer", 0.0)):
            return fail("A")
        if ratio < params["below_ratio_60"]:
            return fail("A")
    ok("A")

    # ---- B: consecutive up days
    us = ind["up_streak"]
    if _is_nan(us) or not (params["up_streak_low"] <= us <= params["up_streak_high"]):
        return fail("B")
    ok("B")

    # ---- C: pct change band
    pc = ind["pct_chg"]
    if _is_nan(pc) or not (params["pct_chg_low"] <= pc <= params["pct_chg_high"]):
        return fail("C")
    ok("C")

    # ---- D: MACD
    dif, dea = float(ind["macd_dif"]), float(ind["macd_dea"])
    prev_dif, prev_dea = float(ind["macd_prev_dif"]), float(ind["macd_prev_dea"])
    bar_v = dif - dea
    prev_bar = prev_dif - prev_dea
    if _is_nan(dif) or _is_nan(dea) or _is_nan(prev_bar):
        return fail("D")
    d_mode = params.get("d_mode", "strict")
    if d_mode == "d_only":
        if not (dif < 0):
            return fail("D")
    elif d_mode == "converge_strict":
        if not (dif < 0 and dea < 0 and abs(bar_v) < abs(prev_bar) * 0.5):
            return fail("D")
    else:
        if not (dif < 0 and dea < 0 and abs(bar_v) < abs(prev_bar)):
            return fail("D")
    ok("D")

    # ---- F: MA20 regression slope
    if params.get("require_ma20_slope_neg", False):
        slope = ind["ma20_slope_5d"]
        if _is_nan(slope) or slope > params["ma20_slope_threshold"]:
            return fail("F")
        ok("F")

    # ---- G: weak-stock windows (each independent, same tag prefix + window)
    for tag, flag, key, thr in (
        ("G1", "require_weak_1m", "return_1m", "weak_1m_threshold"),
        ("G3", "require_weak_3m", "return_3m", "weak_3m_threshold"),
        ("G6", "require_weak_6m", "return_6m", "weak_6m_threshold"),
    ):
        if params.get(flag, False):
            ret = ind[key]
            if _is_nan(ret) or ret > params[thr]:
                return fail(tag)
            ok(tag)

    # ---- H: amount dry-up
    if params.get("require_amount_dryup", False):
        ar = ind["amount_ratio"]
        if _is_nan(ar) or ar > params["amount_dryup_threshold"]:
            return fail("H")
        ok("H")

    # ---- I: RSI oversold
    if params.get("require_rsi_oversold", False):
        rsi_v = ind["rsi"]
        if _is_nan(rsi_v) or rsi_v >= params["rsi_oversold_threshold"]:
            return fail("I")
        ok("I")

    # ---- K: intraday reversal
    if params.get("require_intraday_reversal", False):
        high_v, low_v = float(bar.high), float(bar.low)
        if high_v <= low_v:
            return fail("K")
        close_pos = (close_v - low_v) / (high_v - low_v)
        if close_pos < params["intraday_reversal_threshold"]:
            return fail("K")
        if params.get("intraday_reversal_require_close_above_open", True) and \
                close_v <= float(bar.open):
            return fail("K")
        ok("K")

    return ConditionResult(True, None, checks)
