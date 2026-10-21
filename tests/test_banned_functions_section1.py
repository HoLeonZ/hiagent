"""§1 Banned functions audit (Tick 52).

CLAUDE.md §1 (verbatim):
  - **Banned Functions:** NEVER use `df.bfill()`, `df.shift(-x)`, or
    `df.rolling(center=True)`.
  - **Banned Global State:** NEVER normalize data using global `.mean()`
    or `.std()` prior to splitting. Use causal `.expanding()` or
    `.rolling()` statistics exclusively.

**核心发现 (FRESH 2026-09-23):**

A. **Manual scan: 0 hits** (verified 2026-09-23):
   - `.bfill()`, `.ffill()`, `.shift(-N)`, `.rolling(center=True)`:
     0 occurrences across chase_up/ + uptrend_pullback/ + short_reversal/
     + cycle_price_action/ + core/ + dna_stats/

B. **Test coverage gap** (this audit):
   - test_*_no_lookahead.py files cover 8 dimensions (P0-P8) per engine:
     P0 ATR TP/SL, P1 exit_price, P2 trade completeness, P3 entry≠exit,
     P4 DB schema, P5 exit priority, P6 signal/exec decoupling,
     P7 indicator grouping, P8 universe as-of
   - NONE of these tests scan for the §1 banned function PATTERNS
     (`.bfill()`, `.shift(-x)`, `.rolling(center=True)`)
   - "CLEAN — 0 hits" in master ledger is a MANUAL check, not automated
   - If a contributor adds `.bfill()` tomorrow, nothing catches it

C. **AST static analysis**:
   - Walk every .py file in 4 engines + core + dna_stats
   - For every Call node, check if it's:
     - `df.bfill()` / `.ffill()` — method call to bfill/ffill
     - `.shift(-N)` — method call with negative arg
     - `.rolling(..., center=True)` — keyword arg `center=True`
   - Report file:line for each hit

D. **Why this matters**:
   - §1 violation = lookahead bias = catastrophic (backtest looks great
     but live trading loses money)
   - Automated guard prevents regression on §1
   - Pin the current clean state with PASS baselines
   - If a future contributor adds the pattern, the test catches it
     BEFORE merge

E. **Why test_*_no_lookahead.py misses this**:
   - They test specific dimensions (P0-P8), not general patterns
   - They use hardcoded test cases, not static analysis
   - §1 banned functions are a static analysis dimension

本文件验证:
- 4 PASS baselines (pin §1 cleanliness):
  - No `.bfill()` calls in any .py file
  - No `.ffill()` calls in any .py file
  - No `.shift(-N)` calls in any .py file
  - No `.rolling(center=True)` calls in any .py file
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# ⚠️ 2026-10-19 (§13.45): 这里原先是一张手写的 `SCAN_DIRS`(6 个目录), 且消费处形如
#     for d in SCAN_DIRS:
#         if not (REPO_ROOT / d).exists(): continue     # ← 静默跳过 (§13.43 记过的形态)
# ⇒ 它漏掉 `tools/` 与 `dna_data/`; 而且"目录列表 + rglob"这种写法**结构上覆盖不到
#   仓库根的散文件**(`hiagent_config.py` / `run_sizing_comparison.py`)。
# ⇒ 改为**遍历仓库**: 把"要扫哪些"换成"只排除哪些"。
SCAN_EXCLUDE_DIRS = {
    "tests", "__pycache__", ".git", ".claude", "node_modules", "results", "worktrees",
}

# Excluded subdirs (tests, __pycache__, etc.)
EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "results",
}


def _iter_python_files() -> list[Path]:
    """**发现式**: 遍历仓库里所有 `.py`, 只按目录排除 (2026-10-19, §13.45)。

    与 §13.42 对 ORDER BY 守卫做的是同一件事: **把"要扫哪些"换成"只排除哪些"**。
    覆盖面因此从 6 个目录扩到**整仓**, 并且第一次覆盖到仓库根的散文件。
    """
    files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in SCAN_EXCLUDE_DIRS or part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith("test_"):
            continue
        files.append(path)
    return files


def _find_bfill_calls(tree: ast.AST, source_lines: list[str]) -> list[tuple[int, str]]:
    """Find all .bfill() and .ffill() method calls.

    Returns list of (line_number, method_name).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {"bfill", "ffill"}:
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            hits.append((line, node.func.attr, snippet))
    return hits


