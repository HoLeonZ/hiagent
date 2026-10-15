"""§0/§2/§3/§4 preset 声明**真的到达行为**守卫（审计 2026-10-15）。

背景:`tests/test_preset_to_engine_api_conformance.py` 是**源码文本**审计 ——
它只检查"这个键名在引擎源码里出现过"。这有个致命弱点:往
`params = dict(weight_kline=1.0, ...)` 里加一个默认值就能让审计变绿,**而声明
依然被忽略**(默认值恰好等于声明值时尤其隐蔽 —— 这正是 cycle 权重的病根)。

所以本文件补上文本审计抓不到的那一半:**改了声明,行为必须跟着变**。
两类断言:
  1. 声明驱动行为 —— 两个不同的声明值 → 两个不同的结果。
  2. 声明与引擎实现冲突 → fail-fast(而不是静默按别的方式跑完)。

反面用法警告:读别的引擎源码文本(如 `assert "position_fraction" in src`)来
"证明"接线是不作数的 —— 本文件的 D 段就是那种断言的正例替代:它真的跑一次
`simulate_portfolio` 并比较成交股数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.preset_contract import PresetDeclarationMissing
from cycle_price_action.portfolio import Portfolio
from cycle_price_action.presets import PRESET_V1, resolve_score_weights
from cycle_price_action.signals import entry_signal


# ---------------------------------------------------------------------------
# A. cycle_price_action —— 评分权重(此前硬编码在 fuse_scores 默认参数里)
# ---------------------------------------------------------------------------


def test_score_weights_come_from_the_preset_not_a_hardcoded_default() -> None:
    assert resolve_score_weights(PRESET_V1, "PRESET_V1") == (1.0, 0.7, 0.5)
    # 不同的声明 → 不同的结果。硬编码默认值不可能做到这一点。
    custom = {"weight_kline": 0.1, "weight_cycle": 0.2, "weight_calendar": 0.3}
    assert resolve_score_weights(custom, "custom") == (0.1, 0.2, 0.3)


def test_score_weights_refuse_to_be_absent() -> None:
    with pytest.raises(PresetDeclarationMissing, match="weight_kline"):
        resolve_score_weights({"weight_cycle": 0.7, "weight_calendar": 0.5}, "x")


def test_weights_actually_change_the_fused_signal() -> None:
    """权重要是装饰性的,融合分数就不会随 weights 变化。"""
    kline = pd.Series([2.0])
    cycle = pd.Series([2.0])
    calendar = pd.Series([2.0])
    kw = dict(threshold=2.0, min_dim=1.0)

    with_default = entry_signal(kline, cycle, calendar, **kw).iloc[0]
    zeroed = entry_signal(kline, cycle, calendar, weights=(0.0, 0.0, 0.0), **kw).iloc[0]
    assert bool(with_default) is True, "默认权重下 (2,2,2) 应触发入场"
    assert bool(zeroed) is False, (
        "weights=(0,0,0) 时融合分数恒为 0 —— 若仍触发,说明 weights 根本没被用上"
    )


# ---------------------------------------------------------------------------
# B. cycle_price_action —— 仓位/参与率声明真的改变下单量
# ---------------------------------------------------------------------------


def _entered_shares(portfolio: Portfolio, bar_volume: float | None = None) -> int:
    from datetime import date

    state = portfolio.try_enter(
        "600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.0},
        bar_volume=bar_volume,
    )
    assert state is not None, "夹具应能成交"
    return state.shares


def test_position_fraction_scales_the_slot() -> None:
    """10 万现金、10 元价,`position_sizing='all_in'`。

    full: 预算 10 万 → 10,000 股,但含手续费下限 ¥5 后成本 100,025 > free_cash,
          触发 R527 iterative downsize → 9,900 股。
    half: 预算 5 万 → 5,000 股,成本 ~50,013 远低于 free_cash(闸门按 free_cash
          判定,不是按 fraction 预算),故不再回退 → 5,000 股。

    两者不同即证明 position_fraction 真的参与了计算。
    """
    full = _entered_shares(Portfolio(cash=100_000.0, position_fraction=1.0))
    half = _entered_shares(Portfolio(cash=100_000.0, position_fraction=0.5))
    assert full == 9_900
    assert half == 5_000, (
        "§2 VIOLATION: position_fraction 是装饰 —— 缩小声明没有让下单量变小"
    )


def test_volume_participation_is_declaration_driven() -> None:
    """此前参与率是类常量 0.10,preset 声明无人读取。"""
    generous = _entered_shares(
        Portfolio(cash=100_000.0, max_volume_participation=0.10), bar_volume=100_000.0
    )
    strict = _entered_shares(
        Portfolio(cash=100_000.0, max_volume_participation=0.02), bar_volume=100_000.0
    )
    assert generous == 9_900, "0.10 × 100k = 10k 股 ≈ all-in,不构成有效约束"
    assert strict == 2_000, (
        "§4 VIOLATION: max_volume_participation 未被消费 —— 2% 应把下单量压到 2k"
    )


@pytest.mark.parametrize("kwargs,match", [
    ({"max_positions": 2}, "max_positions"),
    ({"position_sizing": "equal"}, "position_sizing"),
    ({"price_source_for_execution": "adj_close"}, "price_source_for_execution"),
])
def test_declarations_incompatible_with_the_book_fail_fast(kwargs, match) -> None:
    """§2/§3: 单仓 all-in 账本 + raw 执行域。声明成别的东西必须炸,
    而不是静默按它做不到的方式跑完(这正是"声明无人消费"的温床)。"""
    with pytest.raises(ValueError, match=match):
        Portfolio(cash=100_000.0, **kwargs)


# ---------------------------------------------------------------------------
# C. short_reversal —— position_sizing 必须与结构性开关一致
# ---------------------------------------------------------------------------


def _preset_with(**overrides) -> dict:
    from short_reversal.presets import PRESETS

    cfg = dict(PRESETS["v35_agg_pctchg_04_09"])
    cfg.update(overrides)
    return cfg


def test_sizing_declaration_must_match_the_dispatch_switch(monkeypatch) -> None:
    """§2: 此前真正决定路径的是 `"ensemble_substrategies" in cfg`,而
    position_sizing 声明无人读取。两者不一致必须 fail-fast。"""
    from short_reversal import engine as eng

    # 声明集成、却没有子策略
    monkeypatch.setitem(eng.PRESETS, "planted_split", _preset_with(
        position_sizing="ensemble_split"))
    with pytest.raises(ValueError, match="ensemble_substrategies"):
        eng.run_backtest_v3("planted_split", "2024-01-01", "2024-12-31", db_path=None)

    # 声明单腿、却带着子策略
    monkeypatch.setitem(eng.PRESETS, "planted_all_in", _preset_with(
        position_sizing="all_in", ensemble_substrategies=["v35_agg_pctchg_04_09"]))
    with pytest.raises(ValueError, match="ensemble_substrategies"):
        eng.run_backtest_v3("planted_all_in", "2024-01-01", "2024-12-31", db_path=None)


def test_execution_price_source_claim_must_be_true(monkeypatch) -> None:
    """§3: 引擎只有 raw 执行域,声明 adj 必须炸。"""
    from short_reversal import engine as eng

    monkeypatch.setitem(eng.PRESETS, "planted_adj", _preset_with(
        price_source_for_execution="adj_close"))
    with pytest.raises(ValueError, match="price_source_for_execution"):
        eng.run_backtest_v3("planted_adj", "2024-01-01", "2024-12-31", db_path=None)


# ---------------------------------------------------------------------------
# D. chase_up —— position_fraction 真的改变成交股数(端到端,非源码文本)
# ---------------------------------------------------------------------------


def _panel_and_entries(thscode: str = "600000.SH"):
    dates = pd.date_range("2025-09-01", "2025-09-15", freq="B")
    panel = pd.DataFrame([{
        "date": d, "thscode": thscode,
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
        # 成交量足够大,确保**不是** volume cap 在限制下单量 —— 否则
        # position_fraction 的效果会被 cap 掩盖,测试变得没有区分度。
        "volume": 10_000_000.0, "amount": 100_000_000.0, "atr_pct": 0.02,
    } for d in dates])
    entries = pd.DataFrame([{
        "date": pd.Timestamp("2025-09-01"), "thscode": thscode,
        "score": 1.0, "sub_signal_type": "A", "atr_pct": 0.02,
        "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
        "sig_breakout_score": 0.5, "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan,
        "sig_mom120": 0.05, "sig_amount60": 5e7,
    }])
    return panel, entries


@pytest.mark.parametrize("fraction,expected", [(1.0, 100_000), (0.5, 50_000)])
def test_chase_up_position_fraction_changes_fill_size(fraction, expected) -> None:
    """§2: 22 个 chase_up preset 都声明 position_fraction,此前**从不被读取**。
    这里用真实的下单路径证明它现在是生效的(1M 现金 / 10 元 = 全仓 10 万股)。"""
    from chase_up.portfolio import simulate_portfolio

    panel, entries = _panel_and_entries()
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=8, max_positions=1,
        start_date="2025-09-01", end_date="2025-09-15",
        initial_capital=1_000_000.0,
        position_sizing="all_in",
        position_fraction=fraction,
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    assert len(trades) == 1, f"夹具应产生 1 笔交易,实际 {len(trades)}"
    assert int(trades.iloc[0]["size"]) == expected, (
        f"§2 VIOLATION: position_fraction={fraction} 未生效 —— "
        f"应成交 {expected} 股,实际 {int(trades.iloc[0]['size'])}"
    )
