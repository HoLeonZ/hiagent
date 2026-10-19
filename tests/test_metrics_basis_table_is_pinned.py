"""§13.13 那条禁令的**可执行化**: 四族同名指标的**口径对照表**, 逐族钉死。

## 背景
* §13.13 实测: 四族**全部都会报**的指标只有 4 个 (`cagr`/`sharpe`/`max_dd`/`win_rate`),
  而**这 4 个全部定义不同** ⇒ 立了一条禁令:
  > **不得把这 4 个量中的任何一个当作跨族"可比指标"引用, 除非先对齐定义。**
* §13.15: 要修指标层, 第一步**不是**建 `core/metrics.py`, 而是
  **一个查取值/语义的跨引擎测试** —— 而那个测试"今天必然红" ⇒ 闭环一直没开。

## 本文件做什么 / 不做什么
**做**: 把那张对照表从**散文**变成**机器可读的常量**, 并让任何一族的定义变动**立刻变红**。
**不做**: **不把四族统一** —— 统一属**结果变更** (会动四条回测链的全部历史指标),
按既有授权只登记。本节只让"定义不同"这件事**有载体、且不许静默变化**。

## 表是**量出来的**, 不是回忆的 (出处逐条写在 `_SOURCE` 里)
| 量 | `chase_up` | `uptrend_pullback` | `short_reversal` | `cycle_price_action` |
|---|---|---|---|---|
| 年化常数 | **243** | **243** | **252** | **252** |
| `sharpe` 基准 | 日频净值 ×√243 | 同 | `_equity_sharpe` (252) | 日频净值 ×√252 |
| `cagr` 分母 | `n_days/243` | `n_days/243` | `_years_between(...)` | `n/252` |
| `max_dd` 基准 | 净值 (NAV) | 净值 (NAV) | 净值 (NAV) | 净值 (NAV) |
| `win_rate` 字段 | `net`(=`gross-fees`, 元) | 同 | `net_pnl`(现金走账) | `n_wins/n` |
"""
from __future__ import annotations

import importlib
import math

import pytest

# ---------------------------------------------------------------------------
# 对照表 (机器可读; 出处见 _SOURCE)
# ---------------------------------------------------------------------------


def _trading_days(fam: str) -> int:
    """从模块**导入常量**取值 —— 不读源码文本 (§13.78 的教训)。"""
    if fam in ("chase_up", "uptrend_pullback"):
        return int(getattr(importlib.import_module(f"{fam}.backtest"), "TRADING_DAYS"))
    if fam == "short_reversal":
        return int(getattr(importlib.import_module("short_reversal.engine"),
                           "TRADING_DAYS_PER_YEAR"))
    if fam == "cycle_price_action":
        return int(getattr(importlib.import_module("cycle_price_action.allocator"),
                           "TRADING_DAYS_PER_YEAR"))
    raise KeyError(fam)


PINNED_TRADING_DAYS = {
    "chase_up": 243,
    "uptrend_pullback": 243,
    "short_reversal": 252,
    "cycle_price_action": 252,
}

_SOURCE = {
    "chase_up": "chase_up/backtest.py:22 `TRADING_DAYS = 243`; sharpe ×√243 (同文件 :52); "
                "max_dd 用净值 (:55); win_rate 用 `net` = gross−fees, 元 (:368/:77)",
    "uptrend_pullback": "uptrend_pullback/backtest.py:27 `TRADING_DAYS = 243` (:62 ×√243); "
                        "docstring 自陈「max_dd / Sharpe 用净值, 不用逐笔」; win_rate `net` (:345/:90)",
    "short_reversal": "short_reversal/engine.py:53 `TRADING_DAYS_PER_YEAR = 252`; "
                      "**独立**的 `_equity_sharpe` (:121, 自陈年化常数 252); "
                      "cagr 分母走 `_years_between` (:172); win_rate 按 `net_pnl` (:181)",
    "cycle_price_action": "cycle_price_action/allocator.py:41 `TRADING_DAYS_PER_YEAR = 252` (:161 ×√252); "
                          "⚠️ 另有一个 `cycle_price_action/metrics.py` 返回 `sharpe=None, max_dd=None` —— "
                          "**两个产出者**, 完整的那份在 allocator",
}


