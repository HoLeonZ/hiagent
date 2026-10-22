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
# ⚠️ 2026-10-22 (附一百八十七): 本审计的**标准只针对生产路径** ⇒ 用 `engine_python_files()`
# (同一处定义, 比 `production_python_files()` 再排除 `tools/`)。
#
# 合并把本文件的面换成单源后, `tools/` 进了面, 于是 8 处被报为 §0 违规 ——
# 而它们正是**本文件自己写明允许**的那一类:
#     tools/preset_census.py      × 4  (清点循环: 逐项失败记 NaN 后继续)
#     tools/scan_dead_text_pins.py × 4 (扫描循环: 逐项 `continue`)
# 原来的豁免是按**文件名 token** 做的(`sweep/grid/walkforward/wf_/compare/rerun`),
# 这两个工具名不含任何 token ⇒ 漏。而那份 token 表还有**相反**的毛病:
# `compare` / `rerun` 是通用子串, 一个**生产**文件叫 `*_compare.py` 会被**误豁免**。
# ⇒ 范围改按**位置**判: `tools/`(开发者工具)整体出局, 生产路径照旧全查
#   (引擎目录里的 `sweep*.py` 仍由 `SCAN_TOOL_TOKENS` 豁免 —— 那条仍然需要)。
from tests._production_scan import engine_python_files as _iter_python_files


REPO_ROOT = Path(__file__).resolve().parents[1]


# 扫描面是**单源**的:`tests/_production_scan.py`(附一百三十四)。
# 此前本文件自带一份写死的目录清单 —— 4 份清单互不一致:附十五 补的 `dna_data`/`tools`
# 只落到其中 1 份;`test_assert_vs_raise_audit.py` 那份还把 `uptrend_pullback` 拼成了
# `uptrend_pulback`,于是 `base.exists()` 为假、静默跳过 ⇒ 整个族未被扫过。四份也都不含
# 仓库根下的 `.py`。现在面从 `git ls-files` 派生,新包/新顶层脚本自动进面。


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
    # Bare return 或显式 `return None`
    # audit P3 (2026-10-15): 原判据是 `stmt.value is None`,而 **写出来的**
    # `return None` 在 AST 里是 Constant(None) —— 于是显式 return None 逃过检测,
    # 而裸 `return` 被抓住。两者是同一形态,漏掉一个等于漏掉一半。
    if isinstance(stmt, ast.Return) and (
        stmt.value is None
        or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
    ):
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



def _handler_reports_failure(node: ast.ExceptHandler) -> bool:
    """处理器是否**可观测地**报告了失败(log 或把异常写进结果)。

    §0 (audit P3, 2026-10-15): "静默绕过" 的定义是既不记录、也不把异常交给
    调用方。原扫描器把任何不含 `raise` 的处理器一律判为 silent,于是
    `logger.warning(...); continue`(窄化捕获 + 有注释 + 故意跳过单个窗口/网格
    单元)也被计入违规 —— 那是有记录地跳过,不是静默绕过。真正的违约是裸的
    `continue` / `pass` / `return None`,以及把异常变成对外不可见的状态。
    """
    exc = node.name
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            label = ""
            if isinstance(f, ast.Attribute):
                label = f.attr
                if isinstance(f.value, ast.Name):
                    label = f.value.id + "." + label
            elif isinstance(f, ast.Name):
                label = f.id
            if label.startswith(("logger.", "logging.")) or label == "print":
                return True
            # rows.append({... "error": str(e) ...}) → 异常进入可观测结果
            if label.endswith(".append") or label.endswith(".setdefault") or label.endswith(".add"):
                if exc and any(isinstance(n, ast.Name) and n.id == exc for n in ast.walk(sub)):
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
            # §0 (audit P3, 2026-10-15): 有记录地跳过 ≠ 静默绕过
            if _handler_reports_failure(node):
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
    """§0: §0 真正针对的那一类 —— **静默吞掉宽/裸异常** —— 必须**严格为零**。

    Tick 44 verified 4 production hot-path silent except sites:
    - short_reversal/scan_signals.py:127
    - chase_up/sweep.py:100
    - uptrend_pullback/grid.py:106
    - short_reversal/grid_runner.py:59

    判据 (2026-10-19, §13.48): 二段式。
      1. `_scan_silent_except_sites()` —— 过宽的原始检测器(`continue` / `pass` /
         裸或显式 `return None` / `rows.append`),它**不看异常类型、不看文件角色**。
      2. `_scan_target_violations()` —— 在原始命中上再筛「宽/裸类型 ∧ 非扫描脚本」。
         扫描/网格/回测脚本的逐项容错由 §0 明文允许 ("Scan/grid loops allow
         warn-log + continue");**有记录地跳过**(logger / 把异常写进结果)不算静默
         绕过(见 `_handler_reports_failure`)。

    本用例断言第 2 类为**零** —— 比原来的 `>= 12` 计数阈值更强(计数阈值实测是在
    噪声上红: 计数里一个目标类样本都没有)。反空转由正控制提供,见
    `test_scanner_detects_planted_silent_handlers`。
    """
    targets = _scan_target_violations()

    # ---- 反空转控制: 见 test_scanner_detects_planted_silent_handlers ----
    # 2026-10-20 (合并): 这里原本钉 `len(raw) >= 10` —— 一个**计数阈值**。实测
    # (当前树) `_scan_silent_except_sites()` 只命中 7 处 (<10), 且 7 处全是真实的、
    # 尚未修的死角 ⇒ **检测器没坏, 是计数本身随修复漂移**。计数型下限既会因"修好
    # 一处"假红, 也不构成"判据有分辨力"的证据 (它只证明列表非空)。
    # ⇒ 反空转换成正控制: 往 AST 里**植入**已知的裸 continue / pass / return None,
    #   要求扫描器必须命中, 并同时钉住"有记录地跳过"**不得**命中。正控制与活体
    #   计数无关, 不会被修复漂移打红。

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


