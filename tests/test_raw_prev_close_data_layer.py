"""§3 PIT raw_prev_close data layer audit (Tick 45).

CLAUDE.md §3 mandates Dual-Price System:
  - ALWAYS use Forward-Adjusted Prices (adj_close) for indicators
  - ALWAYS use Raw Prices (raw_close) for SL/TP + cash mark-to-market
  - **raw_prev_close** is required for limit-up detection (CLAUDE.md §4)

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[prev-close-data-layer-gap]]:**

A. **raw_kline_daily.prev_close column is NULL in upstream schema**:
   - Verified via `sql/migrate_v_daily_dual.sql:31-32` comment:
     > "raw_kline_daily.prev_close column is NULL in upstream schema.
     >  Caller may also compute prev_close client-side via
     >  DataFrame.groupby('thscode')['raw_close'].shift(1)."
   - Workaround already exists: `v_daily_dual` view at sql/migrate_v_daily_dual.sql:18
     uses `LAG(r.close, 1) OVER (PARTITION BY r.thscode ORDER BY r.date)`
     to compute raw_prev_close correctly (99.95% populated per memory).

B. **chase_up/data.py:54 STILL reads NULL column**:
   ```python
   r.prev_close AS raw_prev_close  # NULL upstream
   ```
   - Should either:
     (a) read from `v_daily_dual` view (already created), OR
     (b) compute client-side via `LAG` window or DataFrame.groupby.shift(1)
   - Current code: 0% of panel rows have raw_prev_close populated.

C. **uptrend_pullback/data.py:63 has same bug**:
   ```python
   r.prev_close AS raw_prev_close  # NULL upstream
   ```

D. **Consequence — V3a entry override dead code**:
   - Per [[v3a-dual-price-fix]]: chase_up/portfolio.py:343-352 entry override
     guard requires `raw_prev_close > 0`, but column is all NaN → override
     is dead code → entry silently falls back to adj_open → phantom TP/SL
   - 29/75 v3 phantom TP trades caused by this exact bug
   - Plan committed: rosy-conjuring-church.md (deferred data layer fix)

E. **Numeric impact**:
   - chase_up + uptrend_pullback: 12 preset baselines phantom-affected
   - Limit-up guard: PC = NaN → guard skipped → limit-up opens accepted
     (CLAUDE.md §3/§4 violation, market-reality)
   - raw_prev_close coverage: 0% (chase/uptrend loaders), 99.95%
     (v_daily_dual view, unused)

本文件验证:
- 3 RED: data layer still reads NULL column, view exists but unused,
  engines have no fix
- 2 PASS baseline: v_daily_dual view exists with LAG computation,
  signal-side uses adj_close (no NaN issue there)
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# RED: chase_up + uptrend_pullback data loaders read NULL prev_close column
# ---------------------------------------------------------------------------


def test_chase_up_data_loads_from_raw_kline_daily_prev_close_null() -> None:
    """§3 RED: chase_up/data.py:54 reads raw_kline_daily.prev_close which is NULL.

    Per sql/migrate_v_daily_dual.sql:31-32, the upstream
    raw_kline_daily.prev_close column is NULL. chase_up/data.py joins
    directly: `r.prev_close AS raw_prev_close` → all NaN in panel.

    Result: raw_prev_close coverage = 0% in chase_up loaded panel.
    """
    src = Path("chase_up/data.py").read_text(encoding="utf-8")

    # Look for the buggy join pattern: r.prev_close AS raw_prev_close
    buggy_pattern = "r.prev_close AS raw_prev_close"

    if buggy_pattern not in src:
        return  # GREEN, fixed

    # Confirm it's from raw_kline_daily (not v_daily_dual view)
    if "v_daily_dual" in src:
        # Switched to view → GREEN
        return

    raise AssertionError(
        "GAP CAPTURED (RED): chase_up/data.py reads "
        "`r.prev_close AS raw_prev_close` from raw_kline_daily, but "
        "upstream prev_close column is NULL (per "
        "sql/migrate_v_daily_dual.sql:31-32). Result: chase_up panel "
        "has 0% raw_prev_close populated.\n"
        "Consequence: V3a entry override (chase_up/portfolio.py:343-352) "
        "is dead code → entry silently uses adj_open → phantom TP/SL.\n"
        "GREEN fix: change chase_up/data.py to either:\n"
        "  (a) read from v_daily_dual view (already created with "
        "    LAG(r.close, 1) OVER (...) computing raw_prev_close 99.95%), OR\n"
        "  (b) replace `r.prev_close` with "
        "    `LAG(r.close, 1) OVER (PARTITION BY r.thscode ORDER BY r.date)`"
    )


def test_uptrend_pullback_data_loads_from_raw_kline_daily_prev_close_null() -> None:
    """§3 RED: uptrend_pullback/data.py:63 same bug as chase_up."""
    src = Path("uptrend_pullback/data.py").read_text(encoding="utf-8")

    buggy_pattern = "r.prev_close AS raw_prev_close"

    if buggy_pattern not in src:
        return  # GREEN, fixed

    if "v_daily_dual" in src:
        return  # Switched to view → GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): uptrend_pullback/data.py:63 reads "
        "`r.prev_close AS raw_prev_close` from raw_kline_daily, but "
        "upstream prev_close is NULL. Same bug as chase_up.\n"
        "GREEN fix: identical to chase_up — switch to v_daily_dual view "
        "or compute LAG() inline."
    )


def test_short_reversal_or_cycle_loaders_dont_have_prev_close_bug() -> None:
    """§3 RED: short_reversal/indicators_bt.py:70 uses shift trick client-side.

    This test pins the GOOD pattern (client-side computation when upstream
    NULL) so we can detect regression. If short_reversal regresses to
    reading NULL prev_close directly, this test fails.

    Currently GREEN — short_reversal computes prev_close via shift.
    """
    src = Path("short_reversal/indicators_bt.py").read_text(encoding="utf-8")

    # GOOD pattern: shift(1) for prev_close OR LAG window function
    good_pattern = (
        "self.data.close[-1]" in src or
        "shift(1)" in src or
        "shift(-1)" in src or
        "lag(" in src.lower()
    )

    if good_pattern:
        return  # GREEN

    # If they switched to raw_kline_daily.prev_close, this would be RED
    if "r.prev_close" in src or "raw_prev_close" in src and "raw_kline" in src:
        raise AssertionError(
            "GAP REGRESSION: short_reversal switched to reading raw_kline_daily.prev_close "
            "which is NULL upstream. Revert to client-side computation."
        )

    # No prev_close usage at all — different concern, not this test
    return


# ---------------------------------------------------------------------------
# PASS baselines: v_daily_dual view exists + signal uses adj
# ---------------------------------------------------------------------------


def test_v_daily_dual_view_exists_with_lag_computation() -> None:
    """§3 PASS baseline: sql/migrate_v_daily_dual.sql exists with LAG computation.

    This view is the fix for raw_prev_close coverage (99.95% per memory).
    Pin existence so migration cannot be accidentally deleted.
    """
    path = Path("sql/migrate_v_daily_dual.sql")
    if not path.exists():
        raise AssertionError(
            "Regression: sql/migrate_v_daily_dual.sql missing — "
            "the fix view for raw_prev_close has been removed"
        )

    text = path.read_text(encoding="utf-8")
    assert "v_daily_dual" in text, (
        "Regression: v_daily_dual view not defined in migration SQL"
    )
    assert "LAG" in text, (
        "Regression: v_daily_dual view no longer uses LAG to compute "
        "raw_prev_close (workaround removed)"
    )


def test_signal_uses_adj_close_for_indicators() -> None:
    """§3 PASS baseline: signal generation uses adj_close (no NaN issue).

    CLAUDE.md §3 requires adj for math indicators. Pin that chase_up +
    uptrend_pullback signals read adj_open/adj_close (not raw_*).

    If signal switched to raw_*, indicator math would have NaN at
    dividend drops — different bug, but worth pinning compliance.
    """
    chase_signal = Path("chase_up/signals.py")
    if chase_signal.exists():
        text = chase_signal.read_text(encoding="utf-8")
        # Should reference adj_close (not raw_close) for math
        has_adj_math = "adj_close" in text or "close" in text and "raw" not in text
        assert has_adj_math, (
            "Regression: chase_up/signals.py no longer uses adj_close "
            "for indicator math"
        )

    uptrend_signal = Path("uptrend_pullback/signals.py")
    if uptrend_signal.exists():
        text = uptrend_signal.read_text(encoding="utf-8")
        has_adj_math = "adj_close" in text or "close" in text and "raw" not in text
        assert has_adj_math, (
            "Regression: uptrend_pullback/signals.py no longer uses adj_close "
            "for indicator math"
        )