"""渲染前 200 笔交易明细 → 单文件 HTML。

每笔交易包含：
  - K 线图（含 MA5/10/20/60 + entry/exit 标记，100 根 K 线）
  - 5 个指标面板：MACD / PCT_CHG / AM60 / UP_STREAK / BELOW_MA60_RATIO_60
  - 入场时 5 条件评估（A/B/C/D/E）
  - 数据表格（每根 bar 的指标值）

入参：通过 --trades-file 传入 trades JSON；默认 200 笔。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DB_PATH = Path("/Users/zhl/code/Financial-API/data/market.duckdb")
DEFAULT_TRADES_FILE = Path(
    "short_reversal/results/v3_v33_mainboard_tp25_sl02_relaxed.json"
)
DEFAULT_OUTPUT = Path("short_reversal/results/trades_detail.html")

BACKTEST_START = "2025-09-12"
BACKTEST_END = "2026-09-12"

# 5 条件参数（v33_mainboard preset 默认）
LIQ_LOW = 3e7
LIQ_HIGH = 3e8
UP_STREAK_LOW = 3
UP_STREAK_HIGH = 10
PCT_CHG_LOW = 0.01  # relaxed preset
PCT_CHG_HIGH = 0.07


# ============================================================ data loading


def fetch_klines(codes: list[str]) -> dict[str, pd.DataFrame]:
    """批量拉取 K 线（一次性 SQL IN 查询）。"""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # 拉前 250 个交易日 + backtest 期间
        sql = """
            SELECT thscode, date, open, high, low, close, volume, amount
            FROM v_daily
            WHERE thscode = ANY(?)
              AND date >= '2025-01-01' AND date <= '2026-12-31'
            ORDER BY thscode, date
        """
        df = con.execute(sql, [codes]).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    return {code: g.reset_index(drop=True) for code, g in df.groupby("thscode")}


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算 9 个指标（pandas 版本）。"""
    out = df.copy()
    out["ma5"] = out["close"].rolling(5).mean()
    out["ma10"] = out["close"].rolling(10).mean()
    out["ma20"] = out["close"].rolling(20).mean()
    out["ma60"] = out["close"].rolling(60).mean()

    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd_dif"] = ema12 - ema26
    out["macd_dea"] = out["macd_dif"].ewm(span=9, adjust=False).mean()
    out["macd_bar"] = (out["macd_dif"] - out["macd_dea"]) * 2

    out["pct_chg"] = out["close"].pct_change()

    out["am60"] = out["amount"].rolling(60).mean()

    streak = np.zeros(len(out), dtype=int)
    for i in range(1, len(out)):
        if out["close"].iloc[i] > out["close"].iloc[i - 1]:
            streak[i] = streak[i - 1] + 1
        else:
            streak[i] = 0
    out["up_streak"] = streak

    ratio = np.full(len(out), np.nan)
    for i in range(59, len(out)):
        win_c = out["close"].iloc[i - 59 : i + 1].values
        win_m = out["ma60"].iloc[i - 59 : i + 1].values
        valid = ~(np.isnan(win_c) | np.isnan(win_m))
        if valid.sum() > 0:
            ratio[i] = (win_c[valid] < win_m[valid]).sum() / valid.sum()
    out["below_ma60_ratio_60"] = ratio

    return out


# ============================================================ date lookup


def find_entry_exit_dates(
    df: pd.DataFrame, entry_price: float, exit_price: float, hold_days: int
) -> tuple[int, int]:
    """返回 (entry_idx, exit_idx) 在 df 中的 0-based 位置。

    exit bar 由 hold_days 决定（不是 exit_price，因为 TP/SL 时 exit_price 是合成价）。
    hold_days = exit_bar_0based - entry_bar_0based - 1
    → exit_idx = entry_idx + hold_days + 1

    entry_idx 在 backtest 区间内查找。
    """
    mask = (df["date"] >= BACKTEST_START) & (df["date"] <= BACKTEST_END)
    sub = df[mask]
    if len(sub) == 0:
        return -1, -1

    # 找 open == entry_price 的 bar（精确匹配）。df 已 reset_index → labels = positions
    matches = sub.index[sub["open"] == entry_price].tolist()
    if not matches:
        # fallback：open 与 entry_price 最接近
        diffs = (sub["open"] - entry_price).abs()
        matches = [int(diffs.idxmin())]

    entry_idx = int(matches[0])
    exit_idx = entry_idx + hold_days + 1
    # clamp 到 backtest 窗口末尾（df 内）
    bt_end_idx = int(sub.index[-1])
    if exit_idx > bt_end_idx:
        exit_idx = bt_end_idx
    if exit_idx < entry_idx:
        exit_idx = entry_idx
    return entry_idx, exit_idx


