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

# Defaults for every key above, mirroring Phase3V3Strategy.params exactly.
#
# Why this table exists: `check_conditions` indexes `params["X"]` with NO .get()
# fallback (see the Step 5 note), so every consumer must supply all 27 keys.
# The strategy's adapter can, because they are all declared params. The live
# consumer (Task 6) needs a defaults source and must not invent one, so it takes
# this. `tests/test_short_reversal_conditions_pure.py` asserts this table equals
# the strategy's declared defaults, so the two can never silently diverge.
#
# Do NOT convert these back into `.get(key, default)` calls inside
# `check_conditions`: a missed key would then silently fall back instead of
# raising, and `intraday_reversal_require_close_above_open` defaults to True —
# i.e. the omitted gate would ENABLE ITSELF on the live path.
CONDITION_PARAM_DEFAULTS: dict[str, object] = {
    "sl_cooldown_days": 0,
    "liq_low": 30_000_000.0,
    "liq_high": 300_000_000.0,
    "signal_price_domain": "adj",
    "a_condition": "default",
    "close_ma60_buffer": 0.0,
    "below_ratio_60": 0.6,
    "up_streak_low": 3,
    "up_streak_high": 10,
    "pct_chg_low": 0.02,
    "pct_chg_high": 0.07,
    "d_mode": "strict",
    "require_ma20_slope_neg": False,
    "ma20_slope_threshold": 0.0,
    "require_weak_1m": False,
    "weak_1m_threshold": -0.05,
    "require_weak_3m": False,
    "weak_3m_threshold": -0.1,
    "require_weak_6m": False,
    "weak_6m_threshold": -0.15,
    "require_amount_dryup": False,
    "amount_dryup_threshold": 0.7,
    "require_rsi_oversold": False,
    "rsi_oversold_threshold": 30,
    "require_intraday_reversal": False,
    "intraday_reversal_threshold": 0.6,
    "intraday_reversal_require_close_above_open": True,
}


def _is_nan(x) -> bool:
    """True for None or any NaN, mirroring the source method's direct np.isnan.

    Deliberately NOT `isinstance(x, float)`: numpy scalar types such as
    np.float32 are not Python float subclasses and would slip through. The None
    guard is the only addition over the source, which did not need one because
    its inputs always came from backtrader LineBuffers (C doubles).
    """
    if x is None:
        return True
    try:
        return bool(np.isnan(x))
    except TypeError:
        return False


