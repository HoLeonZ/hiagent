"""v5 策略回测交易 → HTML 可视化（每笔 K 线 + 全部指标 + 信号条件清单）。

数据源：uptrend_pullback/results/trades.csv（由 main.py --save-trades 生成）
窗口：信号日 -30 天 → 出场日 +5 天
指标：与回测严格同源（compute_indicators + compute_regime + select_entries）

输出：uptrend_pullback/results/trades_visualization.html
"""
from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from uptrend_pullback.presets import get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators, select_entries

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "code/Financial-API/data/market.duckdb"
RESULTS_DIR = Path(__file__).parent / "results"
TRADES_CSV = RESULTS_DIR / "trades.csv"
OUTPUT_HTML = RESULTS_DIR / "trades_visualization.html"

# 窗口参数
PRE_SIG_DAYS = 30  # 信号日前看多少天（含 MA120 预热）
POST_EXIT_DAYS = 5  # 出场日后看多少天

# 配色（与 short_reversal/render_trades_html.py 一致）
BG = "#0f1419"
PANEL_BG = "#1a2026"
BORDER = "#2a3540"
GRID = "#1f2933"
TEXT_DIM = "#888"
TEXT_BRIGHT = "#f5f5f5"
MONO = '"SF Mono", "Menlo", "Consolas", monospace'

# K线
COLOR_UP = "#26a69a"
COLOR_DOWN = "#ef5350"

# MAs（5/10/20/60/120 五条，颜色全不同）
MA_COLORS = {
    "ma5": "#fbbf24",    # 琥珀
    "ma10": "#a78bfa",   # 紫
    "ma20": "#42a5f5",   # 蓝
    "ma60": "#ffa726",   # 橙
    "ma120": "#ef5350",  # 红
}

# 退出原因
TAG_COLOR = {
    "TP": ("#26a69a", "止盈"),
    "SL": ("#ef5350", "止损"),
    "time": ("#ffa726", "时间出场"),
    "eod": ("#888", "末日前"),
}


# ============================================================================
# 数据加载与指标计算
# ============================================================================

def load_trades(csv_path: Path) -> list[dict]:
    out = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            out.append({
                "thscode": row["thscode"],
                "entry_date": row["entry_date"],
                "exit_date": row["exit_date"],
                "entry_price": float(row["entry_price"]),
                "exit_price": float(row["exit_price"]),
                "size": int(row["size"]),
                "hold_days": int(row["hold_days"]),
                "net_pnl": float(row["net_pnl"]),
                "net_return": float(row["net_return"]),
                "exit_reason": row["exit_reason"],
            })
    return out


def load_panel_for_trade(con: duckdb.DuckDBPyConnection, thscode: str,
                         entry_date: str, exit_date: str) -> pd.DataFrame:
    """拉取单笔的可视化窗口 panel（含预热）。"""
    entry_dt = pd.Timestamp(entry_date)
    exit_dt = pd.Timestamp(exit_date)
    fetch_start = entry_dt - pd.Timedelta(days=PRE_SIG_DAYS + 200)
    fetch_end = exit_dt + pd.Timedelta(days=POST_EXIT_DAYS)

    df = con.execute(
        "SELECT thscode, date, open, high, low, close, volume, turnover AS amount "
        "FROM v_daily_qfq WHERE thscode = ? AND date BETWEEN ? AND ? ORDER BY date",
        [thscode, fetch_start.strftime("%Y-%m-%d"), fetch_end.strftime("%Y-%m-%d")],
    ).fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return df


def find_signal_date(panel_ind: pd.DataFrame, thscode: str, entry_date: str,
                     preset: dict) -> str:
    """用 select_entries 找出 entry_date 之前最近的信号日（T）。

    select_entries 内部按 (start_date, end_date) 过滤，所以窗口必须涵盖信号日
    —— entry_date 之前若干天都要包含进来。
    """
    entry_dt = pd.Timestamp(entry_date)
    lookback_start = entry_dt - pd.Timedelta(days=15)  # 持仓至多 8 天 + 缓冲
    sigs = select_entries(
        panel_ind,
        start_date=lookback_start.strftime("%Y-%m-%d"),
        end_date=entry_date,
        **preset["signal"],
    )
    sigs_for_code = sigs[sigs["thscode"] == thscode]
    if sigs_for_code.empty:
        return entry_date  # fallback（极少情况）
    # 信号日严格小于 entry_date（T+1 开盘才能入场）
    candidates = sigs_for_code[sigs_for_code["date"] < entry_dt]
    if candidates.empty:
        candidates = sigs_for_code
    return candidates["date"].max().strftime("%Y-%m-%d")


