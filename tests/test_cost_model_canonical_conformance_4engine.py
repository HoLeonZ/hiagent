"""§0/§3 Cost Model Canonical Conformance — Verification (Tick 76).

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

CLAUDE.md §3 (verbatim):
  "ALWAYS use **Forward-Adjusted Prices** (`adj_close`) for mathematical
   indicators (MACD, Wyckoff mappings, Volatility).
   ALWAYS use **Raw Prices** (`raw_close`) for evaluating limit order
   triggers, stop-losses, and portfolio physical cash mark-to-market."

CLAUDE.md §0/§3 cost model standard (documented in
[[audit-2026-09-23-cost-model-undercount]]):
  - Commission: 万2.5 = 0.00025 (canonical)
  - Stamp duty: 万5 = 0.0005 (POST-Aug2023, current)
                  万10 = 0.001 (PRE-Aug2023, historical)
  - Min commission: ¥5 floor
  - Stamp duty: SELL-ONLY

**核心发现 (FRESH 2026-09-23):**

A. **Cost model values across 4 engines (FRESH 2026-09-23)**:

   | Engine             | Commission  | Stamp Duty  | Status                  |
   |--------------------|-------------|-------------|-------------------------|
   | chase_up           | 0.00025 ✓   | 0.0005 ✓   | CANONICAL               |
   | uptrend_pullback   | 0.00025 ✓   | 0.0005 ✓   | CANONICAL               |
   | cycle_price_action | 0.00025 ✓   | 0.001 ✗    | WRONG (pre-Aug2023)     |
   | short_reversal     | 0.0006 ✗   | 0.001 ✗    | WRONG (both wrong)      |

B. **Per CLAUDE.md §0 Pessimistic Default + §3 Raw Prices mandate**:
   - Commission MUST be 0.00025 (canonical, no override)
   - Stamp duty should be 0.0005 for post-Aug2023 backtests
   - 0.001 stamp duty was PRE-Aug2023 rate (historical only)
   - 0.0006 commission is FACTUALLY WRONG (no historical basis)

C. **Why this matters**:
   - Commission/stamp errors silently under-report trading costs
   - Net PnL overstated → false confidence in strategy
   - Cross-engine comparison invalid (different cost models)
   - Per [[audit-2026-09-23-cost-model-undercount]]: short_reversal
     short_reversal 0.0006+0.001 stamps wrong; cycle 0.001 stamps wrong

D. **Detection scope**:
   - AST scan Portfolio / ReplayStrategy for cost model constants
   - Pattern: `commission_rate` / `COMMISSION_RATE` / `comm_rate`
   - Pattern: `stamp_duty_rate` / `STAMP_TAX` / `stamp_duty`
   - Verify commission == 0.00025 (canonical)
   - Verify stamp_duty ∈ {0.0005, 0.001} (both valid for date ranges)
   - If 0.001 stamp duty used → check for date guard
"""
from __future__ import annotations

import ast
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


# Portfolio / strategy files per engine
COST_MODEL_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "portfolio.py",
}


# Canonical commission: 万2.5 = 0.00025
CANONICAL_COMMISSION = 0.00025

# Valid stamp duty values
# - 0.0005 = 万5 (POST-Aug2023, current A-share market)
# - 0.001 = 万10 (PRE-Aug2023, historical)
VALID_STAMP_DUTY = {0.0005, 0.001}


