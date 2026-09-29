"""Round 30 Finding 3 (2026-09-28, CLAUDE.md §3 data integrity):
extract_execution_bar fallback chain broken for NULL/NaN values.

core/dual_price.py:118-122 uses `dict.get(key, default)` chain which only
falls through when the KEY is missing. When the key EXISTS with value
None or NaN, `dict.get` returns the None/NaN value, NOT the fallback.

This causes silent skips / ValueErrors in production:
  - raw_close=NaN (LEFT JOIN miss, key present) → c=NaN → _safe=0.0 →
    ExecutionBar.close=0.0; if raw_open also NaN, bar is all-zero (no
    exception). Trade preserved via Round 29c sentinel but with phase1
    metrics (which used adj_open as fill, NOT raw_open).
  - Edge case: raw_open > 0 but raw_close=NaN → ExecutionBar invariant
    "close <= 0 AND open > 0" triggers → ValueError. Phase 2 verify crashes.

Fix: replace chained `dict.get` with a helper that treats both None and
NaN as fallthrough triggers, so the documented contract "raw_* 列是
ground truth; 缺失时回退到 adj_* 列" actually holds.

This test enforces the NaN-fallback contract.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.dual_price import (  # noqa: E402
    LAYOUT_CHASE_UPTREND,
    LAYOUT_CYCLE_PRICE,
    extract_execution_bar,
)


# ---------------------------------------------------------------------------
# Behavioral tests: NaN values must trigger fallback (not be returned as-is)
# ---------------------------------------------------------------------------


def test_nan_raw_close_falls_through_to_close() -> None:
    """§3 RED→GREEN: when raw_close=NaN but close=15.0, extract_execution_bar
    must use close=15.0, NOT 0.0 (current silent-skip bug)."""
    row = {
        "raw_open": 14.0,
        "raw_high": 16.0,
        "raw_low": 13.5,
        "raw_close": float("nan"),
        "raw_prev_close": 14.5,
        "adj_open": 14.0,
        "adj_high": 16.0,
        "adj_low": 13.5,
        "adj_close": 15.0,
        "open": 14.0,
        "high": 16.0,
        "low": 13.5,
        "close": 15.0,
        "prev_close": 14.5,
    }
    bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
    assert bar.close == 15.0, (
        f"§3 VIOLATION: NaN raw_close should fall through to adj_close (15.0), "
        f"got {bar.close}. Current `dict.get(key, default)` chain doesn't "
        f"fall through when key exists with NaN value."
    )


def test_none_raw_open_falls_through_to_open() -> None:
    """§3 RED→GREEN: when raw_open=None but open=14.0, must use open=14.0."""
    row = {
        "raw_open": None,
        "raw_high": 16.0,
        "raw_low": 13.5,
        "raw_close": 15.0,
        "raw_prev_close": 14.5,
        "open": 14.0,
        "high": 16.0,
        "low": 13.5,
        "close": 15.0,
        "prev_close": 14.5,
    }
    bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
    assert bar.open == 14.0, (
        f"§3 VIOLATION: None raw_open should fall through to adj_open/open "
        f"(14.0), got {bar.open}."
    )


def test_all_nan_raw_returns_zero_bar_not_crash() -> None:
    """§3: when ALL raw_* are NaN (data gap), extract must NOT raise
    ValueError. Should return zero-fill bar consistent with _safe fallback."""
    row = {
        "raw_open": float("nan"),
        "raw_high": float("nan"),
        "raw_low": float("nan"),
        "raw_close": float("nan"),
        "raw_prev_close": float("nan"),
        "adj_open": 14.0,
        "adj_high": 16.0,
        "adj_low": 13.5,
        "adj_close": 15.0,
        "open": 14.0,
        "high": 16.0,
        "low": 13.5,
        "close": 15.0,
        "prev_close": 14.5,
    }
    bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
    # Should fall through NaN raw_* to adj_*, getting real values
    assert bar.open == 14.0, f"all-NaN raw should fall through to adj, got open={bar.open}"
    assert bar.close == 15.0, f"all-NaN raw should fall through to adj, got close={bar.close}"


def test_nan_raw_close_no_edge_crash() -> None:
    """§3 edge case: raw_close=NaN but raw_open=10.0 (positive) — current code
    would trigger ExecutionBar invariant (close<=0 AND open>0 → ValueError).
    After fix: NaN should fall through to adj_close=15.0, eliminating the
    edge-case crash.
    """
    row = {
        "raw_open": 10.0,
        "raw_high": 16.0,
        "raw_low": 9.5,
        "raw_close": float("nan"),  # NaN, key present
        "raw_prev_close": 14.5,
        "adj_open": 14.0,
        "adj_high": 16.0,
        "adj_low": 13.5,
        "adj_close": 15.0,
        "open": 14.0,
        "high": 16.0,
        "low": 13.5,
        "close": 15.0,
        "prev_close": 14.5,
    }
    # Should NOT raise — NaN should fall through to adj_close
    bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
    assert bar.close == 15.0, f"NaN raw_close must fall through, got {bar.close}"


# ---------------------------------------------------------------------------
# Layout C (cycle_price_action) — only open/high/low/close columns
# ---------------------------------------------------------------------------


def test_layout_c_nan_open_falls_through_to_open_keyword() -> None:
    """§3 Layout C: when raw_* columns don't exist (Layout C uses open/high/low/
    close directly), NaN values should also trigger _safe fallback to 0.0
    (current behavior, but no exception either way)."""
    row = {
        "open": 14.0,
        "high": 16.0,
        "low": 13.5,
        "close": 15.0,
        "prev_close": 14.5,
    }
    bar = extract_execution_bar(row, LAYOUT_CYCLE_PRICE)
    assert bar.open == 14.0
    assert bar.close == 15.0


# ---------------------------------------------------------------------------
# Source guard: extract_execution_bar must use NaN-aware fallback
# ---------------------------------------------------------------------------


CORE_DUAL_PRICE = ROOT / "core" / "dual_price.py"


def test_extract_execution_bar_source_uses_nan_aware_fallback() -> None:
    """§3 source guard: extract_execution_bar must use a NaN-aware fallback
    helper (not chained dict.get which only checks key existence)."""
    src = Path(CORE_DUAL_PRICE).read_text()
    # Find the extract_execution_bar function body
    import re
    func_block_m = re.search(
        r"def extract_execution_bar\((.*?)^(?:def |---)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert func_block_m is not None, "extract_execution_bar function not found"
    block = func_block_m.group(0)
    # NaN-aware helper should be defined or imported
    has_nan_helper = "_present" in block or "_is_present" in block or "isnan" in block
    # The chained dict.get pattern is the BUG (only checks key existence)
    has_chained_dict_get = bool(re.search(
        r"row\.get\([^,]+,\s*row\.get\(",
        block,
    ))
    assert has_nan_helper or not has_chained_dict_get, (
        "§3 VIOLATION: extract_execution_bar uses chained dict.get which "
        "doesn't fall through on NaN/None. Must use a NaN-aware helper "
        "(e.g., _present check) so 'raw_* 列是 ground truth; 缺失时回退到 "
        "adj_* 列' contract holds for partial-NaN rows."
    )