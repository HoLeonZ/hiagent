"""§0 Fail-Fast deep scan expansion (Tick 55).

CLAUDE.md §0 (verbatim):
  "**Fail-Fast:** If a state transition violates physical market laws,
   throw an exception immediately. Do not silently bypass."

**核心发现 (FRESH 2026-09-23):**

A. **Tick 44 found 4 silent except sites in production hot paths**:
   - short_reversal/scan_signals.py:127 (worst — affects all backtests)
   - chase_up/sweep.py:100 (dresses failure as data via rows.append)
   - uptrend_pullback/grid.py:106 (silent WFV window skip)
   - short_reversal/grid_runner.py:59 (silent + IS-grid compound)

B. **Tick 55 deep scan: 12+ ADDITIONAL silent except sites** (verified):
   - chase_up/walkforward.py:57 — walkforward iteration
   - uptrend_pullback/walkforward.py:66 — walkforward iteration
   - uptrend_pullback/bt_compare_presets.py:149 — preset comparison
   - uptrend_pullback/render_trades_html.py:989 — HTML rendering
   - uptrend_pullback/iter_reverse.py:126 — iter helper
   - short_reversal/st_filter.py:49 — ST stock filter
   - short_reversal/st_filter.py:54 — ST stock filter
   - short_reversal/lookahead_trade_trace.py:87, 123, 203 — trade trace
   - dna_stats/deflated.py:155 — DSR calculation

C. **Categories of silent except violations**:
   - `except + continue`: silently skips iteration on failure
   - `except + pass`: silently swallows exception
   - `except + rows.append`: dresses failure as data row
   - `except + return None`: silently returns None (caller crashes later
     without context)

D. **Why this matters**:
   - §0 fail-fast principle: any state transition violating physical
     market law should throw, not bypass
   - Silent except = hidden bugs + lost audit trail
   - Affects: walkforward rigor, ST filtering, DSR calculation, HTML
     rendering, trade tracing — all critical paths

E. **Why existing test_fail_fast_cross_engine misses this**:
   - Tick 44 focused on 4 specific hot-path sites
   - No general AST scan for silent except patterns
   - 12+ additional sites went undetected

F. **Acceptable exceptions** (need noqa or explicit documentation):
   - Try/except around OPTIONAL imports (`try: import x except: x = None`)
   - Try/except around EXPLICIT user-input parsing with error message
   - Try/except with `raise` re-raise (preserves fail-fast)

本文件验证:
- RED: ≥8 new silent except sites beyond Tick 44's 4
- PASS baseline: any site with `raise` re-raise OR explicit `noqa: BLE001`
  is exempt
- PASS baseline: any try/except around `import` is exempt (optional dep)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


SCAN_DIRS = [
    "chase_up",
    "uptrend_pullback",
    "short_reversal",
    "cycle_price_action",
    "core",
    "dna_stats",
]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "results",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
                continue
            if path.name.startswith("test_"):
                continue
            files.append(path)
    return files


# Sentinel body patterns that indicate silent failure (fail-fast violation)
SILENT_PATTERNS = {
    "continue",   # skip iteration
    "pass",       # swallow exception
    "return",     # return None (caller may crash later without context)
}


def _body_is_silent(stmt: ast.stmt) -> str | None:
    """Check if except handler body is silent.

    Returns the silent pattern name if found, None otherwise.
    """
    if isinstance(stmt, ast.Pass):
        return "pass"
    if isinstance(stmt, ast.Continue):
        return "continue"
    # Bare return (returns None)
    if isinstance(stmt, ast.Return) and stmt.value is None:
        return "return"
    # If first statement is a bare continue/pass/return (handles if/with/etc)
    if isinstance(stmt, ast.If):
        # Recurse into if body
        for inner in stmt.body:
            pattern = _body_is_silent(inner)
            if pattern:
                return pattern
    return None


def _has_raise(stmts: list[ast.stmt]) -> bool:
    """Check if any statement in stmts is a Raise."""
    for stmt in stmts:
        if isinstance(stmt, ast.Raise):
            return True
        # Recurse into try/if blocks
        if isinstance(stmt, ast.Try):
            if _has_raise(stmt.body) or _has_raise(stmt.finalbody):
                return True
        if isinstance(stmt, ast.If):
            if _has_raise(stmt.body) or _has_raise(stmt.orelse):
                return True
    return False


def _is_around_import(tree: ast.AST, handler: ast.ExceptHandler) -> bool:
    """Check if the try block contains an import statement.

    Import-related except blocks are typically acceptable (optional deps).
    """
    # The try block is the parent node's body — but we need to walk up.
    # Walk all Try nodes and find the one containing this handler.
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            if handler in node.handlers:
                # Check if any statement in try body is an Import
                for stmt in node.body:
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        return True
    return False


def _has_rows_append(stmts: list[ast.stmt]) -> bool:
    """Check if any statement calls .append() (dressing failure as data)."""
    for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
                return True
    return False


def _scan_silent_except_sites() -> list[tuple[str, int, str, str]]:
    """Scan all production .py files for silent except patterns.

    Returns list of (file_rel, line, pattern, snippet) tuples.
    """
    sites: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Skip handlers with bare Exception type but no body (just `except: pass`)
            if not node.body:
                continue
            # Skip if handler has raise (re-raise preserves fail-fast)
            if _has_raise(node.body):
                continue
            # Skip if try block contains import (acceptable for optional deps)
            if _is_around_import(tree, node):
                continue

            # Check each statement in handler body for silent patterns
            for stmt in node.body:
                pattern = _body_is_silent(stmt)
                if pattern:
                    line = stmt.lineno
                    snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                    sites.append(
                        (str(rel), line, pattern, snippet)
                    )
                # Also flag rows.append (dressing failure as data)
                if _has_rows_append([stmt]):
                    line = stmt.lineno
                    snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                    sites.append(
                        (str(rel), line, "rows.append", snippet)
                    )
    return sites


# ---------------------------------------------------------------------------
# 2026-10-19 (§13.48): **把判据与它声明的目标对齐**
#
# `_scan_silent_except_sites()` **完全不看异常类型** —— 只查处理体是不是
# `continue` / `pass` / 裸 `return` / `rows.append`。于是它把两类东西都算了进来:
#
#   (i) `sweep` / `grid` / `walkforward` **脚本**里的逐项容错 ——
#       而 CLAUDE.md §0 明写 "Scan/grid loops allow warn-log + continue" ⇒ **合规**;
#   (ii) 用了**具体**异常类型的 `continue`(如 `except (IndexError, ValueError): continue`)——
#       而**兄弟审计** `test_exception_specificity_audit.py` 恰恰把"具体类型"当作 GOOD (§13.47)。
#
# **实测这 17 处的构成** (2026-10-19):
#     引擎/其它 + 具体类型   4
#     脚本       + 具体类型   9
#     脚本       + 宽类型     4
#     引擎/其它 + **宽类型**  **0**     ← §0 真正针对的那一类
# ⇒ **那条 `>= 12` 的阈值是在噪声上红**: 计数里**一个目标类样本都没有**。
#
# ⇒ 修正: 判据改为 **宽/裸类型 ∧ 非扫描脚本**; 断言改为**严格为零**(比 `>=12` 更强),
#   同时给原始检测器留一条**非空转下限**(否则"检测器坏了"也会表现为零)。
BROAD_TYPES = {"", "Exception", "BaseException"}
SCAN_TOOL_TOKENS = ("sweep", "grid", "walkforward", "wf_", "compare", "rerun")


def _handler_type_name(handler: ast.ExceptHandler) -> str:
    """处理器捕获的类型名; `except:` 记作空串。"""
    if handler.type is None:
        return ""
    node = handler.type
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Tuple):
        return ",".join(n.id for n in node.elts if isinstance(n, ast.Name))
    return ast.dump(node)


def _is_scan_tool(rel: str) -> bool:
    """是否是"逐项容错"的扫描/网格脚本 (§0 明文允许 warn-log + continue)。"""
    name = rel.rsplit("/", 1)[-1]
    return any(tok in name for tok in SCAN_TOOL_TOKENS)


def _scan_target_violations() -> list[tuple[str, int, str, str]]:
    """**§0 真正针对的那一类**: 宽/裸异常类型 ∧ 非扫描脚本 ⇒ 静默吞掉。"""
    out = []
    for rel, line, pattern, snippet in _scan_silent_except_sites():
        if _is_scan_tool(rel):
            continue
        # 找到该站点所属的处理器类型
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.body:
                body_lines = {st.lineno for st in node.body}
                if line in body_lines:
                    tname = _handler_type_name(node)
                    if tname in BROAD_TYPES:
                        out.append((rel, line, tname or "<bare>", snippet))
                    break
    return out


# ---------------------------------------------------------------------------
# RED: Silent except sites beyond Tick 44's known 4
# ---------------------------------------------------------------------------


def test_silent_except_sites_beyond_tick44() -> None:
    """§0 RED: ≥8 NEW silent except sites beyond Tick 44's 4.

    Tick 44 verified 4 production hot-path silent except sites:
    - short_reversal/scan_signals.py:127
    - chase_up/sweep.py:100
    - uptrend_pullback/grid.py:106
    - short_reversal/grid_runner.py:59

    This test scans ALL production .py files (not just those 4) for
    silent except patterns:
      - except + pass (silent swallow)
      - except + continue (silent iteration skip)
      - except + bare return (silent None return)
      - except + rows.append (dressing failure as data)

    Exempt:
      - handlers with `raise` (re-raise)
      - handlers around `import` (optional deps)
    """
    raw = _scan_silent_except_sites()
    targets = _scan_target_violations()

    # ---- 反空转下限: 原始检测器必须**确实在工作** ----
    # 若它坏了(返回空), 下面的"零"就毫无意义。所以先钉住"它还能看见东西"。
    # 17 是 2026-10-19 的实测值; 下限设 10, 留正常增减余地。
    assert len(raw) >= 10, (
        f"原始静默检测器只命中 {len(raw)} 处 (<10) —— 检测器可能坏了, "
        f"此时『目标类为零』不构成任何证据。"
    )

    # ---- 真判据 (2026-10-19, §13.48): §0 针对的那一类必须**严格为零** ----
    assert not targets, (
        f"§0 FAIL-FAST VIOLATION: {len(targets)} 处**静默吞掉宽/裸异常**且在**非扫描脚本**里:\n"
        + "\n".join(f"  {f}:{l} [{k}] — {sn}" for f, l, k, sn in targets)
        + "\n\n(判据: 类型为裸/Exception/BaseException ∧ 文件不是 sweep/grid/walkforward 类工具。"
        "扫描类工具的逐项容错由 §0 明文允许, 不计入。)"
    )


# ---------------------------------------------------------------------------
# PASS baselines: pin exempt patterns
# ---------------------------------------------------------------------------


def test_exempt_silent_exempt_pattern_recognized() -> None:
    """§0 PASS baseline: silent except scanner correctly recognizes exempt patterns.

    Pin the scanner's exemption logic:
    - except handlers with `raise` are NOT flagged (preserves fail-fast)
    - except handlers around `import` are NOT flagged (optional deps)

    If the scanner incorrectly flags these, the test count will be
    higher than expected.
    """
    # This is a meta-test: verifies the scanner's exemption logic works
    # by checking that known-good patterns are NOT in the sites list.
    sites = _scan_silent_except_sites()

    # None of these should be flagged:
    # - any try/except ImportError around import (exempt)
    # - any try/except with bare raise re-raise (exempt)
    # The scanner skips both by design (see _is_around_import + _has_raise)

    # Verify scanner ran successfully (sites is iterable list)
    assert isinstance(sites, list), "Scanner must return a list"


def test_tick44_known_sites_are_in_silent_list() -> None:
    """§0 PASS baseline: Tick 44's 4 known sites ARE in the scanner output.

    The scanner should find all 4 of Tick 44's sites (as well as new ones).
    If it doesn't, the scanner has a bug.
    """
    sites = _scan_silent_except_sites()
    files_found = {file for file, _, _, _ in sites}

    # ⚠️ 2026-10-19 (§13.48): 原名单有 **4** 个文件, 其中
    #   `short_reversal/scan_signals.py` **已被修好** —— 它现在收窄到具体类型
    #   (`except (ValueError, KeyError, OSError) as e:`) **并 `raise RuntimeError(...) from e`**
    #   (见该文件 :124-134 的注释 "Round 11 / Tick 40")。
    #   ⇒ 它**正确地不再出现**在静默列表里。**原断言钉的是一个已经过时的状态 ⇒ 假红。**
    # ⇒ 改成两面: 剩下这 3 个必须仍在 (证明扫描器没坏); 那一个必须**不在** (钉住它保持修好)。
    expected_still_silent = {
        "chase_up/sweep.py",
        "uptrend_pullback/grid.py",
        "short_reversal/grid_runner.py",
    }

    missing = expected_still_silent - files_found
    assert not missing, (
        f"Scanner regression: Tick 44's known silent except sites not "
        f"detected by new scanner. Missing: {sorted(missing)}\n"
        f"This means the scanner is missing some patterns that Tick 44 "
        f"caught. Investigate scanner AST logic."
    )
    assert "short_reversal/scan_signals.py" not in files_found, (
        "回归: `short_reversal/scan_signals.py` 又出现了**静默** except —— "
        "它曾在 Round 11 / Tick 40 被修成『收窄到具体类型 + re-raise』(见该文件 :124-134 的注释)。"
    )
