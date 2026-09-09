"""pre_simulate_trades 退出优先级 + 全局锁 + 边界。"""
from __future__ import annotations

import pandas as pd
import pytest

from short_reversal.trades import pre_simulate_trades


def _panel(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _entry(date: str, code: str = "X.SH") -> pd.DataFrame:
    return pd.DataFrame({"date": [pd.Timestamp(date)], "thscode": [code]})


def _bars_around(entry_date: str, n: int, *, o: float, h: float, l: float, c: float,
                 code: str = "X.SH") -> pd.DataFrame:
    """构造 entry_date 之后 n 根 K 线，全部相同 OHLC。"""
    dates = pd.date_range(entry_date, periods=n + 1, freq="B")[1:]
    rows = []
    for d in dates:
        rows.append({
            "thscode": code, "date": d,
            "open": o, "high": h, "low": l, "close": c,
        })
    return pd.DataFrame(rows)


def test_tp_fires_when_low_hits_target():
    """T+1 用于 entry 价；T+2 起判定 TP/SL。
    T+2 low=9.4 <= tp_p (10*0.94=9.4) → TP 触发。"""
    entry_date = pd.Timestamp("2025-01-01")
    bday = pd.tseries.offsets.BDay(1)
    panel = pd.DataFrame([
        {"thscode": "X.SH", "date": entry_date,
         "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},  # T0
        {"thscode": "X.SH", "date": entry_date + bday,
         "open": 10.0, "high": 10.1, "low": 10.0, "close": 10.0},  # T+1 (entry)
        {"thscode": "X.SH", "date": entry_date + 2 * bday,
         "open": 10.0, "high": 10.1, "low": 9.39, "close": 9.5},  # T+2 → TP (low<tp_p; 9.4=10*(1-0.06) in math but tp_p=9.3999... in float)
    ])
    trades = pre_simulate_trades(_entry(entry_date.strftime("%Y-%m-%d")), panel,
                                  tp_pct=0.06, sl_pct=0.05, max_hold=30)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "TP"
    assert abs(trades.iloc[0]["exit_price"] - 9.4) < 1e-9  # tp_p=9.399999... differs from 9.4 by 1.7e-15 < 1e-9


def test_sl_fires_when_high_hits_target():
    """T+2 high=10.5 >= sl_p (10*1.05=10.5) → SL 触发。"""
    entry_date = pd.Timestamp("2025-01-01")
    bday = pd.tseries.offsets.BDay(1)
    panel = pd.DataFrame([
        {"thscode": "X.SH", "date": entry_date,
         "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},
        {"thscode": "X.SH", "date": entry_date + bday,
         "open": 10.0, "high": 10.1, "low": 10.0, "close": 10.0},
        {"thscode": "X.SH", "date": entry_date + 2 * bday,
         "open": 10.0, "high": 10.5, "low": 10.0, "close": 10.3},  # T+2 → SL
    ])
    trades = pre_simulate_trades(_entry(entry_date.strftime("%Y-%m-%d")), panel,
                                  tp_pct=0.06, sl_pct=0.05, max_hold=30)
    assert trades.iloc[0]["exit_reason"] == "SL"


def test_time_exit_at_max_hold():
    """30 根 K 线（T+2 到 T+31）都未触发 TP/SL → 第 31 根（i=30）触发 time 退出。"""
    entry_date = pd.Timestamp("2025-01-01")
    bday = pd.tseries.offsets.BDay(1)
    rows = [{"thscode": "X.SH", "date": entry_date,
             "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0}]
    for i in range(1, 33):  # T+1 到 T+32
        rows.append({"thscode": "X.SH", "date": entry_date + i * bday,
                     "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0})
    panel = pd.DataFrame(rows)
    trades = pre_simulate_trades(_entry(entry_date.strftime("%Y-%m-%d")), panel,
                                  tp_pct=0.06, sl_pct=0.05, max_hold=30)
    assert trades.iloc[0]["exit_reason"] == "time"
    # T+2 到 T+32 共 31 根 bar，exit 在 T+32
    assert trades.iloc[0]["exit_date"] == entry_date + 32 * bday


def test_global_lock_skips_overlapping_signal():
    """同日 2 个 entry signal，第 2 个在持仓期被跳过。"""
    entry_date = "2025-01-01"
    # 票 A 持 30 根 K 线；票 B 同日 trigger 但被跳过
    panel_a = pd.concat([
        _panel([{"thscode": "A.SH", "date": pd.Timestamp(entry_date),
                 "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0}]),
        _bars_around(entry_date, 30, o=10.0, h=10.1, l=9.9, c=10.0, code="A.SH"),
    ])
    panel_b = pd.concat([
        _panel([{"thscode": "B.SH", "date": pd.Timestamp(entry_date),
                 "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0}]),
        _bars_around(entry_date, 30, o=10.0, h=10.1, l=9.9, c=10.0, code="B.SH"),
    ])
    panel = pd.concat([panel_a, panel_b]).reset_index(drop=True)
    entries = pd.DataFrame({
        "date": [pd.Timestamp(entry_date), pd.Timestamp(entry_date)],
        "thscode": ["A.SH", "B.SH"],
    })
    trades = pre_simulate_trades(entries, panel,
                                  tp_pct=0.06, sl_pct=0.05, max_hold=30)
    # 全局锁：第一笔 A.SH 成交，B.SH 被跳过
    assert len(trades) == 1
    assert trades.iloc[0]["thscode"] == "A.SH"


def test_no_entry_price_skips():
    """panel 中无 entry_date 当日 K 线 → 跳过该 entry。"""
    entries = _entry("2025-01-01")
    panel = _bars_around("2025-01-01", 5, o=10.0, h=10.1, l=9.9, c=10.0)
    trades = pre_simulate_trades(entries, panel,
                                  tp_pct=0.06, sl_pct=0.05, max_hold=30)
    assert trades.empty


def test_tp_and_sl_pct_validation():
    entries = _entry("2025-01-01")
    panel = _panel([{"thscode": "X.SH", "date": pd.Timestamp("2025-01-01"),
                     "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0}])
    with pytest.raises(ValueError, match="tp_pct"):
        pre_simulate_trades(entries, panel, tp_pct=0.0, sl_pct=0.05, max_hold=30)
    with pytest.raises(ValueError, match="sl_pct"):
        pre_simulate_trades(entries, panel, tp_pct=0.06, sl_pct=-0.01, max_hold=30)
