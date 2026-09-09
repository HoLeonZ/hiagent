"""Phase 1: 持仓循环，按 SL > TP > TECH 退出，输出 trades.parquet。"""
from __future__ import annotations

import numpy as np
import pandas as pd


DEFAULT_PARAMS = {"tp_pct": 0.08, "sl_pct": 0.05, "ma_period": 20}


def pre_simulate_trades(
    entries_df: pd.DataFrame,
    panel_df: pd.DataFrame,
    params: dict | None = None,
) -> pd.DataFrame:
    """输入 entry 信号和 panel K 线，模拟每笔 trade 输出。

    全局持仓锁：任一时刻只允许 1 仓（spec §6 "满仓单只" + §10 "持仓期忽略新信号"）。
    修复前为 per-thscode 锁，违反 spec；2026-09-09 修复。

    列约定：
      entries_df: [date, thscode, score]
      panel_df:   [thscode, date, close]
      返回:       [entry_date, thscode, exit_date, exit_reason, entry_price, exit_price, hold_days]

    退出优先级（spec §5）：SL > TP > TECH（MA20 站上）。
    持仓期内的 entry 信号被忽略。
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    tp_pct = p["tp_pct"]
    sl_pct = p["sl_pct"]
    ma_n = p["ma_period"]

    if entries_df.empty:
        return _empty_trades()

    panel = panel_df[["thscode", "date", "close"]].copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)

    # 每只票的 MA20（用 close rolling，前 ma_n-1 行为 NaN）
    panel["ma"] = (
        panel.groupby("thscode")["close"]
        .transform(lambda s: s.rolling(ma_n, min_periods=ma_n).mean())
    )

    # 标准化 entries
    entries = entries_df[["date", "thscode"]].copy()
    entries["date"] = pd.to_datetime(entries["date"])
    entries = entries.sort_values(["date", "thscode"]).reset_index(drop=True)

    # 按 thscode → {dates, closes, ma} 索引 panel，便于快速查找
    panel_idx: dict[str, dict] = {}
    for code, sub in panel.groupby("thscode"):
        panel_idx[code] = {
            "dates": sub["date"].to_numpy(),
            "closes": sub["close"].to_numpy(),
            "ma": sub["ma"].to_numpy(),
        }

    trades: list[dict] = []
    # 全局锁定：任一时刻只允许 1 仓（spec §6 "满仓单只" + §10 "持仓期忽略新信号"）。
    # 修复前为 per-thscode dict，违反 spec（114 笔 trades 跨 thscode 同时存在）；
    # 2026-09-09 改为全局 pd.Timestamp | None。
    in_position_until: pd.Timestamp | None = None

    for _, ent in entries.iterrows():
        code = ent["thscode"]
        entry_date = ent["date"]
        pi = panel_idx.get(code)
        if pi is None:
            continue  # panel 中无此票 K 线，跳过

        # 检查全局持仓冲突
        if in_position_until is not None and entry_date <= in_position_until:
            continue  # 持仓中，忽略此 entry

        dates_arr = pi["dates"]
        closes = pi["closes"]
        ma_arr = pi["ma"]
        n = len(dates_arr)

        # 找 entry_date 在 panel 中的索引
        entry_idx = int(np.searchsorted(dates_arr, np.datetime64(entry_date), side="left"))
        if entry_idx >= n or dates_arr[entry_idx] != np.datetime64(entry_date):
            continue  # panel 中无此日期 K 线，跳过

        entry_price = float(closes[entry_idx])
        exit_idx = n - 1
        exit_reason = "EOD"

        # 从 entry_idx+1 开始逐根检查
        j = entry_idx + 1
        while j < n:
            ret = closes[j] / entry_price - 1
            ma_j = ma_arr[j]
            # SL 优先（对空头 close/entry - 1 >= sl 表示涨了，价格触发不依赖 MA）
            if ret >= sl_pct:
                exit_idx = j
                exit_reason = "SL"
                break
            # TP（对空头 close/entry - 1 <= -tp 表示跌了，价格触发不依赖 MA）
            if ret <= -tp_pct:
                exit_idx = j
                exit_reason = "TP"
                break
            # TECH（站上 MA20，需 MA 已就绪）
            if not np.isnan(ma_j) and closes[j] >= ma_j:
                exit_idx = j
                exit_reason = "TECH"
                break
            j += 1

        trades.append({
            "entry_date": pd.Timestamp(dates_arr[entry_idx]),
            "thscode": code,
            "exit_date": pd.Timestamp(dates_arr[exit_idx]),
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "exit_price": float(closes[exit_idx]),
            "hold_days": int(exit_idx - entry_idx),
        })

        in_position_until = pd.Timestamp(dates_arr[exit_idx])

    if not trades:
        return _empty_trades()

    return pd.DataFrame(trades, columns=[
        "entry_date", "thscode", "exit_date", "exit_reason",
        "entry_price", "exit_price", "hold_days",
    ])


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "entry_date", "thscode", "exit_date", "exit_reason",
        "entry_price", "exit_price", "hold_days",
    ])
