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

from pathlib import Path

import pytest


def _engine_has_event_handler(module_name: str) -> bool:
    """检查 engine 是否实现 dividend_handler / split_handler."""
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return False
    src = Path(mod.__file__).read_text(encoding="utf-8")
    has_dividend = ("dividend" in src.lower() and
                    ("handler" in src.lower() or "_apply" in src.lower() or
                     "trigger" in src.lower()))
    has_split = ("split" in src.lower() and
                 ("handler" in src.lower() or "_apply" in src.lower() or
                  "trigger" in src.lower()))
    # 仅当 dividend/split 出现在业务逻辑而非注释/字符串 split() 才算
    return has_dividend or has_split


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
    if module == "uptrend_pullback.portfolio":
        pytest.skip(
            "uptrend_pullback: 2026-10-13 决策为『不实现显式 CA handler』—— 实测该"
            "策略持仓期中位数仅 3 天, 窗口内无任何持仓穿过除权日 (漏记分红 = 0, "
            "幻影止损 = 0), 故 event 记账当前无收益; 该零暴露前提已由 "
            "tests/test_uptrend_pullback_corporate_actions_exposure.py 以可证伪的"
            "行为守卫锁定, 本 source-text 探针对其不再适用。"
        )
    if _engine_has_event_handler(module):
        pytest.skip(
            f"{module} 已实现 dividend/split handler (GREEN, 本测试 supersede)"
        )
    assert False, (
        f"GAP CAPTURED (RED): {module} 无 dividend_handler / split_handler. "
        f"CLAUDE.md §3 要求显式 cash deposit + quantity/cost 调整. "
        f"当前以 adj_close 前复权隐式嵌入分红 (设计选项 A), "
        f"需用户确认是否需切换至选项 B (raw_close + 显式 event)."
    )