def get_window(
    df: pd.DataFrame,
    entry_idx: int,
    exit_idx: int,
    signal_idx: int | None = None,
    n_before: int = 50,
    n_after_extra: int = 10,
) -> tuple[pd.DataFrame, int, int, int]:
    """取包含 signal / entry / exit 的窗口。

    返回 (window, w_signal_idx, w_entry_idx, w_exit_idx)。
    若 signal_idx 为 None 或 < 0，则 w_signal_idx = -1（调用方需跳过信号标记）。
    """
    if signal_idx is None or signal_idx < 0:
        w_signal_idx = -1
        actual_signal = entry_idx
    else:
        actual_signal = signal_idx
    start = max(0, min(actual_signal, entry_idx) - n_before)
    end = min(len(df), exit_idx + n_after_extra + 1)
    window = df.iloc[start:end].reset_index(drop=True)
    if signal_idx is None or signal_idx < 0:
        w_signal_idx = -1
    else:
        w_signal_idx = signal_idx - start
    w_entry_idx = entry_idx - start
    w_exit_idx = exit_idx - start
    return window, w_signal_idx, w_entry_idx, w_exit_idx


# ============================================================ SVG rendering


def _scale_x(n: int, width: int, pad_left: int = 40, pad_right: int = 10) -> list[float]:
    return [pad_left + (width - pad_left - pad_right) * i / max(n - 1, 1) for i in range(n)]


