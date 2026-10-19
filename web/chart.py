"""单笔交易的图表数据：K 线（原始域）+ 指标（复权域）+ SL/TP 价位。

单一职责：本模块是**唯一**接触 `v_daily_dual` 的地方。
指标**复用引擎自己的 `compute_indicators`**（§6 单一来源），只是喂正确的价域。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import math

import pandas as pd

#: 交易方向。**SL/TP 的画法依赖它**：空头止损在上方、止盈在下方；多头相反。
#: 若某个引擎标反，tests/test_web_chart.py 的方向判别测试会变红。
ENGINE_DIRECTION: dict[str, str] = {
    "short_reversal": "short",
    "chase_up": "long",
    "uptrend_pullback": "long",
    "cycle_price_action": "long",   # ⚠️ 实现时须用一笔真实交易核对 gross_pnl 符号
}

#: 图表窗口的前置回看（**日历日**），必须覆盖 MA60/MACD 的暖机。
#:
#: ⚠️ **不要照抄 `short_reversal/report_data.py:13` 的 `BAR_PAD_DAYS = 75`。**
#: 那是**日历日**，75 日历日 ≈ **46** 个交易日 —— 比 MA60 需要的 60 根还少，
#: 于是 `ma60` 在整段窗口里**恒为 NaN**，图上那条线**根本不会出现**。
#:
#: 实测（`000001.SZ`，入场 `2026-03-02`，见 `.superpowers/sdd/platform-task-4-report.md`）：
#:
#: | 暖机 | bars | ma60 | macd_dif | macd_bar |
#: |---|---|---|---|---|
#: | 75 日历日（照抄既有） | 46 | **nan** | -0.118838 | 0.013509 |
#: | -1y | 289 | 14.4834536027 | -0.118920 | 0.013684 |
#: | **-400d（策略自身口径）** | 313 | 14.4834536027 | -0.118920 | 0.013684 |
#: | -3y | 772 | 14.4834536027 | -0.118920 | 0.013684 |
#:
#: **两条结论**：
#: 1. MA60 整条缺失（暖机不足，指标根本没算出来）；
#: 2. **`macd_bar` 有偏 1.28%** —— `ewm(adjust=False)` 永不 NaN，但初值有偏，
#:    暖机不足时它是个**与策略当时所见不同的数**，而 MACD 副图正是用来看金叉死叉的。
#:    1.28% 足以在临界处翻号。**这就是 §4.6.1 要防的事，只是成因换成了暖机而非价域。**
#:
#: 取 `400` 与策略自身的面板口径一致（`run_backtest_v3` 的 docstring：
#: "`panel_start = signal_date - 400d` 换取 MA60/126 日回报的预热"）。
#: 实测 **289 根即收敛**（-1y / -400d / -3y 逐位相同），故 400 日历日足够，
#: 且比策略的面板起点**更早**，不会引入比策略更少的暖机。
PAD_DAYS = 400


def sl_tp_prices(entry_price: float, sl_pct: float, tp_pct: float, direction: str) -> tuple[float, float]:
    """由相对百分比推出 SL/TP **价位**（§4：TP/SL 只以相对百分比传递）。"""
    if direction == "short":
        return entry_price * (1.0 + sl_pct), entry_price * (1.0 - tp_pct)
    return entry_price * (1.0 - sl_pct), entry_price * (1.0 + tp_pct)


def exit_levels(params: dict[str, Any], entry_price: float, direction: str,
                atr_pct: float | None = None) -> tuple[float, float] | None:
    """该笔的 `(sl_price, tp_price)`；**只有当引擎确实按这两个百分比出场时才给**，否则 `None`。

    ⚠️ **不能一律按 `entry × (1 ± sl_pct)` 画**（原实现就是这样，是错的）：

    `chase_up` / `uptrend_pullback` 的引擎在**给了 `atr_*_mult` 时改用信号日 ATR 自适应**——

        chase_up/backtrader_engine.py:43-47
        if atr_tp is not None and atr_sl is not None and atr_pct is not None:
            return entry_price * (1 + a * atr_tp_mult), entry_price * (1 - a * atr_sl_mult)
        return entry_price * (1 + fixed_tp_pct), entry_price * (1 - fixed_sl_pct)

    而 **chase_up 的 22/22 个预设都带 `atr_*_mult`** → 那个分支永远走 ATR，
    `sl_pct`/`tp_pct` 是引擎**根本不看**的 fallback。实测差别不小：
    `atr_tp_mult=6.0`、典型 `atr_pct=3%` → 真实止盈 **+18%**，而按 `tp_pct=0.30` 画出来是 **+30%** ——
    **图上那条线在说一件引擎没做过的事。**

    这里只**镜像引擎自己的分支条件**（`atr_*` 是否给全），**不重实现 ATR 价位算术**——
    那套公式留在引擎里（§6）。条件不成立时**返回 `None`**，由调用方如实呈现"这一笔没有可画的 SL/TP 线"，
    而不是编一条。

    同时把"`sl_pct`/`tp_pct` 缺失"也堵掉：原实现用 `params.get("sl_pct", 0.0)`，
    缺失被折成**真的 0**，于是止损线与止盈线**同时落在入场价上**——
    图上看起来"设置了止损"，而它其实是 `0`（三个 ensemble 预设正属此列）。
    """
    atr_sl, atr_tp = params.get("atr_sl_mult"), params.get("atr_tp_mult")
    # **逐字镜像引擎的分支条件**（含最后那项 `atr_pct`），不是"见到 atr_* 就不画"：
    # `atr_pct` 是**逐笔的运行时值**，所以预设带全 `atr_*_mult` 时，
    # 若**这一笔**的 atr_pct 缺失或 NaN，引擎同样会回落到固定的 sl_pct/tp_pct
    # —— 那时平台就**应该**画那两条线。少镜像一项就会过度抑制。
    uses_atr = (atr_sl is not None and atr_tp is not None
                and atr_pct is not None and not math.isnan(float(atr_pct)))
    if uses_atr:
        return None

    sl_pct, tp_pct = params.get("sl_pct"), params.get("tp_pct")
    if sl_pct is None or tp_pct is None:
        return None          # 缺失 ≠ 0：不画，而不是画在入场价上
    return sl_tp_prices(entry_price, float(sl_pct), float(tp_pct), direction)


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
    # `None` 表示**这一笔没有可画的 SL/TP 线**：引擎按 ATR 出场，或预设压根没给这两个参数。
    # 前端必须把 `None` 渲染成"不画线 + 一句说明"，而不是画一条编出来的价位（见 `exit_levels`）。
    levels = exit_levels(params, entry_price, direction, trade.get("atr_pct"))
    sl_price, tp_price = levels if levels is not None else (None, None)
    return {
        "bars": out_bars,
        "entry": {"date": entry_date, "price": entry_price},
        "exit": {"date": exit_date, "price": float(trade["exit_price"]),
                 "reason": trade.get("exit_reason")},
        "sl_price": sl_price,
        "tp_price": tp_price,
        "direction": direction,
    }
