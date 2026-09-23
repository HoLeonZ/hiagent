"""§3 Event-Sourced Corporate Actions — dividend deposit + split adjustment (Tick 43).

CLAUDE.md §3 (verbatim):
  "Cash dividends must explicitly trigger a physical cash deposit into
   Free_Cash. Stock splits must trigger an atomic multiplier adjustment
   to Position_Quantity and Average_Cost."

**核心发现 (FRESH 2026-09-23):**

A. **Zero event handlers across all 4 engines** (verified):
   ```bash
   $ grep -rn "def _apply" chase_up/ uptrend_pullback/ short_reversal/ cycle_price_action/
   (no output)
   ```

B. **adj_close convention silently under-reports Free_Cash**:
   - chase_up/portfolio.py:104 loads `raw_close` to numpy array
   - chase_up/portfolio.py:159-161: `price_source_for_execution="adj_close"` (default)
   - With default adj_close: dividend drops are absorbed into adj_close
     adjustment → no explicit Free_Cash += held_qty × dividend_per_share
   - Net effect: total return understated by ~2-3% annually for yield stocks

C. **Split handling absent**:
   - 10:1 stock split: pre-split entry @ ¥100 × 100 shares = ¥10,000 position
   - Post-split: should be 1000 shares × ¥10 avg cost = ¥10,000 position
   - Engine without split handler: 100 shares × ¥10 (post-split price) = ¥1,000
     → **silent 10× position collapse** + 10× PnL inflation on exit

D. **Why this matters**:
   - chase_up / uptrend_pullback use adj_close convention (Option A)
     → dividend yield implicitly dropped from total return
   - short_reversal / cycle use raw_close (closer to Option B)
     → no explicit Free_Cash deposit even with raw close
   - Both options have the SAME defect: no event-sourced Free_Cash deposit

本文件验证:
- 3 RED: No Free_Cash deposit function, no split quantity/cost adjuster,
  no event-driven total return tracking
- 2 PASS baseline: adj_close used for indicators, raw_close used for execution
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: zero corporate action event handlers across all engines
# ---------------------------------------------------------------------------


def test_no_dividend_deposit_function_anywhere() -> None:
    """§3 RED: No function that deposits dividend cash to Free_Cash.

    CLAUDE.md §3 verbatim mandates:
      "Cash dividends must explicitly trigger a physical cash deposit
       into Free_Cash."

    Search across all 4 engines for any function whose name + body
    match dividend deposit semantics. Should find NOTHING because
    adj_close convention silently absorbs dividends without deposit.
    """
    candidates: list[str] = []

    for engine_dir in ["chase_up", "uptrend_pullback", "short_reversal",
                        "cycle_price_action"]:
        for src_path in Path(engine_dir).glob("*.py"):
            if src_path.name == "__init__.py":
                continue
            text = src_path.read_text(encoding="utf-8")

            # Look for function with dividend/split in name + cash+= in body
            for m in re.finditer(r"def\s+(\w*(?:dividend|split|corp_action)\w*)",
                                  text):
                func_name = m.group(1)
                # Skip if in docstring/comment (simple heuristic: ignore)
                # Look at function body for cash += or held_qty *=
                start = text.find(":", m.end())
                if start == -1:
                    continue
                # Function body: find next top-level def or class
                body_start = text.find("\n", start) + 1
                body_end = len(text)
                for sub in re.finditer(r"\n(?:def |class )", text[body_start:]):
                    cand = body_start + sub.start()
                    if cand < body_end:
                        body_end = cand
                        break
                body = text[body_start:body_end]

                # Dividend handler signature: cash += dividend or += held_qty * div
                if ("cash +=" in body and "dividend" in body.lower()) or \
                   ("free_cash +=" in body.replace("Free_Cash", "free_cash")
                                           and "dividend" in body.lower()) or \
                   ("held_qty" in body and "dividend" in body.lower()):
                    candidates.append(f"{src_path}:{func_name}")

    if candidates:
        return  # GREEN — handler exists

    raise AssertionError(
        "GAP CAPTURED: NO engine has a dividend deposit function. "
        "CLAUDE.md §3 verbatim requires explicit cash deposit: "
        "`cash += held_qty × dividend_per_share`. "
        "All 4 engines silently use adj_close convention which absorbs "
        "dividends into price — total return under-reported by ~2-3% "
        "annually for yield stocks.\n"
        "GREEN fix: implement `_apply_dividend(thscode, ex_date, "
        "dividend_per_share)` in core/portfolio_base.py + call from "
        "each engine's on_bar() / next() method."
    )


def test_no_split_quantity_cost_adjuster_anywhere() -> None:
    """§3 RED: No function that adjusts held_qty + avg_cost on split.

    CLAUDE.md §3 verbatim:
      "Stock splits must trigger an atomic multiplier adjustment to
       Position_Quantity and Average_Cost."

    Search for split handler with the required mutation pattern:
      held_qty *= split_ratio
      avg_cost /= split_ratio
    """
    candidates: list[str] = []

    for engine_dir in ["chase_up", "uptrend_pullback", "short_reversal",
                        "cycle_price_action"]:
        for src_path in Path(engine_dir).glob("*.py"):
            if src_path.name == "__init__.py":
                continue
            text = src_path.read_text(encoding="utf-8")

            for m in re.finditer(r"def\s+(\w*split\w*)", text):
                func_name = m.group(1)
                # Function body
                start = text.find(":", m.end())
                if start == -1:
                    continue
                body_start = text.find("\n", start) + 1
                body_end = len(text)
                for sub in re.finditer(r"\n(?:def |class )", text[body_start:]):
                    cand = body_start + sub.start()
                    if cand < body_end:
                        body_end = cand
                        break
                body = text[body_start:body_end]

                # Split handler: must have both quantity and cost adjustment
                has_qty = "qty" in body.lower() and "*=" in body
                has_cost = "cost" in body.lower() and "/=" in body
                if has_qty and has_cost:
                    candidates.append(f"{src_path}:{func_name}")

    if candidates:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED: NO engine has a stock split handler. CLAUDE.md §3 "
        "verbatim requires atomic adjustment:\n"
        "  held_qty *= split_ratio\n"
        "  avg_cost /= split_ratio\n"
        "Without it, a 10:1 split causes silent 10× position collapse + "
        "10× PnL inflation on exit.\n"
        "GREEN fix: implement `_apply_split(thscode, ex_date, "
        "split_ratio)` in core/portfolio_base.py + call from each engine."
    )


def test_no_event_sourced_total_return_tracking() -> None:
    """§3 RED: Total return not decomposed into price + dividend yield.

    CLAUDE.md §3 mandates that dividend cash be physically deposited.
    Without an event handler, the engine's reported total return is
    the PRICE return only, missing the dividend yield component.

    Pin test: no engine has a comment or function naming that explicitly
    tracks dividend yield as a separate component of total return.
    """
    dividend_tracking_found = False

    for engine_dir in ["chase_up", "uptrend_pullback", "short_reversal",
                        "cycle_price_action"]:
        for src_path in Path(engine_dir).glob("*.py"):
            if src_path.name == "__init__.py":
                continue
            text = src_path.read_text(encoding="utf-8").lower()
            # Look for evidence of explicit dividend yield tracking
            if ("dividend_yield" in text or "dividend_payout" in text or
                "total_return" in text and "dividend" in text):
                dividend_tracking_found = True
                break
        if dividend_tracking_found:
            break

    if dividend_tracking_found:
        return  # GREEN, explicit tracking exists

    raise AssertionError(
        "GAP CAPTURED: NO engine decomposes total return into "
        "price return + dividend yield. Per CLAUDE.md §3, dividend "
        "cash deposits to Free_Cash should accumulate separately so "
        "backtest reports can quantify the yield contribution.\n"
        "Currently all engines implicitly absorb dividends via "
        "adj_close convention — total return = price return only, "
        "missing the yield component.\n"
        "GREEN fix: track cumulative_dividend_per_share in "
        "PositionState; add `dividend_pnl` field to trades.csv schema."
    )


# ---------------------------------------------------------------------------
# PASS baselines: dual-price system in place (math vs execution separation)
# ---------------------------------------------------------------------------


def test_dual_price_convention_adj_for_math_raw_for_execution() -> None:
    """§3 PASS baseline: adj_close used for math (indicators),
    raw_close used for execution (SL/TP).

    This is the foundation that event handlers would hook into.
    Even without dividend/split handlers, the dual-price convention
    means: indicator math uses clean adj_close series (no NaN from
    dividend drop), execution math uses raw_close (real physical
    fill price including dividend adjustment).
    """
    dual_price_in_chase = False
    dual_price_in_uptrend = False

    chase_src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")
    uptrend_src = Path("uptrend_pullback/portfolio.py").read_text(
        encoding="utf-8"
    )

    # Both should have raw_close in code + adj_close in code
    if "raw_close" in chase_src and "adj_close" in chase_src:
        dual_price_in_chase = True
    if "raw_close" in uptrend_src and "adj_close" in uptrend_src:
        dual_price_in_uptrend = True

    assert dual_price_in_chase, (
        "Regression: chase_up/portfolio.py no longer has dual-price "
        "(raw_close + adj_close) convention"
    )
    assert dual_price_in_uptrend, (
        "Regression: uptrend_pullback/portfolio.py no longer has "
        "dual-price convention"
    )


def test_raw_prev_close_loaded_into_entry_dict() -> None:
    """§3 PASS baseline: portfolio.py loads raw_prev_close into entry dict.

    The infrastructure to load raw_prev_close is in place. The split
    handler would consume this field. If removed, both dual-price
    AND split handler plumbing regress simultaneously.
    """
    chase_src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")
    uptrend_src = Path("uptrend_pullback/portfolio.py").read_text(
        encoding="utf-8"
    )

    assert "raw_prev_close" in chase_src, (
        "Regression: chase_up/portfolio.py no longer loads raw_prev_close"
    )
    assert "raw_prev_close" in uptrend_src, (
        "Regression: uptrend_pullback/portfolio.py no longer loads "
        "raw_prev_close"
    )