def render_kline_svg(
    window: pd.DataFrame,
    entry_idx: int,
    exit_idx: int,
    signal_idx: int = -1,
    width: int = 900,
    kline_h: int = 260,
) -> str:
    """K线 + MA + signal/entry/exit 标记。"""
    n = len(window)
    xs = _scale_x(n, width)
    h_pad = 20
    closes = window["close"].values
    lows = window["low"].values
    highs = window["high"].values
    opens = window["open"].values

    pmin = float(np.nanmin(lows))
    pmax = float(np.nanmax(highs))
    prange = pmax - pmin if pmax > pmin else 1.0

    def y(price: float) -> float:
        return h_pad + kline_h - (price - pmin) / prange * kline_h

    parts = [
        f'<svg width="{width}" height="{kline_h + 30}" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {kline_h + 30}" font-family="monospace" font-size="9">',
        f'<rect width="{width}" height="{kline_h + 30}" fill="#0e1117"/>',
    ]

    # grid + Y 轴价格标签
    n_grid = 5
    for i in range(n_grid + 1):
        gy = h_pad + kline_h * i / n_grid
        price_at = pmax - prange * i / n_grid
        parts.append(
            f'<line x1="40" y1="{gy:.1f}" x2="{width - 10}" y2="{gy:.1f}" '
            f'stroke="#222" stroke-width="0.5"/>'
            f'<text x="2" y="{gy + 3:.1f}" fill="#888">{price_at:.2f}</text>'
        )

    # candlesticks
    bar_w = max(2.0, (width - 50) / n * 0.6)
    for i in range(n):
        x = xs[i]
        o, c, lo, hi = opens[i], closes[i], lows[i], highs[i]
        if np.isnan([o, c, lo, hi]).any():
            continue
        up = c >= o
        color = "#ef5350" if up else "#26a69a"  # A股惯例：红涨绿跌
        yo, yc = y(o), y(c)
        yt, yb = min(yo, yc), max(yo, yc)
        # wick
        parts.append(
            f'<line x1="{x:.1f}" y1="{y(hi):.1f}" x2="{x:.1f}" y2="{y(lo):.1f}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
        # body
        parts.append(
            f'<rect x="{x - bar_w / 2:.1f}" y="{yt:.1f}" width="{bar_w:.1f}" '
            f'height="{max(yb - yt, 1):.1f}" fill="{color}"/>'
        )

    # MA lines
    ma_specs = [
        ("ma5", "#ffeb3b", 1.0),
        ("ma10", "#03a9f4", 1.0),
        ("ma20", "#e91e63", 1.2),
        ("ma60", "#9c27b0", 1.4),
    ]
    for col, color, sw in ma_specs:
        ys = []
        for i in range(n):
            v = window[col].iloc[i]
            if pd.isna(v):
                ys.append(None)
            else:
                ys.append(y(v))
        path = []
        started = False
        for i, yv in enumerate(ys):
            if yv is None:
                started = False
                continue
            if not started:
                path.append(f"M {xs[i]:.1f} {yv:.1f}")
                started = True
            else:
                path.append(f"L {xs[i]:.1f} {yv:.1f}")
        if path:
            parts.append(
                f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="{sw}" '
                f'fill="none" opacity="0.85"/>'
            )

    # entry marker
    if 0 <= entry_idx < n:
        x = xs[entry_idx]
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + kline_h}" '
            f'stroke="#ff5722" stroke-width="2" stroke-dasharray="4,2"/>'
            f'<text x="{x + 2:.1f}" y="{h_pad + 10:.1f}" fill="#ff5722" font-weight="bold">▼ ENTRY</text>'
        )

    # signal marker（黄色，entry 前 1 bar）
    if 0 <= signal_idx < n:
        x = xs[signal_idx]
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + kline_h}" '
            f'stroke="#ffeb3b" stroke-width="1.5" stroke-dasharray="2,3"/>'
            f'<rect x="{x + 1:.1f}" y="{h_pad + 0:.1f}" width="56" height="11" '
            f'fill="#0e1117" stroke="#ffeb3b" stroke-width="0.5"/>'
            f'<text x="{x + 3:.1f}" y="{h_pad + 9:.1f}" fill="#ffeb3b" font-weight="bold">⚡ SIGNAL</text>'
        )

    # exit marker（即使同 bar 也要画：标签放更下面）
    if 0 <= exit_idx < n:
        x = xs[exit_idx]
        same_bar = exit_idx == entry_idx
        # 同 bar 时用实线 + 不同 y 位置避开 entry 标签
        dash = "" if same_bar else 'stroke-dasharray="4,2"'
        label_y = h_pad + (34 if same_bar else 22)
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + kline_h}" '
            f'stroke="#2196f3" stroke-width="2" {dash}/>'
            f'<rect x="{x + 1:.1f}" y="{label_y - 9:.1f}" width="44" height="11" '
            f'fill="#0e1117" stroke="#2196f3" stroke-width="0.5"/>'
            f'<text x="{x + 3:.1f}" y="{label_y:.1f}" fill="#2196f3" font-weight="bold">▲ EXIT</text>'
        )

    # legend
    parts.append(
        '<g font-size="10" fill="#bbb">'
        '<rect x="40" y="2" width="14" height="8" fill="#ffeb3b"/><text x="58" y="9">MA5</text>'
        '<rect x="100" y="2" width="14" height="8" fill="#03a9f4"/><text x="118" y="9">MA10</text>'
        '<rect x="170" y="2" width="14" height="8" fill="#e91e63"/><text x="188" y="9">MA20</text>'
        '<rect x="240" y="2" width="14" height="8" fill="#9c27b0"/><text x="258" y="9">MA60</text>'
        '<rect x="320" y="2" width="14" height="8" fill="#ef5350"/><text x="338" y="9">UP</text>'
        '<rect x="380" y="2" width="14" height="8" fill="#26a69a"/><text x="398" y="9">DOWN</text>'
        '</g>'
    )

    parts.append("</svg>")
    return "".join(parts)


