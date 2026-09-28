"""§3 PIT Mandate — cross-engine universe API audit RED tests.

CLAUDE.md §3 mandates:
  - Point-in-Time (PIT): NEVER hardcode universe constituents.
    Always query via PIT API: get_universe('SP500', as_of_time).
    Delisted assets must remain in simulation until physical delisting date.

Universe API matrix (verified 2026-09-23):

| Engine | API | PIT-aware? | Status |
|---|---|---|---|
| short_reversal | load_universe_asof(mode, asof_date, db_path) | ✓ WHERE date <= ? | ✓ COMPLIANT |
| chase_up | load_universe(mode, db_path) | ✗ no date filter | ✗ VIOLATION |
| uptrend_pullback | load_universe(mode, db_path) | ✗ no date filter | ✗ VIOLATION |
| cycle_price_action | inline is_main_board filter (data_feed.py:36) | partial | ⚠️ INLINE |

Per-engine impact:
  - chase_up: 7 call sites pass no asof_date
  - uptrend_pullback: 12 call sites pass no asof_date
  - Total: 19 call sites where backtests use post-hoc universe (lookahead)
  - cycle_price_action: inline filter using MAX(date) >= end as proxy
"""
from __future__ import annotations

from pathlib import Path


def test_chase_up_load_universe_accepts_asof_date() -> None:
    """§3 RED: chase_up.load_universe must accept asof_date parameter.

    Currently chase_up/universe.py:53 has signature
    `def load_universe(mode, db_path, exclude_path=None)` — no
    asof_date. To use PIT, signature must be
    `def load_universe(mode, asof_date, db_path, exclude_path=None)`.
    """
    import inspect
    from chase_up.universe import load_universe

    sig = inspect.signature(load_universe)
    assert "asof_date" in sig.parameters, (
        "GAP CAPTURED: chase_up.universe.load_universe missing "
        "`asof_date` parameter. §3 PIT Mandate violated. "
        "GREEN fix: add `asof_date: str` parameter, filter "
        "`WHERE date <= asof_date` in SQL."
    )


def test_uptrend_pullback_load_universe_accepts_asof_date() -> None:
    """§3 RED: uptrend_pullback.load_universe must accept asof_date."""
    import inspect
    from uptrend_pullback.universe import load_universe

    sig = inspect.signature(load_universe)
    assert "asof_date" in sig.parameters, (
        "GAP CAPTURED: uptrend_pullback.universe.load_universe missing "
        "`asof_date` parameter. §3 PIT Mandate violated."
    )


def test_short_reversal_load_universe_asof_passes_baseline() -> None:
    """§3 PASS baseline: short_reversal.load_universe_asof accepts asof_date."""
    import inspect
    from short_reversal.universe import load_universe_asof

    sig = inspect.signature(load_universe_asof)
    assert "asof_date" in sig.parameters, (
        "Regression: short_reversal lost asof_date parameter — "
        "fix it back to load_universe_asof mode"
    )


def test_chase_up_all_thscodes_has_no_date_filter() -> None:
    """§3 RED: chase_up._all_thscodes returns POST-HOC full universe.

    chase_up/universe.py `_all_thscodes(db_path)` returns
    `SELECT DISTINCT thscode FROM v_daily` without date filter.
    Includes delisted stocks + pre-IPO dates incorrectly.
    """
    import importlib
    import re
    from pathlib import Path

    mod = importlib.import_module("chase_up.universe")
    src = Path(mod.__file__).read_text(encoding="utf-8")

    m = re.search(
        r"def _all_thscodes\(.*?\):.*?(?=\ndef |\Z)",
        src,
        re.DOTALL,
    )
    assert m is not None, "Could not find _all_thscodes function in chase_up/universe.py"
    fn_body = m.group(0)
    has_select = "SELECT DISTINCT thscode" in fn_body
    has_where_date = "WHERE date <=" in fn_body or "WHERE date <" in fn_body

    # RED: SQL has SELECT DISTINCT but NO date filter = §3 violation
    if has_select and not has_where_date:
        # Gap captured — fail loudly
        raise AssertionError(
            "GAP CAPTURED: chase_up.universe._all_thscodes — SQL has "
            "`SELECT DISTINCT thscode` but NO `WHERE date <=` filter. "
            "Universe returns post-hoc constituents including pre-IPO "
            "and post-delisting dates. §3 PIT Mandate violated."
        )
    # GREEN: asof_date filter present
    assert has_select and has_where_date, (
        "Unexpected: chase_up._all_thscodes structure changed. Re-evaluate."
    )


