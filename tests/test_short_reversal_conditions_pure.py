"""Pure condition evaluator: unit tests, no DB, no backtrader."""
from __future__ import annotations

import math
from datetime import date

import pytest

from short_reversal.conditions import BarSnapshot, check_conditions

BASE_PARAMS = {
    "liq_low": 3e7, "liq_high": 3e8,
    "up_streak_low": 3, "up_streak_high": 10,
    "pct_chg_low": 0.03, "pct_chg_high": 0.10,
    "a_condition": "default", "below_ratio_60": 0.2, "close_ma60_buffer": 0.07,
    "d_mode": "converge_strict",
    "signal_price_domain": "adj",
    "sl_cooldown_days": 0,
    "require_ma20_slope_neg": False, "ma20_slope_threshold": 0.0,
    "require_weak_1m": False, "weak_1m_threshold": 0.0,
    "require_weak_3m": False, "weak_3m_threshold": 0.0,
    "require_weak_6m": False, "weak_6m_threshold": 0.0,
    "require_amount_dryup": False, "amount_dryup_threshold": 0.0,
    "require_rsi_oversold": False, "rsi_oversold_threshold": 30.0,
    "require_intraday_reversal": False, "intraday_reversal_threshold": 0.5,
    "intraday_reversal_require_close_above_open": True,
}

def _ind(**over):
    """A snapshot that passes every base condition; override per test.

    The MACD values are chosen so the D gate passes under the legs' actual
    d_mode, 'converge_strict', which requires |bar| < |prev_bar| * 0.5:
        bar      = -0.30 - (-0.20) = -0.10  -> |bar|      = 0.10
        prev_bar = -0.80 - (-0.20) = -0.60  -> |prev_bar| = 0.60
        0.10 < 0.60 * 0.5 = 0.30  -> D passes
    Do NOT "simplify" prev_dif/prev_dea to near dif/dea: |prev_bar| would
    collapse and D would fail, silently breaking every test that expects the
    base fixture to pass all gates.
    """
    base = {
        "am60": 5e7, "ma5": 9.0, "ma10": 9.5, "ma20": 10.0, "ma60": 11.0,
        "signal_close": 10.4, "below_ma60_ratio_60": 0.9,
        "up_streak": 4, "pct_chg": 0.05,
        "macd_dif": -0.30, "macd_dea": -0.20,
        "macd_prev_dif": -0.80, "macd_prev_dea": -0.20,
        "ma20_slope_5d": -0.01,
        "return_1m": -0.08, "return_3m": -0.20, "return_6m": -0.30,
        "amount_ratio": 0.5, "rsi": 25.0,
    }
    base.update(over)
    return base

def _bar(**over):
    kw = {"open": 10.2, "high": 10.8, "low": 10.0, "close": 10.4,
          "date": date(2026, 6, 1)}
    kw.update(over)
    return BarSnapshot(**kw)

def test_all_base_conditions_pass():
    r = check_conditions(_bar(), _ind(), BASE_PARAMS)
    assert r.passed is True
    assert r.failed_at is None

def test_liquidity_gate_rejects_low_am60():
    r = check_conditions(_bar(), _ind(am60=1e7), BASE_PARAMS)
    assert r.passed is False and r.failed_at == "E"

def test_a_condition_uses_signal_close_not_bar_close():
    """§3: with signal_price_domain='adj' the A gate reads ind['signal_close']."""
    # bar.close (raw) is BELOW ma60*1.07, but signal_close (adj) is ABOVE -> reject
    r = check_conditions(_bar(close=10.0), _ind(signal_close=12.0), BASE_PARAMS)
    assert r.passed is False and r.failed_at == "A"
    # flip: bar.close above, signal_close below -> A passes
    r2 = check_conditions(_bar(close=20.0), _ind(signal_close=10.4), BASE_PARAMS)
    assert r2.checks.get("A") is True

def test_close_ma60_buffer_is_honoured():
    """The A gate is `close_v >= ma60 * (1 + close_ma60_buffer)`, buffer 0.07,
    ma60 11.0 -> threshold 11.77."""
    # 11.8 >= 11.77 -> rejected at A
    r = check_conditions(_bar(), _ind(signal_close=11.8), BASE_PARAMS)
    assert r.passed is False and r.failed_at == "A"
    # 11.5 is ABOVE ma60 but inside the buffer -> A passes (asserted via checks,
    # not via .passed, because later gates are not under test here)
    r2 = check_conditions(_bar(), _ind(signal_close=11.5), BASE_PARAMS)
    assert r2.checks.get("A") is True

def test_nan_signal_close_rejects():
    """A NaN signal_close is rejected — but at gate C, not gate A.

    The real adapter CANNOT produce `signal_close=nan` with a non-NaN `pct_chg`:
    `PctChg.next()` (indicators_bt.py:26-38) emits NaN whenever the current bar's
    price is NaN on the same `adj_close_src`, and that line is what feeds
    `_signal_close`. So the fixture must set both, and the rejection must be
    attributed to C. Setting them independently would test a state the engine
    cannot reach, and would only pass if a non-source A-gate guard existed.
    """
    r = check_conditions(
        _bar(), _ind(signal_close=math.nan, pct_chg=math.nan), BASE_PARAMS
    )
    assert r.passed is False
    assert r.failed_at == "C"