def render_indicator_panel(
    window: pd.DataFrame,
    cols: list[tuple[str, str, str]],
    entry_idx: int,
    exit_idx: int,
    signal_idx: int = -1,
    title: str = "",
    width: int = 900,
    height: int = 110,
    ymin: float | None = None,
    ymax: float | None = None,
    zero_line: bool = False,
) -> str:
    """通用指标折线图（多线可叠加）。"""
    n = len(window)
    xs = _scale_x(n, width)
    h_pad = 20
    parts = [
        f'<svg width="{width}" height="{height + 30}" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height + 30}" font-family="monospace" font-size="9">',
        f'<rect width="{width}" height="{height + 30}" fill="#0e1117"/>',
        f'<text x="2" y="12" fill="#bbb" font-weight="bold">{title}</text>',
    ]

    vals_all = []
    for col, _, _ in cols:
        vals_all.extend(window[col].dropna().tolist())
    if not vals_all:
        parts.append("</svg>")
        return "".join(parts)

    if ymin is None:
        ymin = min(vals_all)
    if ymax is None:
        ymax = max(vals_all)
    if ymax == ymin:
        ymax = ymin + 1
    rng = ymax - ymin

    def y(v: float) -> float:
        return h_pad + height - (v - ymin) / rng * height

    # grid
    for i in range(4):
        gy = h_pad + height * i / 4
        val_at = ymax - rng * i / 4
        parts.append(
            f'<line x1="40" y1="{gy:.1f}" x2="{width - 10}" y2="{gy:.1f}" '
            f'stroke="#222" stroke-width="0.5"/>'
            f'<text x="2" y="{gy + 3:.1f}" fill="#888">{val_at:.3f}</text>'
        )

    if zero_line and ymin < 0 < ymax:
        yz = y(0)
        parts.append(
            f'<line x1="40" y1="{yz:.1f}" x2="{width - 10}" y2="{yz:.1f}" '
            f'stroke="#666" stroke-width="1" stroke-dasharray="3,2"/>'
        )

    for col, color, _ in cols:
        ys = []
        for i in range(n):
            v = window[col].iloc[i]
            if pd.isna(v):
                ys.append(None)
            else:
                ys.append(y(v))
        path = []
        started = False
        for i, yv in enumerate(ys):
            if yv is None:
                started = False
                continue
            if not started:
                path.append(f"M {xs[i]:.1f} {yv:.1f}")
                started = True
            else:
                path.append(f"L {xs[i]:.1f} {yv:.1f}")
        if path:
            parts.append(
                f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="1.2" fill="none"/>'
            )

    # entry/exit vertical lines（同 bar 时画在一起，entry 在左、exit 在右各偏移 1px）
    if 0 <= entry_idx < n:
        x = xs[entry_idx] - 0.5
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + height}" '
            f'stroke="#ff5722" stroke-width="1" stroke-dasharray="3,2"/>'
        )
    if 0 <= exit_idx < n:
        x = xs[exit_idx] + 0.5
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + height}" '
            f'stroke="#2196f3" stroke-width="1" stroke-dasharray="3,2"/>'
        )
    # signal vertical line（黄色，在 entry 之前 1 bar）
    if 0 <= signal_idx < n:
        x = xs[signal_idx]
        parts.append(
            f'<line x1="{x:.1f}" y1="{h_pad}" x2="{x:.1f}" y2="{h_pad + height}" '
            f'stroke="#ffeb3b" stroke-width="1" stroke-dasharray="2,3" opacity="0.7"/>'
        )

    # legend
    leg_x = 80
    for col, color, label in cols:
        parts.append(
            f'<rect x="{leg_x}" y="2" width="10" height="6" fill="{color}"/>'
            f'<text x="{leg_x + 12}" y="9" fill="#bbb">{label}</text>'
        )
        leg_x += len(label) * 7 + 30

    parts.append("</svg>")
    return "".join(parts)


# ============================================================ conditions


