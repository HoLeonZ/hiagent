"""§4 Volume Cap Liquidity Floor Verification (Tick 62).

CLAUDE.md §4 (verbatim):
  "Volume Participation Limit: Any generated execution engine must
   enforce a volume cap. Default rule:
   `Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)`.
   Unfilled quantities must be explicitly canceled or queued."

**核心发现 (FRESH 2026-09-23):**

A. **CLAUDE.md §4 mandates liquidity floor**:
   - `Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)`
   - 10% of daily bar volume is the participation cap
   - Unfilled quantities must be CANCELLED or QUEUED (not silently filled)

B. **Known anti-pattern: integer division bypass** (per [[volume-cap-low-bar-bypass]]):
   - Formula: `bar_vol // 100 * 100` rounds DOWN to nearest 100
   - For bar_vol < 1000: cap = 0 → silently bypassed → order fills full size
   - Example: bar_vol=999 → 999 // 100 = 9 → 9 × 100 = 900? Or 9 × 100 = 900?
     Actually bar_vol // 100 = 9 for bar_vol=950, * 100 = 900
     But bar_vol < 100 → cap = 0
   - **Correct formula**: `int(bar_vol * 0.10)` or `bar_vol * 10 // 100`
     OR `(bar_vol * 0.10).astype(int)` in numpy/pandas

C. **Volume cap pattern detection** (AST-based):
   - Look for: `bar_vol` (or `bar_volume`/`volume`/`vol`) used in multiplication
   - Look for: numeric multiplier between 0 and 1 (e.g., 0.10, 0.05)
   - Look for: MIN() / min() wrapping order qty and cap
   - Flag: integer-division-then-multiply pattern (`// 100 * 100`)
   - Flag: missing MIN() (cap not enforced at all)

D. **Per-engine coverage**:
   - chase_up/backtrader_engine.py — primary fill logic
   - uptrend_pulback/backtrader_engine.py — primary fill logic
   - short_reversal/portfolio.py / replay_broker.py — fill logic
   - cycle_price_action/replay_broker.py — fill logic

E. **Why this matters**:
   - §0 Pessimistic Default: ALWAYS assume worst-case liquidity
   - §4 Illusion Prevention: orders must not assume infinite market depth
   - Volume cap bypass → phantom fills → phantom PnL (similar to V3a bug)
   - Daily volume < 1000 shares = illiquid micro-cap stocks
   - chase_up "all_in" sizing means order_qty can be huge relative to vol

F. **Tick 62 verification**:
   - AST scan of backtrader_engine.py / portfolio.py / replay_broker.py
   - Detect: bar_vol multiplier, MIN() wrapper, integer division patterns
   - RED if: no volume cap found, or `// 100 * 100` pattern detected
   - PASS if: clean MIN(bar_vol * 0.10, ...) pattern

G. **Test results (Tick 62 expected)**:
   - 0 RED initially (audit current implementation)
   - May find: chase/uptrend have cap, short_reversal may not,
     volume cap formula variants across engines
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Engine-specific fill logic entry points
FILL_LOGIC_FILES = [
    REPO_ROOT / "chase_up" / "backtrader_engine.py",
    REPO_ROOT / "chase_up" / "portfolio.py",
    REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    REPO_ROOT / "short_reversal" / "replay_broker.py",
    REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    REPO_ROOT / "short_reversal" / "engine.py",
]


def _find_fill_logic_uses() -> dict[str, list[dict[str, object]]]:
    """Scan fill logic files for volume cap patterns.

    Returns dict[file_rel → list of {pattern, line, snippet}].
    """
    results: dict[str, list[dict[str, object]]] = {}

    for path in FILL_LOGIC_FILES:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        rel = path.relative_to(REPO_ROOT)
        sites: list[dict[str, object]] = []

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""

            # Detect MIN(...) / min(...) calls
            if isinstance(node, ast.Call):
                func = node.func
                is_min = (
                    (isinstance(func, ast.Name) and func.id in {"min", "MIN"})
                    or (isinstance(func, ast.Attribute) and func.attr in {"min", "MIN"})
                )
                if is_min:
                    # Check if args reference bar_vol / volume / bar_volume
                    has_vol_ref = False
                    for arg in node.args:
                        for sub in ast.walk(arg):
                            if isinstance(sub, ast.Name) and any(
                                v in sub.id.lower()
                                for v in ("vol", "bar_vol", "barvolume")
                            ):
                                has_vol_ref = True
                                break
                    if has_vol_ref:
                        sites.append({
                            "pattern": "MIN(vol_ref, ...)",
                            "line": line,
                            "snippet": snippet,
                        })

            # Detect `// 100 * 100` integer-division-then-multiply pattern
            # This is the known bypass bug — appears in chase_up/portfolio.py:406
            # and uptrend_pullback/portfolio.py:395 as
            # `int(bar_vol * max_volume_participation // 100) * 100`
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                left = node.left
                # Pattern 1: direct BinOp(FloorDiv) on left
                inner_is_floordiv = (
                    isinstance(left, ast.BinOp)
                    and isinstance(left.op, ast.FloorDiv)
                )
                # Pattern 2: Call(int, ...) wrapping BinOp(FloorDiv)
                if isinstance(left, ast.Call) and left.args:
                    arg0 = left.args[0]
                    inner_is_floordiv = (
                        isinstance(arg0, ast.BinOp)
                        and isinstance(arg0.op, ast.FloorDiv)
                    )

                if inner_is_floordiv:
                    # Check if any part references volume
                    vol_ref = False
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Name) and any(
                            v in sub.id.lower()
                            for v in ("vol", "bar_vol", "barvolume")
                        ):
                            vol_ref = True
                            break
                    if vol_ref:
                        sites.append({
                            "pattern": "VOLUME_INTEGER_DIVISION_BYPASS",
                            "line": line,
                            "snippet": snippet,
                        })

            # Detect bar_vol * 0.10 / bar_vol * 0.1 / bar_vol * 0.05
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                # Check if right side is a small float (0.01 - 0.20)
                right = node.right
                if isinstance(right, ast.Constant) and isinstance(right.value, float):
                    if 0.01 <= right.value <= 0.20:
                        # Check if left side references volume
                        for sub in ast.walk(node.left):
                            if isinstance(sub, ast.Name) and any(
                                v in sub.id.lower()
                                for v in ("vol", "bar_vol", "barvolume")
                            ):
                                sites.append({
                                    "pattern": "bar_vol * small_float",
                                    "line": line,
                                    "snippet": snippet,
                                })
                                break

        results[str(rel)] = sites

    return results


# ---------------------------------------------------------------------------
# RED: integer-division bypass detected
# ---------------------------------------------------------------------------


def test_no_volume_integer_division_bypass_pattern() -> None:
    """§4 RED forward-defense: no `// 100 * 100` volume cap bypass.

    Per CLAUDE.md §4: `Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)`.
    Anti-pattern: `bar_vol // 100 * 100` rounds to 0 for bar_vol < 1000.

    Catches the known bypass bug from [[volume-cap-low-bar-bypass]].
    """
    findings = _find_fill_logic_uses()

    bypass_sites: list[str] = []
    for file_rel, sites in findings.items():
        for site in sites:
            if site["pattern"] == "VOLUME_INTEGER_DIVISION_BYPASS":
                bypass_sites.append(
                    f"{file_rel}:{site['line']} — {site['snippet']}"
                )

    if bypass_sites:
        raise AssertionError(
            f"§4 VOLUME CAP INTEGER-DIVISION BYPASS detected in "
            f"{len(bypass_sites)} site(s):\n\n"
            + "\n".join(f"  {s}" for s in bypass_sites[:10])
            + "\n\nThe `bar_vol // 100 * 100` pattern rounds DOWN, causing "
            "the volume cap to be 0 for illiquid stocks (bar_vol < 1000). "
            "This SILENTLY BYPASSES the §4 10% participation rule.\n\n"
            "GREEN fix: replace with `int(bar_vol * 0.10)` or "
            "`bar_vol * 10 // 100` (which preserves the 0.10 ratio)."
        )


# ---------------------------------------------------------------------------
# PASS baselines: each engine has a MIN(vol_ref, ...) volume cap
# ---------------------------------------------------------------------------


def test_chase_up_has_volume_cap_pattern() -> None:
    """§4 PASS baseline: chase_up has volume cap with bar_vol reference.

    The actual volume cap lives in chase_up/portfolio.py (not
    backtrader_engine.py). Forward-defense guards both.

    NOTE: chase_up uses `max_fill = int(bar_vol * cap // 100) * 100`
    which is the integer-division bypass pattern (caught by RED test).
    This PASS baseline only checks that MIN() wrapper exists somewhere.
    """
    findings = _find_fill_logic_uses()
    chase_engine_sites = findings.get(
        "chase_up/backtrader_engine.py", []
    )
    chase_portfolio_sites = findings.get(
        "chase_up/portfolio.py", []
    )
    chase_up_sites = chase_engine_sites + chase_portfolio_sites

    min_sites = [
        s for s in chase_up_sites
        if s["pattern"] == "MIN(vol_ref, ...)"
    ]

    assert min_sites, (
        "§4 chase_up volume cap MISSING: no MIN(vol_ref, ...) pattern "
        "found in chase_up/{backtrader_engine,portfolio}.py. Per "
        "CLAUDE.md §4:\n"
        "  Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)\n"
        "All fill logic must enforce this volume participation cap."
    )


def test_uptrend_pullback_has_volume_cap_pattern() -> None:
    """§4 PASS baseline: uptrend_pullback has volume cap with bar_vol ref.

    The actual volume cap lives in uptrend_pullback/portfolio.py (not
    backtrader_engine.py). Forward-defense guards both.
    """
    findings = _find_fill_logic_uses()
    uptrend_engine_sites = findings.get(
        "uptrend_pullback/backtrader_engine.py", []
    )
    uptrend_portfolio_sites = findings.get(
        "uptrend_pullback/portfolio.py", []
    )
    uptrend_sites = uptrend_engine_sites + uptrend_portfolio_sites

    min_sites = [
        s for s in uptrend_sites
        if s["pattern"] == "MIN(vol_ref, ...)"
    ]

    assert min_sites, (
        "§4 uptrend_pullback volume cap MISSING: no MIN(vol_ref, ...) "
        "pattern found in uptrend_pullback/{backtrader_engine,portfolio}.py. "
        "Per CLAUDE.md §4: Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
    )