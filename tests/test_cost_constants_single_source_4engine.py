"""§4 Cost Constants Single-Source Verification (Tick 67).

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

CLAUDE.md §3 (verbatim):
  "**Event-Sourced Corporate Actions:** Cash dividends must explicitly
   trigger a physical cash deposit into `Free_Cash`."

**核心发现 (FRESH 2026-09-23):**

A. **§4 Cost model canonical constants**:
   - 万2.5 commission (0.00025)
   - 万5 stamp duty (0.0005 post-Aug2023)
   - ¥5 min commission floor
   - sell-only stamp duty
   - Per [[cost-model-single-source-audit-2026-09-23]] Tick 53:
     - core/dual_price.py does NOT export cost constants
     - chase + uptrend CORRECT but DUPLICATED in 4 files
     - short_reversal WRONG (0.0006+0.001 — does not match §0/§3)
     - cycle WRONG stamp (0.001 instead of 0.0005)
     - "Single-source STILL OPEN" per [[dual-price-refactor-uncommitted]]

B. **Risk: hardcoded rates silently drift**:
   - If new code adds `commission = 0.00025` literal → bypasses single-source
   - If audit fixes one file but miss another → drift
   - If 万5 changes to 万3 in policy → must update single source only

C. **Test scope (Tick 67)**:
   - Forward-defense: detect hardcoded cost model literals in production
   - Detect: `0.00025` (commission), `0.0005` (stamp duty),
     `0.001` (stamp_alt_wrong), `0.0006` (commission_alt_wrong),
     `5` near commission context (¥5 floor)
   - Allowed location: `core/dual_price.py` (canonical single-source)
   - Disallowed location: any other production file

D. **Expected outcome**:
   - 1 PASS: core/dual_price.py may contain cost constants (canonical)
   - 4 PASS baselines: 4 engines do NOT hardcode cost literals
     (they import from core/dual_price.py)
   - 0 RED expected (canonical pattern already enforced per Tick 53)

E. **Why this matters**:
   - §0 Single source of truth: prevents drift between engines
   - §4 Pessimistic Default: cost must be worst-case (commission + stamp
     + floor, no shortcuts)
   - If cost differs across engines: backtests become incomparable
   - If cost differs from policy: backtest misleads on real PnL

F. **Detector strategy**:
   - AST scan for numeric literals in production code
   - For each Float/Constant node, check if value matches cost patterns
   - For each match, verify file is in ALLOWED_LOCATIONS
   - If outside allowed locations → RED forward-defense

G. **Tick 67 results expected**:
   - 5 PASS: 1 allowed (core/dual_price.py) + 4 engines no-hardcode
   - 0 RED (canonical pattern enforced)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Canonical cost constants location (allowed to contain literals)
ALLOWED_LOCATIONS = {
    REPO_ROOT / "core" / "dual_price.py",
}


# Production hot-path files per engine (where hardcodes would be risky)
PRODUCTION_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "strategy.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "strategy.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "portfolio.py",
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "data_feed.py",
    ],
}


# Cost constant patterns to detect (literal values that SHOULD come from
# core/dual_price.py, not be hardcoded)
#: 成本相关的**名字**记号。判定看名字(赋值目标 / 关键字实参),不看数值本身 ——
#: 见 `_scan_hardcoded_costs` 的说明。
COST_NAME_TOKENS = ("commission", "stamp", "duty", "fee", "cost", "tax", "borrow")


def _scan_hardcoded_costs() -> dict[str, list[tuple[str, int, str, float]]]:
    """扫描生产文件里「**成本名 + 非零数值字面量**」的定义。

    Returns dict[engine → list of (file, line, name, value)]

    ### 2026-10-17 重写(旧版是"扫描器本身才是问题"的又一例)

    旧版只按"数值命中费率表(0.00025 / 0.0005 / 0.0006 …)"判定,**不看上下文**:
    源码里算出了一个 `cost_context` 变量,却**从未使用** —— 紧跟着就是无条件
    `violations.append(...)`,注释还写着 *"Always flag ... (even without context)"*。
    后果是实测把 `short_reversal/replay_strategy_v3.py:185` 的 **`sl_pct=0.0005`**
    (止损百分比,一个策略参数)误报成"印花税重复定义"。

    假阳性在这里特别毒:它让**真正的**费率重复可以藏在这类噪声后面(附五 的教训:
    扫描器的假阳性比假阴性更毒)。新规则改按**名字**判定 —— 赋值目标或关键字实参的
    名字里含成本词 —— 且要求值**非零**:零值有合法用途
    (`cerebro.broker.setcommission(commission=0.0)`,成本由策略内部扣),
    而"重复定义费率常量"这个缺陷形态本身要求一个非零费率。
    """
    results: dict[str, list[tuple[str, int, str, float]]] = {}

    for engine, paths in PRODUCTION_FILES.items():
        violations: list[tuple[str, int, str, float]] = []
        for path in paths:
            if not path.exists():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            def _is_cost_name(name: str | None) -> bool:
                return bool(name) and any(t in name.lower() for t in COST_NAME_TOKENS)

            def _is_nonzero_number(node: ast.AST) -> bool:
                return (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)
                    and float(node.value) != 0.0
                )

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Name)
                            and _is_cost_name(target.id)
                            and _is_nonzero_number(node.value)
                        ):
                            violations.append(
                                (str(path.relative_to(REPO_ROOT)), node.lineno,
                                 target.id, float(node.value.value))
                            )
                elif isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if _is_cost_name(kw.arg) and _is_nonzero_number(kw.value):
                            violations.append(
                                (str(path.relative_to(REPO_ROOT)), node.lineno,
                                 kw.arg, float(kw.value.value))
                            )

        results[engine] = violations

    return results


def _scan_canonical_source_exists() -> dict[str, bool]:
    """Verify core/dual_price.py exists and has cost constants defined."""
    results: dict[str, bool] = {}
    for path in ALLOWED_LOCATIONS:
        if not path.exists():
            results[str(path.relative_to(REPO_ROOT))] = False
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            results[str(path.relative_to(REPO_ROOT))] = False
            continue

        # Look for cost constant assignments
        has_constants = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                target_str = (
                    ast.unparse(node.targets[0])
                    if hasattr(ast, "unparse")
                    else ""
                )
                value_str = (
                    ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                )
                combined = (target_str + " " + value_str).lower()
                if any(
                    keyword in combined
                    for keyword in (
                        "commission",
                        "stamp_duty",
                        "stamp",
                        "min_commission",
                        "fee_rate",
                    )
                ):
                    has_constants = True
                    break
        results[str(path.relative_to(REPO_ROOT))] = has_constants

    return results


# ---------------------------------------------------------------------------
# PASS baselines: canonical source exists + each engine has no hardcodes
# ---------------------------------------------------------------------------


def test_canonical_cost_source_exists_in_core() -> None:
    """§0/§3 PASS baseline: core/dual_price.py has cost constants.

    Per [[cost-model-single-source-audit-2026-09-23]] Tick 53:
    canonical source is core/dual_price.py (when constants are added).
    """
    canonical = _scan_canonical_source_exists()

    core_exists = any(canonical.values())
    assert core_exists, (
        "§0/§3 CANONICAL MISSING: core/dual_price.py has no cost "
        "constants defined.\n"
        "Per [[cost-model-single-source-audit-2026-09-23]] Tick 53: "
        "canonical source STILL OPEN.\n"
        "Per [[dual-price-refactor-uncommitted]]: cost model constants "
        "need to be added to core/dual_price.py as single source of truth."
    )


_COST_HINT = (
    "§2/§4:费率常量必须**单源** —— 四引擎一律从 `core.dual_price` import"
    "(COMMISSION_RATE / STAMP_DUTY_RATE / MIN_COMMISSION),不得在引擎内重复写数值;"
    "同值不同源就是下一次漂移的起点(审计 §3.3「费率常量重复定义」族)。"
)

#: 这几个用例此前是**无可失败路径**的:
#:   · chase_up / uptrend_pullback:`if <engine>: pass` —— 扫完不看,永不失败
#:     (而 docstring 却写着"catches NEW hardcodes");
#:   · short_reversal / cycle_price_action:只比对**特定错值**(0.0006 / 0.001),
#:     于是"值抄对了但重复定义"这类漂移起点照样漏过。
#: 2026-10-17 统一为:**任何非零成本字面量即违规**(值对错与否都不该出现在引擎里)。
def _assert_no_cost_literals(engine: str) -> None:
    hits = _scan_hardcoded_costs()[engine]
    assert not hits, (
        f"§2/§4 VIOLATION: {engine} 生产文件里有 {len(hits)} 处硬编码费率:\n  "
        + "\n  ".join(f"{f}:{ln} {name}={val}" for f, ln, name, val in hits)
        + "\n" + _COST_HINT
    )


def test_chase_up_no_hardcoded_cost_literals() -> None:
    """§2/§4:chase_up 生产文件不得有硬编码费率(必须 import 自 core)。"""
    _assert_no_cost_literals("chase_up")


def test_uptrend_pullback_no_hardcoded_cost_literals() -> None:
    """§2/§4:uptrend_pullback 生产文件不得有硬编码费率。"""
    _assert_no_cost_literals("uptrend_pullback")


def test_short_reversal_no_wrong_cost_literals() -> None:
    """§2/§4:short_reversal 生产文件不得有硬编码费率。

    (Tick 53 记过它当时用的是**错值** 0.0006/0.001;现已单源。本用例不再只盯那两个
    数值 —— 值"抄对"但重复定义同样是违规。)
    """
    _assert_no_cost_literals("short_reversal")


def test_cycle_price_action_no_wrong_cost_literals() -> None:
    """§2/§4:cycle_price_action 生产文件不得有硬编码费率。

    (Tick 53 记过它当时的印花税是 0.001;现已单源。)
    """
    _assert_no_cost_literals("cycle_price_action")
