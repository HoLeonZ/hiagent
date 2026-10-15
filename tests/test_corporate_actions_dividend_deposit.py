"""§3 事件驱动公司行为 —— 分红入账 / 送股调整（2026-10-15 重写）。

CLAUDE.md §3 verbatim:
  "Cash dividends must explicitly trigger a physical cash deposit into
   Free_Cash. Stock splits must trigger an atomic multiplier adjustment
   to Position_Quantity and Average_Cost."

**为什么重写**：原版（Tick 43, 2026-09-23）用三条**断言「能力不存在」**的用例来
表达缺口 —— `test_no_dividend_deposit_function_anywhere` 之类。缺口闭合后（四个
引擎现在都经 `core.corporate_actions.apply_corporate_action` 入账），它们没有转绿，
而是变成了**假阴性**：它们只在**引擎目录**里搜处理器的**定义**，而 §2/§6 恰恰要求
共享逻辑收敛到 `core/`（单源）。**把代码放对地方，反而让测试看不见了。**

这正是「用断言缺口来表达待办」的代价：缺口一旦闭合，用例要么转成全红噪音（如果
它钉的是别的），要么像这里一样安静地给出错误结论。断言能力**存在且接线正确**
才是长期可用的形态。

本文件现在验证：
  1. 处理器在 `core/` **单源**定义（不是四个引擎各写一份）。
  2. 四个引擎都真的把它接到自己的账本上。
  3. 语义正确（分红 = 股数 × 每股分红；送股保总成本不变；无事件则无操作）。
  4. 分红现金流在**规范账本 schema** 里可追溯（`cum_dividends`）。

逐引擎的账本级行为覆盖在 `tests/test_corporate_actions_events.py`
（chase_up / uptrend_pullback / short_reversal）与
`tests/test_cycle_corporate_actions.py`（cycle_price_action）；本文件管**接线与 schema**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.corporate_actions import apply_corporate_action
from core.trade_schema import EQUITY_COLS

#: 每个引擎把它接到账本上的**接线点**（调用点所在文件）。
ENGINE_CALLERS = {
    "chase_up": "chase_up/portfolio.py",
    "uptrend_pullback": "uptrend_pullback/portfolio.py",
    "short_reversal": "short_reversal/replay_strategy_v3.py",
    "cycle_price_action": "cycle_price_action/portfolio.py",
}


# ---------------------------------------------------------------------------
# 1) 单源：处理器定义在 core/
# ---------------------------------------------------------------------------


def test_corporate_action_handler_lives_in_core_as_a_single_source() -> None:
    """§2/§6：公司行为逻辑必须**单源**，四个引擎不得各写一份。"""
    core_src = Path("core/corporate_actions.py").read_text(encoding="utf-8")
    assert "def apply_corporate_action(" in core_src, (
        "§3 VIOLATION: core/corporate_actions.py 未定义 apply_corporate_action —— "
        "公司行为处理器必须在 core/ 单源。"
    )


def test_every_engine_routes_corporate_actions_through_the_core_handler() -> None:
    """§3：四个引擎都必须真的把处理器接到自己的账本上（声明 ≠ 接线）。"""
    missing = [
        engine
        for engine, rel in ENGINE_CALLERS.items()
        if "apply_corporate_action(" not in Path(rel).read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"§3 VIOLATION: 以下引擎未调用 core 的公司行为处理器：{missing}。"
        "分红不入 Free_Cash / 送股不调仓 —— §3 要求的是**物理入账**，不是声明。"
    )


# ---------------------------------------------------------------------------
# 2) 语义：分红入现金、送股保总成本、无事件无操作
# ---------------------------------------------------------------------------


def test_dividend_deposits_physical_cash_and_keeps_share_count() -> None:
    """§3 verbatim：现金分红必须触发 `cash += 股数 × 每股分红`，且不改股数。"""
    out = apply_corporate_action(size=1_000, entry_price=10.0, dividend_per_share=0.3)
    assert out.cash_delta == pytest.approx(300.0), (
        "§3 VIOLATION: 分红现金额应为 1000 股 × ¥0.30 = ¥300"
    )
    assert out.size == 1_000, "分红不改变股数"
    assert out.entry_price == pytest.approx(10.0), "分红不改成本价(现金已单独入账)"


def test_bonus_issue_adjusts_qty_and_cost_atomically() -> None:
    """§3 verbatim：送股/拆股必须**原子**调整股数与成本价。"""
    out = apply_corporate_action(size=1_000, entry_price=10.0, bonus_ratio=1.0)
    assert out.size == 2_000, "1:1 送股后股数翻倍"
    assert out.entry_price == pytest.approx(5.0), "成本价按总量不变重定"
    assert out.size * out.entry_price == pytest.approx(1_000 * 10.0), (
        "§3 VIOLATION: 总成本基必须不变 —— 否则现金账被凭空改变"
    )
    assert out.cash_delta == 0.0, "送股不产生现金流"


def test_no_event_is_a_noop() -> None:
    out = apply_corporate_action(size=1_000, entry_price=10.0)
    assert (out.size, out.cash_delta) == (1_000, 0.0)
    assert out.entry_price == pytest.approx(10.0)


def test_rights_issue_warns_rather_than_silently_reclassifying() -> None:
    """配股未建模 —— 必须**显式告警**，不得静默当成别的公司行为处理。"""
    out = apply_corporate_action(size=1_000, entry_price=10.0, rights_ratio=0.4)
    assert out.warnings, "配股未建模 → 必须产出警告（§0：不得静默）"
    assert out.cash_delta == 0.0, "未建模时不得臆造现金流"


# ---------------------------------------------------------------------------
# 3) 可追溯：分红现金流进规范账本 schema
# ---------------------------------------------------------------------------


def test_dividend_cash_is_traceable_in_the_canonical_ledger_schema() -> None:
    """§3：分红现金必须**可追溯** —— 否则「总收益 = 价格收益 + 股息收益」无法分解，
    用 adj_close 的引擎会把股息悄悄折进价格里，收益率看似合理却无法审计。

    注：`cycle_price_action` 目前**没有权益账本输出**（其 equity curve writer 属
    §8 未结事项），故此处只要求"凡是输出权益账本的引擎都必须带该列"。
    """
    assert "cum_dividends" in EQUITY_COLS, (
        "§3 VIOLATION: 规范权益 schema core.trade_schema.EQUITY_COLS 缺 cum_dividends —— "
        "累计分红无处安放，股息收益不可审计。"
    )

    importers = {
        engine: rel
        for engine, rel in ENGINE_CALLERS.items()
        if "EQUITY_COLS" in Path(rel).read_text(encoding="utf-8")
    }
    assert importers, "预期至少有引擎使用规范权益 schema"
    offenders = [
        engine
        for engine, rel in importers.items()
        if "cum_dividends" not in Path(rel).read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"§3 VIOLATION: 以下引擎输出权益账本却不带 cum_dividends：{offenders} —— "
        "分红入了账但报表里看不到。"
    )


# ---------------------------------------------------------------------------
# PASS baselines: dual-price system in place (math vs execution separation)
# ---------------------------------------------------------------------------


def test_dual_price_convention_adj_for_math_raw_for_execution() -> None:
    """§3 PASS baseline: adj_close 用于指标，raw_close 用于执行。

    这是事件处理器挂钩的地基：指标数学吃干净的 adj 序列（不含除权跳空），
    执行数学吃 raw（真实物理成交价，含除权调整）。
    """
    for rel in ("chase_up/portfolio.py", "uptrend_pullback/portfolio.py"):
        src = Path(rel).read_text(encoding="utf-8")
        assert "raw_close" in src and "adj_close" in src, (
            f"Regression: {rel} 不再同时持有 raw_close 与 adj_close（双价制）"
        )


def test_raw_prev_close_loaded_into_entry_dict() -> None:
    """§3 PASS baseline: 组合层加载 raw_prev_close。

    涨跌停守卫（§4）消费该字段；若被移除，双价制与涨跌停守卫会同时回归。
    """
    for rel in ("chase_up/portfolio.py", "uptrend_pullback/portfolio.py"):
        assert "raw_prev_close" in Path(rel).read_text(encoding="utf-8"), (
            f"Regression: {rel} 不再加载 raw_prev_close"
        )
