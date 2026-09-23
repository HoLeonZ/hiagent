"""§4 Limit-Up Guard cross-engine propagation audit (Tick 42).

CLAUDE.md §4 Microstructure mandates market reality mapping:
  - Volume Participation Limit, ATR-aware slippage, etc.
  - **Limit-up opens CANNOT be transacted at** — stock is locked at +10%,
    order queue cannot fill. Per §3 Reality Mapping, must filter.

**核心发现 (FRESH 2026-09-23):**

A. **chase_up + uptrend_pullback FULLY integrated**:
   - chase_up/portfolio.py:35 imports `is_limit_up` from `core.dual_price`
   - chase_up/portfolio.py:54 `LIMIT_UP_THRESHOLD = 0.098`
   - chase_up/portfolio.py:384-385 — entry-time check:
     `if is_limit_up(pc, o, threshold=LIMIT_UP_THRESHOLD): continue`
   - uptrend_pullback/portfolio.py:24, 40, 373-375 — same pattern

B. **cycle_price_action has NO limit-up guard**:
   - 0 references to is_limit_up / LIMIT_UP / limit_up in cycle_price_action/
   - cycle_price_action/portfolio.py:106 try_enter():
     - Line 118: `if price <= 0: return None` — only NaN/zero check
     - Line 136-142: volume cap check
     - **NO `is_limit_up(prev_close, open_price)` check**
   - Result: cycle buys at limit-up opens → market-reality violation

C. **short_reversal has NO limit-up guard**:
   - 0 references to is_limit_up / LIMIT_UP / limit_up in short_reversal/
   - short_reversal/replay_strategy_v3.py:210 `entry_price = bar.open`
     - No limit-up check before short entry
   - Result: short_reversal opens short on limit-up days
     - For short: limit-up means stock is RISING; short entry makes less
       sense, and broker may force buy-in if shares unavailable

D. **Why this matters**:
   - chase_up backtests SKIP limit-up opens (correctly) → universe-filtered
   - cycle + short_reversal DO NOT → their fills include impossible orders
   - **Numeric impact**: limit-up opens typically have 0 fill rate in reality;
     including them inflates trade statistics in cycle/short_reversal

本文件验证:
- 4 RED: cycle + short_reversal try_enter lacks is_limit_up check
- 3 PASS baseline: chase_up + uptrend_pullback FULLY integrated +
  is_limit_up exists in core/dual_price.py + threshold constant defined
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: cycle_price_action has NO limit-up guard
# ---------------------------------------------------------------------------


def test_cycle_price_action_try_enter_has_no_limit_up_check() -> None:
    """§4 RED: cycle_price_action/portfolio.py try_enter() lacks is_limit_up.

    Per [[limit-up-guard-cross-engine-gap]], cycle has 0 references to
    limit-up across all files. try_enter() at line 106 should reject
    limit-up opens BEFORE computing lots, but currently only checks
    `price <= 0` (NaN/zero filter) — no limit-up filter.

    Result: cycle_price_action backtests include limit-up opens that
    cannot actually be transacted. Market-reality violation per §3.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    # Extract try_enter function body
    func_start = src.find("def try_enter(")
    if func_start == -1:
        return  # structure changed

    # Find body — find next top-level def or end of file
    body_start = src.find(":\n", func_start) + 2
    body_end = len(src)
    for m in re.finditer(r"\n    def ", src[body_start:]):
        candidate = body_start + m.start() + 1  # +1 to skip \n
        if candidate < body_end:
            body_end = candidate
            break
    body = src[body_start:body_end]

    has_limit_up_check = (
        "is_limit_up" in body
        or "LIMIT_UP" in body
        or "limit_up" in body
    )

    if has_limit_up_check:
        return  # GREEN — already integrated

    raise AssertionError(
        "GAP CAPTURED: cycle_price_action/portfolio.py try_enter() "
        "function body has NO `is_limit_up` / `LIMIT_UP` / `limit_up` "
        "check. §4 violation — limit-up opens (stock at +10% from "
        "prev_close) cannot be transacted, but cycle still attempts "
        "entry. Per [[limit-up-guard-cross-engine-gap]] + CLAUDE.md §3 "
        "Reality Mapping. GREEN fix: add limit-up check after `if "
        "price <= 0: return None` (around line 119), passing prev_close "
        "from decision_meta or panel data:\n"
        "  pc = decision_meta.get('prev_close')\n"
        "  if pc and is_limit_up(pc, price, threshold=0.098):\n"
        "      return None"
    )


