"""§2 NAV Gate cycle_price_action audit (Tick 46).

CLAUDE.md §2 (verbatim):
  "All-In Sizing Policy: Every entry is sized at 100% of available cash
   for that trade slot... Margin blowout protection still applies:
   `cost > cash` must reject the trade (no leverage) and NAV-floor
   cash gates remain valid for new entries."

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[cycle-nav-gate-missing]]:**

A. **cycle_price_action has ZERO NAV gate infrastructure** (verified):
   ```bash
   $ grep -n "initial_capital" cycle_price_action/*.py
   (no output)
   ```

B. **Other 3 engines have NAV gate**:
   - chase_up/portfolio.py:64 `NAV_GATE_RATIO = 0.05`
   - chase_up/portfolio.py:143 `initial_capital: float = 1_000_000.0` param
   - chase_up/portfolio.py:338-339 nav gate check:
     ```python
     if nav_now < initial_capital * NAV_GATE_RATIO:
         # reject new entry
     ```
   - uptrend_pullback/portfolio.py:48 NAV_GATE_RATIO + same param + check
   - short_reversal/replay_strategy_v3.py:64 min_cash_ratio=0.05 (different name, same logic)

C. **cycle_price_action/portfolio.py:73-82 `__init__` signature**:
   ```python
   def __init__(
       self,
       cash: float,
       atr_slip_scale: float = 0.0,
   ) -> None:
       self.cash = float(cash)
       self.atr_slip_scale = atr_slip_scale
   ```
   - NO `initial_capital` param
   - NO NAV_GATE_RATIO constant
   - NO nav_gate check in try_enter

D. **Why this matters**:
   - Cycle can keep opening new positions even after catastrophic drawdown
   - chase_up + uptrend_pullback stop opening new positions when NAV
     drops below 5% of initial capital (catastrophic loss protection)
   - Cycle continues trading through blowup → over-trading losses
   - Inconsistent risk management across engine portfolio

E. **Numeric impact**:
   - Cycle has no test coverage (no backtest output yet, fail-fast blocks)
   - Once cycle produces output, results will diverge from
     chase_up/uptrend under identical market scenarios
   - Specifically in catastrophic drawdown regimes, cycle will show
     worse (more negative) Sharpe because it keeps entering

本文件验证:
- 3 RED: cycle lacks initial_capital param, lacks NAV_GATE_RATIO constant,
  lacks nav gate check in try_enter
- 2 PASS baseline: other 3 engines fully integrated (chase/uptrend/short)
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: cycle_price_action lacks §2 NAV gate infrastructure
# ---------------------------------------------------------------------------


def test_cycle_portfolio_lacks_initial_capital_param() -> None:
    """§2 RED: cycle_price_action/portfolio.py __init__ lacks initial_capital.

    chase_up/portfolio.py:143 has `initial_capital: float = 1_000_000.0`
    in `__init__`. cycle/portfolio.py:73-82 has only `cash` + `atr_slip_scale`.

    Without initial_capital, NAV gate calculation has no anchor (gate ratio
    needs a baseline to compare current NAV against).
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    if "initial_capital" in src:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py __init__ "
        "lacks `initial_capital` parameter. CLAUDE.md §2 NAV gate "
        "requires initial_capital to compute gate threshold "
        "(nav_now < initial_capital × NAV_GATE_RATIO).\n"
        "Compare chase_up/portfolio.py:143:\n"
        "  initial_capital: float = 1_000_000.0,\n"
        "GREEN fix: add `initial_capital: float = 1_000_000.0` to "
        "cycle_price_action/portfolio.py:73-82 __init__ signature."
    )