@pytest.mark.parametrize("fam", sorted(PINNED_TRADING_DAYS))
def test_family_trading_days_match_the_pinned_table(fam: str) -> None:
    """逐族的**年化常数**必须与对照表一致 —— 它是四族口径差异里最硬的一条。"""
    got = _trading_days(fam)
    assert got == PINNED_TRADING_DAYS[fam], (
        f"§13.13/§13.87: {fam} 的年化常数由 {PINNED_TRADING_DAYS[fam]} 变成 {got}。\n"
        f"这**不一定**是缺陷 —— 但它是四个族共用名字的量的口径之一, **任何变化都必须在 "
        f"docs/strategy_mining_log.md §13.13 的对照表里同步**, 否则「跨族不可比」那条禁令的"
        f"依据就变成了过期信息。\n出处: {_SOURCE[fam]}"
    )


def test_table_records_that_families_actually_differ() -> None:
    """这张表的**内容**就是"四族不同" —— 若哪天被统一了, 本测试必须红以提示更新禁令。

    (§13.13 的禁令建立在"4/4 定义不同"上; 若有人把 243/252 统一, 那条禁令的依据就变了,
     而**没有任何测试会因此变红** —— 这个测试就是那道缺口。)
    """
    vals = set(PINNED_TRADING_DAYS.values())
    assert len(vals) >= 2, (
        "§13.87: 四族的年化常数现在**已经一致**了 —— 这是好事, 但必须同步: "
        "1) 更新 §13.13 的对照表; 2) 重新评估'四个共享指标不可跨族引用'那条禁令是否仍然成立。"
        "本断言是**自失效**的: 它存在的唯一理由是「表里必须记录真实的差异」。"
    )
    assert PINNED_TRADING_DAYS["chase_up"] == PINNED_TRADING_DAYS["uptrend_pullback"] == 243
    assert PINNED_TRADING_DAYS["short_reversal"] == PINNED_TRADING_DAYS["cycle_price_action"] == 252


def test_the_243_vs_252_gap_is_the_documented_1_8_percent() -> None:
    """两族年化常数之比 = √(252/243) ≈ 1.8% —— 与 `short_reversal` 注释自陈的量级一致。

    这是把"散文里的 1.8%"与"表里的两个整数"**对上**的一道小校验:
    若有人改了常数而没改注释, 这里会露。
    """
    ratio = math.sqrt(252 / 243)
    assert abs(ratio - 1.01835) < 1e-4, f"√(252/243) = {ratio} —— 与注释自陈的 1.8% 不符"
    # 且它**确实**是四族之间唯一被量到的标度差 (不是排序差)
    assert max(PINNED_TRADING_DAYS.values()) / min(PINNED_TRADING_DAYS.values()) == 252 / 243


# ---------------------------------------------------------------------------
# §13.89: 口径**自披露** —— 让表"从产出可读", 而不是只由本文件写死
# ---------------------------------------------------------------------------

_BASIS_MODULE = {
    "chase_up": "chase_up.backtest",
    "uptrend_pullback": "uptrend_pullback.backtest",
    "short_reversal": "short_reversal.engine",
    "cycle_price_action": "cycle_price_action.allocator",
}

# 各族的**自披露**应当与上表一致 —— 这是"表"与"引擎"之间的唯一接缝。
PINNED_BASIS = {
    "chase_up": {"trading_days": 243, "sharpe": "equity",
                 "cagr_denominator": "evaluated_days", "win_rate_field": "net",
                 "max_dd": "nav_mtm"},
    "uptrend_pullback": {"trading_days": 243, "sharpe": "equity",
                         "cagr_denominator": "evaluated_days", "win_rate_field": "net",
                         "max_dd": "nav_mtm"},
    "short_reversal": {"trading_days": 252, "sharpe": "equity",
                       "cagr_denominator": "evaluated_days", "win_rate_field": "net_pnl",
                       "max_dd": "nav_mtm"},
    "cycle_price_action": {"trading_days": 252, "sharpe": "equity",
                           "cagr_denominator": "evaluated_days", "win_rate_field": "pnl",
                           "max_dd": "realized_no_mtm"},
}


def _disclosed_basis(fam: str) -> dict:
    """从引擎**自己声明的单一来源**取值 —— 不读源码文本、不重写一遍。"""
    mod = importlib.import_module(_BASIS_MODULE[fam])
    return dict(mod.METRICS_BASIS)


@pytest.mark.parametrize("fam", sorted(PINNED_BASIS))
def test_disclosed_basis_matches_the_pinned_table(fam: str) -> None:
    """§13.89: 引擎**报出的**口径必须与 §13.13 的对照表一致。

    这条把那张表从"我读完源码写下的字符串"变成**与引擎的单一声明对齐的实测**。
    """
    got = _disclosed_basis(fam)
    assert got == PINNED_BASIS[fam], (
        f"§13.89: {fam} 的 `METRICS_BASIS` 与对照表不符。\n"
        f"  表: {PINNED_BASIS[fam]}\n  引擎: {got}\n"
        f"⇒ 若这是有意的口径变更, 请同步更新 docs/strategy_mining_log.md §13.13 的对照表"
        f"与本文件的 `PINNED_BASIS`; 若是无意的, 那它就是一次**静默的口径漂移**。"
    )


