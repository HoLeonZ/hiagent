"""§0 Assert vs Raise Audit (Tick 59).

CLAUDE.md §0 (verbatim):
  "**Fail-Fast:** If a state transition violates physical market laws,
   throw an exception immediately. Do not silently bypass."

**核心发现 (FRESH 2026-09-23):**

A. **Production code uses `assert` for fail-fast invariants** (verified):
   - short_reversal/replay_strategy_v3.py:306:
     `assert self.p.intraday_tiebreak == "sl_first"`
   - This is a §4 intraday tiebreak invariant check

B. **`assert` is a CODE SMELL for fail-fast invariants**:
   - `assert` can be stripped with `python -O` (bytecode optimization)
   - `raise ValueError(...)` cannot be stripped
   - If user runs backtest with `python -O main.py`, all assert checks
     are REMOVED from bytecode
   - Critical invariants silently bypass → bug goes undetected
   - Per PEP 8: "Asserts should not be used to verify data validity;
     use raise instead"

C. **Python `-O` flag impact**:
   - `python -O script.py` strips all `assert` statements from bytecode
   - Common in production deployment for performance
   - Docker images often use `python -O` for size optimization
   - Any fail-fast invariant protected only by `assert` is DEAD CODE in
     production

D. **Acceptable uses of `assert`** (not flagged):
   - Test files (test_*.py, conftest.py)
   - Documentation/examples
   - Internal sanity checks that have NO production impact (e.g.,
     `assert isinstance(x, int)` when downstream code already validates)
   - Debug-only checks explicitly marked as such

E. **Why this matters**:
   - §0 Fail-Fast principle: invariants MUST be enforced in production
   - If `python -O` is ever used (common in deployment), the invariant
     disappears
   - Silent regression: code runs but invariants don't enforce
   - `assert` is debugging tool, NOT production invariant mechanism

F. **Why existing tests miss this**:
   - No test enforces `raise` vs `assert` for fail-fast invariants
   - Type checkers (mypy/pyright) don't catch this
   - Linters (ruff) have `S101` rule but it's often disabled

G. **Tick 59 RED state**: 1 production `assert` site confirmed
   - short_reversal/replay_strategy_v3.py:306

本文件验证:
- RED: production code uses `assert` for fail-fast invariants
- PASS baseline: production code uses `raise` (preferred)
- PASS baseline: test files may use `assert` (acceptable)
- Forward-defense: any new production `assert` fails this test
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ⚠️ 2026-10-19 (§13.46): 这里原先是一张手写的 `SCAN_DIRS`(6 个目录) + `if not exists: continue`
# (§13.43 记过的静默跳过形态)。它与 §13.45 遇到的是同一个**结构性**问题:
# **"目录列表 + rglob"够不到仓库根的散文件**。⇒ 改为遍历仓库, 只按目录排除。
EXCLUDE_DIR_NAMES = {
    "tests",
    "__pycache__",
    ".git",
    ".claude",
    "node_modules",
    "results",
    "worktrees",
}


def _iter_production_files() -> list[Path]:
    """**发现式**: 遍历仓库里所有 `.py`, 只按目录排除 (§13.46)。"""
    files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith("test_"):
            continue
        files.append(path)
    return files


def _scan_assert_sites() -> list[tuple[str, int, str]]:
    """Scan production code for top-level assert statements.

    Returns list of (file_rel, line, snippet) tuples.
    """
    sites: list[tuple[str, int, str]] = []
    for path in _iter_production_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            sites.append((str(rel), line, snippet))

    return sites


def _scan_raise_sites() -> list[tuple[str, int, str]]:
    """Scan production code for `raise` statements (preferred pattern)."""
    sites: list[tuple[str, int, str]] = []
    for path in _iter_production_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            sites.append((str(rel), line, snippet))

    return sites


# ---------------------------------------------------------------------------
# RED: production `assert` for fail-fast invariants
# ---------------------------------------------------------------------------


def test_production_code_has_assert_for_fail_fast() -> None:
    """§0 RED: production code uses `assert` (strippable by `python -O`).

    Per CLAUDE.md §0 Fail-Fast principle:
    - `assert` can be stripped with `python -O` flag
    - `raise ValueError(...)` cannot be stripped
    - Production fail-fast invariants MUST use `raise`

    If any production code uses `assert` for fail-fast, this test fails.
    """
    sites = _scan_assert_sites()

    if sites:
        raise AssertionError(
            f"§0 ASSERT VS RAISE VIOLATION: {len(sites)} production sites "
            f"use `assert` for fail-fast invariants:\n\n" +
            "\n".join(
                f"  {file}:{line} — {snippet}"
                for file, line, snippet in sites[:15]
            ) +
            (f"\n  ... ({len(sites) - 15} more)" if len(sites) > 15 else "") +
            f"\n\n`assert` can be stripped with `python -O` flag (common in "
            f"production deployment). All fail-fast invariants MUST use "
            f"`raise ValueError(...)` instead.\n\n"
            f"GREEN fix: replace each `assert condition, msg` with "
            f"`if not condition: raise ValueError(msg)`"
        )


# ---------------------------------------------------------------------------
# PASS baselines: production code uses `raise` (preferred pattern)
# ---------------------------------------------------------------------------


def test_production_code_uses_raise_for_invariants() -> None:
    """§0 PASS baseline: production code uses `raise` (not assert).

    Pin that production code uses `raise ValueError(...)` for fail-fast
    invariants. If all asserts were removed and no raises were added,
    this test would fail (which is a good regression signal).
    """
    raise_sites = _scan_raise_sites()

    # Sanity check: there should be at least some `raise` statements in
    # production code (otherwise fail-fast is completely missing)
    assert len(raise_sites) >= 10, (
        f"§0 FAIL-FAST REGRESSION: production code has only "
        f"{len(raise_sites)} `raise` statements. §0 Fail-Fast requires "
        f"`raise` for invariants — fewer than 10 is suspicious."
    )


def test_assert_to_raise_ratio_is_healthy() -> None:
    """§0 PASS baseline: raise/assert ratio is healthy in production.

    Per CLAUDE.md §0: production code should use `raise`, not `assert`.
    Healthy ratio: raises >> asserts.

    Pin the ratio for forward-defense. If someone introduces many
    asserts and few raises, this test fails.
    """
    assert_sites = _scan_assert_sites()
    raise_sites = _scan_raise_sites()

    # Healthy production code: ≥10 raises per 1 assert
    # ⚠️ 2026-10-19 (§13.58): 此处原为 `if len(assert_sites) > 0: ...` —— 一个**静默通过**的
    # 条件式: 当前生产代码里 assert 站点为 **0** ⇒ 比值没有分母 ⇒ 分支从不执行
    # ⇒ 这条测试既不会响, 也不会在 `-rs` 里显示为 skip, 看上去与"跑过并通过"完全一样。
    # 条件本身是**合法前置条件** (比值需要分母), 所以改成**显式 skip** —— 让它可见。
    if not assert_sites:
        pytest.skip(
            "生产代码里当前 0 处 assert ⇒ 比值判据没有分母, 本判据**不适用** "
            "(这不是通过; 见 §13.58 的说明)"
        )
    ratio = len(raise_sites) / len(assert_sites)
    assert ratio >= 10.0, (
        f"§0 RAISE/ASSERT RATIO WARNING: {len(raise_sites)} raises "
        f"vs {len(assert_sites)} asserts (ratio {ratio:.1f}:1, "
        f"target ≥10:1). Production code should prefer `raise`."
    )

# ---------------------------------------------------------------------------
# 反空转对照 (§13.46): 扫描必须是**发现式**的
# ---------------------------------------------------------------------------


def test_scan_is_discovery_based_and_reaches_root_files() -> None:
    """扫描必须覆盖旧手写清单**之外**的位置 —— 否则"放宽覆盖面"是句空话。

    ⚠️ 2026-10-19 (§13.46): 原用 `SCAN_DIRS`(6 个目录) + `rglob`。
    "目录列表 + rglob" **结构上够不到仓库根的散文件** (见 §13.45);
    实测改为遍历仓库后覆盖到 `tools/` / `dna_data/` / 两个根散文件。
    """
    rels = {f.relative_to(REPO_ROOT).as_posix() for f in _iter_production_files()}
    old_scope = {"chase_up", "uptrend_pullback", "short_reversal",
                 "cycle_price_action", "core", "dna_stats"}
    assert {r for r in rels if r.split("/")[0] not in old_scope}, (
        "扫描没有越出旧的那 6 个目录 ⇒ 覆盖面并未真的放宽"
    )
    assert {r for r in rels if "/" not in r}, (
        "扫描够不到仓库根的散文件 ⇒ 目录列表 + rglob 的老问题还在"
    )
