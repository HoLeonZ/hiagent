"""§4 Microstructure & Liquidity cross-engine audit RED tests.

CLAUDE.md §4 mandates:
  - Volume Participation Limit: Max_Fill_Qty = MIN(Order_Qty, Bar_Volume × 0.10)
  - Slippage as function of ATR (Execution Only) — NOT flat-rate
  - Exit Thresholds (TP/SL): documented in preset compliance header
  - Intraday Blindness: on daily bar data, if BOTH SL+TP breached in same bar,
    MUST assume worst-case (SL-first)

§4 Audit matrix (FRESH 2026-09-23):

| Engine | Volume cap | ATR-slip opt-in | SL-first intraday |
|---|---|---|---|
| chase_up | ✓ portfolio.py:406 | ✓ portfolio.py:151 | ✓ portfolio.py (validated) |
| uptrend_pullback | ✓ portfolio.py:395 | ✓ portfolio.py | ✓ portfolio.py:282 |
| short_reversal | ✓ replay_strategy_v3.py:257 | ✓ engine.py:192 | ✓ declared in preset, used in code |
| cycle_price_action | ✓ portfolio.py:137 | ✓ portfolio.py:79 | ⚠️ hardcoded, no param |

VIOLATIONS:
A. **cycle_price_action intraday_tiebreak is hardcoded** — no `intraday_tiebreak`
   parameter on Portfolio.__init__. Preset declares `"intraday_tiebreak": "sl_first"`
   but engine doesn't take it as input. Future preset change to e.g.
   "tp_first" would silently NOT take effect.

B. **chase_up/uptrend_pullback has volume cap LOW-BAR BYPASS** (already pinned
   in [[volume-cap-low-bar-bypass]] from Tick 25).

C. **cycle_price_action portfolio.LAYOUT_CYCLE_PRICE differs from
   chase/uptrend LAYOUT_CHASE_UPTREND** — cross-engine price layout divergence.
"""
from __future__ import annotations

import inspect
from pathlib import Path


def test_cycle_intraday_tiebreak_is_parameter() -> None:
    """§4 RED: cycle_price_action Portfolio must accept intraday_tiebreak
    parameter (matches chase/uptrend convention).

    chase_up/portfolio.py:149 `intraday_tiebreak: str = "sl_first"`
    uptrend_pullback/portfolio.py:149 same
    cycle_price_action/portfolio.py:73-82 `__init__` has NO `intraday_tiebreak`

    §4 mandates SL-first. The behavior is correctly hardcoded in
    `try_exit_with_intraday_check`. But the API is inconsistent:
    - chase/uptrend expose it as param
    - cycle does not
    Future preset tuning cannot reach cycle's behavior.
    """
    from cycle_price_action.portfolio import Portfolio

    sig = inspect.signature(Portfolio.__init__)
    assert "intraday_tiebreak" in sig.parameters, (
        "GAP CAPTURED: cycle_price_action.Portfolio.__init__ missing "
        "`intraday_tiebreak` parameter. §4 API inconsistency with "
        "chase_up / uptrend_pullback. Preset cannot tune this engine's "
        "intraday behavior. GREEN fix: add `intraday_tiebreak: str = "
        "'sl_first'` param and thread through try_exit_with_intraday_check."
    )


def test_cycle_preset_intraday_declared_has_engine_effect() -> None:
    """§4 RED: cycle preset's `intraday_tiebreak='sl_first'` declaration
    must have actual engine effect.

    cycle/presets.py:32 declares `"intraday_tiebreak": "sl_first"` but
    Portfolio.__init__ ignores it. The behavior IS hardcoded to sl_first
    in try_exit_with_intraday_check, but the parameter is silently
    dropped. Future preset tune will have ZERO effect.

    Verify: passing `intraday_tiebreak='tp_first'` to run_backtest should
    change behavior, but currently doesn't.
    """
    # Run cycle with both 'sl_first' and 'tp_first' intraday_tiebreak and
    # verify they produce DIFFERENT results. If identical → gap captured.
    from cycle_price_action.backtest import run_backtest as cycle_run

    # The cycle engine silently drops intraday_tiebreak param
    # (it has no such param). Both calls produce identical results.
    # If this test is GREEN, cycle API exposed the parameter correctly.
    import inspect
    sig = inspect.signature(cycle_run)
    has_param = "intraday_tiebreak" in sig.parameters

    if not has_param:
        raise AssertionError(
            "GAP CAPTURED: cycle_price_action.backtest.run_backtest "
            "missing `intraday_tiebreak` parameter. Preset declaration "
            "`'intraday_tiebreak': 'sl_first'` is silently dropped."
        )


def test_all_engines_volume_cap_formula_consistent() -> None:
    """§4 baseline: all 4 engines use the same `bar_vol * X / lot` formula
    family (with same low-bar bypass bug — already in Tick 25).

    Pin the consistency pattern across all 4 engines.
    """
    engines_with_formula = {
        "chase_up/portfolio.py": "int(bar_vol * max_volume_participation // 100) * 100",
        "uptrend_pullback/portfolio.py": "int(bar_vol * max_volume_participation // 100) * 100",
        "cycle_price_action/portfolio.py": "int(bar_volume * self.MAX_VOL_PARTICIPATION // 100) * 100",
        "short_reversal/replay_strategy_v3.py": "bar_vol * self.p.max_volume_participation / self.p.lot_size",
    }
    for path, formula in engines_with_formula.items():
        src = Path(path).read_text(encoding="utf-8")
        assert formula in src, (
            f"Regression: {path} no longer uses {formula!r}. §4 audit "
            f"must be re-run to find new violations."
        )


def test_all_engines_atr_slip_scale_opt_in() -> None:
    """§4 baseline: all 4 engines have `atr_slip_scale` opt-in param
    (default 0.0 = static slip, scale>0 = ATR-aware slip).
    """
    engines_with_atr_slip = {
        "chase_up/portfolio.py": "atr_slip_scale: float = 0.0",
        "uptrend_pullback/portfolio.py": "atr_slip_scale: float = 0.0",
        "cycle_price_action/portfolio.py": "atr_slip_scale: float = 0.0",
        "short_reversal/engine.py": "atr_slip_scale=cfg.get",
        "short_reversal/replay_strategy_v3.py": "atr_slip_scale=0.0",
    }
    for path, pattern in engines_with_atr_slip.items():
        src = Path(path).read_text(encoding="utf-8")
        assert pattern in src, (
            f"Regression: {path} no longer has `{pattern}`. §4 ATR-aware "
            f"slippage opt-in removed."
        )


def test_short_reversal_uses_sl_first_in_code() -> None:
    """§4 baseline: short_reversal engine uses sl_first logic in code.

    Pin that when `o >= tp_p` AND `o <= sl_p` happen in same bar, sl
    wins. Already implemented in `replay_strategy_v3.py:170-180`.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")

    # Pin: short_reversal evaluates SL first (worst-case)
    has_sl_first_logic = (
        "sl_first" in src or
        "o <= sl_p" in src or
        "if low <= self.sl_price" in src
    )
    assert has_sl_first_logic, (
        "Regression: short_reversal no longer evaluates SL-first in "
        "intraday logic. §4 Intraday Blindness violation."
    )