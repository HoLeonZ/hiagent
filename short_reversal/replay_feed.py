"""Phase 2: 合成 feed，每日一根 K 线（持仓日真实 OHLCV，未持仓日 prev_close 占位）。"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def build_synthetic_feed(
    trades_df: pd.DataFrame,
    panel_df: pd.DataFrame,
) -> pd.DataFrame:
    """构造 backtrader 用的合成 K 线 DataFrame。

    Args:
      trades_df: 列 [entry_date, thscode, exit_date, exit_reason, entry_price, exit_price, hold_days]
      panel_df: 列 [thscode, date, open, high, low, close, volume]

    Returns:
      DataFrame，index=date（DatetimeIndex 升序），列 [open, high, low, close, volume]
      - 持仓日（entry_date ≤ d ≤ exit_date，对应 thscode 在 panel 中有 K 线）：
        用该 thscode 当日真实 OHLCV
      - 未持仓日：open=high=low=close=prev_close, volume=0
        （prev_close = 前一根 bar 的 close；首根 prev_close 为 None 时用 0.0）
    """
    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)

    all_dates = sorted(panel["date"].unique())
    if not all_dates:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        empty.index = pd.DatetimeIndex([], name="date")
        return empty

    # 每日持仓标的：(date -> thscode) 映射
    held_map: dict[pd.Timestamp, str] = {}
    for _, t in trades_df.iterrows():
        code = t["thscode"]
        d0 = pd.Timestamp(t["entry_date"])
        d1 = pd.Timestamp(t["exit_date"])
        cur = d0
        # 用 BDay 推进，覆盖 entry 至 exit（含 exit 当日）
        while cur <= d1:
            held_map[cur] = code
            cur = cur + pd.tseries.offsets.BDay(1)

    rows: list[dict] = []
    # bootstrap prev_close from the first panel day's close, so unheld days
    # inherit the most recent real close rather than 0.0 on the first bar
    prev_close: float | None = None
    first_panel = panel[panel["date"] == all_dates[0]]
    if not first_panel.empty:
        prev_close = float(first_panel.iloc[0]["close"])
    for d in all_dates:
        code = held_map.get(d)
        if code is not None:
            sub = panel[(panel["thscode"] == code) & (panel["date"] == d)]
            if not sub.empty:
                r = sub.iloc[0]
                rows.append({
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                })
                prev_close = float(r["close"])
                continue
            logger.warning(
                "build_synthetic_feed: thscode=%s date=%s 在 held_map 但 panel 无 K 线，按占位 bar 处理",
                code, d,
            )
        # 未持仓或 panel 缺失此日 K 线 → 用 prev_close 占位
        flat = prev_close if prev_close is not None else 0.0
        rows.append({
            "open": flat, "high": flat, "low": flat, "close": flat,
            "volume": 0.0,
        })

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(all_dates, name="date"))
    return df
