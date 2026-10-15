"""§4 回补侧涨停 no-fill 守卫（审计 P1-9，2026-10-15）。

CLAUDE.md §4：涨停/跌停封板的 bar 上无法成交。做空的**回补是一次 BUY** ——
涨停封板时买不进（买单队列锁死），故回补必须被拒、持仓顺延到下一根可成交 bar。

审计发现：short_reversal 只守了**入场侧**的 `is_limit_down`，**回补侧完全没有**
`is_limit_up` 守卫 —— 于是在涨停板上照常"买入回补"，把亏损截断在一个物理上
取不到的价位（与长仓引擎的跌停幻影止损互为镜像）。

方向保守：跳过 SL 回补意味着浮亏可能继续扩大，符合 §0 Pessimistic Default。
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy

# SMA(60) 暖机：next() 首次在 len(d)=60（bar 59）触发 → 信号 bar 59，
# 成交 bar 60（entry_bar = len(self) = 61）。_check_exit 的 held<1 保护
# 使判定首次生效于 bar 62 —— 故 _COVER_BAR = 62，不是 61。
_SIGNAL_BAR = 59
_FILL_BAR = 60
_COVER_BAR = 62
_N = 80


def _panel(cover_open: float) -> pd.DataFrame:
    dates = pd.date_range("2025-09-01", periods=_N, freq="B")
    rows = []
    for i, d in enumerate(dates):
        p = cover_open if i == _COVER_BAR else 10.0
        rows.append({
            "thscode": "600000.SH", "date": d,
            "open": p, "high": p + 0.001, "low": p - 0.001, "close": p,
            "volume": 1e6, "amount": 5e7,
        })
    return pd.DataFrame(rows)


def _run(cover_open: float, monkeypatch) -> tuple[list, pd.DataFrame]:
    panel = _panel(cover_open)
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
        Phase3V3Strategy,
        result_holder=holder,
        nav_gate_ratio=0.05,
        tp_pct=0.02,          # tp_p = 10.0 × 0.98 = 9.80(不会触及)
        sl_pct=0.05,          # sl_p = 10.0 × 1.05 = 10.50
        max_hold=3,
        signal_price_domain="adj",
    )
    cerebro.run()
    return holder["trades"], panel


def test_cover_on_limit_up_sealed_bar_is_rejected(monkeypatch) -> None:
    """bar 61 开盘 11.0(+10%)→ 涨停封板 → 不得在该 bar 回补,持仓顺延。"""
    # +10% 相对 bar 60 的 close(10.0),超过 9.5% 阈值
    assert abs(11.0 / 10.0 - 1.0) >= 0.095
    trades, panel = _run(cover_open=11.0, monkeypatch=monkeypatch)
    cover_date = panel.iloc[_COVER_BAR]["date"]

    assert trades, "应至少有一笔成交(顺延后由 time 出场)"
    for t in trades:
        assert pd.Timestamp(t["exit_date"]) != cover_date, (
            f"§4 VIOLATION: 在涨停封板 bar({cover_date.date()}) 上完成了回补成交 —— "
            "封板时买不进,必须顺延到下一根可成交 bar"
        )


def test_cover_on_normal_bar_still_triggers_sl(monkeypatch) -> None:
    """反向对照:bar 61 开盘 10.6(+6%,非封板)→ 跳空穿越止损应照常成交。

    这条证明上一条确实是**涨停守卫**在起作用。
    """
    assert abs(10.6 / 10.0 - 1.0) < 0.095
    trades, panel = _run(cover_open=10.6, monkeypatch=monkeypatch)
    cover_date = panel.iloc[_COVER_BAR]["date"]

    assert trades, "非封板时应成交"
    sl_trades = [t for t in trades if pd.Timestamp(t["exit_date"]) == cover_date]
    assert sl_trades, (
        "非封板时应在该 bar 触发止损回补 —— 若为空说明守卫把正常成交也挡掉了"
    )
    assert sl_trades[0]["exit_reason"] == "SL"
