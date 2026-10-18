"""单笔交易的图表数据：K 线（原始域）+ 指标（复权域）+ SL/TP 价位。

单一职责：本模块是**唯一**接触 `v_daily_dual` 的地方。
指标**复用引擎自己的 `compute_indicators`**（§6 单一来源），只是喂正确的价域。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

#: 交易方向。**SL/TP 的画法依赖它**：空头止损在上方、止盈在下方；多头相反。
#: 若某个引擎标反，tests/test_web_chart.py 的方向判别测试会变红。
ENGINE_DIRECTION: dict[str, str] = {
    "short_reversal": "short",
    "chase_up": "long",
    "uptrend_pullback": "long",
    "cycle_price_action": "long",   # ⚠️ 实现时须用一笔真实交易核对 gross_pnl 符号
}

#: 图表窗口的前置回看，覆盖 MA60/MACD 暖机（与 short_reversal/report_data.py 的 75 天同量级）。
PAD_DAYS = 75


def sl_tp_prices(entry_price: float, sl_pct: float, tp_pct: float, direction: str) -> tuple[float, float]:
    """由相对百分比推出 SL/TP **价位**（§4：TP/SL 只以相对百分比传递）。"""
    if direction == "short":
        return entry_price * (1.0 + sl_pct), entry_price * (1.0 - tp_pct)
    return entry_price * (1.0 - sl_pct), entry_price * (1.0 + tp_pct)


def _load_dual_bars(db_path: Path, code: str, start: str, end: str) -> pd.DataFrame:
    """取一只票 `[start - PAD, end]` 的**双价**日线（原始 + 复权）。"""
    import duckdb

    lo = (pd.Timestamp(start) - pd.Timedelta(days=PAD_DAYS)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, "
            "raw_open, raw_high, raw_low, raw_close, "
            "adj_open, adj_high, adj_low, adj_close, "
            "volume, amount "
            "FROM v_daily_dual WHERE thscode = ? AND date BETWEEN ? AND ? "
            "ORDER BY date",
            [code, lo, end],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _indicators_on_adj(bars: pd.DataFrame) -> pd.DataFrame:
    """在**复权**域上调用引擎自己的指标定义。

    `compute_indicators` 读的是名为 `close` 的列，所以这里把 `adj_close` 改名喂进去——
    复用的是引擎那份实现（§6 单一来源），没有第二份指标代码。
    """
    from short_reversal.render_trade_detail import compute_indicators

    work = bars.copy()
    work["close"] = work["adj_close"]
    return compute_indicators(work)


def chart_payload(engine: str, params: dict[str, Any], trade: dict[str, Any], db_path: Path) -> dict[str, Any]:
    """组装一笔交易的图表数据。"""
    direction = ENGINE_DIRECTION[engine]
    code = trade["thscode"]
    entry_date = str(trade["entry_date"])[:10]
    exit_date = str(trade["exit_date"])[:10]

    bars = _load_dual_bars(db_path, code, entry_date, exit_date)
    if bars.empty:
        return {"bars": [], "entry": None, "exit": None,
                "sl_price": None, "tp_price": None, "direction": direction}

    ind = _indicators_on_adj(bars)

    cols = ["date", "raw_open", "raw_high", "raw_low", "raw_close",
            "adj_open", "adj_high", "adj_low", "adj_close", "volume",
            "ma5", "ma10", "ma20", "ma60", "macd_dif", "macd_dea", "macd_bar"]
    out_bars = []
    for _, r in ind.iterrows():
        out_bars.append({
            "date": r["date"].strftime("%Y-%m-%d"),
            **{c: (None if pd.isna(r[c]) else float(r[c])) for c in cols if c != "date"},
        })

    entry_price = float(trade["entry_price"])
    sl_price, tp_price = sl_tp_prices(
        entry_price,
        float(params.get("sl_pct", 0.0)),
        float(params.get("tp_pct", 0.0)),
        direction,
    )
    return {
        "bars": out_bars,
        "entry": {"date": entry_date, "price": entry_price},
        "exit": {"date": exit_date, "price": float(trade["exit_price"]),
                 "reason": trade.get("exit_reason")},
        "sl_price": sl_price,
        "tp_price": tp_price,
        "direction": direction,
    }
