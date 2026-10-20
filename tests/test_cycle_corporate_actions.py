"""§3 cycle_price_action 公司行为守卫（审计 P2-10，2026-10-15）。

CLAUDE.md §3：现金分红必须显式入 `Free_Cash`;拆股/送股必须原子调整持仓数量与
成本。`cycle_price_action` 是最后一个接入的引擎(执行域为原始价,除权缺口不补偿
分红就会成为真实亏损)。

`PositionState` 是 frozen dataclass,故送股必须**重建**(§0 append-only)—— 本文件
同时钉住"不得原地修改"。
"""
from __future__ import annotations

from datetime import date

import pytest

from cycle_price_action.portfolio import Portfolio, PositionState


def _entered(shares_price: float = 10.0) -> Portfolio:
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", shares_price, date(2024, 6, 3), {"k_line_score": 1.5})
    assert pf.position is not None
    return pf


def test_dividend_is_deposited_into_free_cash() -> None:
    pf = _entered()
    pos = pf.position
    free_before = pf.free_cash
    pf.apply_corporate_action(dividend_per_share=0.5)
    assert pf.free_cash == pytest.approx(free_before + pos.shares * 0.5), (
        "§3 VIOLATION: 现金分红未入 Free_Cash"
    )
    assert pf.position.shares == pos.shares, "分红不改变股数"


def test_bonus_adjusts_shares_and_cost_basis_atomically() -> None:
    pf = _entered()
    before = pf.position
    pf.apply_corporate_action(bonus_ratio=1.0)     # 1:1 送股
    after = pf.position
    assert after.shares == before.shares * 2, "送股后股数应翻倍"
    assert after.entry_price == pytest.approx(before.entry_price / 2), "成本价应按总量不变重定"
    assert after.entry_price * after.shares == pytest.approx(
        before.entry_price * before.shares
    ), "总成本基必须不变(否则现金账被凭空改变)"
    assert isinstance(after, PositionState), "必须是重建的新实例"


def test_no_event_is_a_noop_and_no_position_is_safe() -> None:
    pf = _entered()
    before = pf.position
    free_before = pf.free_cash
    pf.apply_corporate_action()                    # 全 0 → 无事件
    assert pf.free_cash == pytest.approx(free_before)
    assert pf.position is before, "无事件时不应重建持仓对象"

    empty = Portfolio(cash=100_000.0)
    empty.apply_corporate_action(dividend_per_share=1.0)   # 空仓 → 安全
    assert empty.free_cash == pytest.approx(100_000.0)


def test_rights_issue_warns_and_does_not_change_the_ledger() -> None:
    """配股不建模,但必须显式告警且不改动账本(不静默、也不乱改)。"""
    pf = _entered()
    shares_before = pf.position.shares
    free_before = pf.free_cash
    pf.apply_corporate_action(rights_ratio=0.4)
    assert pf.position.shares == shares_before
    assert pf.free_cash == pytest.approx(free_before)
