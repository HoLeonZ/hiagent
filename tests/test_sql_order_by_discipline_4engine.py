"""§1 SQL ORDER BY Discipline in Production Control Plane (Tick 68).

CLAUDE.md §1 (verbatim):
  "Time is a strictly monotonic, first-class citizen."

CLAUDE.md §6 (verbatim):
  "**Control Plane / Orchestrator:** Manages time-stepping and PIT data
   dispatching."

**核心发现 (FRESH 2026-09-23):**

A. **§1 SQL time-series monotonicity mandate**:
   - Any SQL query that produces time-series data MUST end with
     ORDER BY timestamp (or equivalent monotonic column)
   - Without ORDER BY, row order is implementation-defined (often
     insertion order, not temporal order)
   - If Control Plane ingests unordered rows:
     - iterrows() iterates in arbitrary order
     - Strategy may compute today's signal using yesterday's data
     - PIT mandate silently violated

B. **Per [[reproducibility-audit-2026-09-23]] Tick 36**:
   - cycle_price_action/data_feed.py:52 — MISSING ORDER BY
   - This is the EXECUTABLE FINDING that motivates this tick
   - Other engines' SQL queries need similar audit

C. **Detector scope (Tick 68)**:
   - Scan production files for SQL query patterns
   - Look for SELECT statements (regex on string literals)
   - For each SELECT, verify ORDER BY is present
   - PASS if all time-series queries have ORDER BY
   - RED if any time-series query lacks ORDER BY

D. **SQL pattern detection**:
   - Detect via Python string literals (triple-quoted SELECT blocks)
   - Look for `ORDER BY` clause
   - Identify "time-series" queries (queries selecting date/timestamp
     columns from kline/bar/trade tables)

E. **Out-of-scope (deferred)**:
   - Aggregation queries (COUNT/SUM/AVG) — naturally don't need ORDER BY
   - Lookup queries (WHERE single id) — don't need ORDER BY
   - Tick 68 focuses on time-series producing queries only

F. **Why this matters**:
   - §1 Temporal Determinism: time is strictly monotonic
   - §6 Control Plane: PIT data dispatching must be ordered
   - Without ORDER BY, SQL is non-deterministic across DB engines
   - SQLite vs DuckDB vs PostgreSQL return different orderings
   - Backtest becomes non-reproducible across DBs

G. **Tick 68 expected results**:
   - 4 PASS: each engine's SQL queries (when time-series) have ORDER BY
   - 0 RED expected (chase/uptrend/short_reversal may be compliant;
     cycle has 1 known missing ORDER BY per Tick 36)
   - If cycle RED found, that's CONFIRMED the Tick 36 finding
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production files with SQL queries (per-engine)
SQL_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "data.py",
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "data.py",
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "data.py",
        REPO_ROOT / "short_reversal" / "engine.py",
        REPO_ROOT / "short_reversal" / "scan_signals.py",
        REPO_ROOT / "short_reversal" / "scan_signals_fast.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "data_feed.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
    ],
}


# SQL query extraction regex (matches triple-quoted strings with SELECT)
SQL_TRIPLE_QUOTE_RE = re.compile(
    r'"""(.*?SELECT[^"]*?)"""',
    re.DOTALL | re.IGNORECASE,
)
SQL_SINGLE_QUOTE_RE = re.compile(
    r"'''(.*?SELECT.*?)'''",
    re.DOTALL | re.IGNORECASE,
)


def _is_time_series_query(query: str) -> bool:
    """Determine if a SQL query produces time-series output.

    Heuristic:
    - Extract SELECT clause (between SELECT and FROM)
    - If SELECT clause has bare `date` / `timestamp` column (not
      wrapped in MAX/MIN/SUM/AVG/COUNT) → time-series
    - Pure aggregation queries (no bare date column in SELECT) →
      not time-series (output is scalar or per-group aggregate)
    """
    q_lower = query.lower()
    if "select" not in q_lower:
        return False

    # Find SELECT clause: between first SELECT and FROM
    select_match = re.search(r"\bselect\b(.*?)\bfrom\b", q_lower, re.DOTALL)
    if not select_match:
        # SELECT without FROM (e.g., SELECT 1) — not time-series
        return False
    select_clause = select_match.group(1)

    # Find time-series tables
    time_series_table = any(
        kw in q_lower
        for kw in (
            "kline",
            "bar",
            "trade",
            "ohlc",
            "raw_kline",
            "v_daily",
            "panel",
            "universe",
        )
    )

    # Look for bare `date` / `timestamp` column (not aggregated)
    # Strip aggregation function calls first
    select_no_aggs = re.sub(
        r"\b(?:MAX|MIN|SUM|AVG|COUNT)\s*\([^)]*\)",
        "",
        select_clause,
        flags=re.IGNORECASE,
    )
    has_bare_date = bool(re.search(
        r"\b(?:date|timestamp|trade_date|bar_date)\b",
        select_no_aggs,
    ))

    # Time-series iff: queries a time-series table AND selects bare date
    return time_series_table and has_bare_date


_OVER_RE = re.compile(r"\bOVER\s*\(", re.IGNORECASE)


def _strip_window_clauses(sql: str) -> str:
    """去掉所有 `OVER (...)` 窗口子句。

    ⚠️ §13.73: 窗口子句里的 `ORDER BY` **只排窗口内的行, 不决定结果集的行序**
    (`ROW_NUMBER() OVER (PARTITION BY code ORDER BY date)` 里的那个)。
    因此它**不满足** §1 的"结果集行序确定"要求。
    **注入实证**: 删掉 `chase_up/data.py` 的**顶层** `ORDER BY` (保留窗口里那个)
    ⇒ 改动前 **7 passed 不响**。
    """
    out: list[str] = []
    i = 0
    while True:
        m = _OVER_RE.search(sql, i)
        if not m:
            out.append(sql[i:])
            break
        out.append(sql[i:m.start()])
        j = m.end() - 1                      # 指向 '('
        depth = 0
        while j < len(sql):
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1
    return "".join(out)


def _has_order_by(query: str) -> bool:
    """Check if SQL query has a **顶层** ORDER BY clause (窗口子句里的不算, §13.73)。"""
    return bool(re.search(r"\bORDER\s+BY\b", _strip_window_clauses(query), re.IGNORECASE))


def _collect_strings(node, out) -> None:
    """收集字符串字面量 —— **遇到 JoinedStr 不再下钻**。

    ⚠️ 这一条是本函数最重要的一行。f-string 在 AST 里是 `JoinedStr`, 它的字面量部分
    是**若干个分散的 `ast.Constant`**。若逐个 `Constant` 去判"有没有 ORDER BY",
    那么 `ORDER BY` 落在**另一个片段**里 ⇒ **一条合规的查询会被误判成违规**。
    (本仓库的 `cycle_price_action/data_feed.py` 里就留着这条教训的注释:
     "multi-line f-strings split into multiple Constants, hiding ORDER BY from the
      AST-based auditor"。)
    **2026-10-19 (§13.42): 我写这一版之前, 第一版扫描器正是栽在这里 —— 它在全库报出
    3 处"缺 ORDER BY", 而修正后是 0 处。差一点去"修"三个本来就正确的文件。**
    """
    import ast

    if isinstance(node, ast.JoinedStr):
        out.append((
            "".join(
                x.value for x in node.values
                if isinstance(x, ast.Constant) and isinstance(x.value, str)
            ),
            node.lineno,
        ))
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append((node.value, node.lineno))
        return
    for child in ast.iter_child_nodes(node):
        _collect_strings(child, out)


# 扫描时跳过的目录 —— **不是"只扫这几个", 而是"只排除这几个"**。
# ⚠️ 2026-10-19 (§13.42): 本函数此前用一张**手写的 `SQL_FILES` 字典**枚举要扫哪些文件
# (`data.py` / `portfolio.py` / `backtrader_engine.py` / `engine.py` / `scan_signals*.py` /
# `data_feed.py` / `replay_broker.py`)。那张表**就是"作者当时想起来的那几个文件"** ——
# 于是 `tools/` / `core/**` / `dna_data/` / 各种 `render_*.py` **从来不在扫描范围内**。
# 这与 §13.22/§13.23 记过的形态是同一个: **守卫的覆盖面 = 作者已修过的东西。**
# ⇒ 改为**遍历仓库**, 只按目录排除。
SKIP_DIRS = {".git", "__pycache__", ".claude", "node_modules", "worktrees", "tests"}


def _scan_sql_queries() -> dict[str, list[tuple[str, int, str, bool]]]:
    """**发现式**扫描: 遍历仓库里所有 `.py`, 找**时序 SQL** 里缺 ORDER BY 的。

    Returns dict[顶层目录 → list of (file, line, query_snippet, has_order_by)]
    (键由 `chase_up` / `uptrend_pullback` / ... 变成顶层目录名, 四个既有测试仍可过滤。)
    """
    import ast

    results: dict[str, list[tuple[str, int, str, bool]]] = {}

    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        key = path.relative_to(REPO_ROOT).parts[0]

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        docstring_end = 0
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            docstring_end = tree.body[0].end_lineno or 0

        strings: list[tuple[str, int]] = []
        _collect_strings(tree, strings)

        for query, line in strings:
            if line <= docstring_end or len(query) < 20:
                continue
            stripped = query.strip().lower()
            if not (stripped.startswith("select") or stripped.startswith("with ")):
                continue
            if not _is_time_series_query(query):
                continue
            results.setdefault(key, []).append((
                str(path.relative_to(REPO_ROOT)),
                line,
                query.strip()[:120].replace("\n", " "),
                _has_order_by(query),
            ))

    return results


# ---------------------------------------------------------------------------
# PASS baselines: time-series SQL queries have ORDER BY
# ---------------------------------------------------------------------------


def test_chase_up_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: chase_up SQL queries (time-series) have ORDER BY.

    Per CLAUDE.md §1: SQL queries producing time-series data must
    end with ORDER BY timestamp to guarantee monotonic delivery.
    """
    results = _scan_sql_queries()
    chase = results["chase_up"]

    # Filter to time-series queries WITHOUT order by
    missing = [v for v in chase if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: chase_up has {len(missing)} time-series "
        f"SQL queries without ORDER BY clause.\n"
        f"Per CLAUDE.md §1: time-series queries MUST end with "
        f"ORDER BY timestamp for monotonic delivery.\n"
        f"Per CLAUDE.md §6: Control Plane requires ordered PIT data.\n"
        f"Violations: {missing[:5]}"
    )


def test_uptrend_pullback_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: uptrend_pullback SQL queries have ORDER BY."""
    results = _scan_sql_queries()
    uptrend = results["uptrend_pullback"]

    missing = [v for v in uptrend if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: uptrend_pullback has {len(missing)} "
        f"time-series SQL queries without ORDER BY.\n"
        f"Violations: {missing[:5]}"
    )


def test_short_reversal_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: short_reversal SQL queries have ORDER BY."""
    results = _scan_sql_queries()
    short = results["short_reversal"]

    missing = [v for v in short if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: short_reversal has {len(missing)} "
        f"time-series SQL queries without ORDER BY.\n"
        f"Violations: {missing[:5]}"
    )


def test_cycle_price_action_sql_queries_have_order_by() -> None:
    """§1 RED documented: cycle_price_action data_feed.py:52 missing ORDER BY.

    Per [[reproducibility-audit-2026-09-23]] Tick 36:
    cycle_price_action/data_feed.py:52 — MISSING ORDER BY.

    This is an EXECUTABLE VERIFICATION of the documented finding.
    """
    results = _scan_sql_queries()
    cycle = results["cycle_price_action"]

    missing = [v for v in cycle if not v[3]]

    if missing:
        raise AssertionError(
            f"§1 MISSING ORDER BY (CONFIRMED per Tick 36): "
            f"cycle_price_action has {len(missing)} time-series SQL "
            f"queries without ORDER BY.\n"
            f"Per CLAUDE.md §1: time-series queries MUST end with "
            f"ORDER BY timestamp for monotonic delivery.\n"
            f"Per [[reproducibility-audit-2026-09-23]]: cycle/data_feed.py:52 "
            f"is documented missing ORDER BY.\n"
            f"Violations: {missing[:5]}"
        )

# ---------------------------------------------------------------------------
# 反空转对照 (§13.42): 扫描必须是**发现式**的
# ---------------------------------------------------------------------------


def test_scan_is_discovery_based_and_covers_more_than_the_old_list() -> None:
    """扫描必须看到**旧手写清单之外**的目录 —— 否则"放宽覆盖面"是句空话。

    ⚠️ 2026-10-19 (§13.42): 本文件原先用手写的 `SQL_FILES` 字典枚举要扫什么,
    那里只有四个族。改为遍历仓库后, 实测多出 **`dna_data`** 与 **`tools`**
    —— 前者是 §9 说的"共享双价层"(入口已备但未被引擎采用), 后者是 §13.41
    刚从 `/tmp` 抢救进来的 §7 复现脚本。**这 5 条时序查询此前不在任何守卫的视野里。**
    """
    results = _scan_sql_queries()
    families = {"chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"}
    assert families <= set(results), (
        f"四个族必须都在扫描范围内; 实际只看到 {sorted(results)}"
    )
    extra = set(results) - families
    assert extra, (
        "扫描只看到四个族 ⇒ 它退化成了旧的手写清单, 覆盖面没有真的放宽。"
        "请检查 _scan_sql_queries 是否仍在读某个硬编码的文件列表。"
    )


def test_fstring_queries_are_not_split_into_fragments() -> None:
    """反空转对照之二的**前置**: f-string 必须被当成**一条**查询来判。

    这条守的是扫描器**自己的**一个已知陷阱: f-string 在 AST 里是 `JoinedStr`,
    字面量部分是若干个分散的 `Constant`。逐个判 ⇒ `ORDER BY` 落在别的片段里 ⇒
    **合规查询被误报成违规**。(§13.42 第一版扫描器正是如此, 全库误报 3 处。)
    """
    import ast

    src = 'sql = f"""\n  SELECT thscode, date FROM v_daily\n  WHERE date BETWEEN ? AND ?\n  ORDER BY thscode, date\n"""'
    tree = ast.parse(src)
    out: list[tuple[str, int]] = []
    _collect_strings(tree, out)
    texts = [t for t, _ in out if "select" in t.lower()]
    assert len(texts) == 1, f"f-string 被拆成了 {len(texts)} 段: {texts}"
    assert _has_order_by(texts[0]), (
        "拼回来的查询里看不到 ORDER BY ⇒ 收集器又把 f-string 拆碎了"
    )


def test_every_scanned_time_series_query_has_order_by() -> None:
    """**全仓断言**: 凡被扫到的时序查询, 都必须有 ORDER BY —— 不按族分。

    ⚠️ 2026-10-19 (§13.42): 只把扫描改成发现式**是不够的** —— 四个既有测试各自只断言
    **自己那一族**的键, 于是 `tools` / `dna_data` 里的查询**被扫到却无人断言**。
    **实测**: 往 `tools/` 放一条缺 ORDER BY 的时序查询, 六个测试**全绿**。
    ⇒ 覆盖面是名义上的。这条补上真正的性质: **扫到 = 断言**。
    """
    results = _scan_sql_queries()
    violations = [
        (f, line, snippet)
        for _key, items in results.items()
        for f, line, snippet, has_order in items
        if not has_order
    ]
    assert not violations, (
        "以下**时序 SQL 缺 ORDER BY** (§1 时间单调性 + §0 可复现性):\n"
        + "\n".join(f"  {f}:{line}  {snippet[:80]}" for f, line, snippet in violations)
    )
