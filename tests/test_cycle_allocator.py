"""cycle 跨股容量层: 单发子弹 / 结算隔离 / 确定性。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from cycle_price_action.allocator import allocate, portfolio_metrics
from cycle_price_action.metrics import TradeRecord


def _tr(code: str, entry: date, hold: int, ret: float, score: float = 1.0) -> TradeRecord:
    """造一笔收益率为 ret 的成交 (entry_price × shares = 100_000)。"""
    entry_price, shares = 10.0, 10_000
    return TradeRecord(
        thscode=code,
        entry_date=entry,
        exit_date=entry + timedelta(days=hold),
        entry_price=entry_price,
        exit_price=entry_price * (1 + ret),
        shares=shares,
        pnl=100_000 * ret,
        hold_days=hold,
        k_line_score=score,
        phase_score=0.0,
        calendar_score=0.0,
    )


DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]


def test_single_slot_rejects_overlapping_signals() -> None:
    """max_positions=1: 持仓期间的信号必须被丢弃, 不排队 (§2)。"""
    a = _tr("600001.SH", date(2024, 1, 1), 10, 0.05)
    b = _tr("600002.SH", date(2024, 1, 3), 2, 0.10)   # 与 a 重叠 → 应被丢
    res = allocate(
        [a, b], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert [t.thscode for t in res.taken] == ["600001.SH"]
    assert res.n_rejected_capacity == 1


def test_same_day_exit_does_not_free_the_slot() -> None:
    """§2 结算隔离: T 日卖出所得不得在 T 日用于买入 → 释放条件严格小于。"""
    a = _tr("600001.SH", date(2024, 1, 1), 5, 0.05)    # exit = 2024-01-06
    b = _tr("600002.SH", date(2024, 1, 6), 5, 0.10)    # 同一天入场
    res = allocate(
        [a, b], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert [t.thscode for t in res.taken] == ["600001.SH"]
    assert res.n_rejected_capacity == 1


def test_next_day_after_exit_is_accepted() -> None:
    a = _tr("600001.SH", date(2024, 1, 1), 5, 0.05)    # exit = 2024-01-06
    b = _tr("600002.SH", date(2024, 1, 7), 5, 0.10)
    res = allocate(
        [a, b], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert [t.thscode for t in res.taken] == ["600001.SH", "600002.SH"]


def test_equity_compounds() -> None:
    a = _tr("600001.SH", date(2024, 1, 1), 5, 0.10)
    b = _tr("600002.SH", date(2024, 1, 7), 5, 0.10)
    res = allocate(
        [a, b], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert res.final_equity == pytest.approx(1_000_000 * 1.10 * 1.10)


def test_capacity_two_allows_two_concurrent() -> None:
    a = _tr("600001.SH", date(2024, 1, 1), 10, 0.05)
    b = _tr("600002.SH", date(2024, 1, 3), 10, 0.05)
    c = _tr("600003.SH", date(2024, 1, 5), 10, 0.05)
    res = allocate(
        [a, b, c], trading_days=DAYS, initial_capital=1_000_000, max_positions=2
    )
    assert len(res.taken) == 2
    assert res.n_rejected_capacity == 1


def test_ranking_is_by_fused_score_then_code() -> None:
    """满仓时按 融合分 降序选, 平分按 thscode —— 与输入顺序无关。"""
    strong = _tr("600009.SH", date(2024, 1, 1), 10, 0.05, score=2.5)
    weak = _tr("600001.SH", date(2024, 1, 1), 10, 0.05, score=1.0)
    res = allocate(
        [weak, strong], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert [t.thscode for t in res.taken] == ["600009.SH"]


def test_result_is_independent_of_input_order() -> None:
    trades = [
        _tr(f"60000{i}.SH", date(2024, 1, 1) + timedelta(days=i), 4, 0.01 * i, score=1.0)
        for i in range(1, 6)
    ]
    a = allocate(
        trades, trading_days=DAYS, initial_capital=1_000_000, max_positions=2
    )
    b = allocate(
        list(reversed(trades)),
        trading_days=DAYS,
        initial_capital=1_000_000,
        max_positions=2,
    )
    assert [t.thscode for t in a.taken] == [t.thscode for t in b.taken]
    assert a.equity == b.equity


def test_exposure_counts_held_days() -> None:
    a = _tr("600001.SH", date(2024, 1, 1), 10, 0.05)   # 01-01..01-10 held
    res = allocate(
        [a], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert res.exposure == pytest.approx(10 / 40)


def test_metrics_are_computable_from_the_equity_curve() -> None:
    """这是 cycle 第一次能给出 cagr / max_dd —— 旧 compute_metrics 全为 None。"""
    a = _tr("600001.SH", date(2024, 1, 1), 5, 0.10)
    b = _tr("600002.SH", date(2024, 1, 7), 5, -0.20)
    res = allocate(
        [a, b], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    m = portfolio_metrics(res)
    assert m["total_return"] == pytest.approx(1.10 * 0.80 - 1.0)
    assert m["max_dd"] > 0
    assert m["cagr"] is not None
    assert m["n_rejected_capacity"] == 0


def test_empty_trade_list_is_allowed() -> None:
    res = allocate(
        [], trading_days=DAYS, initial_capital=1_000_000, max_positions=1
    )
    assert res.final_equity == 1_000_000
    assert res.exposure == 0.0