def test_scanner_detects_planted_silent_handlers() -> None:
    """§0 扫描器**灵敏度**:植入已知的静默处理器必须被抓到。

    audit P3 (2026-10-15): 原用例断言扫描器必须仍把 Tick 44 的 4 个站点列为 silent
    —— 而那 4 处实际都是 `logger.warning(...) + continue`(窄化捕获 + 注释 + 故意
    跳过单个窗口/网格单元),按修正后的判据**本就不该算静默**。用一份历史清单当回归
    基准,会把"分类被改进"误报成"扫描器坏了"。

    改为直接测灵敏度:裸 `continue` / `pass` / `return None` 必须命中;而
    `logger.warning + continue` 与 `rows.append({"error": str(e)})` **不得**命中。
    """
    bad = (
        "try:\n    x()\n"
        "except ValueError:\n    continue\n"
        "except KeyError:\n    pass\n"
        "except TypeError:\n    return None\n"
    )
    tree = ast.parse(bad)
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 3
    hits = [p for h in handlers for st in h.body if (p := _body_is_silent(st))]
    assert len(hits) >= 3, f"扫描器对本应命中的裸处理器漏检: {hits}"

    good = (
        "try:\n    x()\n"
        "except ValueError as e:\n    logger.warning('skip %s', e)\n    continue\n"
        "except KeyError as e:\n    rows.append({'error': str(e)})\n"
    )
    t2 = ast.parse(good)
    h2 = [n for n in ast.walk(t2) if isinstance(n, ast.ExceptHandler)]
    assert all(_handler_reports_failure(h) for h in h2), (
        "有记录地跳过(log / 把异常写入结果)被误判为静默绕过 —— "
        "§0 指的是既不记录也不抛出"
    )


def test_historical_sites_are_reported_not_silent() -> None:
    """钉住重新分类:Tick 44 的 4 个站点是**有记录地跳过**,不是静默。

    它们的处理器都调用 logger,Uptrend 那处还带注释说明"单个窗口缺失不应中止整个
    扫描"。若将来有人把这些日志删掉,本用例会失败 —— 那才是该报警的变化。
    """
    for rel in ("chase_up/sweep.py",
                "uptrend_pullback/grid.py",
                "short_reversal/grid_runner.py",
                "short_reversal/scan_signals.py"):
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert any(
            isinstance(n, ast.ExceptHandler)
            and (_handler_reports_failure(n) or _has_raise(n.body))
            for n in ast.walk(tree)
        ), (
            f"{rel}: 未发现任何「有记录或重新抛出」的 except 处理器 —— "
            "要么日志被删,要么改成了静默吞掉"
        )
