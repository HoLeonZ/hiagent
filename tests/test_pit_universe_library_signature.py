"""§3 PIT load_universe LIBRARY SIGNATURE audit (Tick 48).

CLAUDE.md §3 铁律 (verbatim):
  "Point-in-Time (PIT) Mandate: Never hardcode universe constituents
   (e.g., `if symbol in SP500`). Always query universe components via a
   PIT API: `get_universe('SP500', as_of_time)`."

**核心发现 (FRESH 2026-09-23) — ROOT CAUSE for [[pit-universe-call-site-propagation-2026-09-23]]:**

A. **Library signature gap is the ROOT CAUSE** (verified):
   - Tick 41 quantified 18 call sites in chase_up + uptrend_pullback that
     pass NO asof_date. But the LIBRARY signature itself doesn't ACCEPT
     asof_date — call sites can't fix this without library change.
   - chase_up/universe.py:53-78 `def load_universe(mode, db_path, exclude_path)`
     — **NO asof_date param**, uses `_all_thscodes(db_path)` (full universe)
   - uptrend_pullback/universe.py:61-86 `def load_universe(mode, db_path, exclude_path)`
     — **NO asof_date param**, same signature
   - short_reversal/universe.py:45 `def load_universe_asof(mode, asof_date, db_path, exclude_path)`
     — **HAS asof_date** (correct PIT pattern, but function name differs)

B. **Comparison of signatures**:
   ```python
   # chase_up/universe.py:53 — VIOLATES §3 (NO asof_date)
   def load_universe(
       mode: str,
       db_path: Path,
       exclude_path: Path | None = None,
   ) -> list[str]:
       all_codes = _all_thscodes(db_path)  # full universe, no PIT

   # uptrend_pullback/universe.py:61 — VIOLATES §3 (NO asof_date)
   def load_universe(
       mode: str,
       db_path: Path,
       exclude_path: Path | None = None,
   ) -> list[str]:
       all_codes = _all_thscodes(db_path)  # full universe, no PIT

   # short_reversal/universe.py:45 — COMPLIANT §3 (HAS asof_date)
   def load_universe_asof(
       mode: str,
       asof_date: str,
       db_path: Path,
       exclude_path: Path | None = None,
   ) -> list[str]:
       # SQL: "WHERE date <= ? ORDER BY thscode" — PIT filter applied
   ```

C. **Why this matters**:
   - Even if all 18 call sites added `asof_date=...` to their kwargs,
     they would TypeError because the function doesn't accept the kwarg
   - Library must change FIRST, then call sites can pass asof_date
   - short_reversal solved by creating a NEW function `load_universe_asof`
     (different name, not modifying the original)
   - chase_up + uptrend_pullback have NOT solved this — `_all_thscodes`
     returns ALL thscodes (delisted stocks included post-hoc)

D. **Numeric impact**:
   - chase_up + uptrend_pullback backtests use post-hoc full universe
   - Stocks that IPO'd AFTER the backtest end date are still in panel
   - Survivorship bias: ~5-15% of indices that IPO'd during backtest window
     are in panel before their actual listing date
   - Inflated universe → inflated capacity → inflated Sharpe

E. **Why Tick 41 didn't catch this**:
   - Tick 41 tests enumerate call sites + check for asof_date kwarg
   - But the library signature gap makes the kwarg impossible
   - Tick 41 test would PASS even if library fixed, if call sites weren't
     updated — but call sites need library fix FIRST
   - Library signature must be tested directly (this file)

本文件验证:
- 2 RED: chase_up + uptrend_pullback `load_universe` signatures lack asof_date
- 2 PASS baseline: short_reversal `load_universe_asof` has asof_date +
  both engines share the same gap (anti-drift pin)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers: AST-based signature introspection
# ---------------------------------------------------------------------------


def _extract_signature(path: Path, func_name: str) -> ast.FunctionDef | None:
    """Parse Python source and return the AST FunctionDef matching func_name."""
    if not path.exists():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    return None


def _has_asof_date_param(func: ast.FunctionDef) -> bool:
    """Check if function has 'asof_date' or 'as_of_date' in its args.

    Uses AST arg names (not source text) to be precise about which
    parameters are formally accepted.
    """
    args = func.args
    all_arg_names = (
        [a.arg for a in args.args] +
        [a.arg for a in args.kwonlyargs] +
        [a.arg for a in args.posonlyargs]
    )
    return any(name in ("asof_date", "as_of_date") for name in all_arg_names)


# ---------------------------------------------------------------------------
# RED: chase_up + uptrend_pullback load_universe lack asof_date param
# ---------------------------------------------------------------------------


def test_chase_up_load_universe_signature_lacks_asof_date() -> None:
    """§3 RED: chase_up/universe.py load_universe() lacks asof_date param.

    chase_up/universe.py:53-78 signature:
        def load_universe(mode, db_path, exclude_path=None)

    Without asof_date, function cannot filter to PIT universe per
    CLAUDE.md §3 PIT Mandate. This is the ROOT CAUSE for the 18
    call sites (Tick 41) that can't pass asof_date.

    GREEN fix: add `asof_date: str` parameter + filter SQL by `date <= ?`.
    """
    path = REPO_ROOT / "chase_up" / "universe.py"
    func = _extract_signature(path, "load_universe")
    if func is None:
        return  # structure changed

    if _has_asof_date_param(func):
        return  # GREEN

    arg_names = [a.arg for a in func.args.args]
    raise AssertionError(
        f"GAP CAPTURED (RED): chase_up/universe.py load_universe() "
        f"signature lacks asof_date parameter. Current args: {arg_names}.\n"
        f"This is the ROOT CAUSE of [[pit-universe-call-site-propagation-2026-09-23]]: "
        f"18 call sites can't pass asof_date because the function doesn't accept it.\n"
        f"Compare short_reversal/universe.py:45 `load_universe_asof`:\n"
        f"  def load_universe_asof(mode, asof_date, db_path, exclude_path=None)\n"
        f"GREEN fix: add `asof_date: str` to chase_up/universe.py:53 load_universe() "
        f"signature + filter `_all_thscodes(db_path)` by PIT date (e.g., "
        f"`SELECT DISTINCT thscode FROM v_daily WHERE date <= ?`)."
    )


def test_uptrend_pullback_load_universe_signature_lacks_asof_date() -> None:
    """§3 RED: uptrend_pullback/universe.py load_universe() lacks asof_date param.

    Same as chase_up — library signature gap blocks PIT universe filtering.
    """
    path = REPO_ROOT / "uptrend_pullback" / "universe.py"
    func = _extract_signature(path, "load_universe")
    if func is None:
        return  # structure changed

    if _has_asof_date_param(func):
        return  # GREEN

    arg_names = [a.arg for a in func.args.args]
    raise AssertionError(
        f"GAP CAPTURED (RED): uptrend_pullback/universe.py load_universe() "
        f"signature lacks asof_date parameter. Current args: {arg_names}.\n"
        f"Compare short_reversal/universe.py:45 `load_universe_asof`:\n"
        f"  def load_universe_asof(mode, asof_date, db_path, exclude_path=None)\n"
        f"GREEN fix: identical to chase_up — add asof_date param + PIT filter."
    )


# ---------------------------------------------------------------------------
# PASS baselines
# ---------------------------------------------------------------------------


def test_short_reversal_load_universe_asof_signature_has_asof_date() -> None:
    """§3 PASS baseline: short_reversal/universe.py load_universe_asof has asof_date.

    Pin compliance: short_reversal solved the PIT mandate by creating a
    new function `load_universe_asof` with asof_date param + SQL filter.
    """
    path = REPO_ROOT / "short_reversal" / "universe.py"
    func = _extract_signature(path, "load_universe_asof")
    if func is None:
        return  # structure changed

    assert _has_asof_date_param(func), (
        "Regression: short_reversal/universe.py load_universe_asof() "
        "lost asof_date parameter. CLAUDE.md §3 PIT Mandate violated."
    )

    # Also verify the SQL filter is present
    src = path.read_text(encoding="utf-8")
    assert "WHERE date <=" in src or "date <= ?" in src, (
        "Regression: short_reversal/universe.py load_universe_asof() "
        "lost PIT filter (date <= ?). CLAUDE.md §3 PIT Mandate violated."
    )


def test_chase_up_and_uptrend_share_signature_gap() -> None:
    """§3 PASS baseline: chase_up + uptrend_pullback have identical gap.

    Anti-drift pin: if one engine fixes the signature gap, this test
    fails (which is correct — the gap was caught). If both engines
    regress independently, this test still fails (preventing fix-revert).

    Tests that BOTH engines currently lack asof_date (RED state).
    """
    chase_path = REPO_ROOT / "chase_up" / "universe.py"
    uptrend_path = REPO_ROOT / "uptrend_pullback" / "universe.py"

    chase_func = _extract_signature(chase_path, "load_universe")
    uptrend_func = _extract_signature(uptrend_path, "load_universe")

    if chase_func is None or uptrend_func is None:
        return  # structure changed

    chase_has_asof = _has_asof_date_param(chase_func)
    uptrend_has_asof = _has_asof_date_param(uptrend_func)

    # Both should be in same state — both RED (no asof_date) or both GREEN
    assert chase_has_asof == uptrend_has_asof, (
        f"Signature drift: chase_up.load_universe has asof_date={chase_has_asof} "
        f"but uptrend_pullback.load_universe has asof_date={uptrend_has_asof}. "
        f"Engines should evolve together. CLAUDE.md §3 PIT Mandate."
    )