def test_uptrend_pullback_all_thscodes_has_no_date_filter() -> None:
    """§3 RED: uptrend_pullback._all_thscodes returns POST-HOC full universe."""
    import importlib
    import re

    mod = importlib.import_module("uptrend_pullback.universe")
    src = Path(mod.__file__).read_text(encoding="utf-8")

    m = re.search(
        r"def _all_thscodes\(.*?\):.*?(?=\ndef |\Z)",
        src,
        re.DOTALL,
    )
    assert m is not None, "Could not find _all_thscodes"
    fn_body = m.group(0)
    has_select = "SELECT DISTINCT thscode" in fn_body
    has_where_date = "WHERE date <=" in fn_body or "WHERE date <" in fn_body

    if has_select and not has_where_date:
        raise AssertionError(
            "GAP CAPTURED: uptrend_pullback.universe._all_thscodes — same "
            "post-hoc universe issue. SQL has no date filter. §3 PIT "
            "Mandate violated."
        )
    assert has_select and has_where_date, (
        "Unexpected: uptrend_pullback._all_thscodes structure changed."
    )


def test_chase_up_sweep_passes_no_asof_date() -> None:
    """§3 RED: chase_up sweep calls load_universe without asof_date.

    Per memory [[pit-mandate-cross-engine-gap]], 7 call sites in
    chase_up pass no asof_date. Pin that at least one such call
    exists in sweep / walkforward (production paths).
    """
    import re
    src = Path("chase_up/sweep.py").read_text(encoding="utf-8")

    has_call = bool(re.search(r"load_universe\(", src))
    # 检测 asof_date 是否在某个 load_universe(...) 调用的同一行内
    # (原 `[^)]*` 在嵌套括号 (如 Path(args.db_path)) 处截断,误报 RED)。
    has_pit_call = any(
        "asof_date" in line
        for line in src.splitlines()
        if "load_universe(" in line
    )

    if has_call and not has_pit_call:
        raise AssertionError(
            "GAP CAPTURED: chase_up/sweep.py — load_universe() called "
            "without asof_date. §3 PIT Mandate violated. Sweep results "
            "report inflated universe count (includes post-hoc listings)."
        )
    assert has_call and has_pit_call, (
        "Unexpected: chase_up/sweep.py load_universe call structure changed"
    )


def test_cycle_price_action_pit_universe_inline() -> None:
    """§3 RED: cycle_price_action inline universe filter has no asof_date."""
    src = Path("cycle_price_action/data_feed.py").read_text(encoding="utf-8")

    has_main_board_filter = "is_main_board" in src or "mainboard" in src.lower()
    has_asof_in_data_feed = "asof_date" in src or "as_of_date" in src

    # cycle_price_action currently uses inline MAX(date) proxy — §3 partial
    if has_main_board_filter and not has_asof_in_data_feed:
        # GAP captured
        raise AssertionError(
            "GAP CAPTURED: cycle_price_action/data_feed.py — universe "
            "filter does NOT use PIT API (no asof_date param). Inline "
            "filter uses MAX(date) proxy which captures post-hoc "
            "constituents. §3 PIT Mandate partial compliance."
        )
    # GREEN: asof_date integrated
    assert has_main_board_filter and has_asof_in_data_feed, (
        "Unexpected: cycle data_feed structure changed. Re-evaluate."
    )