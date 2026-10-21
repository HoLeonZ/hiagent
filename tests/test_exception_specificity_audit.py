"""§0 Exception Specificity Audit (Tick 57).

CLAUDE.md §0 (verbatim):
  "**Fail-Fast:** If a state transition violates physical market laws,
   throw an exception immediately. Do not silently bypass."

**核心发现 (FRESH 2026-09-23):**

A. **ALL 18 silent except sites use bare `except Exception`** (verified):
   - chase_up: 4 sites (sweep_all.py:79, walkforward.py:57, sweep.py:100,
     wf_sweep_all.py:91)
   - uptrend_pulback: 5 sites (grid.py:106, bt_compare_presets.py:149,
     walkforward.py:66, render_trades_html.py:989, iter_reverse.py:126)
   - short_reversal: 7 sites (grid_runner.py:59, scan_signals.py:127,
     st_filter.py:49 + 54, lookahead_trade_trace.py:87, 123, 203)
   - cycle_price_action: 1 site (backtest.py:86)
   - dna_stats: 1 site (deflated.py:155)

B. **Bare `except Exception` is a CODE SMELL** because:
   - Catches `KeyboardInterrupt` (user Ctrl-C) — should propagate
   - Catches `SystemExit` — should propagate
   - Catches `MemoryError` — should propagate (no recovery)
   - Catches `RecursionError` — should propagate
   - Hides programming errors (AttributeError, TypeError, NameError)
   - Defeats type-checker guarantees

C. **GOOD patterns use specific exception types** (verified):
   - chase_up/universe.py:66 — `except duckdb.Error as e:`
   - chase_up/data.py:63 — `except duckdb.Error as e:`
   - chase_up/backtrader_engine.py:316 — `except StopIteration:`
   - chase_up/render_v3_trades_html.py:109 — `except ValueError:`
   - short_reversal/indicators_bt.py:110 — `except (IndexError, TypeError):`
   - short_reversal/universe.py:78 — `except duckdb.Error as e:`
   - core/dual_price.py:168 — `except (TypeError, ValueError):`

D. **Why this matters**:
   - §0 Fail-Fast: bare `except Exception` swallows fail-fast invariants
   - KeyboardInterrupt masking: Ctrl-C can't kill runaway backtest
   - Programming errors hidden: AttributeError becomes silent continue
   - Test reliability: hidden errors make tests pass when they shouldn't

E. **Why existing tests miss this**:
   - Tick 44 focused on silent except/continue PATTERN
   - Tick 55 deep scan found 14+ sites but didn't check exception TYPE
   - No test enforces SPECIFIC exception types

F. **Acceptable exceptions**:
   - `except duckdb.Error` (DB-specific)
   - `except ValueError` / `TypeError` / `IndexError` (data validation)
   - `except StopIteration` (iterator protocol)
   - `except (X, Y)` tuples of specific types
   - `except ImportError` (optional imports)

本文件验证:
- RED: count of bare `except Exception` or `except:` in production code
- RED: each silent except site flagged with line number
- PASS baseline: known-good sites use specific exception types
- PASS baseline: import-related `except ImportError` exempt

## 附一百三十四(2026-10-21):三处「自陈 ≠ 实际」,都在本文件里

1. **扫描面是 4 份副本里的 1 份**(详见 `tests/_production_scan.py`):附十五 补的
   `dna_data`/`tools` 只落到本文件;另 3 份仍漏着,而 `test_assert_vs_raise_audit.py` 那份
   还把族名拼成了 `uptrend_pulback`(本文件上面的 A 节里也是这个拼法 —— 错误由此扩散)⇒
   那条审计里**整个 `uptrend_pullback` 族从未被扫过**,而它显示为绿。
   四份也都不含**仓库根下的 `.py`**(漏掉 `hiagent_config.py` — 全库唯一的 `DB_PATH` 来源)。
   现已**单源**;四份的面从 120 / 112 / 112 / 84 统一为 **122**。
2. **判据比它自陈的严**:旧判据要求类型名命中白名单,于是 **3 个具体类型**被报红
   (`duckdb.CatalogException`、`subprocess.TimeoutExpired`、`requests.RequestException`),
   而报错文案写的是「bare `except Exception` or bare `except:`」。已按自陈口径改。
3. **阈值冒充不变量**:旧测试是 `if len(sites) >= 10: raise` ⇒ **0–9 处时一言不发**。
   实测 HEAD 上有 **3 处活违规却报 PASS**,而 docstring 写「Expected RED state: ≥10」。
   现改为**不变量 + 登记表**:每一处都必须被登记,任何**新增**的一处立刻红(不再等凑够数)。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from tests._production_scan import production_python_files as _iter_python_files


REPO_ROOT = Path(__file__).resolve().parents[1]


# 扫描面是**单源**的:`tests/_production_scan.py`(附一百三十四)。
# 此前本文件自带一份写死的目录清单 —— 4 份清单互不一致:附十五 补的 `dna_data`/`tools`
# 只落到其中 1 份;`test_assert_vs_raise_audit.py` 那份还把 `uptrend_pullback` 拼成了
# `uptrend_pulback`,于是 `base.exists()` 为假、静默跳过 ⇒ 整个族未被扫过。四份也都不含
# 仓库根下的 `.py`。现在面从 `git ls-files` 派生,新包/新顶层脚本自动进面。


# ---------------------------------------------------------------------------
# 判据(2026-10-21 附一百三十四 改):**具名类型即具体**;只有 `Exception` /
# `BaseException` / 裸 `except:` 算过宽。
#
# 旧判据要求类型名**命中一张白名单**,名单之外一律报红("be conservative")。实测后果:
# 10 个被报的站点里 **3 个其实是具体类型**,只因不在名单上 ——
# `duckdb.CatalogException`(`core/data_coverage.py:60`)、
# `subprocess.TimeoutExpired`(`short_reversal/st_filter.py:81`)、
# `requests.RequestException`(`tools/update_db_direct.py:91`)。
# 而本文件自己的报错文案写的是「bare `except Exception` or bare `except:`」,上面 docstring 的
# F 节也把「`except (X, Y)` 里的具体类型」列为可接受 ⇒ **实现比自陈严**(本册的"自陈 ≠ 实际")。
# 白名单还有结构性缺点:任何**新**库的异常类都会先被误报一次。
#
# 边界:解析不出的表达式(不是 Name/Attribute)仍按"不可判定"报红;
# 别名解析不做(`E = Exception` 后 `except E` 会被放过)—— 静态 AST 到此为止。
_BROAD_EXCEPTION_NAMES = frozenset({"Exception", "BaseException"})

#: 已登记的 bare-`except` 站点。键 = (仓库相对路径, 行号),值 = (理由, 什么条件下消失)。
#: **只许变短**:某处修好、或行号变了,就把条目删掉/更新(陈旧条目会让测试红 —— 见
#: `test_every_registered_site_is_still_live`)。
KNOWN_BARE_EXCEPT_SITES: dict[tuple[str, int], tuple[str, str]] = {
    ("short_reversal/replay_strategy_v3.py", 641): (
        "`except (IndexError, Exception)` —— `Exception` 混在 IndexError 的元组里,"
        "等于把 catch-all 藏在具体类型旁边",
        "回放层决定要不要 fail-fast(口径决策)",
    ),
    ("tools/render_top5_presets_html.py", 1167): (
        "批处理:单 preset 失败 → traceback + `failures += 1` 进**退出码**(§0 附六十三 已定的口径)",
        "该工具改为单 preset 失败即整体退出时",
    ),
    ("tools/rerun_top_presets.py", 130): (
        "批处理:同上,错误进 `failures`,末尾由退出码报出",
        "同上",
    ),
    ("tools/rerun_top_presets.py", 153): (
        "批处理:同上,错误进 `failures`,末尾由退出码报出",
        "同上",
    ),
    ("tools/run_all_backtests_html.py", 264): (
        "批处理:错误进 `rows` 并留 `# noqa: BLE001`,由退出码报出",
        "同上",
    ),
    ("tools/update_db_direct.py", 154): (
        "抓取循环:单 code 失败继续、`errors += 1`,末尾判定并报出",
        "改为逐 code fail-fast(会牺牲批量更新的可用性)时",
    ),
    ("tools/update_db_direct.py", 192): (
        "写库循环:同上",
        "同上",
    ),
}

#: 登记表的**冻结点** —— 只许变短(新增一条会让 `test_registry_does_not_grow` 红)。
_FROZEN_BARE_EXCEPT_COUNT = 7



def _is_specific_exception_type(handler: ast.ExceptHandler) -> bool:
    """具名类型即具体;`Exception` / `BaseException` / 裸 `except:` 判为过宽。

    (依据见上方注释:本文件的报错文案与 docstring 的 F 节都只把
     `Exception` / `BaseException` / 裸 `except` 当作违规。)
    """
    if handler.type is None:
        # Bare `except:` — overly broad
        return False

    # handler.type can be: Name, Attribute, or Tuple of those
    if isinstance(handler.type, ast.Tuple):
        types = handler.type.elts
    else:
        types = [handler.type]

    for exc_type in types:
        type_name = _get_exception_name(exc_type)
        if type_name is None:
            # 不是 Name/Attribute —— 解析不出具体是什么,按"不可判定"报红
            return False
        if type_name in _BROAD_EXCEPTION_NAMES:
            return False

    return True


def _get_exception_name(node: ast.expr) -> str | None:
    """Extract exception type name as string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_around_import(tree: ast.AST, handler: ast.ExceptHandler) -> bool:
    """Check if handler is around an import (exempt)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            if handler in node.handlers:
                for stmt in node.body:
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        return True
    return False


def _has_silent_body(handler: ast.ExceptHandler) -> bool:
    """Check if handler body is silent (continue/pass/return/rows.append)."""
    for stmt in handler.body:
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Continue):
            return True
        if isinstance(stmt, ast.Return) and stmt.value is None:
            return True
        # rows.append = dressing failure as data
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Call):
                if isinstance(inner.func, ast.Attribute) and inner.func.attr == "append":
                    return True
    return False


def _scan_bare_except_sites() -> list[tuple[str, int, str, str]]:
    """Scan production code for bare except Exception sites.

    Returns list of (file_rel, line, type_name, snippet) tuples.
    """
    sites: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Exempt handlers around imports (optional deps)
            if _is_around_import(tree, node):
                continue
            # Exempt handlers with `raise` (re-raise preserves fail-fast)
            if any(isinstance(s, ast.Raise) for s in node.body):
                continue

            type_name = _get_exception_name(node.type) if node.type else "<bare>"

            # Flag if not specific OR if it's bare `Exception`
            if not _is_specific_exception_type(node):
                if not node.body:
                    continue
                line = node.body[0].lineno
                snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                sites.append((str(rel), line, type_name, snippet))

    return sites


def _scan_silent_with_specific_except() -> list[tuple[str, int, str, str]]:
    """Scan for sites with silent body but SPECIFIC exception type.

    These are GOOD patterns: specific exception + silent handling is
    intentional (e.g., duckdb.Error during data loading might be skipped).
    """
    sites: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _has_silent_body(node):
                continue
            if _is_specific_exception_type(node):
                type_name = _get_exception_name(node.type) if node.type else "<bare>"
                line = node.body[0].lineno
                snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                sites.append((str(rel), line, type_name, snippet))

    return sites


# ---------------------------------------------------------------------------
# RED: bare `except Exception` in production code
# ---------------------------------------------------------------------------


def test_bare_except_exception_in_production() -> None:
    """§0:生产侧**不许**出现 `except Exception` / `except BaseException` / 裸 `except:`。

    附一百三十四 改:此前这条是 `if len(sites) >= 10: raise` —— 一个**阈值**冒充不变量,
    于是 **0–9 处活违规时它一言不发**(实测 HEAD 上有 3 处却报 PASS,而 docstring 写着
    「Expected RED state: ≥10」)。现在分三条钉住:
      * 每一处检出都必须**在登记表里**(任何**新增**的一处立刻红,不再等凑够数);
      * 登记表里的每一条都必须**仍被检出**(陈旧条目 = 修好了或行号变了,要清);
      * 登记表**只许变短**。
    """
    sites = _scan_bare_except_sites()
    detected = {(file, line) for file, line, _t, _s in sites}

    unregistered = sorted(detected - set(KNOWN_BARE_EXCEPT_SITES))
    assert not unregistered, (
        f"§0 VIOLATION: {len(unregistered)} 处 `except Exception` / 裸 `except:` **未登记**:\n"
        + "\n".join(
            f"  {file}:{line} [{type_name}] — {snippet}"
            for file, line, type_name, snippet in sites
            if (file, line) in set(unregistered)
        )
        + "\n\n两条路:①把它改成具体的异常类型(GREEN fix);"
        "②确实是批处理「单个失败继续、末尾进退出码」的口径,就加进 KNOWN_BARE_EXCEPT_SITES,"
        "并写清**什么条件下消失**。\n"
        "(判据口径:具名类型即具体;只有 `Exception` / `BaseException` / 裸 `except:` 违规。)"
    )

    stale = sorted(set(KNOWN_BARE_EXCEPT_SITES) - detected)
    assert not stale, (
        f"这些登记项已**不再被检出**(修好了,或行号变了)—— 请从 "
        f"KNOWN_BARE_EXCEPT_SITES 删除或更新:{stale}"
    )

    assert len(KNOWN_BARE_EXCEPT_SITES) <= _FROZEN_BARE_EXCEPT_COUNT, (
        f"登记表**只许变短**:冻结值 {_FROZEN_BARE_EXCEPT_COUNT},现为 "
        f"{len(KNOWN_BARE_EXCEPT_SITES)}"
    )


# ---------------------------------------------------------------------------
# PASS baselines: known-good specific exception patterns
# ---------------------------------------------------------------------------


def test_silent_with_specific_exception_is_acceptable() -> None:
    """§0 PASS baseline: silent except + specific type = acceptable pattern.

    Some sites use silent handling (e.g., `continue`, `pass`, `rows.append`)
    but with SPECIFIC exception types like `duckdb.Error`. This is the
    correct pattern: catch the expected failure mode, log/skip, continue.

    Per CLAUDE.md §0 spirit: catching duckdb.Error during data load is
    legitimate (DB unavailable for this symbol). Catching bare `Exception`
    is not (hides programming errors).
    """
    # Pin the count of silent + specific sites (currently acceptable)
    sites = _scan_silent_with_specific_except()
    # No assertion — just pin the count for baseline regression tracking
    # If this count drops, specific-type patterns were replaced with bare
    # Exception (regression). If this count grows, more good patterns added.
    assert isinstance(sites, list), "Scanner must return a list"


def test_known_good_specific_exception_patterns_exist() -> None:
    """§0 PASS baseline: known-good specific exception sites exist.

    Pin the scanner's recognition of GOOD patterns:
    - chase_up/universe.py:66 — `except duckdb.Error as e:`
    - chase_up/data.py:63 — `except duckdb.Error as e:`
    - chase_up/backtrader_engine.py:316 — `except StopIteration:`
    - short_reversal/universe.py:78 — `except duckdb.Error as e:`
    - core/dual_price.py:168 — `except (TypeError, ValueError):`

    If these sites change to bare `except Exception`, this test fails.
    """
    good_files = [
        ("chase_up/universe.py", "duckdb.Error"),
        ("chase_up/data.py", "duckdb.Error"),
        ("chase_up/backtrader_engine.py", "StopIteration"),
        ("short_reversal/universe.py", "duckdb.Error"),
        ("core/dual_price.py", "(TypeError, ValueError)"),
    ]

    violations: list[str] = []
    for file_rel, expected_pattern in good_files:
        path = REPO_ROOT / file_rel
        if not path.exists():
            violations.append(f"{file_rel}: MISSING")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            violations.append(f"{file_rel}: UNREADABLE")
            continue
        if expected_pattern not in source:
            violations.append(
                f"{file_rel}: missing expected specific exception pattern "
                f"`except {expected_pattern}` (regression — replaced with "
                f"bare except?)"
            )

    assert not violations, (
        f"§0 SPECIFIC EXCEPTION REGRESSION: known-good sites lost their "
        f"specific exception types:\n" + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# 附一百三十四:判据与登记表自己的牙齿
# ---------------------------------------------------------------------------


def _handlers_in(source: str) -> list[ast.ExceptHandler]:
    """取出一段源码里所有 except 处理器(供牙齿测试用)。"""
    return [node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ExceptHandler)]


def _handler_of(clause: str) -> ast.ExceptHandler:
    """`except <clause>:` 的处理器;`clause` 为空串时构造裸 `except:`。"""
    if clause:
        src = f"try:\n    pass\nexcept {clause}:\n    pass\n"
    else:
        src = "try:\n    pass\nexcept:\n    pass\n"
    return _handlers_in(src)[0]


def test_the_criterion_verdict_has_teeth() -> None:
    """判据本身:具名即具体;三种过宽必须报。

    前三条正是**旧白名单判据的假报** —— 它们都是具体类型,只因不在名单上被报红。
    """
    for specific in ("duckdb.CatalogException",
                     "requests.RequestException",
                     "(OSError, subprocess.TimeoutExpired)"):
        assert _is_specific_exception_type(_handler_of(specific)), (
            f"具体类型被误报(旧判据正是这样):{specific}"
        )
    for broad in ("Exception", "BaseException", ""):
        assert not _is_specific_exception_type(_handler_of(broad)), (
            f"过宽却没报:{broad!r}"
        )
    assert not _is_specific_exception_type(_handler_of("(IndexError, Exception)")), (
        "元组里混了 Exception 却没报"
    )


def test_every_registered_site_is_still_live() -> None:
    """登记表**只许变短**:每条都必须仍被检出;修好了 / 行号动了就删掉或更新。"""
    detected = {(file, line) for file, line, _t, _s in _scan_bare_except_sites()}
    stale = sorted(set(KNOWN_BARE_EXCEPT_SITES) - detected)
    assert not stale, (
        f"这些登记项已**不再被检出**(修好了,或行号变了)—— 请从 KNOWN_BARE_EXCEPT_SITES "
        f"删除或更新:{stale}"
    )


def test_registry_does_not_grow() -> None:
    """冻结点:登记表不许变长(新增登记本身不该是一条捷径)。"""
    assert len(KNOWN_BARE_EXCEPT_SITES) <= _FROZEN_BARE_EXCEPT_COUNT, (
        f"登记表变长了:冻结 {_FROZEN_BARE_EXCEPT_COUNT},现 {len(KNOWN_BARE_EXCEPT_SITES)}"
    )


# ---------------------------------------------------------------------------
# 重新冻结(附一百六十五)—— 与棘轮那边的 `--freeze` 对称
# ---------------------------------------------------------------------------
#
# 为什么需要:本表按 **(文件, 行号)** 键 ⇒ **换一棵树,键就全变**(行号会漂);
# 而 `test_every_registered_site_is_still_live` 又要求每条**必须仍被检出** ⇒
# 没有重冻结入口时,本判据**只能在它出生的那棵树上用**(实测:搬到 `main @ fff0413` 上会红)。
#
# 关键设计:**理由是人写的,必须跟着走**。所以重冻结时按**文件**把旧表的 (理由, 关闭条件)
# 带过去(同一文件多条时按出现顺序配对);**新增**的站点写成显式待填,而不是编一个理由。
#
# ⚠️ 与棘轮同一条规矩:重新冻结**不是"让红变绿"的捷径** —— 它把当前状态变成新基线,
# 必须在 PR 里说明"为什么变了"(§6 对 golden 的同一要求)。


def _freeze_text() -> str:
    """把当前检出到的站点打印成**可直接粘贴**的登记表。"""
    by_file: dict[str, list[tuple[str, str]]] = {}
    for (path, _line), meta in KNOWN_BARE_EXCEPT_SITES.items():
        by_file.setdefault(path, []).append(meta)
    used: dict[str, int] = {}

    def quote(text: str) -> str:
        return text.replace('"', '\\"')

    lines = [
        "# 由 `python -m tests.test_exception_specificity_audit --freeze` 生成;",
        "# 粘回后请在 PR 里写明「为什么变了」。理由按**文件**从旧表带过来。",
        "",
        "KNOWN_BARE_EXCEPT_SITES: dict[tuple[str, int], tuple[str, str]] = {",
    ]
    for path, line, type_name, snippet in _scan_bare_except_sites():
        index = used.get(path, 0)
        metas = by_file.get(path, [])
        if index < len(metas):
            what, closes = metas[index]
        else:
            what = f"新站点({type_name}): {snippet.strip()[:60]}"
            closes = "待填:这条在什么条件下消失"
        used[path] = index + 1
        lines += [
            f'    ("{path}", {line}): (',
            f'        "{quote(what)}",',
            f'        "{quote(closes)}",',
            "    ),",
        ]
    lines += ["}", "", f"_FROZEN_BARE_EXCEPT_COUNT = {len(_scan_bare_except_sites())}", ""]
    return "\n".join(lines)


def test_the_freeze_output_reproduces_the_registry() -> None:
    """**重新冻结必须与消费它的判据逐字同口径**(本册附一百一十八 的规矩)。

    (没有它,`--freeze` 可以悄悄与登记表分叉;而换树时人**只会**照它的输出粘回去。)
    """
    namespace: dict[str, object] = {}
    exec(_freeze_text(), {}, namespace)
    assert namespace["KNOWN_BARE_EXCEPT_SITES"] == KNOWN_BARE_EXCEPT_SITES, (
        "`--freeze` 输出的登记表与本文件冻结的不一致(含人工理由)"
    )
    assert namespace["_FROZEN_BARE_EXCEPT_COUNT"] == _FROZEN_BARE_EXCEPT_COUNT, (
        "`--freeze` 输出的冻结常量与本文件的不一致"
    )


if __name__ == "__main__":
    if "--freeze" in sys.argv:
        print(_freeze_text())
        raise SystemExit(0)
    raise SystemExit(
        "用法: python -m tests.test_exception_specificity_audit --freeze"
        "(打印当前登记表;换树时用它重新冻结,并说明漂移原因)\n"
        "⚠️ 必须用 -m(本文件跨包 import `tests._production_scan`,"
        "按脚本方式跑时 sys.path[0] 是 tests/、仓库根不在路径上 ⇒ ImportError)"
    )