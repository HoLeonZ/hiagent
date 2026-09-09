"""Phase 1 持仓循环 — 全局单 key 锁 + TP/SL/time 退出。

按 (date ASC, thscode ASC) 排序 entry 信号，循环中维护 in_position_until:
  - entry_date <= in_position_until → 跳过（持仓期忽略新信号）
  - 否则：从 panel 找 entry_idx + 1 起逐根判定
      TP: low <= tp_p
      SL: high >= sl_p
      time: i >= max_hold
    优先级 TP → SL → time（严格匹配 v33 原实现）。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "entry_date", "thscode", "exit_date", "exit_reason",
        "entry_price", "exit_price", "hold_days",
    ])


def pre_simulate_trades(
    entries_df: pd.DataFrame,
    panel_df: pd.DataFrame,
    *,
    tp_pct: float,
    sl_pct: float,
    max_hold: int,
) -> pd.DataFrame:
    if tp_pct <= 0:
        raise ValueError(f"tp_pct must be > 0, got {tp_pct}")
    if sl_pct <= 0:
        raise ValueError(f"sl_pct must be > 0, got {sl_pct}")
    if max_hold <= 0:
        raise ValueError(f"max_hold must be > 0, got {max_hold}")

    if entries_df.empty:
        return _empty_trades()

    panel = panel_df[["thscode", "date", "open", "high", "low", "close"]].copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)

    entries = entries_df[["date", "thscode"]].copy()
    entries["date"] = pd.to_datetime(entries["date"])
    entries = entries.sort_values("date").reset_index(drop=True)

    panel_idx: dict[str, dict] = {}
    for code, sub in panel.groupby("thscode"):
        panel_idx[code] = {
            "dates": sub["date"].to_numpy(),
            "opens": sub["open"].to_numpy(),
            "highs": sub["high"].to_numpy(),
            "lows": sub["low"].to_numpy(),
            "closes": sub["close"].to_numpy(),
        }

    trades: list[dict] = []
    in_position_until: pd.Timestamp | None = None

    for _, ent in entries.iterrows():
        code = ent["thscode"]
        entry_date = ent["date"]

        if in_position_until is not None and entry_date <= in_position_until:
            continue

        pi = panel_idx.get(code)
        if pi is None:
            logger.debug("entry %s %s: panel 中无此票", code, entry_date)
            continue

        dates_arr = pi["dates"]
        n = len(dates_arr)
        entry_idx = int(np.searchsorted(dates_arr, np.datetime64(entry_date), side="left"))
        if entry_idx >= n or dates_arr[entry_idx] != np.datetime64(entry_date):
            logger.debug("entry %s %s: panel 中无该日 K 线", code, entry_date)
            continue

        opens = pi["opens"]
        highs = pi["highs"]
        lows = pi["lows"]
        closes = pi["closes"]

        # entry 价 = T+1 open
        if entry_idx + 1 >= n:
            logger.debug("entry %s %s: 无 T+1 起 K 线", code, entry_date)
            continue
        entry_price = float(opens[entry_idx + 1])

        tp_p = entry_price * (1 - tp_pct)
        sl_p = entry_price * (1 + sl_pct)

        # parity：原 v33 的 future = panel[date > sig_date].iloc[1:]，
        # 即从 T+2 起开始判定 TP/SL，T+1 仅用于 entry 价。
        # 这里 i = 0 对应 panel 绝对索引 entry_idx + 2。
        exit_idx = n - 1
        exit_reason = "time"
        exit_price: float = float(closes[n - 1])
        i = 0
        j = entry_idx + 2

        while j < n:
            # 顺序：time 检查优先于 TP/SL（v33 原顺序）
            if i >= max_hold:
                exit_idx = j
                exit_reason = "time"
                exit_price = float(closes[j])
                break
            if lows[j] <= tp_p:
                exit_idx = j
                exit_reason = "TP"
                # legacy parity: TP records tp_p (target threshold), not bar close
                exit_price = float(tp_p)
                break
            if highs[j] >= sl_p:
                exit_idx = j
                exit_reason = "SL"
                # legacy parity: SL records sl_p (target threshold), not bar close
                exit_price = float(sl_p)
                break
            i += 1
            j += 1

        # 兜底：循环跑完仍未退出（panel 长度不足 max_hold+1）
        if exit_reason == "time" and i < max_hold:
            # v33: k = min(max_hold - 1, len(future) - 1)
            k = min(max_hold - 1, n - (entry_idx + 2) - 1)
            if k >= 0:
                fallback_idx = entry_idx + 2 + k
                if fallback_idx < n:
                    exit_idx = fallback_idx
                    exit_reason = "time"
                    exit_price = float(closes[fallback_idx])

        trades.append({
            # TEAM-LEAD OVERRIDE: legacy strategy_v33_mainboard.py:188 sets
            # entry_date = future.iloc[0]["date"] AFTER future = future.iloc[1:],
            # so legacy entry_date = T+2 (off-by-one quirk). Match legacy byte-parity.
            "entry_date": pd.Timestamp(dates_arr[entry_idx + 2]),
            "thscode": code,
            "exit_date": pd.Timestamp(dates_arr[exit_idx]),
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "hold_days": int(exit_idx - entry_idx - 1),  # T+1 到 exit_idx 的天数差
        })

        in_position_until = pd.Timestamp(dates_arr[exit_idx])

    if not trades:
        return _empty_trades()

    return pd.DataFrame(trades, columns=[
        "entry_date", "thscode", "exit_date", "exit_reason",
        "entry_price", "exit_price", "hold_days",
    ])
