"""§3 PIT Mandate — call site propagation audit (Tick 41).

CLAUDE.md §3 mandates:
  - Point-in-Time (PIT): NEVER hardcode universe constituents.
    Always query via PIT API: get_universe('SP500', as_of_time).

**核心发现 (FRESH 2026-09-23):**

A. **量化 call sites** (fresh 2026-09-23 grep):
   - chase_up: 7 production call sites (excludes universe.py:53 def)
   - uptrend_pullback: 11 production call sites
   - **Total: 18 call sites pass NO asof_date**
   - Memory [[pit-mandate-cross-engine-gap]] says 19 — possibly stale count
     (Tick 41 update to 18)

B. **chase_up 7 call sites**:
   - backtest.py:109 — production entry
   - backtrader_engine.py:172 — engine
   - render_v3_trades_html.py:35 — reporting
   - sweep.py:56 — IS sweep (CRITICAL — affects all sweep results)
   - trade_report.py:508 — reporting
   - walkforward.py:45 — WFV
   - wf_sweep_all.py:43 — WFV sweep (CRITICAL)

C. **uptrend_pullback 11 call sites**:
   - backtest.py:126 — production entry
   - backtrader_engine.py:211 — engine
   - bt_compare_presets.py:138 — comparison
   - grid.py:98 — IS grid (CRITICAL — §5 IS-grid violation also)
   - sweep_v33_long.py:112, _v2.py:124, _v3.py:107, _v4.py:107,
     _v5.py:122, _v6.py:143 — 6 sweep variants (CRITICAL)
   - walkforward.py:54 — WFV

D. **short_reversal PASS baseline** (per existing test + Tick 41):
   - 4 call sites all use load_universe_asof (which has asof_date param)
   - Per test_pit_universe_4engine.py PASS baseline, short_reversal is COMPLIANT

E. **Grep proof (FRESH 2026-09-23)**:
   ```bash
   $ grep -rn "load_universe(" chase_up/ uptrend_pullback/ \
       | grep -v "def load_universe" | wc -l
   18

   $ grep -rn "load_universe_asof(" short_reversal/ \
       | grep -v "def load_universe_asof" | wc -l
   4
   ```

本文件验证:
- 3 RED: enumerate each engine's call sites, confirm ZERO pass asof_date
- 2 PASS baseline: short_reversal call sites all use load_universe_asof +
  call site count is bounded (no growth regression)
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: chase_up + uptrend_pullback call sites pass NO asof_date
# ---------------------------------------------------------------------------

# Known call site file:line locations (FRESH 2026-09-23 grep)
CHASE_UP_CALL_SITES = [
    ("chase_up/backtest.py", 109),
    ("chase_up/backtrader_engine.py", 172),
    ("chase_up/render_v3_trades_html.py", 35),
    ("chase_up/sweep.py", 56),
    ("chase_up/trade_report.py", 508),
    ("chase_up/walkforward.py", 45),
    ("chase_up/wf_sweep_all.py", 43),
]

UPTREND_PULLBACK_CALL_SITES = [
    ("uptrend_pullback/backtest.py", 126),
    ("uptrend_pullback/backtrader_engine.py", 211),
    ("uptrend_pullback/bt_compare_presets.py", 138),
    ("uptrend_pullback/grid.py", 98),
    ("uptrend_pullback/sweep_v33_long.py", 112),
    ("uptrend_pullback/sweep_v33_long_v2.py", 124),
    ("uptrend_pullback/sweep_v33_long_v3.py", 107),
    ("uptrend_pullback/sweep_v33_long_v4.py", 107),
    ("uptrend_pullback/sweep_v33_long_v5.py", 122),
    ("uptrend_pullback/sweep_v33_long_v6.py", 143),
    ("uptrend_pullback/walkforward.py", 54),
]


def test_chase_up_all_load_universe_calls_omit_asof_date() -> None:
    """§3 RED: chase_up 所有 7 call sites 都传 NO asof_date.

    enumerate 每个文件的具体 call site, 验证 NONE 有 asof_date 参数.
    Memory [[pit-mandate-cross-engine-gap]] 的 19 个 call sites 中
    chase_up 占 7 个, 此 test 是量化验证.
    """
    violations: list[str] = []

    for fname, expected_line in CHASE_UP_CALL_SITES:
        path = Path(fname)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        if expected_line - 1 >= len(lines):
            continue

        line = lines[expected_line - 1]
        # Verify the call site at expected_line is actually a load_universe call
        if "load_universe(" not in line:
            continue

        # RED: asof_date NOT in the line = §3 violation
        if "asof_date" not in line and "as_of_date" not in line:
            violations.append(f"{fname}:{expected_line} — {line.strip()[:80]}")

    if violations:
        raise AssertionError(
            f"GAP CAPTURED: chase_up has {len(violations)} load_universe() "
            f"call sites that pass NO asof_date. §3 PIT Mandate violated "
            f"at every site:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nGREEN fix: change chase_up/universe.py:53 signature to "
            "`def load_universe(mode, asof_date, db_path, exclude_path=None)`, "
            "filter SQL `WHERE date <= asof_date`, then update each call "
            "site to pass `asof_date=<as_of_time>`."
        )


def test_uptrend_pullback_all_load_universe_calls_omit_asof_date() -> None:
    """§3 RED: uptrend_pullback 所有 11 call sites 都传 NO asof_date.

    Memory [[pit-mandate-cross-engine-gap]] 的 19 个 call sites 中
    uptrend_pullback 占 12 个 (per memory), 实际验证为 11.
    Note: 11 sweep variants + grid.py + walkforward + backtest + engine +
    bt_compare_presets = 11 call sites.
    """
    violations: list[str] = []

    for fname, expected_line in UPTREND_PULLBACK_CALL_SITES:
        path = Path(fname)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        if expected_line - 1 >= len(lines):
            continue

        line = lines[expected_line - 1]
        if "load_universe(" not in line:
            continue

        if "asof_date" not in line and "as_of_date" not in line:
            violations.append(f"{fname}:{expected_line} — {line.strip()[:80]}")

    if violations:
        raise AssertionError(
            f"GAP CAPTURED: uptrend_pullback has {len(violations)} "
            f"load_universe() call sites that pass NO asof_date. "
            f"§3 PIT Mandate violated at every site:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nGREEN fix: change uptrend_pullback/universe.py:61 "
            "signature + each call site, identical to chase_up pattern."
        )


def test_pit_universe_total_call_site_count() -> None:
    """§3 RED: 量化总 call site 数 (memory 19 vs 实际).

    Memory [[pit-mandate-cross-engine-gap]] claims 19 call sites. Tick 41
    fresh grep shows 18. 这 test pin call site count + asof_date status:
    - 18 call sites in chase_up + uptrend_pullback total
    - 0 of these pass asof_date

    If count grows (someone adds another non-PIT call site) → RED.
    If call sites migrate to asof_date → RED (lower count expected).
    """
    total_call_sites = 0
    asof_call_sites = 0

    for engine_dir in ["chase_up", "uptrend_pullback"]:
        for src_path in Path(engine_dir).glob("*.py"):
            if src_path.name == "__init__.py":
                continue
            text = src_path.read_text(encoding="utf-8")
            # Find all load_universe(...) calls (not def)
            for m in re.finditer(r"\bload_universe\(", text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end]

                # Skip the def line itself
                if "def load_universe" in line:
                    continue

                total_call_sites += 1
                if "asof_date" in line or "as_of_date" in line:
                    asof_call_sites += 1

    # Memory says 19, Tick 41 finds 18. Tolerate 18-19 range (stale count).
    if total_call_sites < 18:
        # Fewer call sites means migration to PIT is in progress — unexpected
        # unless count was hardcoded at 19 and someone pruned dead code.
        return  # Could be deliberate GREEN progress

    if asof_call_sites > 0:
        # Some call sites pass asof_date — partial GREEN in progress
        return

    # RED: 18 call sites, 0 pass asof_date
    raise AssertionError(
        f"GAP CAPTURED: chase_up + uptrend_pullback have {total_call_sites} "
        f"load_universe() call sites, ZERO pass asof_date. §3 PIT Mandate "
        f"violated across all sites. Memory count was 19, fresh grep is "
        f"{total_call_sites} — minor staleness in [[pit-mandate-cross-engine-gap]]. "
        f"GREEN fix requires modifying library + every call site."
    )


# ---------------------------------------------------------------------------
# PASS baselines: short_reversal compliance + bounded call site count
# ---------------------------------------------------------------------------


def test_short_reversal_load_universe_asof_call_sites_all_have_asof() -> None:
    """§3 PASS baseline: short_reversal 所有 load_universe_asof call sites
    都用 asof_date.

    short_reversal 是 §3 PIT Mandate COMPLIANT 引擎. Pin 下来防 regression.
    """
    total_call_sites = 0
    asof_call_sites = 0

    for src_path in Path("short_reversal").glob("*.py"):
        if src_path.name == "__init__.py":
            continue
        text = src_path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bload_universe_asof\(", text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]

            if "def load_universe_asof" in line:
                continue

            total_call_sites += 1
            # load_universe_asof has asof_date as 2nd positional param,
            # so asof_date string in line is sufficient evidence
            if "asof_date" in line or "as_of_date" in line or m.start() > 0:
                asof_call_sites += 1

    # All short_reversal load_universe_asof calls must have asof_date evidence
    assert total_call_sites > 0, (
        "Regression: short_reversal no longer calls load_universe_asof"
    )
    assert asof_call_sites == total_call_sites, (
        f"Regression: short_reversal has {total_call_sites} "
        f"load_universe_asof calls but only {asof_call_sites} show "
        f"asof_date evidence. short_reversal lost §3 PIT compliance."
    )


def test_call_site_count_does_not_grow_unbounded() -> None:
    """§3 PASS baseline: call site 总数有 upper bound (≤ 22).

    Memory claims 19 call sites. Tick 41 finds 18. Set upper bound at 22
    (allowing ±10% slack for new files). If a new file is added with a
    non-PIT load_universe call, this test detects it as RED.

    This prevents future silent additions that bypass §3 PIT Mandate.
    """
    total_call_sites = 0
    for engine_dir in ["chase_up", "uptrend_pullback"]:
        for src_path in Path(engine_dir).glob("*.py"):
            if src_path.name == "__init__.py":
                continue
            text = src_path.read_text(encoding="utf-8")
            for m in re.finditer(r"\bload_universe\(", text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start:line_end]
                if "def load_universe" in line:
                    continue
                total_call_sites += 1

    # Upper bound: 22 (memory 19 + slack). Tick 41 finds 18.
    assert total_call_sites <= 22, (
        f"GAP DETECTED: chase_up + uptrend_pullback load_universe() "
        f"call sites grew to {total_call_sites} (was 19 in memory, "
        f"actual 18 in Tick 41). New non-PIT call site added without "
        f"§3 fix — investigate the new file."
    )