def test_disclosure_is_a_single_source_not_a_copy() -> None:
    """§13.89: 披露必须**只有一份** —— metrics 里报出的那个必须是同一个对象的内容。

    做法: 拿 cycle 的纯函数真跑一次, 比对它报出的 `metrics_basis` 与模块常量。
    (另三族要从 `backtest`/`engine` 跑出 metrics, 代价高; 它们的两处 dict 都写成
     `dict(METRICS_BASIS)`, 由 `test_every_family_discloses_single_source_in_source` 覆盖。)
    """
    import cycle_price_action.allocator as ca

    eq = [1_000_000.0 * (1 + 0.001 * i) for i in range(50)]
    res = ca.AllocationResult(
        trading_days=list(range(50)), equity=eq, taken=[], n_signals=0,
        n_rejected_capacity=0, exposure=0.0, initial_capital=1_000_000.0, final_equity=eq[-1],
    )
    m = ca.portfolio_metrics(res)
    assert "metrics_basis" in m, "§13.89: cycle 的 portfolio_metrics 不再报 metrics_basis"
    assert m["metrics_basis"] == dict(ca.METRICS_BASIS), (
        "§13.89: cycle 报出的 metrics_basis 与模块常量不一致 ⇒ 披露被复制成了第二份"
    )


@pytest.mark.parametrize("fam", sorted(_BASIS_MODULE))
def test_every_family_discloses_single_source_in_source(fam: str) -> None:
    """§13.89: 每个族的 metrics dict 里必须是 `dict(METRICS_BASIS)` —— 不得内联再写一遍。

    (AST 判定: 找 `metrics_basis` 这个键在 dict 字面量里的值节点是否为 `dict(METRICS_BASIS)`。)
    """
    import ast
    from pathlib import Path as _P

    src_path = _P(_BASIS_MODULE[fam].replace(".", "/") + ".py")
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "metrics_basis":
                    found += 1
                    assert isinstance(v, ast.Call) and ast.unparse(v) == "dict(METRICS_BASIS)", (
                        f"§13.89: {fam} 的 metrics dict 里 `metrics_basis` 不是 "
                        f"`dict(METRICS_BASIS)` 而是 `{ast.unparse(v)}` ⇒ 又是「同名两份」。"
                    )
    assert found >= 1, f"§13.89: {fam} 的 metrics dict 里**找不到** metrics_basis 键"


# ---------------------------------------------------------------------------
# §13.90: 跨族**报表生成器**必须披露口径 (发现式 + 具名豁免)
# ---------------------------------------------------------------------------

_FAMS = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

# 具名豁免: 提到 ≥2 个族名, 但**不做跨族并列** (按 preset 各自出报告, 不合并不排序)。
_EXEMPT = {
    "tools/entry_gap_attribution.py":
        "§13.90/§13.137 —— 它**一次只处理一个族** (`--family` 选一个), 输出里**没有跨族并列**、"
        "不合并行、不排序 ⇒ 无需口径披露。四个族名只出现在 `--family` 的**取值清单**里。"
        "(⚠️ 与本轮另一个新工具 `gap_stop_attribution_4engine.py` **不同**: 那个**真的**"
        "把四族放进同一张表 ⇒ 那个补了披露、**不走豁免**。"
        "两者的区别正是本条守卫要区分的那件事。)",
    "tools/scan_dead_text_pins.py":
        "§13.90/§13.122 —— 它只做**文本钉桩的静态分析** (在测试文件的源码里找"
        "`assert \"…\" in SRC` / `SRC.index(\"…\")` 这类断言, 再去被钉的**那个文件**里"
        "核对该字面量在不在)。它**不读任何一族的指标**、不合并行、不排序、"
        "不产出任何数 ⇒ **没有跨族并列**, 无需口径披露。"
        "(族名只是它注释里**举例**用的 —— 那个例子的目标文件恰好是引擎源码。"
        "⚠️ 这是本守卫抓到的**第三个**新工具, 三次都是「提到族名 ≠ 并列族口径」。)",
    "tools/scan_unused_core_imports.py":
        "§13.120 —— 它只用四个族名作**目录名**去遍历 (PKGS 列表), **不读任何一族的指标**、"
        "不合并行、不排序 ⇒ **没有跨族并列**, 无需口径披露。"
        "(⚠️ 本条目是 §13.90 的守卫在我**第二个**新工具上**再次抓到我**之后加的 —— "
        "上一个普查工具被它抓到时我选择了补披露, 这一次它确实不并列, 故走豁免。)",
    "tools/preset_census.py":
        "§13.90/§13.110 —— 该工具**确实把四族计数并排**, 故它在 §13.110 已改为"
        "**静态 `from … import METRICS_BASIS`** 并在输出里披露; 此处豁免**仅为**"
        "免得发现式扫描把它当成「只提到未披露」的第三类。",
    "tools/render_top5_presets_html.py":
        "§13.90 —— 该脚本为 5 个 preset **各自**输出一份 HTML, 只在选加载器时分支到族名, "
        "既不合并行也不跨族排序 ⇒ **没有跨族并列**, 无需口径披露。",
}