def evaluate_conditions(window: pd.DataFrame, entry_idx: int) -> dict:
    """入场 bar 评估 5 条件。"""
    row = window.iloc[entry_idx]
    cond = {}

    am60 = row.get("am60", np.nan)
    cond["E_liquidity"] = (not pd.isna(am60)) and (LIQ_LOW <= am60 <= LIQ_HIGH)
    cond["E_val"] = f"{am60:.2e}" if not pd.isna(am60) else "NaN"

    close = row["close"]
    ma60 = row.get("ma60", np.nan)
    ratio = row.get("below_ma60_ratio_60", np.nan)
    cond["A_close_lt_ma60"] = (not pd.isna(ma60)) and (close < ma60)
    cond["A_ratio_ge_06"] = (not pd.isna(ratio)) and (ratio >= 0.6)
    cond["A_pass"] = cond["A_close_lt_ma60"] and cond["A_ratio_ge_06"]
    cond["A_close"] = f"{close:.2f}"
    cond["A_ma60"] = f"{ma60:.2f}" if not pd.isna(ma60) else "NaN"
    cond["A_ratio"] = f"{ratio:.2f}" if not pd.isna(ratio) else "NaN"

    us = int(row.get("up_streak", 0))
    cond["B_up_streak_3_10"] = UP_STREAK_LOW <= us <= UP_STREAK_HIGH
    cond["B_val"] = str(us)

    pc = row.get("pct_chg", np.nan)
    cond["C_pct_chg_in_range"] = (not pd.isna(pc)) and (PCT_CHG_LOW <= pc <= PCT_CHG_HIGH)
    cond["C_val"] = f"{pc * 100:.2f}%" if not pd.isna(pc) else "NaN"

    dif = row.get("macd_dif", np.nan)
    dea = row.get("macd_dea", np.nan)
    bar = row.get("macd_bar", np.nan)
    prev_bar = window.iloc[entry_idx - 1].get("macd_bar", np.nan) if entry_idx > 0 else np.nan
    cond["D_dif_lt_0"] = (not pd.isna(dif)) and (dif < 0)
    cond["D_dea_lt_0"] = (not pd.isna(dea)) and (dea < 0)
    cond["D_bar_shrinking"] = (not pd.isna(bar)) and (not pd.isna(prev_bar)) and (abs(bar) < abs(prev_bar))
    cond["D_pass"] = cond["D_dif_lt_0"] and cond["D_dea_lt_0"] and cond["D_bar_shrinking"]
    cond["D_dif"] = f"{dif:.4f}" if not pd.isna(dif) else "NaN"
    cond["D_dea"] = f"{dea:.4f}" if not pd.isna(dea) else "NaN"
    cond["D_bar"] = f"{bar:.4f}" if not pd.isna(bar) else "NaN"
    cond["D_prev_bar"] = f"{prev_bar:.4f}" if not pd.isna(prev_bar) else "NaN"

    cond["ALL_PASS"] = cond["E_liquidity"] and cond["A_pass"] and cond["B_up_streak_3_10"] and cond["C_pct_chg_in_range"] and cond["D_pass"]
    return cond


