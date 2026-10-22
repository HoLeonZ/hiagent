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
- PASS baselines(pin §1 cleanliness):
  - 无**填充方向**类调用:`.bfill()` / `.backfill()` / `.ffill()` / `.pad()`,
    以及 `.fillna(method="bfill")` / `.reindex(..., method="bfill")` /
    `.interpolate(method="bfill")` 这类**委托**写法
  - 无 `.shift(-N)`(含 `shift(periods=-1)` / `shift(n=-1)` 的关键字写法)
  - 无 `.rolling(..., center=True)`(含 `center` 走**位置参数**的写法)

## 附一百三十五(2026-10-21):**同一个操作,合法写法有八种逃掉**

上面三条判据此前只认**一种写法**(方法名 / 第一个位置参数 / `center=` 关键字)。
实测八种**合法**写法全部逃掉(它们与点名形态是同一个操作):

| 逃掉的写法 | 为什么它等价于点名形态 |
|---|---|
| `.backfill()` | `.bfill()` 的别名 |
| `.pad()` | `.ffill()` 的别名 |
| `.fillna(method="bfill")` | **同一个操作换入口** |
| `.reindex(idx, method="bfill")` | 同上 |
| `.interpolate(method="bfill")` | 同上 |
| `.shift(periods=-1)` | 与 `.shift(-1)` 是同一次调用 |
| `.shift(n=-1)` | 同上(旧参数名) |
| `.rolling(5, None, True)` | `center` 走**位置**参数 |

⇒ 这是 §1 明文里"NEVER use `df.bfill()`"的**式**那一半:**只认拼写、不认操作**。
后来者可以**逐字避开明文**而写出同样的前视。已按"操作"识别(`_FILL_METHOD_NAMES` /
`_SHIFT_PERIOD_KWARGS` / `_ROLLING_CENTER_POSITION`),并配一条**反向**判据
(`test_the_banned_forms_guard_does_not_over_fire`)防假报 —— 本册的规矩是**假报比漏报更坏**。

**边界**(不假装覆盖):别名解析不做(`E = "bfill"; df.fillna(method=E)` 逃掉);
`center` 由变量给值(`CENTRE = True`)逃掉;裸 `df.interpolate()`(默认双向)与
`pandas.merge_asof` 之类**未被 §1 点名**的写法不在本守卫范围 —— 它们是否该禁是口径决策,已记。
"""
from __future__ import annotations

import ast
from pathlib import Path
from tests._production_scan import production_python_files as _iter_python_files


REPO_ROOT = Path(__file__).resolve().parents[1]

# 历史(2026-10-15,附十五):当时面是一份**写死的目录清单**;下面是那次补丁的记录。
# 2026-10-15 (audit 附十五): 此前漏掉 `dna_data` 与 `tools` —— 而 `dna_data` 正是
# **产出引擎所消费的 panel** 的那一层:`bfill` / `shift(-1)` 出现在那里,会把前视
# 注入到下游**每一个**回测里,而守卫看不到(它只看引擎、core、dna_stats)。
# 覆盖缺口是静默的:它不会报错,只会让"没被扫到的地方"与"合规"看起来一样。
# `sql/` 未纳入:AstScanner 是 Python AST 实现,SQL 需要另一套检查(已登记)。
# 扫描面是**单源**的:`tests/_production_scan.py`(附一百三十四)。
# 此前本文件自带一份写死的目录清单 —— 4 份清单互不一致:附十五 补的 `dna_data`/`tools`
# 只落到其中 1 份;`test_assert_vs_raise_audit.py` 那份还把 `uptrend_pullback` 拼成了
# `uptrend_pulback`,于是 `base.exists()` 为假、静默跳过 ⇒ 整个族未被扫过。四份也都不含
# 仓库根下的 `.py`。现在面从 `git ls-files` 派生,新包/新顶层脚本自动进面。


# ---------------------------------------------------------------------------
# 禁用的**式**:同一个操作有好几种合法写法,只认方法名会漏(附一百三十五 实测 8 种逃掉)
# ---------------------------------------------------------------------------

#: 填充方向的方法名。`bfill` 是 §1 点名的;`backfill` 是它的别名,`ffill` / `pad` 与它同族 ——
#: 本守卫**一并禁**(比 §1 明文更严;这是有意为之,不是漏)。
_FILL_METHOD_NAMES = frozenset({"bfill", "backfill", "ffill", "pad"})
#: 这些方法用 `method=` 参数**委托**给上面那组:`fillna(method="bfill")` 就是 bfill 本身。
_FILL_VIA_METHOD_KWARG = frozenset({"fillna", "reindex", "interpolate"})
#: `shift` 的周期参数名(pandas 2+ 是 `periods`;旧名 `n`)。
_SHIFT_PERIOD_KWARGS = ("periods", "n")
#: `rolling(window, min_periods, center, …)` —— `center` 的位置参数下标。
_ROLLING_CENTER_POSITION = 2


def _is_negative_literal(node: ast.expr) -> bool:
    """`-1`(UnaryOp)或字面负数(ast 里极少见)。"""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant)
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and node.value < 0)


def _constant_str_lower(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.lower()
    return None


def _line_of(node: ast.AST, source_lines: list[str]) -> tuple[int, str]:
    line = node.lineno
    return line, (source_lines[line - 1].strip() if line <= len(source_lines) else "")


def _find_bfill_calls(tree: ast.AST, source_lines: list[str]) -> list[tuple[int, str, str]]:
    """**填充方向**类调用 —— 含别名与 `method=` 委托写法。

    §1 点名的是 `df.bfill()`。实测(附一百三十五)只认方法名会漏掉这些**合法写法**:

    * **别名**:`.backfill()`(与 `.bfill()` 同义)、`.pad()`(与 `.ffill()` 同义);
    * **委托**:`.fillna(method="bfill")` —— 那就是 bfill 本身,只换了个入口;
      同类还有 `.reindex(..., method="bfill")` 与 `.interpolate(method="bfill")`。

    Returns list of (line_number, method_name, snippet)。
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr in _FILL_METHOD_NAMES:
            line, snippet = _line_of(node, source_lines)
            hits.append((line, attr, snippet))
            continue
        if attr in _FILL_VIA_METHOD_KWARG:
            for kw in node.keywords:
                if kw.arg == "method" and _constant_str_lower(kw.value) in _FILL_METHOD_NAMES:
                    line, snippet = _line_of(node, source_lines)
                    hits.append((line, f"{attr}(method=…)", snippet))
                    break
    return hits