def _cross_family_tools() -> list:
    """发现式: `tools/` 下**同时提到 ≥2 个族名**的 `.py`。"""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1] / "tools"
    out = []
    for p in sorted(root.rglob("*.py")):
        try:
            s = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if sum(1 for f in _FAMS if f in s) >= 2:
            out.append(p.relative_to(root.parent).as_posix())
    return out


# 族名 → 承载其披露的模块
_BASIS_MODULE_OF_FAMILY = {
    "chase_up": "chase_up.backtest",
    "uptrend_pullback": "uptrend_pullback.backtest",
    "short_reversal": "short_reversal.engine",
    "cycle_price_action": "cycle_price_action.allocator",
}


def _families_mentioned(rel: str) -> set:
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
    return {f for f in _FAMS if f in src}


def _families_disclosed(rel: str) -> set:
    """该文件**真的 import 了**哪些族的 `METRICS_BASIS` (AST 判定)。

    ⚠️ §13.90: 第一版是 `return True`——**只要有一处 import 就算满足**。
    注入实证: 四族里删掉一个 ⇒ **仍然 18 passed 不响**。
    这正是本册记了 15 轮的「任一处匹配即满足」。⇒ 改判**逐个族**:
    **提到哪个族, 就得披露哪个族** (否则被并列的那些数里, 有人的口径没人说)。
    """
    import ast
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in _BASIS_MODULE_OF_FAMILY.values():
            for a in n.names:
                if a.name == "METRICS_BASIS":
                    for fam, mod in _BASIS_MODULE_OF_FAMILY.items():
                        if mod == n.module:
                            out.add(fam)
    return out


def test_discovery_finds_cross_family_tools() -> None:
    """发现式扫描必须真的找到东西 —— 否则下面的断言全是空的 (§13.19 的教训)。"""
    found = _cross_family_tools()
    assert len(found) >= 2, f"只发现 {len(found)} 个跨族工具: {found} —— 发现逻辑坏了"


def test_every_cross_family_tool_discloses_basis_or_is_exempt() -> None:
    """§13.90: 会**跨族并列**的报表生成器**必须**从引擎导入 `metrics_basis` 并报出来。

    这与 §13.13 那条禁令是同一件事的产物侧: 禁令说"不得把这四个量当作跨族可比指标引用",
    而**报表正是最容易发生那次引用的地方** (三张榜单)。
    """
    found = _cross_family_tools()
    gaps = {}
    for t in found:
        if t in _EXEMPT:
            continue
        missing = _families_mentioned(t) - _families_disclosed(t)
        if missing:
            gaps[t] = sorted(missing)
    assert not gaps, (
        f"§13.90: 这些工具**提到**了某些族, 却没披露它们的口径: {gaps}\n"
        f"⇒ 请为每个被并列的族 import 它的 `METRICS_BASIS` 并把差异报进产出; "
        f"若某个族名只是顺带提到、并未并列其数字, 请把该工具加入 `_EXEMPT` 并写明理由。"
    )


def test_exemptions_do_not_swallow_the_whole_population() -> None:
    """反空转: 豁免名单不得大到把整个总体吞掉 (否则这条守卫等于没有)。"""
    found = _cross_family_tools()
    assert len(_EXEMPT) < len(found), (
        f"§13.90: 豁免 {len(_EXEMPT)} 个, 而发现只有 {len(found)} 个 ⇒ 豁免把总体吞光了"
    )
    for rel in _EXEMPT:
        assert rel in found, (
            f"§13.90: 豁免里的 `{rel}` 已经不在发现集里 ⇒ 那条豁免该删了"
        )