def check_conditions(
    bar: BarSnapshot,
    ind: Mapping[str, float],
    params: Mapping[str, Any],
    last_sl_date: date | None = None,
) -> ConditionResult:
    # ---- §3 fail-fast: Gate K cannot run in the 'adj' signal domain. ----
    # Gate K (below) reads the bar's RAW high/low/open but compares them against
    # `close_v`, which is `signal_close` (= adj_close, v_daily_hfq) whenever
    # signal_price_domain == 'adj'. adj and raw are different series (measured
    # ~55% of the universe differs), so `close_pos = (adj_close - raw_low) /
    # (raw_high - raw_low)` divides across two domains: on 000001.SZ
    # (2026-09-01..09-08) it measured 13.4 / 28.2 / 15.7 / 26.1 / 16.8 / 24.8
    # against the 0.6 threshold, and `close_v > bar.open` (15.80 > 11.68) is
    # likewise trivial — so K silently degrades to a no-op (§3 violation).
    # Do NOT silently re-point K at adj high/low: that would change the trade
    # list of every K-enabled preset, mid-branch, with no re-validation (§5).
    # Fail fast instead (§0): a K-enabled preset CANNOT run as configured, and K
    # must be re-derived on a SINGLE price domain (adj high/low/open → compare
    # against adj signal_close; or raw high/low/open → compare against raw
    # bar.close) before it can be enabled.
    #
    # ⚠️ Do NOT prescribe `signal_price_domain='raw'` as the remedy. That is
    # precisely the configuration that makes gate A a SILENT NO-OP — raw
    # `bar.close` compared against an SMA of `adj_close` — the §3 violation the
    # `v81_adj` work removed (raw close sits systematically below adj close, so A's
    # close<ma60 leg is almost always true; see replay_strategy_v3.py:305-308).
    # Prescribing 'raw' would just swap one silent no-op (K) for another (A).
    #
    # ⚠️ This guard keys on the DECLARED `signal_price_domain`, not the EFFECTIVE
    # price source. `replay_strategy_v3.py:353` falls back to `d.close` when the
    # panel carries no `adj_*` columns (legacy/baseline-parity panels), in which
    # case both domains coincide and K would in fact evaluate correctly — yet the
    # guard still raises a "mixing two price domains" error. Latent today (the live
    # panel always carries adj columns), but it is the same declared-vs-effective
    # confusion this raise exists to police. Keying on the effective source would
    # require plumbing it through this evaluator's scalar interface (it currently
    # receives only `bar` + `ind` and has no way to see which source fed
    # `signal_close`); left as a precise note rather than an interface change.
    if params["require_intraday_reversal"] and params["signal_price_domain"] == "adj":
        raise ValueError(
            "Gate K (require_intraday_reversal=True) is enabled while the "
            "DECLARED signal_price_domain='adj': K compares the adjusted "
            "`signal_close` against the RAW bar high/low/open, mixing two price "
            "domains (CLAUDE.md §3) and collapsing K to a no-op. This preset "
            "CANNOT run as configured. Do NOT 'fix' it by switching to "
            "signal_price_domain='raw' — that re-introduces the §3 violation "
            "that makes gate A a silent no-op. K must be re-derived on a single "
            "price domain before it can be enabled (§0 fail-fast)."
        )

    checks: dict[str, bool] = {}

    def fail(tag: str) -> ConditionResult:
        checks[tag] = False
        return ConditionResult(False, tag, checks)

    def ok(tag: str) -> None:
        checks[tag] = True

    # ---- J: SL cooldown (must stay first — cheapest, and blocks everything)
    if params["sl_cooldown_days"] > 0 and last_sl_date is not None:
        days_since = (bar.date - last_sl_date).days
        if days_since < params["sl_cooldown_days"]:
            return fail("J")
    if params["sl_cooldown_days"] > 0:
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
        if params["signal_price_domain"] == "adj"
        else float(bar.close)
    )
    # No NaN check on close_v here — the source method has none, and none is
    # reachable: PctChg.next() emits NaN whenever the current bar's price is NaN
    # on the same adj_close_src, so a NaN signal_close is already rejected at
    # gate C. Adding a guard here would be a semantic delta from the engine
    # (see Fix 1 in the Task 2 report), and a guard present on one side only is
    # exactly where a real divergence can hide later.
    if params["a_condition"] == "cascade_price":
        ma5_v, ma10_v, ma20_v = ind["ma5"], ind["ma10"], ind["ma20"]
        if _is_nan(ma5_v) or _is_nan(ma10_v) or _is_nan(ma20_v):
            return fail("A")
        if not (ma5_v < ma10_v < ma20_v < ma60_v and close_v < ma20_v):
            return fail("A")
    else:
        ratio = ind["below_ma60_ratio_60"]
        if _is_nan(ratio):
            return fail("A")
        if close_v >= ma60_v * (1.0 + params["close_ma60_buffer"]):
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
    d_mode = params["d_mode"]
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
    if params["require_ma20_slope_neg"]:
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
        if params[flag]:
            ret = ind[key]
            if _is_nan(ret) or ret > params[thr]:
                return fail(tag)
            ok(tag)

    # ---- H: amount dry-up
    if params["require_amount_dryup"]:
        ar = ind["amount_ratio"]
        if _is_nan(ar) or ar > params["amount_dryup_threshold"]:
            return fail("H")
        ok("H")

    # ---- I: RSI oversold
    if params["require_rsi_oversold"]:
        rsi_v = ind["rsi"]
        if _is_nan(rsi_v) or rsi_v >= params["rsi_oversold_threshold"]:
            return fail("I")
        ok("I")

    # ---- K: intraday reversal
    if params["require_intraday_reversal"]:
        high_v, low_v = float(bar.high), float(bar.low)
        if high_v <= low_v:
            return fail("K")
        close_pos = (close_v - low_v) / (high_v - low_v)
        if close_pos < params["intraday_reversal_threshold"]:
            return fail("K")
        if params["intraday_reversal_require_close_above_open"] and \
                close_v <= float(bar.open):
            return fail("K")
        ok("K")

    return ConditionResult(True, None, checks)