def test_d_mode_converge_strict_requires_halving():
    # |bar| = 0.10 ; |prev_bar| = 0.04 -> 0.04*0.5 = 0.02 ; 0.10 > 0.02 -> reject
    ind = _ind(macd_dif=-0.30, macd_dea=-0.20, macd_prev_dif=-0.26, macd_prev_dea=-0.22)
    assert check_conditions(_bar(), ind, BASE_PARAMS).failed_at == "D"
    # widening prev so that 0.10 < |prev_bar|*0.5 -> pass
    ind2 = _ind(macd_dif=-0.30, macd_dea=-0.20, macd_prev_dif=-0.80, macd_prev_dea=-0.20)
    assert check_conditions(_bar(), ind2, BASE_PARAMS).passed is True

def test_each_optional_gate_is_off_by_default():
    """Optional gates must be inert unless params enable them."""
    r = check_conditions(_bar(), _ind(rsi=90.0, amount_ratio=99.0,
                                     return_1m=0.5, ma20_slope_5d=5.0), BASE_PARAMS)
    assert r.passed is True

def test_optional_gates_fire_when_enabled():
    p = dict(BASE_PARAMS, require_ma20_slope_neg=True)
    assert check_conditions(_bar(), _ind(ma20_slope_5d=0.5), p).failed_at == "F"
    p = dict(BASE_PARAMS, require_rsi_oversold=True)
    assert check_conditions(_bar(), _ind(rsi=90.0), p).failed_at == "I"
    p = dict(BASE_PARAMS, require_amount_dryup=True)
    assert check_conditions(_bar(), _ind(amount_ratio=99.0), p).failed_at == "H"

def test_sl_cooldown_blocks_all_entries():
    p = dict(BASE_PARAMS, sl_cooldown_days=5)
    r = check_conditions(_bar(date=date(2026, 6, 3)), _ind(), p,
                         last_sl_date=date(2026, 6, 1))
    assert r.passed is False and r.failed_at == "J"

def test_checks_dict_reports_only_evaluated_conditions():
    """Short-circuit order J,E,A,B,C,D,... must be preserved.

    `checks` records only conditions actually EVALUATED. With the base params
    sl_cooldown_days == 0, the J gate is skipped entirely, so a failure at E
    leaves checks == {"E"} — J must NOT appear.
    """
    r = check_conditions(_bar(), _ind(am60=1e7), BASE_PARAMS)
    assert set(r.checks) == {"E"}


def test_checks_reports_j_when_cooldown_is_enabled():
    """J is evaluated (and therefore recorded) only when the gate is active."""
    p = dict(BASE_PARAMS, sl_cooldown_days=5)
    # inside the cooldown -> J fails and short-circuits every later gate
    r = check_conditions(_bar(date=date(2026, 6, 3)), _ind(), p,
                         last_sl_date=date(2026, 6, 1))
    assert set(r.checks) == {"J"}
    assert r.failed_at == "J"
    # outside the cooldown -> J recorded True and evaluation continues to the end
    r2 = check_conditions(_bar(date=date(2026, 6, 10)), _ind(), p,
                          last_sl_date=date(2026, 6, 1))
    assert r2.checks.get("J") is True
    assert r2.passed is True


def test_param_defaults_match_the_strategy_exactly():
    """CONDITION_PARAM_DEFAULTS is hand-maintained. Lock it to the strategy's
    declared params so the two cannot silently diverge, and so a key added to
    the strategy but forgotten here fails HERE rather than in production.

    Why this matters more than it looks: the adapter builds `params` with
    `getattr(self.p, k) for k in CONDITION_PARAM_KEYS`. A key in the tuple that
    the strategy does not declare raises AttributeError for EVERY preset — all
    75 of them — not just the one being run.
    """
    from short_reversal.conditions import CONDITION_PARAM_DEFAULTS
    from short_reversal.replay_strategy_v3 import Phase3V3Strategy

    for key, default in CONDITION_PARAM_DEFAULTS.items():
        assert hasattr(Phase3V3Strategy.params, key), (
            f"{key} is in CONDITION_PARAM_DEFAULTS but is not a declared "
            f"parameter of Phase3V3Strategy"
        )
        actual = getattr(Phase3V3Strategy.params, key)
        assert type(actual) is type(default) and actual == default, (
            f"{key}: strategy default {actual!r} != conditions default {default!r}"
        )


def test_param_keys_and_defaults_describe_the_same_set():
    from short_reversal.conditions import (
        CONDITION_PARAM_DEFAULTS, CONDITION_PARAM_KEYS,
    )
    assert set(CONDITION_PARAM_KEYS) == set(CONDITION_PARAM_DEFAULTS)


def test_check_conditions_raises_on_a_missing_param_instead_of_defaulting():
    """The fail-fast property the `.get()`-free body buys us. A consumer that
    omits a key must fail loudly: `intraday_reversal_require_close_above_open`
    defaults to True, so a silent fallback would ENABLE that gate rather than
    disable it — the opposite of a safe default."""
    from short_reversal.conditions import CONDITION_PARAM_KEYS

    partial = {k: BASE_PARAMS[k] for k in CONDITION_PARAM_KEYS if k != "d_mode"}
    with pytest.raises(KeyError):
        check_conditions(_bar(), _ind(), partial)