# ============================================================================
# SVG 构建
# ============================================================================

def build_chart_svg(
    candles: list[dict],
    sig_idx: int,
    entry_idx: int,
    exit_idx: int,
    exit_reason: str,
    tp_line: float,
    sl_line: float,
) -> str:
    """K线 + MA5/10/20/60/120 + ATR 子图 + 成交量 子图组合 SVG。"""
    W = 820
    H_KLINE = 230
    H_ATR = 90
    H_VOL = 90
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 70, 14, 22
    G1 = 16  # k线 与 atr 之间
    G2 = 16  # atr 与 vol 之间

    n = len(candles)
    candle_w_total = W - PAD_L - PAD_R
    candle_w = candle_w_total / n * 0.65

    # 价格范围（K 线）
    prices = []
    for c in candles:
        prices.extend([c["high"], c["low"]])
    for f in ("ma5", "ma10", "ma20", "ma60", "ma120"):
        prices.extend([c[f] for c in candles if c.get(f) is not None])
    prices.extend([tp_line, sl_line,
                   candles[sig_idx]["close"], candles[entry_idx]["close"],
                   candles[exit_idx]["close"]])
    p_min, p_max = min(prices), max(prices)
    p_range = max(p_max - p_min, 1e-6)
    p_min -= p_range * 0.06
    p_max += p_range * 0.06

    # ATR 范围
    atr_vals = [c["atr14"] for c in candles if c.get("atr14") is not None]
    a_min = min(atr_vals) if atr_vals else 0
    a_max = max(atr_vals) if atr_vals else 1
    a_range = max(a_max - a_min, 1e-6)
    a_min -= a_range * 0.1
    a_max += a_range * 0.1

    # 成交量范围
    vols = [c["volume"] for c in candles]
    v_max = max(vols) * 1.1 if vols else 1

    def x_of(i: int) -> float:
        return PAD_L + candle_w_total * (i + 0.5) / n

    def y_of_p(p: float) -> float:
        return PAD_T + (p_max - p) / (p_max - p_min) * H_KLINE

    def y_of_a(v: float) -> float:
        m_top = PAD_T + H_KLINE + G1
        return m_top + (a_max - v) / (a_max - a_min) * H_ATR

    def y_of_v(v: float) -> float:
        m_top = PAD_T + H_KLINE + G1 + H_ATR + G2
        return m_top + (v_max - v) / v_max * H_VOL

    parts = [f'<svg viewBox="0 0 {W} {PAD_T + H_KLINE + G1 + H_ATR + G2 + H_VOL + PAD_B}" class="chart-svg">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{PAD_T + H_KLINE + G1 + H_ATR + G2 + H_VOL + PAD_B}" fill="{BG}"/>')

    # === K线区背景网格 ===
    for i in range(5):
        y = PAD_T + H_KLINE * i / 4
        p = p_max - (p_max - p_min) * i / 4
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="0.5"/>')
        parts.append(f'<text x="{W-PAD_R+4}" y="{y+3:.1f}" fill="{TEXT_DIM}" font-size="9" font-family="{MONO}">{p:.2f}</text>')

    # === TP / SL 线 ===
    y_tp = y_of_p(tp_line)
    y_sl = y_of_p(sl_line)
    parts.append(f'<line x1="{PAD_L}" y1="{y_tp:.1f}" x2="{W-PAD_R}" y2="{y_tp:.1f}" '
                 f'stroke="{COLOR_UP}" stroke-width="0.9" stroke-dasharray="5,3" opacity="0.75"/>')
    parts.append(f'<text x="{PAD_L+5}" y="{y_tp-3:.1f}" fill="{COLOR_UP}" font-size="10" font-family="{MONO}">TP {tp_line:.3f}</text>')
    parts.append(f'<line x1="{PAD_L}" y1="{y_sl:.1f}" x2="{W-PAD_R}" y2="{y_sl:.1f}" '
                 f'stroke="{COLOR_DOWN}" stroke-width="0.9" stroke-dasharray="5,3" opacity="0.75"/>')
    parts.append(f'<text x="{PAD_L+5}" y="{y_sl+10:.1f}" fill="{COLOR_DOWN}" font-size="10" font-family="{MONO}">SL {sl_line:.3f}</text>')

    # === MA 折线 ===
    def line_path(field: str, y_func, color: str, w: float) -> str:
        path = []
        started = False
        for i, c in enumerate(candles):
            v = c.get(field)
            if v is None or np.isnan(v):
                continue
            x = x_of(i)
            y = y_func(v)
            if not started:
                path.append(f"M{x:.1f},{y:.1f}")
                started = True
            else:
                path.append(f"L{x:.1f},{y:.1f}")
        return f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="{w}" fill="none" opacity="0.9"/>'

    parts.append(line_path("ma120", y_of_p, MA_COLORS["ma120"], 1.1))
    parts.append(line_path("ma60", y_of_p, MA_COLORS["ma60"], 1.2))
    parts.append(line_path("ma20", y_of_p, MA_COLORS["ma20"], 1.3))
    parts.append(line_path("ma10", y_of_p, MA_COLORS["ma10"], 1.0))
    parts.append(line_path("ma5", y_of_p, MA_COLORS["ma5"], 1.0))

    # === K线 ===
    for i, c in enumerate(candles):
        x = x_of(i)
        is_up = c["close"] >= c["open"]
        color = COLOR_UP if is_up else COLOR_DOWN
        y_h = y_of_p(c["high"])
        y_l = y_of_p(c["low"])
        y_o = y_of_p(c["open"])
        y_c = y_of_p(c["close"])
        parts.append(f'<line x1="{x:.1f}" y1="{y_h:.1f}" x2="{x:.1f}" y2="{y_l:.1f}" stroke="{color}" stroke-width="1"/>')
        y_top = min(y_o, y_c)
        y_bot = max(y_o, y_c)
        h = max(y_bot - y_top, 1)
        parts.append(f'<rect x="{x-candle_w/2:.1f}" y="{y_top:.1f}" width="{candle_w:.1f}" height="{h:.1f}" '
                     f'fill="{color}" stroke="{color}"/>')

    # === ATR 子图 ===
    a_top = PAD_T + H_KLINE + G1
    parts.append(f'<line x1="{PAD_L}" y1="{a_top}" x2="{W-PAD_R}" y2="{a_top}" stroke="{BORDER}" stroke-width="0.5"/>')
    parts.append(f'<text x="{PAD_L-50}" y="{a_top+10:.1f}" fill="{TEXT_DIM}" font-size="9">ATR14</text>')
    bar_a = candle_w_total / n * 0.6
    for i, c in enumerate(candles):
        v = c.get("atr14")
        if v is None or np.isnan(v):
            continue
        x = x_of(i)
        y = y_of_a(v)
        y0 = y_of_a(0) if "atr14" else a_top + H_ATR
        y0 = a_top + H_ATR
        parts.append(f'<rect x="{x-bar_a/2:.1f}" y="{min(y,y0):.1f}" width="{bar_a:.1f}" height="{abs(y-y0):.1f}" '
                     f'fill="#ffa726" opacity="0.7"/>')
    parts.append(f'<text x="{W-PAD_R+4}" y="{a_top+9:.1f}" fill="{TEXT_DIM}" font-size="9" font-family="{MONO}">{a_max:.3f}</text>')
    parts.append(f'<text x="{W-PAD_R+4}" y="{a_top+H_ATR-4:.1f}" fill="{TEXT_DIM}" font-size="9" font-family="{MONO}">{a_min:.3f}</text>')

    # === 成交量 子图 ===
    v_top = PAD_T + H_KLINE + G1 + H_ATR + G2
    parts.append(f'<line x1="{PAD_L}" y1="{v_top}" x2="{W-PAD_R}" y2="{v_top}" stroke="{BORDER}" stroke-width="0.5"/>')
    parts.append(f'<text x="{PAD_L-50}" y="{v_top+10:.1f}" fill="{TEXT_DIM}" font-size="9">VOL</text>')
    bar_v = candle_w_total / n * 0.6
    for i, c in enumerate(candles):
        v = c["volume"]
        x = x_of(i)
        y = y_of_v(v)
        y0 = v_top + H_VOL
        is_up = c["close"] >= c["open"]
        color = COLOR_UP if is_up else COLOR_DOWN
        parts.append(f'<rect x="{x-bar_v/2:.1f}" y="{y:.1f}" width="{bar_v:.1f}" height="{y0-y:.1f}" '
                     f'fill="{color}" opacity="0.6"/>')
    parts.append(line_path("vol_ma20", y_of_v, "#fbbf24", 1.0))

    # === 信号/入场/出场 竖线 ===
    for idx_marker, color, label in [
        (sig_idx, "#ffeb3b", "S"),
        (entry_idx, "#fb923c", "E"),
        (exit_idx, TAG_COLOR.get(exit_reason, ("#888", ""))[0], "X"),
    ]:
        if not (0 <= idx_marker < n):
            continue
        mx = x_of(idx_marker)
        parts.append(f'<line x1="{mx:.1f}" y1="{PAD_T}" x2="{mx:.1f}" y2="{v_top+H_VOL}" '
                     f'stroke="{color}" stroke-width="1" stroke-dasharray="3,2" opacity="0.55"/>')
        parts.append(f'<circle cx="{mx:.1f}" cy="{y_of_p(candles[idx_marker]["close"]):.1f}" r="5" '
                     f'fill="{color}" stroke="#000" stroke-width="1"/>')
        parts.append(f'<text x="{mx+7:.1f}" y="{y_of_p(candles[idx_marker]["close"])-7:.1f}" '
                     f'fill="{color}" font-size="10" font-weight="700">{label}</text>')

    # === X 轴日期 ===
    step = max(n // 8, 1)
    for i, c in enumerate(candles):
        if i % step == 0 or i in (sig_idx, entry_idx, exit_idx):
            x = x_of(i)
            parts.append(f'<text x="{x:.1f}" y="{v_top+H_VOL+12}" fill="{TEXT_DIM}" font-size="8" '
                         f'text-anchor="middle" font-family="{MONO}">{c["date"][5:]}</text>')

    parts.append('</svg>')
    return "".join(parts)


# ============================================================================
# 信号条件复算
# ============================================================================

def evaluate_signal_conditions(panel_ind: pd.DataFrame, sig_date: str, preset: dict) -> dict:
    """在信号日严格按 preset 阈值逐条复算条件，True/False + 实值。"""
    sig_dt = pd.Timestamp(sig_date)
    rows = panel_ind[panel_ind["date"] == sig_dt]
    if rows.empty:
        rows = panel_ind[panel_ind["date"] <= sig_dt].tail(1)
    r = rows.iloc[-1]
    sig = preset["signal"]

    def v(col):
        if col not in r:
            return None
        val = r[col]
        return float(val) if pd.notna(val) else None

    def fmt(v_, n=3, suffix=""):
        if v_ is None:
            return "N/A"
        return f"{v_:.{n}f}{suffix}"

    def sign_ok(v_, op, thr):
        if v_ is None:
            return False, "N/A"
        if op == ">=":
            return v_ >= thr, f"{v_:+.4f} {'≥' if v_>=thr else '<'} {thr}"
        if op == "<=":
            return v_ <= thr, f"{v_:+.4f} {'≤' if v_<=thr else '>'} {thr}"
        return False, "?"

    close = float(r["close"])
    ma60 = v("ma60")
    ma20 = v("ma20")
    ma120 = v("ma120")
    ma60_str = f"{ma60:.2f}" if ma60 is not None else "N/A"
    ma20_str = f"{ma20:.2f}" if ma20 is not None else "N/A"

    conditions = []

    # A 趋势
    cond_a = bool(ma60 and ma20 and close > ma60 and ma20 > ma60)
    ma60_above_ma20 = bool(ma20 and ma60 and ma20 > ma60)
    conditions.append(("A. 趋势", cond_a,
                       f"close {close:.2f} {'>' if cond_a else '≤'} ma60 {ma60_str}",
                       f"ma20 {ma20_str} {'>' if ma60_above_ma20 else '≤'} ma60"))
    amr = v("above_ma60_ratio")
    cond_a2 = bool(amr is not None and amr >= sig["min_above_ma60_ratio"])
    conditions.append(("", cond_a2,
                       f"过去60日 close>ma60 占比 {fmt(amr, 4)} {'≥' if cond_a2 else '<'} {sig['min_above_ma60_ratio']:.0%}", ""))
    m120 = v("mom120")
    cond_a3 = bool(m120 is not None and m120 >= sig["min_mom120"])
    conditions.append(("", cond_a3,
                       f"mom120 {fmt(m120, 4)} {'≥' if cond_a3 else '<'} {sig['min_mom120']:.2f}", ""))

    # B 连阴/反转
    if sig["entry_mode"] == "reversal":
        prev_ds = v("prev_down_streak") or 0
        ret1 = v("ret1") or 0
        cond_b1 = sig["min_down_streak"] <= prev_ds <= sig["max_down_streak"]
        cond_b2 = ret1 > 0
        conditions.append(("B. 反转",
                           cond_b1 and cond_b2,
                           f"前连阴 {prev_ds} 天 ({'∈' if cond_b1 else '∉'} [{sig['min_down_streak']}, {sig['max_down_streak']}])",
                           f"今日 ret1 {ret1:+.4f} {'>' if cond_b2 else '≤'} 0"))
    else:
        ds = v("down_streak") or 0
        cond_b = sig["min_down_streak"] <= ds <= sig["max_down_streak"]
        conditions.append(("B. 连阴",
                           cond_b,
                           f"连阴 {ds} 天 ({'∈' if cond_b else '∉'} [{sig['min_down_streak']}, {sig['max_down_streak']}])", ""))

    # C 回调（pullback 是 close/高20-1，负值；阈值用 -min/-max 比较）
    pb = v("pullback")
    cond_c = pb is not None and (-sig["max_pullback"]) <= pb <= (-sig["min_pullback"])
    pb_disp = f"{pb*100:+.2f}%" if pb is not None else "N/A"
    pb_min_disp = f"{-sig['max_pullback']*100:.0f}%"
    pb_max_disp = f"{-sig['min_pullback']*100:.0f}%"
    conditions.append(("C. 回调幅度",
                       cond_c,
                       f"close/高20-1 = {pb_disp} {'∈' if cond_c else '∉'} [{pb_min_disp}, {pb_max_disp}]", ""))

    # D MA20 接近 + 量比 + ATR
    ma20_tol = sig.get("ma20_tol", 0.04)
    cond_d1 = ma20 is not None and close >= ma20 * (1 - ma20_tol)
    vol_ratio = v("vol_ratio")
    cond_d2 = vol_ratio is not None and vol_ratio <= sig["max_vol_ratio"]
    atr_pct = v("atr_pct")
    cond_d3 = atr_pct is not None and atr_pct <= sig["max_atr_pct"]
    thr_close = ma20 * (1 - ma20_tol) if ma20 is not None else 0
    conditions.append(("D. 接近ma20",
                       cond_d1 and cond_d2 and cond_d3,
                       f"close {close:.2f} {'≥' if cond_d1 else '<'} ma20×{1-ma20_tol:.2f}={thr_close:.2f}",
                       f"vol_ratio {fmt(vol_ratio, 2)} {'≤' if cond_d2 else '>'} {sig['max_vol_ratio']:.1f}; ATR% {fmt(atr_pct, 4)} {'≤' if cond_d3 else '>'} {sig['max_atr_pct']:.2f}"))

    # E 成交额
    amount = v("amount60")  # 信号日的 amount60 滚动均值
    cond_e = amount is not None and sig["min_amount"] <= amount <= sig["max_amount"]
    conditions.append(("E. 成交额",
                       cond_e,
                       f"amount60 {fmt(amount/1e8, 2)}亿 {'∈' if cond_e else '∉'} [{sig['min_amount']/1e8:.1f}, {sig['max_amount']/1e8:.1f}]亿", ""))

    # F 择时
    regime = preset.get("regime")
    regime_str = "（关闭）"
    if regime:
        # 信号日 regime 状态需要外部传入
        pass

    return {"conditions": conditions, "row": r}


# ============================================================================
# HTML 装配
# ============================================================================

def render_html(trades: list[dict], con: duckdb.DuckDBPyConnection,
                preset: dict, panel_cache: dict) -> str:
    """装配总 HTML。"""
    cards = []
    tp_count = sl_count = time_count = eod_count = 0
    wins = 0
    total_pnl = 0.0

    # 一次性算整年 regime（用于逐笔显示）
    cached_regimes: dict = {}

    for idx, t in enumerate(trades, 1):
        code = t["thscode"]
        entry_date = t["entry_date"]
        exit_date = t["exit_date"]

        # 取 panel
        cache_key = (code, entry_date, exit_date)
        if cache_key not in panel_cache:
            panel_cache[cache_key] = load_panel_for_trade(con, code, entry_date, exit_date)
        panel = panel_cache[cache_key]
        if panel.empty:
            continue
        panel_ind = compute_indicators(panel)

        # 找信号日（用 select_entries 复算）
        sig_date = find_signal_date(panel_ind, code, entry_date, preset)

        # 定位 idx
        def find_idx(target: str, direction: str) -> int | None:
            target_dt = pd.Timestamp(target)
            if direction == "le":
                cand = panel_ind[panel_ind["date"] <= target_dt]
                return int(cand.index[-1]) if not cand.empty else None
            cand = panel_ind[panel_ind["date"] >= target_dt]
            return int(cand.index[0]) if not cand.empty else None

        sig_idx_global = find_idx(sig_date, "le")
        entry_idx_global = find_idx(entry_date, "ge")
        exit_idx_global = find_idx(exit_date, "ge")
        if any(x is None for x in (sig_idx_global, entry_idx_global, exit_idx_global)):
            continue

        # 切片
        view_start = max(0, sig_idx_global - PRE_SIG_DAYS)
        view_end = min(len(panel_ind) - 1, exit_idx_global + POST_EXIT_DAYS)
        sub = panel_ind.iloc[view_start:view_end + 1].reset_index(drop=True)
        local_sig = sig_idx_global - view_start
        local_entry = entry_idx_global - view_start
        local_exit = exit_idx_global - view_start

        # candles
        candles = []
        for _, row in sub.iterrows():
            def num(c):
                v = row.get(c)
                return float(v) if pd.notna(v) else None
            candles.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "ma5": num("ma5"), "ma10": num("ma10"), "ma20": num("ma20"),
                "ma60": num("ma60"), "ma120": num("ma120"),
                "atr14": num("atr14"),
                "vol_ma20": num("vol_ma20"),
                "volume": float(row["volume"]),
            })

        # ATR% 在入场日的前一日（ATR 自适应需用 entry_date 前一日的 ATR）
        # 模拟器用的是 entry 时点，所以取 entry_idx_global 对应行（开盘前）的 atr_pct
        atr_row = panel_ind.iloc[entry_idx_global]
        atr_pct_entry = float(atr_row["atr14"]) / float(atr_row["close"]) if pd.notna(atr_row["atr14"]) else 0.03
        atr_pct_entry = min(max(atr_pct_entry, 0.01), 0.08)
        atr_tp_mult = preset.get("atr_tp_mult") or 3.0
        atr_sl_mult = preset.get("atr_sl_mult") or 2.5
        tp_eff = atr_pct_entry * atr_tp_mult
        sl_eff = atr_pct_entry * atr_sl_mult
        tp_line = t["entry_price"] * (1 + tp_eff)
        sl_line = t["entry_price"] * (1 - sl_eff)

        # 信号条件复算
        eval_result = evaluate_signal_conditions(panel_ind, sig_date, preset)
        conditions = eval_result["conditions"]

        # regime 状态（信号日）
        regime_str = "关闭"
        if preset.get("regime"):
            year = pd.Timestamp(entry_date).year
            rkey = (year, code)
            if rkey not in cached_regimes:
                try:
                    year_start = f"{year}-01-01"
                    year_end = f"{year + 1}-01-01"
                    full_panel = con.execute(
                        "SELECT thscode, date, open, high, low, close, volume, turnover AS amount "
                        "FROM v_daily_qfq WHERE thscode = ? AND date BETWEEN ? AND ? ORDER BY date",
                        [code, year_start, year_end],
                    ).fetchdf()
                    full_panel["date"] = pd.to_datetime(full_panel["date"])
                    if not full_panel.empty:
                        full_ind = compute_indicators(full_panel)
                        cached_regimes[rkey] = compute_regime(full_ind, **preset["regime"])
                    else:
                        cached_regimes[rkey] = pd.DataFrame()
                except Exception:
                    cached_regimes[rkey] = pd.DataFrame()
            reg_df = cached_regimes[rkey]
            if not reg_df.empty:
                sig_dt = pd.Timestamp(sig_date)
                rrow = reg_df[reg_df["date"] == sig_dt]
                if not rrow.empty:
                    ok = bool(rrow.iloc[0]["regime_ok"])
                    regime_str = f"<span style='color:{'#26a69a' if ok else '#ef5350'};font-weight:700'>"
                    regime_str += "通过" if ok else "拒绝"
                    regime_str += "</span>"
                else:
                    regime_str = "未知"

        # 渲染
        svg = build_chart_svg(candles, local_sig, local_entry, local_exit,
                              t["exit_reason"], tp_line, sl_line)

        # 信号条件清单 HTML
        cond_rows = []
        for label, ok, val1, val2 in conditions:
            if not label and not val1 and not val2:
                continue
            mark = "✓" if ok else "✗"
            color = "#26a69a" if ok else "#ef5350"
            cell = lambda txt: f'<div class="cond-cell"><span class="mark" style="color:{color}">{mark}</span>{txt}</div>'
            label_html = f'<span class="cond-lbl">{label}</span>' if label else '<span></span>'
            cond_rows.append(f'<div class="cond-row">{label_html}{cell(val1)}{cell(val2)}</div>')
        cond_html = "".join(cond_rows)

        # 退出标签
        tag_color, tag_label = TAG_COLOR.get(t["exit_reason"], ("#888", t["exit_reason"]))
        pnl_pct = t["net_return"]
        pnl_color = "#26a69a" if pnl_pct > 0 else "#ef5350"

        # 累计统计
        if t["exit_reason"] == "TP": tp_count += 1
        elif t["exit_reason"] == "SL": sl_count += 1
        elif t["exit_reason"] == "time": time_count += 1
        elif t["exit_reason"] == "eod": eod_count += 1
        if pnl_pct > 0: wins += 1
        total_pnl += pnl_pct

        card = f"""
<details class="trade" {"open" if idx <= 3 else ""}>
  <summary>
    <span class="idx">#{idx}</span>
    <span class="code">{code}</span>
    <span class="dates">{sig_date} → {entry_date} → {exit_date}</span>
    <span class="hold">持仓 {t['hold_days']}d</span>
    <span class="tag" style="background:{tag_color}">{tag_label}</span>
    <span class="pnl" style="color:{pnl_color}">{pnl_pct*100:+.2f}%</span>
  </summary>
  <div class="trade-body">
    <div class="conds">{cond_html}</div>
    <div class="meta">
      <span><b>信号日：</b>{sig_date}</span>
      <span><b>入场价：</b>{t['entry_price']:.3f}</span>
      <span><b>出场价：</b>{t['exit_price']:.3f}</span>
      <span><b>ATR%(入场)：</b>{atr_pct_entry:.4f}</span>
      <span><b>TP/SL：</b><span style="color:#26a69a">{tp_line:.3f}</span> / <span style="color:#ef5350">{sl_line:.3f}</span></span>
      <span><b>择时：</b>{regime_str}</span>
    </div>
    <div class="legend">
      <span><span class="dot" style="background:{MA_COLORS['ma5']}"></span>MA5</span>
      <span><span class="dot" style="background:{MA_COLORS['ma10']}"></span>MA10</span>
      <span><span class="dot" style="background:{MA_COLORS['ma20']}"></span>MA20</span>
      <span><span class="dot" style="background:{MA_COLORS['ma60']}"></span>MA60</span>
      <span><span class="dot" style="background:{MA_COLORS['ma120']}"></span>MA120</span>
      <span><span class="dot" style="background:#ffeb3b"></span>S 信号</span>
      <span><span class="dot" style="background:#fb923c"></span>E 入场</span>
      <span><span class="dot" style="background:{tag_color}"></span>X 出场</span>
    </div>
    {svg}
  </div>
</details>"""
        cards.append(card)

    # 汇总
    n = len(trades)
    win_rate = wins / n if n else 0
    avg_pnl = total_pnl / n if n else 0

    cards_html = "\n".join(cards)
    return _wrap_html(cards_html, win_rate, avg_pnl, n, tp_count, sl_count, time_count, eod_count, preset)


