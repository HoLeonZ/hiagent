"""§2 All-In Sizing Formula Verification (Tick 63).

CLAUDE.md §2 (verbatim, 2026-09-21 update):
  "**All-In Sizing Policy (2026-09-21):** Every entry is sized at
   100% of available cash for that trade slot
   (`position_sizing = "all_in"`, `MAX_POSITION_PCT = 1.0`,
   `position_fraction = 1.0`). Tail risk is absorbed at the *exit*
   layer (per-trade ATR-based SL + TP), not at the *entry* layer
   via a pre-trade cash buffer."

**核心发现 (FRESH 2026-09-23):** `position_fraction` 若被引擎静默忽略,
`1.0` 的 preset 靠巧合仍然对, 而 `0.5` 的半仓会**静默变满仓** ⇒ 实际风险 2×。

---------------------------------------------------------------------------
⛔ 2026-10-19 (§13.66): 本文件此前**三个族里有三个是空转的** —— 已重写
---------------------------------------------------------------------------
原版把引擎路径**手写死**为:
    chase_up/portfolio.py / uptrend_pullback/portfolio.py / short_reversal/portfolio.py
三处问题, 全部由**缺陷注入**暴露 (注入 `replay_strategy_v3.py:792` 去掉
`position_fraction`, 本文件**毫无反应**):

1. **`short_reversal/portfolio.py` 根本不存在** —— short_reversal 的引擎是
   `short_reversal/replay_strategy_v3.py`。不存在的路径 ⇒ `has_portfolio_class=False`
   ⇒ 那条测试 **early-return, 空转**; 而**真正的引擎文件从未被扫过**。
   (文件头 D 节把它写成 `short_reversal/portfolio.py:try_enter` —— 那个路径从来没有过。)
2. **`cycle_price_action` 不在清单里**, 一条测试都没有。原因是文件头 D 节断言
   "cycle_price_action: no Portfolio class (uses cerebro), skip" —— **而那句话是错的**:
   `cycle_price_action/portfolio.py:69` 就是 `class Portfolio`。**一个未被核实的前提,
   让一整族失明。**
3. **AST 扫描只断言"文件里出现过 `position_fraction`"**。同文件 245 行的行为式守卫
   自己就写明了这一点: "上面那几个 AST 扫描只断言源码里「出现」标识符 ——
   一条 fail-fast 断言也能满足它"。而那条行为式守卫**只给 uptrend 补了**。

### 修法 (三处, 都是"让空转变响", 不改任何生产代码)
* **发现式取文件** + **断言每个路径存在** + **断言每个族都被扫到** (§13.43/§13.45 的同一手段);
* 断言改为**路径感知**: `position_fraction` 必须出现在**赋值给 sizing 变量**的表达式里,
  而不是文件里任意一处;
* `chase_up` / `cycle_price_action` 的"**preset 声明了、引擎不读**"登记为
  **自失效豁免** (§13.24 的形状): 债还清 ⇒ 立刻红, 提示删掉豁免。

### 实测结论 (重写后)
| 族 | preset 声明 | 引擎的 sizing 表达式里读到 | 判定 |
|---|---|---|---|
| `uptrend_pullback` | ✅ | ✅ `slot_value *= position_fraction` | 通过 (+ 行为式守卫) |
| `short_reversal` | ✅ | ✅ `target_value = free_cash * position_fraction` | 通过 |
| `chase_up` | **22/22** | ❌ **无** | **登记在案的 §2 违反** |
| `cycle_price_action` | **21/21** | ❌ **无** | **登记在案的 §2 违反** |

⇒ 两族是"**声明了却不被读**": §2 要求 preset 显式声明 (它们做到了), 但引擎不消费它 ——
**声明本身因此不携带信息**。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 预算类变量的名字 —— 每一处对它们的赋值都必须引用 position_fraction 或 max_positions
BUDGET_TARGETS = {"target_value", "slot_value", "budget", "budget_value", "target_qty"}

# §2 允许的**替代**: N 槽等额 (max_positions > 1 时每笔 = free_cash / N)。
# 因此"这条预算赋值没有 position_fraction"本身不算违反 —— 除非它连 max_positions 也没有。
ALTERNATIVE_ALLOWED = {"max_positions"}

# ⛔ 登记的债 (§13.66): 这些族的 preset **声明了** position_fraction, 而引擎**不读**它。
# **修好后必须删掉对应那一行** —— 下面的断言会在债还清时立刻变红。
REGISTERED_DEBT = {
    "chase_up": "§13.66 —— 22/22 preset 声明 position_fraction, 而 "
                "chase_up/portfolio.py 的 sizing 只用 `cash_only / max_positions`, "
                "从不读 position_fraction。修它属**结果变更** (半仓会真的变半仓), 按授权只登记。",
    "cycle_price_action": "§13.66 —— 21/21 preset 声明 position_fraction, 而 "
                          "cycle_price_action/portfolio.py 的 Portfolio 里没有 "
                          "position_fraction 这个参数 (只有类常量 MAX_POSITION_PCT=1.0)。"
                          "补它属**架构变更**, 按授权只登记。",
}


def _families() -> list[str]:
    """发现式: 任何含 `presets.py` 的目录都是一个族 (§13.22/§13.23 的教训)。"""
    return sorted(p.parent.name for p in REPO_ROOT.glob("*/presets.py"))


def _engine_files() -> list[Path]:
    """**发现式**取引擎文件 —— 不再手写清单。

    `*/portfolio.py` 覆盖三个族 (含此前被漏掉的 `cycle_price_action`);
    `short_reversal` 的引擎是 `replay_strategy_v3.py`, 单列 (§13.66: 此前手写的
    `short_reversal/portfolio.py` 根本不存在)。
    """
    files = sorted(REPO_ROOT.glob("*/portfolio.py"))
    extra = REPO_ROOT / "short_reversal" / "replay_strategy_v3.py"
    if extra.exists():
        files.append(extra)
    return files


def _mentions(node: ast.AST, name: str) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == name:
            return True
        if isinstance(n, ast.Name) and n.id == name:
            return True
    return False


def _budget_assignments(tree: ast.AST) -> list[tuple[int, bool, bool]]:
    """★ 路径感知: 所有赋值给**预算类变量**的语句 → [(行号, 含 position_fraction, 含 max_positions)]。

    为什么不能只问"文件里出现过 position_fraction" (§13.66 的注入实证):
    `short_reversal/replay_strategy_v3.py` 有**两处** budget 赋值读它 (768 的 atr 分支、
    792 的常规分支)。只要求"有一处"⇒ 把 792 改成常数**照样绿**。

    ⇒ 正确的不变式是**逐处**的: 每一处预算赋值都必须引用 `position_fraction`
      **或** `max_positions` (§2 认可的 N 槽等额形态)。这样任何一处退化成常数都会红。
    """
    out: list[tuple[int, bool, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in BUDGET_TARGETS:
                    out.append((node.lineno, _mentions(node.value, "position_fraction"),
                                any(_mentions(node.value, a) for a in ALTERNATIVE_ALLOWED)))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id in BUDGET_TARGETS:
                out.append((node.lineno, _mentions(node.value, "position_fraction"),
                            any(_mentions(node.value, a) for a in ALTERNATIVE_ALLOWED)))
    return out


def _scan() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for path in _engine_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        out[rel.as_posix()] = {
            "family": rel.parts[0],
            "budget_assignments": _budget_assignments(tree),
        }
    return out


# ---------------------------------------------------------------------------
# 反空转守卫 (§13.66): 扫描本身必须是真的
# ---------------------------------------------------------------------------


def test_engine_file_list_is_discovery_based_and_all_paths_exist() -> None:
    """每个被扫的路径都必须**存在** —— 不存在的路径会让那条测试静默 early-return。

    §13.66 的根因之一: 手写的 `short_reversal/portfolio.py` 从来不存在,
    于是 short_reversal 那条测试**空转了不知道多久**。
    """
    files = _engine_files()
    missing = [str(p.relative_to(REPO_ROOT)) for p in files if not p.exists()]
    assert not missing, f"扫描清单里有不存在的路径: {missing} —— 那些测试会静默空转"
    assert len(files) >= 4, f"只取到 {len(files)} 个引擎文件: {files}"


def test_every_family_is_scanned() -> None:
    """**每个族**都必须至少有一个被扫到的引擎文件 —— 防"一整族失明"。

    §13.66 的根因之二: 文件头断言 "cycle_price_action: no Portfolio class, skip"
    —— 而 `cycle_price_action/portfolio.py:69` 就是 `class Portfolio`。
    **一个未被核实的前提让一整族没有被检查过。**
    """
    scanned = {p.relative_to(REPO_ROOT).parts[0] for p in _engine_files()}
    blind = [f for f in _families() if f not in scanned]
    assert not blind, f"这些族**没有任何**引擎文件被扫到, 守卫对它们失明: {blind}"


# ---------------------------------------------------------------------------
# §2: 每个族的 sizing 表达式必须**真的**读到 position_fraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fam", _families())
def test_sizing_expression_uses_position_fraction(fam: str) -> None:
    """§2: **每一处**预算赋值都必须引用 `position_fraction`, 或 §2 认可的 `max_positions`。

    判据是**逐处路径感知**的, 不是"文件里出现过" —— 见 §13.66 的注入实证:
    只要求"有一处"会让"另一处退化成常数"完全隐身。
    """
    hits = {k: v for k, v in _scan().items() if v["family"] == fam}
    if not hits:
        pytest.skip(f"{fam}: 没有扫到引擎文件 (由 test_every_family_is_scanned 负责报警)")

    entries = [e for v in hits.values() for e in v["budget_assignments"]]  # type: ignore[index]
    any_pf = any(has_pf for _, has_pf, _ in entries)
    where = ", ".join(f"{k}:{[e[0] for e in v['budget_assignments']]}"  # type: ignore[index]
                      for k, v in hits.items())

    ok = bool(entries) and any_pf

    if fam in REGISTERED_DEBT:
        assert not ok, (
            f"{fam} 现在**已经**在预算表达式里读 position_fraction 了 ({where}) —— "
            f"说明 §13.66 那笔登记的债已经还清。请把 REGISTERED_DEBT 里 `{fam}` 这一条删掉 "
            f"(豁免不得继续挂着), 并在 docs/strategy_mining_log.md §13.66 记下结果漂移。"
            f"\n债的原文: {REGISTERED_DEBT[fam]}"
        )
        pytest.xfail(f"{fam}: 登记在案的 §2 违反 —— {REGISTERED_DEBT[fam]}")

    assert entries, (
        f"§2: {fam} 里**找不到任何**预算赋值 (赋值给 {sorted(BUDGET_TARGETS)}) —— "
        f"守卫对这一族的 sizing 无内容, 必须先让扫描认出它的形态。"
    )
    assert any_pf, (
        f"§2: {fam} 的预算赋值**没有一处**读 position_fraction: {where}\n"
        f"⇒ preset 里声明的 position_fraction 被引擎静默忽略。"
    )


# ---------------------------------------------------------------------------
# ⛔ 本守卫**做不到**什么 (§13.66 实测, 不是推断)
# ---------------------------------------------------------------------------
# 注入实证 (2026-10-19): 把 `short_reversal/replay_strategy_v3.py` 的
#   792 行 `target_value = self.free_cash * self.p.position_fraction` 改成 `* 1.0`
# 本文件**不会变红** —— 因为 768 行 (atr 分支) 也读 position_fraction,
# "至少有一处" 仍然成立。
#
# 试过更严的规则「**每一处**预算赋值都必须引用 position_fraction 或 max_positions」:
# **它抓得到那两次注入, 但产生 5 处假报** —— 全是合法形态:
#   `slot_value = cash_only`                        (all_in 分支, 分数恒为 1.0)
#   `slot_value = cash_only * kelly_fraction`        (kelly 分支, §2 认可的另一种模式)
#   `budget = min(slot_value, pf.free_cash)`         (下游钳制; 那个 `pf` 是**持仓对象**, 同名巧合)
# ⇒ **假报的守卫与不响的守卫是同一回事** (§13.19/§13.58 的同一病) ⇒ 该规则已收回。
#
# ⇒ **结论 (实测): AST 无法证明 §2 这条性质** —— 它只能证明"某处用到"。
#   真正能证明的是**行为式**守卫 (`test_uptrend_pullback_position_fraction_scales_order_size`),
#   而**四族里只有 uptrend 有**。
#   **未做 (下一轮的入口)**: 给 `short_reversal` / `cycle_price_action` / `chase_up`
#   各补一条同强度的行为式守卫 (三者引擎接口不同: 前者 backtrader, 中者 backtrader,
#   后者 pandas) ⇒ 需要各写一份 fixture。


# ---------------------------------------------------------------------------
# 行为式守卫: 声明必须真的缩放**下单规模** (只给 uptrend 有 —— 见下)
# ---------------------------------------------------------------------------


def test_uptrend_pullback_position_fraction_scales_order_size() -> None:
    """§2: uptrend_pullback 必须真正按 position_fraction 缩放下单规模。

    上面那几个 AST 扫描只断言源码里「出现」标识符 —— 一条 fail-fast 断言也能
    满足它。这里跑行为: 同一组输入在 position_fraction=1.0 / 0.5 下各下一次单,
    断言规模按比例缩放 (fixture 特意把 volume cap 调高, 使预算而非成交量成为约束)。

    ⚠️ §13.66: **四族里只有这一族有行为式守卫。** 其余三族的引擎接口不同
    (`chase_up`/`uptrend` 是 pandas `simulate_portfolio(entries, panel, …)`;
    `short_reversal`/`cycle` 走 backtrader) ⇒ 同样强度的行为式守卫需要另写三份。
    **这是本册唯一能真正证明"声明→规模"的手段 ⇒ 记为未做, 不是已否。**
    """
    import pandas as pd

    from uptrend_pullback.portfolio import simulate_portfolio

    def _bar(day: str) -> dict[str, object]:
        return {"date": pd.Timestamp(day), "thscode": "SIZE.SZ", "open": 10.0,
                "high": 10.5, "low": 9.5, "close": 10.0, "volume": 100_000.0,
                "amount": 1e6, "atr_pct": 0.05}

    panel = pd.DataFrame([_bar("2025-09-01"), _bar("2025-09-02"), _bar("2025-09-03")])
    entries = pd.DataFrame([
        {"date": pd.Timestamp("2025-09-01"), "thscode": "SIZE.SZ",
         "score": 1.0, "atr_pct": 0.05},
    ])

    def _size(position_fraction: float) -> int:
        trades, _ = simulate_portfolio(
            entries, panel,
            tp_pct=0.10, sl_pct=0.05, max_hold=8, max_positions=1,
            start_date="2025-09-01", end_date="2025-09-03",
            initial_capital=10_000.0,
            position_sizing="all_in",
            position_fraction=position_fraction,
            commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        )
        assert len(trades) == 1, f"fixture 应产生 1 笔成交, 实际 {len(trades)}"
        return int(trades.iloc[0]["size"])

    full, half = _size(1.0), _size(0.5)
    assert full == 1000, f"position_fraction=1.0 应为满仓 1000 股, 实际 {full}"
    assert half == 500, (
        f"§2 POSITION_FRACTION IGNORED: position_fraction=0.5 应下 500 股, "
        f"实际 {half} (1.0 时为 {full})。等值说明该 preset 键被引擎静默忽略 —— "
        f"半仓变全仓, 实际风险 2× 于 preset 声明。"
    )
