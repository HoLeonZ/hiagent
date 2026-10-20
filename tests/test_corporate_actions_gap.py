"""§3 Event-Sourced Corporate Actions RED tests: 现金股息 + 拆股事件无 handler.

CLAUDE.md §3: "Cash dividends must explicitly trigger a physical cash
deposit into Free_Cash. Stock splits must trigger an atomic multiplier
adjustment to Position_Quantity and Average_Cost."

当前状态:
- 任何 engine (chase_up / uptrend_pullback / short_reversal /
  cycle_price_action) 均无 dividend_handler / split_handler 函数
- v_daily_qfq 使用前复权价, 历史分红已隐式嵌入 adj_close 序列
- 但 CLAUDE.md §3 显式要求物理 cash deposit + 拆股 quantity/cost 调整

设计张力 (用户决策点):
- 选项 A (当前): 全部用 adj_close (前复权), 分红已隐式嵌入价格差,
  不再做 cash deposit → 价格已反映, 不会双重计算
- 选项 B (CLAUDE.md §3 字面): 用 raw_close + 显式 dividend event handler
  把分红计入 Free_Cash, 拆股时调整 quantity + avg_cost

按 CLAUDE.md §3 字面执行, 当前是 ✗ (无 event handler). 本测试 RED 锁定
该 gap, 修复方案需用户拍板 (选 A 还是 B).

2026-10-13 决策 (uptrend_pullback 部分已收口):
- 实测该策略 (v33_long_reverse_v19, 2024-09-01..2026-09-01) 持仓期中位数仅
  **3 天**, 105 笔交易中**没有任何一笔持仓穿过除权日** → 漏记分红现金 = 0,
  除权日幻影止损 = 0 (同窗口全市场 9,667 个除权日, 故「零」是真实结果)。
- 因此 uptrend_pullback 选择『不实现显式 CA handler, 但用可证伪的行为守卫
  锁住零暴露前提』, 见 tests/test_uptrend_pullback_corporate_actions_exposure.py。
  这样既不写投机性 event 引擎, 也不会留下无法执行的永久红灯。
- 既不采用选项 A 的字面表述 (「一律 adj_close」会与 §3 执行层用 raw 价冲突),
  也未采用选项 B (当前无实测收益)。
- 其余 3 个 engine 仍未收口, 继续 RED (超出本次改动范围)。

2026-10-19 (§13.26) 补测 —— **"零暴露"是 preset/窗口特定的, 不推广**:
  同一窗口 2024-10-08..2026-09-29、同一判定 (除权日在 (entry, exit] 内):

  | 族 | 成交 | 穿越除权日 | 含送股 | 漏记分红现金 |
  |---|---|---|---|---|
  | `uptrend_pullback` (已收口, 用的是**另一个** preset/窗口) | 105 | **0** | 0 | 0 |
  | `short_reversal` (v58_mp_2) | 642 | **3** | **1** | 4,475.90 |
  | `chase_up` (chase_v5_pos2_...) | 75 | **1** | 0 | 2,070.00 |
  | `cycle_price_action` (PRESET_V1) | 24,610 | **164** | **7** | 2,782,753 |

  ⇒ 本测试的 3 条 RED **不是形式问题**: 有实测暴露, 而 cycle 的暴露量级不小。
  ⇒ 其中**送股**才是最危险的一类 (现金分红只造成 ~1% 的缺口): 送股会让**不复权的
     raw 价**出现机械缺口。已完整定案一笔 —— `short_reversal` / `002976.SZ`
     2026-06-25 建 @33.65 → 06-26 平 @27.59, 记为 **TP +17.9% / +9,644.58 元**;
     而 06-26 的复权价是 **上涨 0.7%** (43.92 → 44.24), raw 价却 −22.7%
     (35.70 → 27.59, 正是 1/1.3 的除权比例)。**该空头在股票上涨的那天记了一笔
     幻影止盈。**
  ⇒ 复现: `python -c "..."` 见 docs/strategy_mining_log.md §13.26。

修复方案:
- 选 A: 在 CLAUDE.md §3 增加注释 "本项目以 adj_close 前复权为 canonical
  source, 视为隐式 event 注入, 无需独立 handler"
- 选 B: 增加 dividend_events 表 + 引擎逐 bar 检查, 对持仓股票匹配
  ex_date 后:
    - cash += held_qty × dividend_per_share
    - 平均成本不变 (cash 已入账)
  + split_events 表:
    - held_qty *= split_ratio
    - avg_cost /= split_ratio
"""
from __future__ import annotations

import ast

from pathlib import Path

import pytest


def _engine_has_event_handler(module_name: str) -> bool:
    """引擎是否**导入并调用**了公司行为 handler(audit P3, 2026-10-15)。

    原实现是**子串启发式**:在引擎源码里找 "dividend" 且 ("handler"|"_apply"|
    "trigger")。它刚在一个合法重构上失效 —— 把 handler 提到 core 单源、引擎改为
    导入调用之后,引擎文件里仍有 "dividend" 但不再有 "_apply",于是判为"无 handler",
    而语义完全没变(反而更好了)。

    这正是审计反复指出的"守卫断言的是文本形状而非行为"。改为 AST 判定:
      (a) 从 core.corporate_actions 导入 apply_corporate_action,且
      (b) 源码中确实**调用**了它。
    对未接入的引擎为 False —— 那就是诚实的现状。
    """
    import importlib

    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return False
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    imported = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "core.corporate_actions"
        and any(a.name == "apply_corporate_action" for a in n.names)
        for n in ast.walk(tree)
    )
    if not imported:
        return False
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "apply_corporate_action"
        for n in ast.walk(tree)
    )