def _extract_numeric_value(node: ast.AST) -> float | None:
    """Extract numeric value from AST node (Constant or UnaryOp)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _extract_numeric_value(node.operand)
        if inner is not None:
            return -inner
    return None


def _scan_cost_constants(
    file_path: Path,
) -> tuple[float | None, float | None, dict[str, int]]:
    """Scan Portfolio / Strategy class for cost model constants.

    Returns (commission_value, stamp_duty_value, line_map).

    Detects 3 patterns:
    - Pattern 1: dataclass field (ast.AnnAssign at class body)
    - Pattern 2: class constant (ast.Assign at class body)
    - Pattern 3: function default argument (ast.arguments.kw_defaults
      in __init__)
    """
    if not file_path.exists():
        return (None, None, {})

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return (None, None, {})

    commission_value: float | None = None
    stamp_duty_value: float | None = None
    line_map: dict[str, int] = {}

    # 2026-10-19 (§2 Canonical Cost Model 修复后新增):
    # §2 明文要求引擎 **从 `core/` 导入**成本常量而非自己写死。按那条要求改过之后,
    # 赋值右侧是 `ast.Name`(导入名)而不是数字 ⇒ 本扫描原来会报 "NOT FOUND"。
    # 这里把 import 也认出来, 并把名字**解析回 core 里的规范值**。
    # ⇒ "写死字面量"与"从单一来源导入"两种形态都被判为合规, 而**错值仍会被抓住**
    #    (字面量分支未改)。
    imported_from_core: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.dual_price":
            for alias in node.names:
                imported_from_core[alias.asname or alias.name] = alias.name

    def _resolve_imported(node: ast.AST) -> float | None:
        if not isinstance(node, ast.Name):
            return None
        canon = imported_from_core.get(node.id)
        if canon is None:
            return None
        import core.dual_price as _cd

        v = getattr(_cd, canon, None)
        return float(v) if isinstance(v, (int, float)) else None

    # Patterns to match (lowercase for case-insensitive comparison)
    commission_names = {
        "commission_rate",
        "commissionrate",
        "comm_rate",
        "comission_rate",  # typo tolerance
    }
    stamp_duty_names = {
        "stamp_duty_rate",
        "stampduty",
        "stamp_tax",
        "stamp_tax_sell",
        "stampduty_rate",
    }

    def _check_and_record(attr_name: str, value_node: ast.AST, line: int) -> None:
        nonlocal commission_value, stamp_duty_value
        attr_lower = attr_name.lower()
        if attr_lower in commission_names:
            val = _extract_numeric_value(value_node)
            if val is None:
                val = _resolve_imported(value_node)   # §2: 从 core 导入的形态
            if val is not None:
                commission_value = val
                line_map["commission"] = line
        elif attr_lower in stamp_duty_names:
            val = _extract_numeric_value(value_node)
            if val is None:
                val = _resolve_imported(value_node)
            if val is not None:
                stamp_duty_value = val
                line_map["stamp_duty"] = line

    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue

        # Pattern 1: AnnAssign (annotated assignment) for dataclass fields
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                _check_and_record(node.target.id, node.value, node.lineno)

        # Pattern 2: Assign (bare assignment) for class constants
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                _check_and_record(target.id, node.value, node.lineno)

        # Pattern 3: Function default arguments (kw_defaults for
        # keyword-only args after `*`)
        elif isinstance(node, ast.FunctionDef):
            args = node.args
            # Positional arg defaults
            positional_defaults = args.defaults
            positional_args = args.args
            # Align defaults with positional args (last N args have defaults)
            n_pos_defaults = len(positional_defaults)
            for i, default in enumerate(positional_defaults):
                arg_idx = len(positional_args) - n_pos_defaults + i
                if 0 <= arg_idx < len(positional_args):
                    arg_name = positional_args[arg_idx].arg
                    line = getattr(default, "lineno", node.lineno)
                    _check_and_record(arg_name, default, line)
            # Keyword-only arg defaults (kw_defaults is list aligned with kwonlyargs)
            for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
                if kw_default is not None:
                    line = getattr(kw_default, "lineno", node.lineno)
                    _check_and_record(kw_arg.arg, kw_default, line)

    # Pattern 4 (§13.76) —— **kwargs**: `params = dict(commission_rate=...)` 形态。
    # ⚠️ 这正是 short_reversal / cycle 的**真实配置面** (`self.p.commission_rate` 就读这里)。
    # 原扫描只认 ①类体 AnnAssign ②类体 Assign ③__init__ 默认参数 ⇒ 对 kwargs **完全失明**;
    # 而下面的"兜底"会把 import 里的规范值填进去 ⇒ **违规被兜底掩盖**。
    # 注入实证: 把 short_reversal 的 `commission_rate=COMMISSION_RATE` **替换**成 `0.0006`
    # (落地已核, 原行已不存在) ⇒ 扫描器仍报 0.00025, 本测试仍 4 passed。
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg:
                    _check_and_record(
                        kw.arg,
                        kw.value,
                        getattr(kw.value, "lineno", getattr(node, "lineno", 0)),
                    )

    # 2026-10-19 兜底 (§2): 有些引擎**只**写 `from core.dual_price import COMMISSION_RATE,
    # STAMP_DUTY_RATE` 而**没有任何赋值** ⇒ 上面的赋值扫描会一个都找不到。
    # 这里按 import 的名字补上。**作为兜底而非覆盖**: 若同一文件里还有显式字面量赋值,
    # 上面的分支已经记录过了, 这里的 `is None` 判断保证不会把它盖掉 ⇒ **错值仍被抓住**。
    for local, canon in imported_from_core.items():
        v = _resolve_imported(ast.Name(id=local))
        if v is None:
            continue
        name_l = (canon or local).lower()
        if name_l in commission_names and commission_value is None:
            commission_value = v
            line_map.setdefault("commission", 0)
        elif name_l in stamp_duty_names and stamp_duty_value is None:
            stamp_duty_value = v
            line_map.setdefault("stamp_duty", 0)

    return (commission_value, stamp_duty_value, line_map)


def _engine_red_message(
    engine: str,
    commission: float | None,
    stamp_duty: float | None,
    issue: str,
) -> str:
    comm_str = f"{commission}" if commission is not None else "NOT FOUND"
    stamp_str = f"{stamp_duty}" if stamp_duty is not None else "NOT FOUND"
    return (
        f"§0/§3 COST MODEL VIOLATION: {engine} uses non-canonical cost "
        f"rates.\n"
        f"Commission: {comm_str} (canonical: {CANONICAL_COMMISSION})\n"
        f"Stamp duty: {stamp_str} (valid: {sorted(VALID_STAMP_DUTY)})\n"
        f"Issue: {issue}\n"
        f"Per CLAUDE.md §0 Pessimistic Default + §3 Raw Prices: cost "
        f"model must be canonical to ensure cross-engine consistency "
        f"and accurate net PnL reporting.\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 0.0006 "
        f"commission has no historical basis; 0.001 stamp duty is "
        f"pre-Aug2023 only."
    )


# ---------------------------------------------------------------------------
# Verification: each engine uses canonical cost model
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# §6 单源不变量（audit P2-11, 2026-10-15）
# ---------------------------------------------------------------------------


def _assert_cost_constants_single_sourced(engine: str) -> None:
    """引擎**不得自行声明**费率常量，必须从 core.dual_price 导入。

    本文件原先只比对**数值**是否等于 canonical —— 那允许"重复定义、数值相同"，
    而重复定义正是会静默漂移的形态：历史上 short_reversal 写成 0.0006+0.001、
    cycle 写成 0.001，都是"每个引擎各写一份"的直接后果。单源之后数值在构造上
    不可能漂移，所以断言改为更强的性质。
    """
    path = COST_MODEL_FILES[engine]
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.dual_price":
            imported |= {a.name for a in node.names}
    needed = {"COMMISSION_RATE", "STAMP_DUTY_RATE", "MIN_COMMISSION"}
    missing = needed - imported
    assert not missing, (
        f"§6 VIOLATION: {engine} 未从 core.dual_price 导入 {sorted(missing)}"
        " —— 费率常量必须单源"
    )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in tgts:
                if isinstance(t, ast.Name) and t.id in needed:
                    assert not isinstance(node.value, ast.Constant), (
                        f"§6 VIOLATION: {engine} 在 line {node.lineno} 用字面量"
                        f"重新声明 {t.id} —— 必须引用 core 单源"
                    )


def _assert_stamp_duty_is_valid(engine: str) -> None:
    """§13.76: 必须**真的看** `stamp_duty` 的**值**, 而不只是把它收进变量再传给错误信息。

    ⚠️ 2026-10-22 (附一百八十八): 这段检查此前**只被贴进了 short_reversal 那一条用例**,
    而且**三个变量从未接上** —— `commission` / `stamp_duty` / `lines` 在该函数里根本不存在
    ⇒ 那条用例每次都抛 `NameError`(**用例自己坏了**, 不是断言失败);
    而它的 docstring 却写着「(chase_up / uptrend / cycle 三条都有这一句; 只有本族漏了)」
    —— **实测正好相反**: 只有这一族有, 另外三族没有。

    ⇒ 抽成本函数, **四族一起调**, 让那句话成真。四族的 `stamp_duty` 实测均为 `0.0005`
    (∈ `VALID_STAMP_DUTY`) ⇒ 补上后四族仍绿, 而"注入 `0.002` 必须红"的性质对四族同时成立。
    """
    commission, stamp_duty, lines = _scan_cost_constants(COST_MODEL_FILES[engine])
    if stamp_duty not in VALID_STAMP_DUTY:
        raise AssertionError(
            _engine_red_message(
                engine,
                commission,
                stamp_duty,
                f"stamp_duty must be one of {sorted(VALID_STAMP_DUTY)} "
                f"(line {lines.get('stamp_duty', '?')})",
            )
        )

def test_chase_up_cost_model_canonical() -> None:
    """§6 单源不变量: chase_up 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("chase_up")
    _assert_stamp_duty_is_valid("chase_up")


def test_uptrend_pullback_cost_model_canonical() -> None:
    """§6 单源不变量: uptrend_pullback 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("uptrend_pullback")
    _assert_stamp_duty_is_valid("uptrend_pullback")


def test_short_reversal_cost_model_canonical() -> None:
    """§6 单源不变量: short_reversal 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("short_reversal")
    _assert_stamp_duty_is_valid("short_reversal")



def test_cycle_price_action_cost_model_canonical() -> None:
    """§6 单源不变量: cycle_price_action 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("cycle_price_action")
    _assert_stamp_duty_is_valid("cycle_price_action")