# ============================================================ HTML assembly


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ background: #0e1117; color: #ddd; font-family: -apple-system, sans-serif; margin: 0; padding: 20px; }}
  .nav {{ position: fixed; top: 0; right: 0; background: #1a1d24; padding: 8px 14px; border-radius: 4px; z: 1000; }}
  .nav a {{ color: #4dd0e1; text-decoration: none; margin: 0 6px; }}
  .trade-card {{ background: #16191f; border: 1px solid #2a2e36; border-radius: 6px; padding: 14px; margin-bottom: 24px; }}
  .trade-card:hover {{ border-color: #4dd0e1; }}
  .trade-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; flex-wrap: wrap; }}
  .trade-header h2 {{ margin: 0; color: #fff; font-size: 16px; }}
  .trade-header .meta {{ color: #888; font-size: 12px; margin-left: 12px; }}
  .pnl-pos {{ color: #ef5350; font-weight: bold; }}
  .pnl-neg {{ color: #26a69a; font-weight: bold; }}
  .reason-TP {{ background: #ef5350; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 11px; }}
  .reason-SL {{ background: #26a69a; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 11px; }}
  .reason-time {{ background: #ff9800; color: #fff; padding: 2px 8px; border-radius: 3px; font-size: 11px; }}
  .conditions {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-top: 10px; font-size: 11px; }}
  .cond {{ background: #1a1d24; padding: 6px 8px; border-radius: 3px; }}
  .cond-ok {{ border-left: 3px solid #66bb6a; }}
  .cond-fail {{ border-left: 3px solid #ef5350; opacity: 0.7; }}
  .cond-name {{ color: #4dd0e1; font-weight: bold; }}
  .cond-val {{ color: #aaa; font-family: monospace; }}
  .panel-block {{ margin: 6px 0; }}
  .panel-title {{ color: #888; font-size: 11px; margin: 4px 0 2px 0; }}
  table.data {{ width: 100%; border-collapse: collapse; font-family: monospace; font-size: 10px; margin-top: 8px; }}
  table.data th, table.data td {{ padding: 2px 4px; border-bottom: 1px solid #1a1d24; text-align: right; }}
  table.data th {{ background: #1a1d24; color: #4dd0e1; font-weight: normal; position: sticky; top: 0; }}
  table.data tr.entry-row {{ background: #2a1810 !important; }}
  table.data tr.exit-row {{ background: #102a18 !important; }}
  table.data tr.signal-row {{ background: #2a2810 !important; }}
  table.data td.date {{ text-align: left; color: #888; }}
  h1 {{ color: #fff; border-bottom: 1px solid #2a2e36; padding-bottom: 10px; }}
  .summary {{ background: #1a1d24; padding: 14px; border-radius: 6px; margin-bottom: 20px; }}
  .summary table {{ width: 100%; }}
  .summary td {{ padding: 4px 8px; }}
</style>
</head>
<body>
"""


def render_data_table(window: pd.DataFrame, entry_idx: int, exit_idx: int, signal_idx: int = -1) -> str:
    """每根 bar 的指标值表（紧凑显示）。"""
    cols = ["date", "open", "high", "low", "close", "amount",
            "ma5", "ma10", "ma20", "ma60",
            "macd_dif", "macd_dea", "macd_bar",
            "pct_chg", "am60", "up_streak", "below_ma60_ratio_60"]
    headers = ["date", "O", "H", "L", "C", "amt",
               "MA5", "MA10", "MA20", "MA60",
               "DIF", "DEA", "BAR",
               "PCT", "AM60", "US", "RATIO"]
    rows = []
    for i in range(len(window)):
        cls = ""
        if i == signal_idx:
            cls = ' class="signal-row"'
        elif i == entry_idx:
            cls = ' class="entry-row"'
        elif i == exit_idx:
            cls = ' class="exit-row"'
        cells = []
        for c in cols:
            v = window.iloc[i][c]
            if pd.isna(v):
                cells.append('<td>-</td>')
            elif c == "date":
                cells.append(f'<td class="date">{v.strftime("%m-%d")}</td>')
            elif c == "amount":
                cells.append(f'<td>{v / 1e8:.2f}e8</td>')
            elif c in ("pct_chg", "below_ma60_ratio_60"):
                cells.append(f'<td>{v * 100:+.2f}%</td>' if c == "pct_chg" else f'<td>{v:.2f}</td>')
            elif c == "up_streak":
                cells.append(f'<td>{int(v)}</td>')
            elif c in ("macd_dif", "macd_dea", "macd_bar"):
                cells.append(f'<td>{v:+.3f}</td>')
            else:
                cells.append(f'<td>{v:.2f}</td>')
        rows.append(f'<tr{cls}>{"".join(cells)}</tr>')

    return (
        '<table class="data"><thead><tr>'
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_trade_card(
    idx: int, trade: dict, klines: dict[str, pd.DataFrame]
) -> str:
    """单笔交易的完整 HTML。"""
    code = trade["thscode"]
    if code not in klines:
        return f'<div class="trade-card"><h2>Trade #{idx + 1}: {code}</h2><p>K线数据缺失</p></div>'

    raw = klines[code]
    indicators = compute_indicators(raw)
    entry_idx, exit_idx = find_entry_exit_dates(
        indicators,
        trade["entry_price"],
        trade["exit_price"],
        trade["hold_days"],
    )
    if entry_idx < 0:
        return f'<div class="trade-card"><h2>Trade #{idx + 1}: {code}</h2><p>未找到 entry bar</p></div>'

    # 校验 exit_idx 必在 df 内
    if exit_idx >= len(indicators):
        exit_idx = len(indicators) - 1

    # 自适应窗口：保证 signal/entry/exit 都在窗口内
    signal_idx = entry_idx - 1  # 信号 bar = entry 前 1 bar（T 日 close 触发）
    if signal_idx < 0:
        signal_idx = entry_idx  # 边界情况：entry 在最前 bar
    window, w_signal_idx, w_entry_idx, w_exit_idx = get_window(
        indicators, entry_idx, exit_idx, signal_idx=signal_idx,
        n_before=50, n_after_extra=max(10, trade["hold_days"] + 5),
    )

    signal_date = window.iloc[w_signal_idx]["date"]
    entry_date = window.iloc[w_entry_idx]["date"]
    exit_date = window.iloc[w_exit_idx]["date"]

    pnl_class = "pnl-pos" if trade["net"] > 0 else "pnl-neg"
    pnl_sign = "+" if trade["net"] > 0 else ""

    # 条件评估在 SIGNAL bar（信号实际触发的位置），不是 entry bar
    cond = evaluate_conditions(window, w_signal_idx)

    parts = [
        f'<div class="trade-card" id="t{idx}">',
        '<div class="trade-header">',
        f'<h2>#{idx + 1} {code}</h2>',
        f'<span class="meta" style="color:#ffeb3b">⚡ signal: <b>{signal_date.strftime("%Y-%m-%d")}</b> close={window.iloc[w_signal_idx]["close"]:.2f}</span>',
        f'<span class="meta">entry: <b>{entry_date.strftime("%Y-%m-%d")}</b> @ {trade["entry_price"]:.2f}</span>',
        f'<span class="meta">exit: <b>{exit_date.strftime("%Y-%m-%d")}</b> @ {trade["exit_price"]:.2f}</span>',
        f'<span class="reason-{trade["exit_reason"]}">{trade["exit_reason"]}</span>',
        f'<span class="{pnl_class}">{pnl_sign}{trade["net"] * 100:.2f}%</span>',
        f'<span class="meta">size={trade["size"]:,} | hold={trade["hold_days"]}d</span>',
        '</div>',
        '<div class="panel-block">',
        render_kline_svg(window, w_entry_idx, w_exit_idx, w_signal_idx),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("ma5", "#ffeb3b", "MA5"),
             ("ma10", "#03a9f4", "MA10"),
             ("ma20", "#e91e63", "MA20"),
             ("ma60", "#9c27b0", "MA60")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="均线簇 (MA5/10/20/60)",
            height=110,
        ),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("macd_dif", "#ffeb3b", "DIF"),
             ("macd_dea", "#03a9f4", "DEA"),
             ("macd_bar", "#e91e63", "BAR×2")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="MACD (12/26/9)",
            height=110,
            zero_line=True,
        ),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("pct_chg", "#ffeb3b", "PCT_CHG")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="单日涨跌幅",
            height=70,
            zero_line=True,
        ),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("am60", "#03a9f4", "AM60 (成交额 60日均值)")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="流动性指标",
            height=70,
        ),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("up_streak", "#e91e63", "连续上涨天数")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="连阳计数 (UP_STREAK)",
            height=70,
        ),
        '</div>',
        '<div class="panel-block">',
        render_indicator_panel(
            window,
            [("below_ma60_ratio_60", "#9c27b0", "close<MA60 比例 (60 日)")],
            w_entry_idx, w_exit_idx, w_signal_idx,
            title="V1 A 条件: close<MA60 比例",
            height=70,
            ymin=0, ymax=1,
        ),
        '</div>',
        '<div class="conditions">',
        f'<div class="cond {"cond-ok" if cond["E_liquidity"] else "cond-fail"}">'
        f'<div class="cond-name">E 流动性</div><div class="cond-val">am60={cond["E_val"]}</div></div>',
        f'<div class="cond {"cond-ok" if cond["A_pass"] else "cond-fail"}">'
        f'<div class="cond-name">A 默认</div><div class="cond-val">close={cond["A_close"]} ma60={cond["A_ma60"]} ratio={cond["A_ratio"]}</div></div>',
        f'<div class="cond {"cond-ok" if cond["B_up_streak_3_10"] else "cond-fail"}">'
        f'<div class="cond-name">B 连阳</div><div class="cond-val">up_streak={cond["B_val"]}</div></div>',
        f'<div class="cond {"cond-ok" if cond["C_pct_chg_in_range"] else "cond-fail"}">'
        f'<div class="cond-name">C 涨幅</div><div class="cond-val">pct_chg={cond["C_val"]}</div></div>',
        f'<div class="cond {"cond-ok" if cond["D_pass"] else "cond-fail"}">'
        f'<div class="cond-name">D MACD</div><div class="cond-val">dif={cond["D_dif"]} dea={cond["D_dea"]} bar={cond["D_bar"]} prev={cond["D_prev_bar"]}</div></div>',
        '</div>',
        '<details style="margin-top: 10px;"><summary style="color: #4dd0e1; cursor: pointer; font-size: 12px;">点击查看原始数据表（黄=signal 红=entry 绿=exit）</summary>',
        render_data_table(window, w_entry_idx, w_exit_idx, w_signal_idx),
        '</details>',
        '</div>',
    ]
    return "".join(parts)


# ============================================================ main


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades-file", default=str(DEFAULT_TRADES_FILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--n-trades", type=int, default=200)
    args = parser.parse_args()

    trades_file = Path(args.trades_file)
    output = Path(args.output)
    n_trades = args.n_trades

    with open(trades_file) as f:
        m = json.load(f)
    trades = m["trades"][:n_trades]

    # 批量拉 K 线
    print(f"拉取 {len(trades)} 笔交易的 K 线...")
    codes = list({t["thscode"] for t in trades})
    klines = fetch_klines(codes)
    print(f"K 线 ready：{len(klines)} 只票")

    # 摘要
    summary_html = '<div class="summary"><h2>回测摘要</h2><table>'
    summary_html += (
        f'<tr><td>preset</td><td>{m["preset"]}</td></tr>'
        f'<tr><td>区间</td><td>{m["start"]} → {m["end"]}</td></tr>'
        f'<tr><td>展示笔数</td><td>{len(trades)} / {m["trades_count"]}</td></tr>'
        f'<tr><td>胜率</td><td>{m["win_rate"] * 100:.1f}%</td></tr>'
        f'<tr><td>期末资金</td><td>¥{m["final_capital"]:,.2f}</td></tr>'
        f'<tr><td>总收益</td><td>{m["total_yield"] * 100:+.2f}%</td></tr>'
        f'<tr><td>CAGR</td><td>{m["cagr"] * 100:+.2f}%</td></tr>'
        f'<tr><td>Sharpe</td><td>{m["sharpe"]:.2f}</td></tr>'
        f'<tr><td>最大回撤</td><td>{m["max_dd"] * 100:.2f}%</td></tr>'
        f'<tr><td>TP/SL/time</td><td>{m["tp_count"]} / {m["sl_count"]} / {m["time_count"]}</td></tr>'
    )
    summary_html += '</table></div>'

    # 导航
    nav = '<div class="nav">'
    for i in range(0, len(trades), 10):
        nav += f'<a href="#t{i}">{i + 1}-{min(i + 10, len(trades))}</a> '
    nav += '</div>'

    # 渲染每笔交易
    cards = []
    for i, t in enumerate(trades):
        cards.append(render_trade_card(i, t, klines))
        if (i + 1) % 20 == 0:
            print(f"  渲染进度: {i + 1}/{len(trades)}")

    html = (
        HTML_HEAD.format(title=f"Trades Detail - {trades_file.stem}")
        + f"<h1>前 {len(trades)} 笔交易明细</h1>"
        + summary_html
        + nav
        + "".join(cards)
        + "</body></html>"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"输出: {output} ({len(html) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()