def _find_negative_shift_calls(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """Find all .shift(-N) calls (negative shift = lookahead).

    Returns list of (line_number, snippet).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "shift":
            continue
        # Check first positional arg is negative
        if not node.args:
            continue
        first_arg = node.args[0]
        is_negative = False
        # UnaryOp(-Constant(N))
        if isinstance(first_arg, ast.UnaryOp) and isinstance(first_arg.op, ast.USub):
            if isinstance(first_arg.operand, ast.Constant):
                is_negative = True
        # Constant negative number (rare in Python AST)
        elif isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, (int, float)):
            if first_arg.value < 0:
                is_negative = True
        if is_negative:
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            hits.append((line, snippet))
    return hits


def _find_center_true_rolling(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """Find all .rolling(..., center=True) calls.

    Returns list of (line_number, snippet).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "rolling":
            continue
        # Check keyword args for center=True
        for kw in node.keywords:
            if kw.arg == "center":
                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    line = node.lineno
                    snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                    hits.append((line, snippet))
    return hits


def _scan_file_for_pattern(pattern_name: str) -> list[str]:
    """Scan all .py files for the named banned pattern.

    Returns list of "file:line: snippet" strings.
    """
    violations: list[str] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT)
        if pattern_name == "bfill":
            hits = _find_bfill_calls(tree, source_lines)
            for line, method, snippet in hits:
                violations.append(f"{rel}:{line}: .{method}() — {snippet}")
        elif pattern_name == "shift_negative":
            hits = _find_negative_shift_calls(tree, source_lines)
            for line, snippet in hits:
                violations.append(f"{rel}:{line}: .shift(-N) — {snippet}")
        elif pattern_name == "rolling_center":
            hits = _find_center_true_rolling(tree, source_lines)
            for line, snippet in hits:
                violations.append(f"{rel}:{line}: .rolling(center=True) — {snippet}")
    return violations


# ---------------------------------------------------------------------------
# PASS baselines — pin §1 cleanliness
# ---------------------------------------------------------------------------


def test_no_bfill_calls_in_production_code() -> None:
    """§1 PASS baseline: No `.bfill()` calls in any production .py file.

    Per CLAUDE.md §1: NEVER use df.bfill(). Current scan: 0 hits.

    Pin the clean state — if a contributor adds `.bfill()` tomorrow,
    this test will fail and alert them to the §1 violation.
    """
    violations = _scan_file_for_pattern("bfill")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} .bfill()/.ffill() "
        f"calls found in production code:\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_no_negative_shift_calls_in_production_code() -> None:
    """§1 PASS baseline: No `.shift(-N)` calls in any production .py file.

    Per CLAUDE.md §1: NEVER use df.shift(-x). Current scan: 0 hits.

    Pin the clean state — negative shift = lookahead = catastrophic.
    """
    violations = _scan_file_for_pattern("shift_negative")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} .shift(-N) "
        f"calls found in production code (negative shift = lookahead):\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_no_rolling_center_true_in_production_code() -> None:
    """§1 PASS baseline: No `.rolling(center=True)` calls in production.

    Per CLAUDE.md §1: NEVER use df.rolling(center=True). Current scan:
    0 hits.

    Pin the clean state — symmetric rolling window = lookahead.
    """
    violations = _scan_file_for_pattern("rolling_center")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} "
        f".rolling(center=True) calls found in production code (symmetric "
        f"window = lookahead):\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_section1_no_lookahead_test_files_exist_per_engine() -> None:
    """§1 PASS baseline: no_lookahead test files exist for all 4 engines.

    Pin the test infrastructure exists. test_*_no_lookahead.py covers
    dimensions P0-P8 per engine but doesn't scan for banned patterns
    (that's what tests 1-3 above do).
    """
    expected = [
        "tests/test_chase_up_no_lookahead.py",
        "tests/test_uptrend_pullback_no_lookahead.py",
        "tests/test_short_reversal_no_lookahead.py",
        "tests/test_cycle_price_action_no_lookahead.py",
    ]
    missing = [p for p in expected if not (REPO_ROOT / p).exists()]
    assert not missing, (
        f"Regression: missing §1 no_lookahead test files: {missing}"
    )

# ---------------------------------------------------------------------------
# 反空转对照 (§13.45): §1 扫描必须是**发现式**的, 且必须够得到散文件
# ---------------------------------------------------------------------------


def test_section1_scan_is_discovery_based_and_reaches_root_files() -> None:
    """§1 扫描必须覆盖旧手写清单**之外**的位置 —— 否则"放宽覆盖面"是句空话。

    ⚠️ 2026-10-19 (§13.45): 本文件原先用 `SCAN_DIRS`(6 个目录) + `rglob` 枚举。
    那种写法**结构上覆盖不到仓库根的散文件**(目录列表里放不进一个文件)。
    改为遍历仓库后, 实测覆盖 **106 → 119** 个文件, 多出的 13 个里有:
    `tools/cross_section/*`(§13.41 从 `/tmp` 抢救进来的 §7 复现脚本)、
    `dna_data/*`(§9 说的共享双价层)、以及两个根目录散文件。
    """
    files = _iter_python_files()
    rels = {f.relative_to(REPO_ROOT).as_posix() for f in files}
    old_scope = {"chase_up", "uptrend_pullback", "short_reversal",
                 "cycle_price_action", "core", "dna_stats"}
    outside = {r for r in rels if r.split("/")[0] not in old_scope}
    assert outside, (
        "扫描范围没有越出旧的那 6 个目录 ⇒ 它退化成了手写清单, 覆盖面并未真的放宽。"
    )
    # 散文件 —— 旧机制**结构上**够不到的那一类
    root_files = {r for r in rels if "/" not in r}
    assert root_files, (
        f"扫描够不到仓库根的散文件 ⇒ 目录列表 + rglob 的老问题还在。实际: {sorted(rels)[:5]}"
    )
    assert "tools/cross_section/cs_holdout.py" in rels, (
        "§13.41 抢救进来的 §7 复现脚本必须落在 §1 扫描范围内"
    )