@pytest.mark.parametrize("module", [
    "chase_up.portfolio",
    "uptrend_pullback.portfolio",
    "short_reversal.replay_strategy_v3",
    "cycle_price_action.portfolio",
])
def test_engine_has_dividend_or_split_handler(module: str) -> None:
    """§3 Event-Sourced: 任何 engine 都应有 dividend_handler 或 split_handler。

    当前 RED: 4 个 engine 均无 (因为使用 adj_close 前复权隐式嵌入分红,
    但 CLAUDE.md §3 字面要求显式 handler)。
    """
    if _engine_has_event_handler(module):
        pytest.skip(
            f"{module} 已实现 dividend/split handler (GREEN, 本测试 supersede)"
        )
    # 背景(2026-10-13):uptrend_pullback 曾因"持仓期中位数仅 3 天、窗口内无持仓
    # 穿过除权日"而决策不实现显式 handler。2026-10-15 已接入 core 共享实现,
    # 故该理由不再适用 —— 判定统一由 _engine_has_event_handler 给出。
    # 原先按模块名硬编码的那条 uptrend skip **已删除**: 它在 handler 被移除时
    # 会**照旧跳过**(典型死钉桩 —— 永不可能通过的守卫的反面), 而现在"接入了就
    # skip / 没接入就 RED"由同一个判定给出, 不再有第二种豁免路径。
    #
    # ⚠️ 但『uptrend 零暴露』这件事**只对它的一个 preset + 一个窗口**成立, 不得
    # 据此认为 §3 的 gap 是形式问题 (2026-10-19 §13.26, 实测见模块 docstring):
    # 同一窗口 2024-10-08..2026-09-29 三族穿越除权日的笔数为
    # short_reversal 3/642 (含送股 1)、chase_up 1/75、cycle_price_action **164/24610
    # (含送股 7)**; short_reversal 一笔送股穿越产生 **+17.9% 的幻影止盈**
    # (002976.SZ 2026-06-26, 空头, 复权价当天实际上涨 0.7%)。
    assert False, (
        f"GAP CAPTURED (RED): {module} 无 dividend_handler / split_handler. "
        f"CLAUDE.md §3 要求显式 cash deposit + quantity/cost 调整. "
        f"当前以 adj_close 前复权隐式嵌入分红 (设计选项 A), "
        f"需用户确认是否需切换至选项 B (raw_close + 显式 event)."
    )

# ---------------------------------------------------------------------------
# 附五十四 —— Phase-2(backtrader)引擎的公司行为缺口:**登记**而非"通过"
# ---------------------------------------------------------------------------
#
# 上面那条 `test_engine_has_dividend_or_split_handler` 把**四个 Phase-1 模块**
# 当作"四个引擎"来判定 —— 于是它宣布 §3 已闭合,而 chase_up 的 CLI **默认引擎**
# (`chase_up/main.py` 的 `--engine`, default="backtrader")恰恰是**未接入**的那条路径。
# 又一次"锁一处 ≠ 锁一族"。
#
# 事实(逐条可核):
#   * `chase_up.backtrader_engine` / `uptrend_pullback.backtrader_engine` 里
#     没有任何公司行为代码路径(AST 判定,见 `_engine_has_event_handler`)。
#   * 25 个 preset(22 chase + 3 uptrend)**全部**声明
#     `price_source_for_execution: "raw_close"` ⇒ feed 会重映射到**原始价**
#     (`backtrader_engine.py:96-103`),除权缺口因此是真实的原始价跳空。
#   * Phase-2 是**逐笔 replay**:`target_size` 在构造时固定(chase_up/replay_strategy.py),
#     没有"数量 ×(1+bonus)"或"成本价重定"的通路,也没有分红入账通路。
#   * 后果:送股除权日会按**原始股数**在**腰斩价**卖出 ⇒ 幻影 ≈ −bonus/(1+bonus) 的亏损;
#     现金分红日则把缺口记成亏损、分红永不入账。
#
# 实测暴露面(2024-09-01..2026-09-01,活库):
#   chase v8/v10/v19 共 129 笔 + uptrend v21 68 笔 ⇒ 只有 **1 笔**跨越除权日
#   (002534.SZ,2026-05-29,现金分红 0.1/21.61 = 0.46%),且该笔 Phase-1 与
#   Phase-2 结果**逐字段一致**(58 笔成交、同价同 net_pnl)。
#   即:**没有观测到 in-sample 数值背离** —— 本缺口是结构性的,不是已发生的错误。
#   不做"Phase-2 接公司行为"这件事,是因为它是**新功能**(replay 需引入持仓量/成本
#   的跨 bar 状态),属研究决策,登记待评估。

_PHASE2_ENGINES = [
    "chase_up.backtrader_engine",
    "uptrend_pullback.backtrader_engine",
]


@pytest.mark.parametrize("module", _PHASE2_ENGINES)
def test_phase2_engine_corporate_action_gap_is_registered(module: str) -> None:
    """登记:Phase-2 引擎**没有**公司行为路径 = 已知缺口(不是"通过")。

    与 `test_benchmark_data_gap_is_registered` 同形:钉住"现状 = 已登记的缺口"。
    一旦有人把公司行为接进 Phase-2,本用例**变红**,提示更新审计 附五十四 的登记
    并改写本守卫 —— 而不是让登记悄悄过期(本仓库吃过"登记逾期"的亏,见附十九)。
    """
    assert not _engine_has_event_handler(module), (
        f"{module} 已接入公司行为 —— 请更新 docs/audits 附五十四 的登记,并把本守卫"
        f"改成断言「用百分比 / 事件源」(或直接删除)。"
    )