def _find_negative_shift_calls(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """`.shift(-N)` —— 负向移位 = 前视;**含关键字写法**。

    实测(附一百三十五):旧实现只看**第一个位置参数** ⇒ `shift(periods=-1)` 与 `shift(n=-1)`
    这两种合法写法完全逃掉,而它们与 `shift(-1)` 是**同一次调用**。

    Returns list of (line_number, snippet)。
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "shift":
            continue
        negative = any(_is_negative_literal(arg) for arg in node.args[:1])
        if not negative:
            negative = any(
                kw.arg in _SHIFT_PERIOD_KWARGS and _is_negative_literal(kw.value)
                for kw in node.keywords
            )
        if negative:
            hits.append(_line_of(node, source_lines))
    return hits


def _find_center_true_rolling(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """`.rolling(..., center=True)` —— 对称窗口 = 前视;**含位置参数写法**。

    (`rolling(window, min_periods, center, …)` ⇒ `center` 的下标是 2;
     实测 `df.rolling(5, None, True)` 在旧实现下逃掉。)

    Returns list of (line_number, snippet)。
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "rolling":
            continue
        centered = any(
            kw.arg == "center"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        if not centered and len(node.args) > _ROLLING_CENTER_POSITION:
            positional = node.args[_ROLLING_CENTER_POSITION]
            centered = isinstance(positional, ast.Constant) and positional.value is True
        if centered:
            hits.append(_line_of(node, source_lines))
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


def test_no_fill_method_calls_in_production_code() -> None:
    """§1 PASS baseline:**填充方向**类调用 0 处 —— 含别名与 `method=` 委托写法。

    Per CLAUDE.md §1: NEVER use `df.bfill()`. 实测当前 0 处。
    (本判据比 §1 明文更严:连 `ffill` / `pad` 一并禁 —— 见模块 docstring 的说明;
      名字里不再只写 bfill,是为了让**名字与行为一致**。)
    """
    violations = _scan_file_for_pattern("bfill")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} 处填充方向调用"
        f"(`bfill`/`backfill`/`ffill`/`pad`,或 `fillna`/`reindex`/`interpolate` 的 "
        f"`method=` 委托写法)出现在生产代码里:\n" +
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
# 附一百三十五:禁用**式**的牙齿(认"操作",不认拼写)
# ---------------------------------------------------------------------------


def _hit_count(source: str) -> int:
    """把一段源码按三条检测器跑一遍,返回命中总数。"""
    tree = ast.parse(source)
    lines = source.splitlines()
    return (len(_find_bfill_calls(tree, lines))
            + len(_find_negative_shift_calls(tree, lines))
            + len(_find_center_true_rolling(tree, lines)))


def test_the_banned_forms_are_recognised_in_every_legal_spelling() -> None:
    """**牙齿**:§1 点名的三个操作,每种**合法写法**都必须被抓到。

    (下面这 12 条里,前 8 条在本批之前**全部逃掉** —— 见模块 docstring 的附一百三十五。)
    """
    banned = [
        # 填充方向:点名形态 / 别名 / 委托
        "df.bfill()",
        "df.backfill()",
        "df.ffill()",
        "df.pad()",
        "df.fillna(method=\"bfill\")",
        "df.reindex(idx, method=\"bfill\")",
        "df.interpolate(method=\"bfill\")",
        # 负向移位:位置参数 / 关键字参数
        "df.shift(-1)",
        "df.shift(periods=-1)",
        "df.shift(n=-1)",
        # 对称窗口:关键字 / 位置参数
        "df.rolling(5, center=True)",
        "df.rolling(5, None, True)",
    ]
    escaped = [src for src in banned if _hit_count(src) == 0]
    assert not escaped, (
        "这些**合法写法**逃过了 §1 守卫(它们与点名形态是同一个操作):\n  "
        + "\n  ".join(escaped)
    )


def test_the_banned_forms_guard_does_not_over_fire() -> None:
    """**反向**:非禁用写法不得被误报 —— 本册的规矩是**假报比漏报更坏**。"""
    allowed = [
        "df.shift(1)",
        "df.shift(periods=1)",
        "df.rolling(5)",
        "df.rolling(5, min_periods=3)",
        "df.rolling(5, center=False)",
        "df.fillna(0)",
        "df.fillna(method=\"ffil\")",     # 拼错的值,不是合法方法名
        "df.reindex(idx, method=\"nearest\")",
        "df.interpolate(method=\"linear\")",
    ]
    over_fired = [src for src in allowed if _hit_count(src) != 0]
    assert not over_fired, (
        "这些不是禁用写法却被报(假报比漏报更坏):\n  " + "\n  ".join(over_fired)
    )
    assert _hit_count("df.shift(-1, fill_value=0)") == 1, (
        "带额外关键字的负向移位应当被抓到"
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