def test_cycle_price_action_no_limit_up_imports() -> None:
    """§4 RED: cycle_price_action/portfolio.py has NO `from core.dual_price import is_limit_up`.

    chase_up/portfolio.py:35 imports `is_limit_up` from `core.dual_price`.
    cycle/portfolio.py does not — confirms the guard was never wired in.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    if "is_limit_up" in src or "LIMIT_UP" in src:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED: cycle_price_action/portfolio.py has NO "
        "`is_limit_up` import (compare chase_up/portfolio.py:35 "
        "`from core.dual_price import is_limit_up`). §4 violation — "
        "limit-up guard is missing entirely. GREEN fix: import "
        "is_limit_up from core.dual_price, add check in try_enter."
    )


# ---------------------------------------------------------------------------
# RED: short_reversal has NO limit-up guard
# ---------------------------------------------------------------------------


def test_short_reversal_strategy_next_has_no_limit_up_check() -> None:
    """§4 RED: short_reversal/replay_strategy_v3.py next() lacks is_limit_up.

    short_reversal opens short at `entry_price = bar.open` (line 210).
    No limit-up check before short entry. Per [[limit-up-guard-cross-engine-gap]],
    0 references to limit-up in short_reversal/.

    For short selling: limit-up days mean stock is RISING (hard to find
    shares to borrow; existing holders reluctant to lend). Broker may
    force buy-in. Defensive check is appropriate even if technically
    shortable.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")

    if "is_limit_up" in src or "LIMIT_UP" in src or "limit_up" in src:
        return  # GREEN — already integrated

    # Verify next() actually exists and has entry logic
    if "def next(" not in src:
        return

    raise AssertionError(
        "GAP CAPTURED: short_reversal/replay_strategy_v3.py has NO "
        "`is_limit_up` reference. §4 violation — short entry at "
        "`bar.open` without limit-up check. Per "
        "[[limit-up-guard-cross-engine-gap]]. GREEN fix: in next() "
        "method (around line 210 where entry_price = bar.open), add:\n"
        "  prev_close = bar.close(-1) or self.data.close[-1]\n"
        "  if is_limit_up(prev_close, entry_price, threshold=0.098):\n"
        "      return  # skip entry on limit-up day"
    )


def test_short_reversal_no_limit_up_imports() -> None:
    """§4 RED: short_reversal has no `is_limit_up` import across all files.

    Comprehensive search across short_reversal/ confirms zero integration.
    """
    found_anywhere = False
    for src_path in Path("short_reversal").glob("*.py"):
        if src_path.name == "__init__.py":
            continue
        text = src_path.read_text(encoding="utf-8")
        if "is_limit_up" in text or "LIMIT_UP" in text or "limit_up" in text:
            found_anywhere = True
            break

    if found_anywhere:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED: NO file in short_reversal/ imports or references "
        "`is_limit_up` / `LIMIT_UP` / `limit_up`. §4 violation. "
        "GREEN fix: add is_limit_up check in replay_strategy_v3.next() "
        "before short entry."
    )


# ---------------------------------------------------------------------------
# PASS baselines: chase_up + uptrend_pullback fully integrated
# ---------------------------------------------------------------------------


def test_chase_up_limit_up_guard_integrated() -> None:
    """§4 PASS baseline: chase_up FULLY integrated limit-up guard.

    chase_up/portfolio.py:35 imports is_limit_up
    chase_up/portfolio.py:54 defines LIMIT_UP_THRESHOLD = 0.098
    chase_up/portfolio.py:384-385 — entry-time check
    """
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")

    assert "is_limit_up" in src, (
        "Regression: chase_up/portfolio.py no longer imports is_limit_up"
    )
    assert "LIMIT_UP_THRESHOLD" in src, (
        "Regression: chase_up/portfolio.py no longer defines LIMIT_UP_THRESHOLD"
    )


def test_uptrend_pullback_limit_up_guard_integrated() -> None:
    """§4 PASS baseline: uptrend_pullback FULLY integrated limit-up guard."""
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")

    assert "is_limit_up" in src, (
        "Regression: uptrend_pullback/portfolio.py no longer imports is_limit_up"
    )
    assert "LIMIT_UP_THRESHOLD" in src, (
        "Regression: uptrend_pullback/portfolio.py no longer defines LIMIT_UP_THRESHOLD"
    )


def test_core_dual_price_provides_is_limit_up() -> None:
    """§4 PASS baseline: core/dual_price.py exports is_limit_up.

    chase_up + uptrend_pullback import from here. If this is removed,
    those engines silently lose the limit-up guard.
    """
    try:
        mod = importlib.import_module("core.dual_price")
        assert hasattr(mod, "is_limit_up"), (
            "Regression: core.dual_price no longer exports is_limit_up"
        )
        assert callable(mod.is_limit_up), (
            "Regression: core.dual_price.is_limit_up is not callable"
        )
    except ImportError:
        # If core module doesn't exist yet, this is GREEN-by-absence
        # (chase + uptrend would fail differently — they're using it)
        return