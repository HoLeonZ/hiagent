"""大盘择时 — 由样本内个股自身合成等权指数，判断多头环境。

为什么需要：目标年主板中位数个股 -8.1%、仅 38.8% 上涨。在这种环境里
无差别做多必然亏损，必须有市场状态开关。

无未来函数：T 日的 regime 只用 ≤T 的数据（等权指数与其均线）。
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_regime(
    panel_ind: pd.DataFrame,
    *,
    ma_window: int = 20,
    breadth_window: int = 20,
    min_breadth: float = 0.45,
    require_rising: bool = False,
    rising_lookback: int = 5,
) -> pd.DataFrame:
    """返回 columns=[date, ew_index, ew_ma, breadth_sm, regime_ok]。

    regime_ok = 等权指数 > 自身 MA(ma_window)
                且 市场宽度 ≥ min_breadth
                且（可选）MA 本身在上行

    require_rising 用于过滤"熊市反抽"——指数短暂上穿均线但均线仍在下行。
    """
    daily = (
        panel_ind.groupby("date", sort=True)
        .agg(ret=("ret1", "mean"), breadth=("above_ma20", "mean"))
        .reset_index()
    )
    daily["ret"] = daily["ret"].fillna(0.0)
    daily["ew_index"] = (1.0 + daily["ret"]).cumprod()
    daily["ew_ma"] = daily["ew_index"].rolling(ma_window, min_periods=ma_window).mean()
    daily["breadth_sm"] = (
        daily["breadth"].rolling(breadth_window, min_periods=1).mean()
    )

    ok = (daily["ew_index"] > daily["ew_ma"]) & (daily["breadth_sm"] >= min_breadth)
    if require_rising:
        ok &= daily["ew_ma"] > daily["ew_ma"].shift(rising_lookback)
    daily["regime_ok"] = ok.fillna(False)

    logger.info(
        "regime: %d/%d 天可做多 (%.1f%%)",
        int(daily["regime_ok"].sum()), len(daily),
        100.0 * daily["regime_ok"].mean(),
    )
    return daily[["date", "ew_index", "ew_ma", "breadth_sm", "regime_ok"]]