def test_cycle_portfolio_lacks_nav_gate_ratio_constant() -> None:
    """§2 RED: cycle_price_action/portfolio.py lacks NAV_GATE_RATIO constant.

    chase_up/portfolio.py:64 + uptrend_pullback/portfolio.py:48 define
    `NAV_GATE_RATIO = 0.05`. cycle has no equivalent.

    Without the ratio, even if initial_capital is added, no gate threshold
    can be computed.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    if "NAV_GATE_RATIO" in src or "nav_gate_ratio" in src:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py lacks "
        "`NAV_GATE_RATIO` constant. CLAUDE.md §2 mandates 5% NAV floor "
        "gate for new entries.\n"
        "Compare chase_up/portfolio.py:64:\n"
        "  NAV_GATE_RATIO = 0.05\n"
        "GREEN fix: add `NAV_GATE_RATIO = 0.05` to module-level constants "
        "in cycle_price_action/portfolio.py."
    )


def test_cycle_try_enter_lacks_nav_gate_check() -> None:
    """§2 RED: cycle_price_action try_enter() lacks nav_gate check.

    chase_up/portfolio.py:338-339:
      if nav_now < initial_capital * NAV_GATE_RATIO:
          # reject new entry

    cycle try_enter() at line 106 has:
      - Line 118: `if price <= 0: return None` (NaN check)
      - Line 136: volume cap
      - **NO nav gate check**

    Cycle keeps opening new positions through catastrophic drawdowns.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    # Extract try_enter body
    func_start = src.find("def try_enter(")
    if func_start == -1:
        return  # structure changed

    body_start = src.find(":\n", func_start) + 2
    body_end = len(src)
    for m in re.finditer(r"\n    def ", src[body_start:]):
        candidate = body_start + m.start() + 1
        if candidate < body_end:
            body_end = candidate
            break
    body = src[body_start:body_end]

    has_nav_gate = (
        "nav_gate" in body or
        "NAV_GATE" in body or
        ("initial_capital" in body and "cash +=" in body)  # implicit
    )

    if has_nav_gate:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py try_enter() "
        "lacks NAV gate check. CLAUDE.md §2 NAV floor mandate: when "
        "nav_now < initial_capital × NAV_GATE_RATIO, reject new entries.\n"
        "Per [[cycle-nav-gate-missing]], this is the ONLY engine without "
        "the gate — chase_up + uptrend_pullback + short_reversal all "
        "integrated.\n"
        "GREEN fix: add at start of try_enter() (after price > 0 check):\n"
        "  if hasattr(self, 'initial_capital') and hasattr(self, 'NAV_GATE_RATIO'):\n"
        "      nav_now = self.cash + (self._pos.mark_to_market if self._pos else 0)\n"
        "      if nav_now < self.initial_capital * self.NAV_GATE_RATIO:\n"
        "          return None  # reject catastrophic drawdown entries"
    )


# ---------------------------------------------------------------------------
# PASS baselines: other 3 engines have NAV gate
# ---------------------------------------------------------------------------


def test_chase_up_nav_gate_fully_integrated() -> None:
    """§2 PASS baseline: chase_up/portfolio.py FULLY integrated NAV gate.

    chase_up/portfolio.py:64 NAV_GATE_RATIO + :143 initial_capital param +
    :338-339 nav gate check. Pin compliance.
    """
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")

    assert "NAV_GATE_RATIO" in src, (
        "Regression: chase_up/portfolio.py lost NAV_GATE_RATIO constant"
    )
    assert "initial_capital" in src, (
        "Regression: chase_up/portfolio.py lost initial_capital param"
    )
    assert "nav_now < initial_capital * NAV_GATE_RATIO" in src or \
           "nav < initial_capital * NAV_GATE_RATIO" in src, (
        "Regression: chase_up/portfolio.py lost nav gate check"
    )


def test_uptrend_pullback_nav_gate_fully_integrated() -> None:
    """§2 PASS baseline: uptrend_pullback/portfolio.py FULLY integrated."""
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")

    assert "NAV_GATE_RATIO" in src, (
        "Regression: uptrend_pullback/portfolio.py lost NAV_GATE_RATIO"
    )
    assert "initial_capital" in src, (
        "Regression: uptrend_pullback/portfolio.py lost initial_capital"
    )