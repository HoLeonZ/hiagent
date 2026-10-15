"""§3 做空方向的现金分红:付出,而非收讫（审计 P2-10，2026-10-15）。

做空与多头的现金流方向相反:空头须把分红**付给**借券方(`free_cash` 不减的原因是
本引擎的做空现金模型把卖股款冻结在 `locked_margin`,故从该池扣出)。共享的
`core.corporate_actions.apply_corporate_action` 只返回多头口径的正值,符号由引擎
按方向决定 —— 把符号藏进共享代码,就是把符号错误放在没人会去找的地方。

本文件锁定:
  1. 除权日在持仓期内 → 扣出一笔 = size × dividend_per_share,并记入
     `pos["dividends_paid"]` 与累计量(供对账)。
  2. **权益归属**:除权日**当天新建**的仓位不享有/不承担本次分红。
     (本引擎的建仓在同一 `next()` 内更早发生,故需显式按 `entry_bar` 跳过;
     chase_up/uptrend 由退出循环的 `entry_t == t` 天然跳过。)
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy

_SIGNAL_BAR, _FILL_BAR, _N = 59, 60, 80


def _panel(ex_bar: int, div: float = 1.0) -> pd.DataFrame:
    dates = pd.date_range("2025-09-01", periods=_N, freq="B")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "thscode": "600000.SH", "date": d,
            "open": 10.0, "high": 10.001, "low": 9.999, "close": 10.0,
            "volume": 1e6, "amount": 5e7,
            "adj_open": 10.0, "adj_high": 10.001, "adj_low": 9.999, "adj_close": 10.0,
            "div_per_share": div if i == ex_bar else 0.0,
            "bonus_ratio": 0.0, "rights_ratio": 0.0,
        })
    return pd.DataFrame(rows)


def _run(ex_bar: int, monkeypatch):
    panel = _panel(ex_bar)
    state = {"called": False}

    def first_bar_only(self, d):
        if not state["called"]:
            state["called"] = True
            return True
        return False

    monkeypatch.setattr(Phase3V3Strategy, "_all_conditions", first_bar_only)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.adddata(AShareData(dataname=panel, plot=False), name="600000.SH")
    holder: dict = {"cash": 100_000.0, "trades": [], "max_dd": 0.0}
    cerebro.addstrategy(
        Phase3V3Strategy, result_holder=holder, min_cash_ratio=0.05,
        tp_pct=0.02, sl_pct=0.99, max_hold=3, signal_price_domain="adj",
    )
    results = cerebro.run()
    return results[0], holder


def test_short_pays_the_dividend_on_the_ex_date(monkeypatch) -> None:
    """除权日在持仓期内(bar 61)→ 付出 size × div。"""
    strat, _ = _run(ex_bar=_FILL_BAR + 1, monkeypatch=monkeypatch)
    paid = getattr(strat, "_dividends_paid_total", 0.0)
    assert paid > 0, (
        "§3 VIOLATION: 除权日在持仓期内,做空却未付出分红 —— "
        "空头必须把分红付给借券方"
    )
    # 数量 × 1.0/股 = 该笔付出额;size 由 all_in 定,故只校验量纲与量级
    assert paid > 1_000.0, f"付出额 {paid:.2f} 与 size×div 量级不符"


def test_no_dividend_when_entering_on_the_ex_date(monkeypatch) -> None:
    """权益归属:除权日**当天**建仓(bar 60)→ 不付分红。"""
    strat, _ = _run(ex_bar=_FILL_BAR, monkeypatch=monkeypatch)
    paid = getattr(strat, "_dividends_paid_total", 0.0)
    assert paid == pytest.approx(0.0), (
        f"§3 VIOLATION: 除权日当天建仓不应承担本次分红,实际付出 {paid:.2f} —— "
        "建仓发生在同一 next() 内更早,必须按 entry_bar 显式跳过"
    )