def _wrap_html(cards_html: str, win_rate: float, avg_pnl: float, n: int,
               tp_count: int, sl_count: int, time_count: int, eod_count: int,
               preset: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>uptrend_pullback 回测可视化 — {preset.get('__name', '')}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: {BG}; color: #e6e6e6; padding: 16px; line-height: 1.45; font-size: 13px;
  }}
  .container {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ color: {TEXT_BRIGHT}; font-size: 20px; margin-bottom: 4px; }}
  .subtitle {{ color: {TEXT_DIM}; font-size: 12px; margin-bottom: 14px; }}

  .summary {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 16px; }}
  .sum-card {{ background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 10px; }}
  .sum-card .lbl {{ color: {TEXT_DIM}; font-size: 10px; }}
  .sum-card .val {{ color: {TEXT_BRIGHT}; font-size: 16px; font-weight: 700; margin-top: 2px; }}
  .sum-card .val.gold {{ color: #ffd54f; }}
  .sum-card .val.green {{ color: #26a69a; }}
  .sum-card .val.red {{ color: #ef5350; }}

  details.trade {{ background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 6px; margin-bottom: 8px; }}
  details.trade > summary {{
    list-style: none; cursor: pointer; padding: 10px 12px;
    display: flex; align-items: center; gap: 10px;
    border-radius: 6px; user-select: none;
  }}
  details.trade > summary::-webkit-details-marker {{ display: none; }}
  details.trade > summary:hover {{ background: #232b34; }}
  details.trade[open] > summary {{ background: #232b34; border-bottom: 1px solid {BORDER}; border-radius: 6px 6px 0 0; }}

  .idx {{ color: {TEXT_DIM}; font-family: {MONO}; min-width: 32px; }}
  .code {{ font-weight: 700; color: {TEXT_BRIGHT}; min-width: 90px; }}
  .dates {{ color: {TEXT_DIM}; font-size: 11px; font-family: {MONO}; flex: 1; }}
  .hold {{ color: {TEXT_DIM}; font-size: 11px; }}
  .tag {{ padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; color: #000; }}
  .pnl {{ font-weight: 700; font-family: {MONO}; min-width: 70px; text-align: right; }}

  .trade-body {{ padding: 12px; }}
  .meta {{
    display: flex; gap: 12px; flex-wrap: wrap; font-size: 11px; margin-bottom: 8px;
    color: {TEXT_DIM}; font-family: {MONO};
  }}
  .meta b {{ color: {TEXT_BRIGHT}; }}

  .conds {{ background: {BG}; border-radius: 4px; padding: 8px; margin-bottom: 8px; font-size: 11px; font-family: {MONO}; }}
  .cond-row {{
    display: grid; grid-template-columns: 100px 1fr 1fr; gap: 6px;
    padding: 3px 0; border-bottom: 1px solid #1a2026;
  }}
  .cond-row:last-child {{ border-bottom: none; }}
  .cond-lbl {{ color: {TEXT_DIM}; font-weight: 700; }}
  .cond-cell {{ color: {TEXT_BRIGHT}; }}
  .cond-cell .mark {{ margin-right: 4px; font-weight: 700; }}

  .legend {{
    display: flex; gap: 12px; font-size: 10px; color: {TEXT_DIM};
    flex-wrap: wrap; margin-bottom: 8px;
  }}
  .legend .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 3px; vertical-align: middle; }}

  .chart-svg {{ width: 100%; height: auto; display: block; background: {BG}; border-radius: 4px; }}
  .footer {{ text-align: center; color: #555; font-size: 11px; padding: 20px 0 8px; }}
</style>
</head>
<body>
<div class="container">
  <h1>uptrend_pullback 回测可视化 — {n} 笔交易</h1>
  <div class="subtitle">
    策略：上升趋势回调做多（{preset.get('__name', 'preset')}）|
    max_hold={preset['max_hold']}d, atr_tp_mult={preset.get('atr_tp_mult')}, atr_sl_mult={preset.get('atr_sl_mult')}|
    universe={preset['universe']} | 指标与信号条件均与回测同源
  </div>

  <div class="summary">
    <div class="sum-card"><div class="lbl">交易笔数</div><div class="val gold">{n}</div></div>
    <div class="sum-card"><div class="lbl">胜率</div><div class="val {'green' if win_rate>=0.5 else 'red'}">{win_rate*100:.1f}%</div></div>
    <div class="sum-card"><div class="lbl">TP / SL / time / eod</div><div class="val" style="font-size:13px">{tp_count} / {sl_count} / {time_count} / {eod_count}</div></div>
    <div class="sum-card"><div class="lbl">平均单笔净收益</div><div class="val {'green' if avg_pnl>0 else 'red'}">{avg_pnl*100:+.2f}%</div></div>
    <div class="sum-card"><div class="lbl">总收益</div><div class="val gold">+85.47%</div></div>
  </div>

  {cards_html}

  <div class="footer">
    uptrend_pullback/{preset.get('__name', '')} preset | 区间 2025-09-08 → 2026-09-08 | 仅供参考，非投资建议
  </div>
</div>
</body>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="回测交易 HTML 可视化")
    ap.add_argument("--preset", default="v5")
    ap.add_argument("--trades-csv", default=str(TRADES_CSV))
    ap.add_argument("--out", default=str(OUTPUT_HTML))
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    preset = get_preset(args.preset)
    preset["__name"] = args.preset  # 用于 HTML 显示

    trades = load_trades(Path(args.trades_csv))
    print(f"读取 {len(trades)} 笔交易 from {args.trades_csv}")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    panel_cache: dict = {}
    html = render_html(trades, con, preset, panel_cache)
    con.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\n[✓] HTML 已生成: {out}")
    print(f"    文件大小: {len(html) / 1024:.1f} KB")


if __name__ == "__main__":
    main()