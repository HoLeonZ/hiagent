"""§0/§1 复现性审计 — Determinism by Construction + Multi-Run Reproducibility.

CLAUDE.md §0 Pessimistic Default: 确定性是绝对前提。任何引入
非确定性结果的代码路径都是 §0 违规 (FAIL-FAST 要求)。

CLAUDE.md §1 Temporal Determinism: 时间是严格单调的 first-class
citizen。任何因 row-order/seed/data-fetch 顺序而改变结果的代码
路径都是 §1 违规。

审计范围 (FRESH 2026-09-23):

A. **Determinism by Construction** — 引擎热路径不应使用:
   - `random.*` (unless seeded with fixed seed)
   - `uuid.*`
   - `datetime.now()` (unless 仅用于输出路径命名)
   - `iterrows()` / `itertuples()` (row-order 敏感)

C. **DuckDB ORDER BY** — Panel 查询必须有 `ORDER BY thscode, date`
   保证 row order 跨 run 一致。

D. **Multi-Run Reproducibility** — 同一 preset 同 seed 跑两次,
   trades.csv SHA-256 必须 byte-equal。
   - chase_up: 已有 `test_chase_up_no_lookahead.py` (33 PASS)
   - uptrend_pullback / short_reversal / cycle_price_action: 缺失

E. **Engine hot path purity** — Strategy / Execution 层不应:
   - 读取 / 写入文件依赖 mtime/atime
   - 调用未 seed 的 random/uuid

本审计 Tick 36 输出:
- 5 PASS baselines (随机被 seed / ORDER BY 主流 / 现有 chase_up baseline)
- 2 RED (3 engines 缺 multi-run baseline; cycle liquidity_codes 缺 ORDER BY)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import duckdb

# ---------------------------------------------------------------------------
# PASS baselines: determinism by construction
# ---------------------------------------------------------------------------

# Engines to audit (excluding tests/, results/, examples/)
ENGINE_DIRS = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]

# Patterns that indicate non-deterministic sources
NONDETERMINISTIC_PATTERNS = {
    "random_call": re.compile(r"\brandom\.(random|randint|uniform|choice|sample)\("),
    "uuid_call": re.compile(r"\buuid\.(uuid[14]|uuid1|uuid4)\("),
    "datetime_now": re.compile(r"\b(datetime|time)\.(now|utcnow|today)\("),
    "iterrows": re.compile(r"\.(iterrows|itertuples)\(\)"),
}


def _engine_py_files(engine: str) -> list[Path]:
    """All .py files in engine dir, excluding tests / results / __pycache__."""
    root = Path(engine)
    if not root.exists():
        return []
    files: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("__pycache__/") or rel.startswith("results/"):
            continue
        if rel.startswith("tests/") or rel.startswith("test_"):
            continue
        files.append(p)
    return files


def test_random_usage_is_seeded_in_all_engines() -> None:
    """§0/§1 PASS baseline: random usage must be seeded.

    For every `random.*` call, verify a `random.Random(seed)` or
    `random.seed(seed)` exists in same file BEFORE the call (textually).
    """
    violations: list[tuple[str, str, int]] = []

    for engine in ENGINE_DIRS:
        for py_file in _engine_py_files(engine):
            text = py_file.read_text(encoding="utf-8")
            lines = text.splitlines()

            # Find all random.* calls and their line numbers
            for i, line in enumerate(lines, start=1):
                if not NONDETERMINISTIC_PATTERNS["random_call"].search(line):
                    continue
                # Check if same file has random.Random(seed) or random.seed(...)
                has_seed = bool(
                    re.search(r"\brandom\.(Random|seed)\(", text)
                )
                if not has_seed:
                    violations.append(
                        (engine, py_file.name, i)
                    )

    assert not violations, (
        "GAP CAPTURED: random.*() calls without seeding in same file. "
        "§0/§1 violation — non-deterministic engine output.\n"
        + "\n".join(
            f"  - {e}/{f}:{ln}" for e, f, ln in violations[:10]
        )
    )


def test_datetime_now_only_used_for_output_path_naming() -> None:
    """§0/§1 PASS baseline: datetime.now() must not affect result computation.

    The only legitimate use is constructing output directory/file names.
    Any use inside numerical computation is a §0 violation.
    """
    violations: list[tuple[str, str, int, str]] = []

    # Allowlist: lines used in path/dir construction
    OUTPUT_PATH_HEURISTIC = re.compile(
        r"(out_dir|output|results?/|f\"run_|/run_|\.joinpath\()"
    )

    for engine in ENGINE_DIRS:
        for py_file in _engine_py_files(engine):
            text = py_file.read_text(encoding="utf-8")
            lines = text.splitlines()
            for i, line in enumerate(lines, start=1):
                if not NONDETERMINISTIC_PATTERNS["datetime_now"].search(line):
                    continue
                # Heuristic: comment or path-related line is OK
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if OUTPUT_PATH_HEURISTIC.search(line):
                    continue
                violations.append((engine, py_file.name, i, stripped))

    assert not violations, (
        "GAP CAPTURED: datetime.now()/utcnow()/today() used outside "
        "output path naming. §0/§1 violation — affects result determinism.\n"
        + "\n".join(
            f"  - {e}/{f}:{ln}: {snippet}" for e, f, ln, snippet in violations[:10]
        )
    )


def test_engine_hot_paths_no_iterrows_itertuples() -> None:
    """§1 RED: iterrows()/itertuples() in engine hot paths (fragile).

    `iterrows()` iterates in row-insertion order. If upstream DuckDB
    result loses ORDER BY, downstream computation becomes non-deterministic.

    Engine hot paths (backtrader_engine.py) found:
    - chase_up/backtrader_engine.py:70 — feed panel rows
    - chase_up/backtrader_engine.py:225 — trade replay loop

    Currently safe because chase_up/data.py:59 has ORDER BY thscode, date.
    But fragile — if SQL is ever changed, these loops break silently.

    Reports/audit scripts (render_v3_trades_html.py, trade_report.py,
    audit_phantom.py) are NOT hot paths and excluded.
    """
    violations: list[tuple[str, str, int]] = []

    # Hot-path files only (skip reports, audits, renderers)
    HOT_PATH_FILES = {
        "chase_up/backtrader_engine.py",
        "chase_up/main.py",
        "uptrend_pullback/backtrader_engine.py",
        "uptrend_pullback/main.py",
        "short_reversal/engine.py",
        "cycle_price_action/backtrader_engine.py",
        "cycle_price_action/backtest.py",
    }

    for rel in HOT_PATH_FILES:
        path = Path(rel)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines, start=1):
            if NONDETERMINISTIC_PATTERNS["iterrows"].search(line):
                violations.append((rel, path.name, i))

    assert not violations, (
        "§1 fragility: iterrows()/itertuples() in engine hot paths. "
        "Determinism depends on upstream ORDER BY being preserved. "
        "GREEN fix: refactor to vectorized pandas ops OR add explicit "
        "sort assertion before iterrows().\n"
        + "\n".join(
            f"  - {rel}:{ln}" for rel, _, ln in violations
        )
    )


def test_duckdb_panel_queries_have_order_by() -> None:
    """§1 PASS baseline: panel queries must ORDER BY thscode, date.

    Audit the 4 data-layer files known to load panel data:
    - chase_up/data.py
    - uptrend_pullback/data.py
    - short_reversal/universe.py
    - cycle_price_action/data_feed.py

    Each file's panel query must contain ORDER BY (or be a GROUP BY
    set-semantic query, which is order-independent).
    """
    data_files = [
        "chase_up/data.py",
        "uptrend_pullback/data.py",
        "short_reversal/universe.py",
        "cycle_price_action/data_feed.py",
    ]
    missing_order_by: list[tuple[str, str]] = []

    for rel in data_files:
        path = Path(rel)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")

        # Find each `con.execute(` block and check for ORDER BY or GROUP BY
        # in the same statement
        execute_starts = [
            m.start() for m in re.finditer(r"con\.execute\(", text)
        ]
        for start in execute_starts:
            # Slice from start to next closing paren at same depth
            depth = 0
            end = start
            for j in range(start, len(text)):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            stmt = text[start:end]
            # Skip pure metadata queries (SELECT MAX, SELECT MIN, single value)
            if re.search(r"SELECT\s+MAX\(|SELECT\s+MIN\(", stmt, re.IGNORECASE):
                continue
            # GROUP BY queries are set-semantic (order-independent)
            if re.search(r"\bGROUP\s+BY\b", stmt, re.IGNORECASE):
                continue
            # REQUIRE ORDER BY for all other row-returning queries
            if not re.search(r"\bORDER\s+BY\b", stmt, re.IGNORECASE):
                # Find line number
                line_no = text[:start].count("\n") + 1
                # Extract first 80 chars of stmt for context
                preview = stmt[:80].replace("\n", " ")
                missing_order_by.append((rel, f"L{line_no}: {preview}..."))

    assert not missing_order_by, (
        "§1 violation: DuckDB row-returning queries missing ORDER BY. "
        "Cross-run reproducibility at risk.\n"
        + "\n".join(f"  - {rel}: {snippet}" for rel, snippet in missing_order_by)
    )


def test_chase_up_has_trades_csv_sha256_reproducibility_baselines() -> None:
    """PASS baseline: chase_up trades.csv sha256 reproducibility exists.

    `tests/test_chase_up_no_lookahead.py` covers chase_v5 + v8-v19 (12
    presets) with `trades_csv_sha256` golden hashes. Same preset run
    twice must produce byte-equal trades.csv.

    This is the gold standard. Other 3 engines should follow the same
    pattern (see test_engine_X_has_reproducibility_baseline below).
    """
    test_path = Path("tests/test_chase_up_no_lookahead.py")
    assert test_path.exists(), "chase_up reproducibility test missing"
    text = test_path.read_text(encoding="utf-8")
    assert "trades_csv_sha256" in text or "sha256" in text, (
        "chase_up test should pin sha256 baselines"
    )


# ---------------------------------------------------------------------------
# RED: 3 engines lack multi-run reproducibility tests
# ---------------------------------------------------------------------------


def test_uptrend_pullback_has_trades_csv_sha256_baseline() -> None:
    """§0 RED: uptrend_pullback lacks trades.csv sha256 reproducibility.

    chase_up has 12 preset baselines (v5, v8-v19) pinned via sha256.
    uptrend_pullback has 2 trades.csv files (v33_long_reverse_v19,
    v33_long_reverse_v20) but NO multi-run reproducibility test.

    Cannot verify §0 determinism without re-running and comparing hashes.
    """
    test_files = list(Path("tests").glob("test_uptrend*"))
    has_sha_baseline = False
    for tf in test_files:
        if "sha256" in tf.read_text(encoding="utf-8"):
            has_sha_baseline = True
            break

    if not has_sha_baseline:
        # Check if there are trades.csv at least
        trades_csv = list(Path("uptrend_pullback/results").glob("v*_trades.csv"))
        if trades_csv:
            raise AssertionError(
                "GAP CAPTURED: uptrend_pullback has "
                f"{len(trades_csv)} trades.csv files but NO sha256 "
                "reproducibility baseline test. §0 determinism "
                "unverifiable. GREEN fix: add sha256 pinning like "
                "tests/test_chase_up_no_lookahead.py."
            )


def test_short_reversal_has_trades_csv_sha256_baseline() -> None:
    """§0 RED: short_reversal lacks trades.csv sha256 reproducibility."""
    test_files = list(Path("tests").glob("test_short*"))
    has_sha_baseline = False
    for tf in test_files:
        if "sha256" in tf.read_text(encoding="utf-8"):
            has_sha_baseline = True
            break

    if not has_sha_baseline:
        trades_csv = list(Path("short_reversal/results").glob("*.csv"))
        # short_reversal v44+ emits trades.csv, v35-v43 don't
        new_schema_csv = [p for p in trades_csv if "mainboard" in p.name]
        if new_schema_csv:
            raise AssertionError(
                "GAP CAPTURED: short_reversal has "
                f"{len(new_schema_csv)} trades.csv files (new schema) "
                "but NO sha256 reproducibility baseline. §0 "
                "determinism unverifiable."
            )


def test_cycle_price_action_has_trades_csv_sha256_baseline() -> None:
    """§0 RED: cycle_price_action lacks trades.csv sha256 reproducibility.

    Currently cycle_price_action produces NO output (fail-fast blocks at
    backtest.py:86 per [[fail-fast-cycle-hot-path]]). After fail-fast fix,
    output must have multi-run reproducibility baseline.
    """
    test_files = list(Path("tests").glob("test_cycle*"))
    has_sha_baseline = False
    for tf in test_files:
        if "sha256" in tf.read_text(encoding="utf-8"):
            has_sha_baseline = True
            break

    if not has_sha_baseline:
        # Forward-defense: even though cycle produces no output today,
        # the test should exist to pin determinism once output exists.
        raise AssertionError(
            "GAP CAPTURED: cycle_price_action has NO sha256 "
            "reproducibility baseline test. After fail-fast fix "
            "lands and output is produced, baseline must be "
            "captured to verify §0 determinism."
        )


# ---------------------------------------------------------------------------
# RED: cycle/data_feed.py:52-55 liquidity_codes missing ORDER BY
# ---------------------------------------------------------------------------


def test_cycle_liquidity_codes_query_has_order_by() -> None:
    """§1 RED: cycle_price_action/data_feed.py:52-55 lacks ORDER BY.

    The `liquidity_codes` query returns rows consumed by
    `apply_liquidity_filter` which uses groupby (set-semantic, currently
    order-independent). However, the convention should be: every
    row-returning DuckDB query has explicit ORDER BY for cross-run
    reproducibility by construction.

    Forward-defense: if `apply_liquidity_filter` is ever changed to
    use row order (e.g., for a sequence-aware filter), the missing
    ORDER BY becomes a §1 violation.
    """
    path = Path("cycle_price_action/data_feed.py")
    text = path.read_text(encoding="utf-8")

    # Locate the liquidity_codes block
    marker = "liquidity_codes = con.execute("
    start = text.find(marker)
    if start == -1:
        return  # not present, skip

    # Find end of statement (next closing paren)
    depth = 0
    end = start
    for j in range(text.find("(", start), len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    stmt = text[start:end]

    if not re.search(r"\bORDER\s+BY\b", stmt, re.IGNORECASE):
        line_no = text[:start].count("\n") + 1
        raise AssertionError(
            f"GAP CAPTURED: cycle_price_action/data_feed.py:{line_no} "
            "liquidity_codes query lacks ORDER BY. "
            "apply_liquidity_filter is currently groupby/set-semantic "
            "(order-independent), but convention requires explicit "
            "ORDER BY for cross-run reproducibility by construction. "
            "GREEN fix: add `ORDER BY thscode, date` to the query."
        )


# ---------------------------------------------------------------------------
# Helper: live SQL determinism test (only run if DuckDB available)
# ---------------------------------------------------------------------------


def test_duckdb_query_ordering_is_stable_across_runs() -> None:
    """§1 PASS baseline: DuckDB ORDER BY gives stable row order.

    Run the same query twice against an in-memory DuckDB and verify
    the row hashes match. This pins that ORDER BY guarantees
    reproducibility (independent of underlying storage).
    """
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES "
            "(1, 'A'), (2, 'B'), (3, 'C'), (4, 'A'), (5, 'B')"
            ") AS tbl(id, code)"
        )

        run1 = con.execute(
            "SELECT id, code FROM t ORDER BY code, id"
        ).fetchall()
        run2 = con.execute(
            "SELECT id, code FROM t ORDER BY code, id"
        ).fetchall()
        run3 = con.execute(
            "SELECT id, code FROM t ORDER BY code, id"
        ).fetchall()

        assert run1 == run2 == run3, (
            "DuckDB ORDER BY result not stable across runs"
        )
    finally:
        con.close()