"""39 笔回测交易 → HTML 可视化 (信号详情 + K线 + MACD)。

数据源: short_reversal/results/backtest.json (主回测产物)
窗口: 每笔信号日 -30 天 → 出场日 +5 天 (含入场前预热 + 完整持仓 + 缓冲)
指标: signals.compute_panel_indicators (与回测严格同源)

输出: short_reversal/results/trades_visualization.html
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from short_reversal.signals import compute_panel_indicators

DB_PATH = Path("/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb")
RESULTS_DIR = Path(__file__).parent / "results"
BACKTEST_JSON = RESULTS_DIR / "backtest.json"
OUTPUT_HTML = RESULTS_DIR / "trades_visualization.html"

# 窗口参数
PRE_SIG_DAYS = 30  # 信号日前看多少天 (含 MA60 预热)
POST_EXIT_DAYS = 5  # 出场日后看多少天

# 持仓颜色
TAG_COLOR = {
    "TP": ("#26a69a", "止盈"),
    "SL": ("#ef5350", "止损"),
    "time": ("#ffa726", "时间出场"),
}


def build_chart_svg(
    candles: list[dict],
    sig_idx: int,
    entry_idx: int,
    exit_idx: int,
    exit_reason: str,
    tp_line: float,
    sl_line: float,
) -> str:
    """K线 + MA + MACD 组合 SVG.

    candles: list of {date, open, high, low, close, ma20, ma60, dif, dea, macd_bar}
    sig_idx: 信号日 (S 黄色)
    entry_idx: 入场日 (E 橙色)
    exit_idx: 出场日 (X 按 reason 颜色)
    """
    W = 760
    H_KLINE = 220
    H_MACD = 110
    PAD_L = 56
    PAD_R = 60
    PAD_T = 12
    PAD_B = 20
    CHART_GAP = 18

    candle_w_total = W - PAD_L - PAD_R
    n = len(candles)
    candle_w = candle_w_total / n * 0.7

    # 价格范围
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ma60_vals = [c["ma60"] for c in candles if c["ma60"] is not None]
    ma20_vals = [c["ma20"] for c in candles if c["ma20"] is not None]
    all_prices = highs + lows + ma60_vals + ma20_vals + [
        tp_line, sl_line, candles[sig_idx]["close"],
        candles[entry_idx]["close"], candles[exit_idx]["close"],
    ]
    p_min, p_max = min(all_prices), max(all_prices)
    p_range = p_max - p_min if p_max > p_min else 1.0
    p_min -= p_range * 0.06
    p_max += p_range * 0.06

    # MACD 范围
    dif_vals = [c["dif"] for c in candles if c["dif"] is not None]
    dea_vals = [c["dea"] for c in candles if c["dea"] is not None]
    bar_vals = [c["macd_bar"] for c in candles if c["macd_bar"] is not None]
    m_min = min(min(dif_vals), min(dea_vals), min(bar_vals))
    m_max = max(max(dif_vals), max(dea_vals), max(bar_vals))
    m_range = m_max - m_min if m_max > m_min else 1.0
    m_min -= m_range * 0.1
    m_max += m_range * 0.1

    def x_of(i: int) -> float:
        return PAD_L + candle_w_total * (i + 0.5) / n

    def y_of_price(p: float) -> float:
        return PAD_T + (p_max - p) / (p_max - p_min) * H_KLINE

    def y_of_macd(v: float) -> float:
        m_top = PAD_T + H_KLINE + CHART_GAP
        return m_top + (m_max - v) / (m_max - m_min) * H_MACD

    parts = [f'<rect x="0" y="0" width="{W}" height="{PAD_T + H_KLINE + CHART_GAP + H_MACD + PAD_B}" fill="#0f1419"/>']

    # ===== K线区背景网格 =====
    for i in range(5):
        y = PAD_T + H_KLINE * i / 4
        p = p_max - (p_max - p_min) * i / 4
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" stroke="#1f2933" stroke-width="0.5"/>')
        parts.append(f'<text x="{W-PAD_R+4}" y="{y+3:.1f}" fill="#666" font-size="9" font-family="monospace">{p:.2f}</text>')

    # ===== TP / SL 水平线 =====
    y_tp = y_of_price(tp_line)
    y_sl = y_of_price(sl_line)
    parts.append(f'<line x1="{PAD_L}" y1="{y_tp:.1f}" x2="{W-PAD_R}" y2="{y_tp:.1f}" '
                 f'stroke="#26a69a" stroke-width="0.8" stroke-dasharray="4,3" opacity="0.7"/>')
    parts.append(f'<text x="{PAD_L+4}" y="{y_tp-2:.1f}" fill="#26a69a" font-size="9">TP {tp_line:.2f}</text>')
    parts.append(f'<line x1="{PAD_L}" y1="{y_sl:.1f}" x2="{W-PAD_R}" y2="{y_sl:.1f}" '
                 f'stroke="#ef5350" stroke-width="0.8" stroke-dasharray="4,3" opacity="0.7"/>')
    parts.append(f'<text x="{PAD_L+4}" y="{y_sl+10:.1f}" fill="#ef5350" font-size="9">SL {sl_line:.2f}</text>')

    # ===== MA 折线 =====
    def line_path(field: str, y_func, color: str, w: float) -> str:
        path = []
        started = False
        for i, c in enumerate(candles):
            v = c[field]
            if v is None:
                continue
            x = x_of(i)
            y = y_func(v)
            if not started:
                path.append(f"M{x:.1f},{y:.1f}")
                started = True
            else:
                path.append(f"L{x:.1f},{y:.1f}")
        return f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="{w}" fill="none" opacity="0.85"/>'

    parts.append(line_path("ma60", y_of_price, "#ffa726", 1.5))
    parts.append(line_path("ma20", y_of_price, "#42a5f5", 1.2))

    # ===== K线 =====
    for i, c in enumerate(candles):
        x = x_of(i)
        is_up = c["close"] >= c["open"]
        color = "#26a69a" if is_up else "#ef5350"
        y_h = y_of_price(c["high"])
        y_l = y_of_price(c["low"])
        y_o = y_of_price(c["open"])
        y_c = y_of_price(c["close"])
        parts.append(f'<line x1="{x:.1f}" y1="{y_h:.1f}" x2="{x:.1f}" y2="{y_l:.1f}" stroke="{color}" stroke-width="1"/>')
        y_top = min(y_o, y_c)
        y_bot = max(y_o, y_c)
        h = max(y_bot - y_top, 1)
        parts.append(f'<rect x="{x-candle_w/2:.1f}" y="{y_top:.1f}" width="{candle_w:.1f}" height="{h:.1f}" '
                     f'fill="{color}" stroke="{color}"/>')

    # ===== 入场日 E (橙色竖线 + 圆点) =====
    entry_x = x_of(entry_idx)
    parts.append(f'<line x1="{entry_x:.1f}" y1="{PAD_T}" x2="{entry_x:.1f}" y2="{PAD_T+H_KLINE}" '
                 f'stroke="#fb923c" stroke-width="1.2" stroke-dasharray="4,2" opacity="0.8"/>')
    parts.append(f'<circle cx="{entry_x:.1f}" cy="{y_of_price(candles[entry_idx]["close"]):.1f}" r="5" '
                 f'fill="#fb923c" stroke="#000" stroke-width="1"/>')
    parts.append(f'<text x="{entry_x+8:.1f}" y="{y_of_price(candles[entry_idx]["close"])-8:.1f}" '
                 f'fill="#fb923c" font-size="11" font-weight="700">E</text>')

    # ===== 信号日 S (黄色竖线 + 圆点, 在入场日之前; 若重叠则 S 在 E 之后画) =====
    if sig_idx != entry_idx:
        sig_x = x_of(sig_idx)
        parts.append(f'<line x1="{sig_x:.1f}" y1="{PAD_T}" x2="{sig_x:.1f}" y2="{PAD_T+H_KLINE}" '
                     f'stroke="#ffeb3b" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>')
        parts.append(f'<circle cx="{sig_x:.1f}" cy="{y_of_price(candles[sig_idx]["close"]):.1f}" r="4" '
                     f'fill="#ffeb3b" stroke="#000" stroke-width="1"/>')
        parts.append(f'<text x="{sig_x+7:.1f}" y="{y_of_price(candles[sig_idx]["close"])+12:.1f}" '
                     f'fill="#ffeb3b" font-size="10" font-weight="700">S</text>')

    # ===== 出场日 X (按 reason 颜色) =====
    if 0 <= exit_idx < n:
        exit_color, exit_label = TAG_COLOR.get(exit_reason, ("#888", exit_reason))
        exit_x = x_of(exit_idx)
        parts.append(f'<line x1="{exit_x:.1f}" y1="{PAD_T}" x2="{exit_x:.1f}" y2="{PAD_T+H_KLINE}" '
                     f'stroke="{exit_color}" stroke-width="1.2" stroke-dasharray="2,2" opacity="0.9"/>')
        parts.append(f'<circle cx="{exit_x:.1f}" cy="{y_of_price(candles[exit_idx]["close"]):.1f}" r="6" '
                     f'fill="{exit_color}" stroke="#000" stroke-width="1.2"/>')
        parts.append(f'<text x="{exit_x+9:.1f}" y="{y_of_price(candles[exit_idx]["close"])-9:.1f}" '
                     f'fill="{exit_color}" font-size="11" font-weight="700">X</text>')

    # ===== X 坐标日期 =====
    step = max(n // 10, 1)
    for i, c in enumerate(candles):
        if i % step == 0 or i == sig_idx or i == entry_idx or i == exit_idx:
            x = x_of(i)
            parts.append(f'<text x="{x:.1f}" y="{H_KLINE+PAD_T+12}" fill="#888" font-size="8" '
                         f'text-anchor="middle" font-family="monospace">{c["date"][5:]}</text>')

    # ===== MACD 区 =====
    m_top = PAD_T + H_KLINE + CHART_GAP
    parts.append(f'<line x1="{PAD_L}" y1="{m_top}" x2="{W-PAD_R}" y2="{m_top}" stroke="#2a3540" stroke-width="0.5"/>')
    y_zero = y_of_macd(0)
    parts.append(f'<line x1="{PAD_L}" y1="{y_zero:.1f}" x2="{W-PAD_R}" y2="{y_zero:.1f}" stroke="#444" stroke-width="0.5"/>')

    # 柱状
    bar_w = candle_w_total / n * 0.6
    for i, c in enumerate(candles):
        v = c["macd_bar"]
        if v is None:
            continue
        x = x_of(i)
        y = y_of_macd(v)
        y0 = y_of_macd(0)
        color = "#26a69a" if v >= 0 else "#ef5350"
        parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{min(y,y0):.1f}" width="{bar_w:.1f}" height="{abs(y-y0):.1f}" '
                     f'fill="{color}" opacity="0.7"/>')

    parts.append(line_path("dif", y_of_macd, "#42a5f5", 1.2))
    parts.append(line_path("dea", y_of_macd, "#ffa726", 1.2))

    # MACD 右侧数值
    for i, v in enumerate([m_max, (m_max + m_min) / 2, m_min]):
        if i == 0:
            y = m_top + 2
        elif i == 1:
            y = y_of_macd(v)
        else:
            y = m_top + H_MACD - 4
        parts.append(f'<text x="{W-PAD_R+4}" y="{y:.1f}" fill="#666" font-size="9" font-family="monospace">{v:.3f}</text>')

    # MACD 区信号/入场/出场竖线
    for idx_marker, color in [(sig_idx, "#ffeb3b"), (entry_idx, "#fb923c"), (exit_idx, TAG_COLOR.get(exit_reason, ("#888", ""))[0])]:
        if 0 <= idx_marker < n:
            mx = x_of(idx_marker)
            parts.append(f'<line x1="{mx:.1f}" y1="{m_top}" x2="{mx:.1f}" y2="{m_top+H_MACD}" '
                         f'stroke="{color}" stroke-width="0.8" stroke-dasharray="3,2" opacity="0.4"/>')

    return (
        f'<svg viewBox="0 0 {W} {PAD_T + H_KLINE + CHART_GAP + H_MACD + PAD_B}" '
        f'class="chart-svg">{"".join(parts)}</svg>'
    )


def load_panel_for_trade(con: duckdb.DuckDBPyConnection, thscode: str,
                         sig_date: str, entry_date: str, exit_date: str) -> pd.DataFrame:
    """拉取单笔交易的可视化窗口 panel (信号日 -30d → 出场日 +5d)。

    为保证指标完整, 额外向前取 100 天供 MA60 预热。
    """
    sig_dt = pd.Timestamp(sig_date)
    fetch_start = sig_dt - pd.Timedelta(days=PRE_SIG_DAYS + 100)
    fetch_end = pd.Timestamp(exit_date) + pd.Timedelta(days=POST_EXIT_DAYS)

    df = con.execute(
        "SELECT thscode, date, open, high, low, close, amount, volume "
        "FROM v_daily WHERE thscode = ? AND date BETWEEN ? AND ? ORDER BY date",
        [thscode, fetch_start.strftime("%Y-%m-%d"), fetch_end.strftime("%Y-%m-%d")],
    ).fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return df


def main() -> None:
    if not BACKTEST_JSON.exists():
        raise SystemExit(f"未找到 {BACKTEST_JSON}, 请先运行 python3 -m short_reversal.main")

    with BACKTEST_JSON.open() as f:
        backtest = json.load(f)

    trades = backtest["trades"]
    print(f"读取 {len(trades)} 笔交易")

    con = duckdb.connect(str(DB_PATH), read_only=True)

    cards = []
    tp_count = sl_count = time_count = 0
    total_pnl = 0.0

    for idx, t in enumerate(trades, 1):
        code = t["thscode"]
        entry_date = t["entry_date"]
        exit_date = t["exit_date"]
        entry_price = t["entry_price"]
        exit_price = t["exit_price"]
        exit_reason = t["exit_reason"]
        hold_days = t["hold_days"]

        # 做空 PnL: (entry - exit) / entry
        pnl_pct = (entry_price - exit_price) / entry_price
        total_pnl += pnl_pct
        if exit_reason == "TP":
            tp_count += 1
        elif exit_reason == "SL":
            sl_count += 1
        elif exit_reason == "time":
            time_count += 1

        # 找信号日: 经验上是 entry_date - 2 (T+2 奇偶)
        sig_date_est = (pd.Timestamp(entry_date) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        # 防止信号日超出 entry_date (持仓 0 天的情况)
        if pd.Timestamp(sig_date_est) >= pd.Timestamp(entry_date):
            sig_date_est = (pd.Timestamp(entry_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        panel = load_panel_for_trade(con, code, sig_date_est, entry_date, exit_date)
        if panel.empty:
            print(f"  [{idx}] {code} 数据缺失, 跳过")
            continue

        # 用新框架的 compute_panel_indicators 计算指标 (与回测一致)
        panel_ind = compute_panel_indicators(panel)

        # 找各关键日期在 panel_ind 中的位置 (允许 ±3 天窗口匹配, 应对周末/节假日)
        def find_idx(target_date_str: str, direction: str) -> int | None:
            target = pd.Timestamp(target_date_str)
            candidates = panel_ind[panel_ind["date"] <= target] if direction == "le" else \
                         panel_ind[panel_ind["date"] >= target]
            if direction == "le":
                if candidates.empty:
                    return None
                # 取最大的 ≤ target (最近过去的交易日)
                return int(candidates.index[-1])
            else:
                if candidates.empty:
                    return None
                return int(candidates.index[0])

        sig_idx = find_idx(sig_date_est, "le")
        entry_idx = find_idx(entry_date, "ge")
        exit_idx = find_idx(exit_date, "ge")

        if sig_idx is None or entry_idx is None or exit_idx is None:
            print(f"  [{idx}] {code} 关键日定位失败 (sig≈{sig_date_est}, entry={entry_date}, exit={exit_date})")
            continue

        # 取窗口面板: 信号日 -PRE_SIG_DAYS → 出场日 +POST_EXIT_DAYS
        view_start = max(0, sig_idx - PRE_SIG_DAYS)
        view_end = min(len(panel_ind) - 1, exit_idx + POST_EXIT_DAYS)
        sub = panel_ind.iloc[view_start:view_end + 1].reset_index(drop=True)
        local_sig = sig_idx - view_start
        local_entry = entry_idx - view_start
        local_exit = exit_idx - view_start

        # 提取蜡烛 + 指标
        candles = []
        for _, row in sub.iterrows():
            candles.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "ma20": float(row["ma20"]) if pd.notna(row["ma20"]) else None,
                "ma60": float(row["ma60"]) if pd.notna(row["ma60"]) else None,
                "dif": float(row["dif"]) if pd.notna(row["dif"]) else None,
                "dea": float(row["dea"]) if pd.notna(row["dea"]) else None,
                "macd_bar": float(row["macd_bar"]) if pd.notna(row["macd_bar"]) else None,
            })

        tp_line = entry_price * (1 - 0.06)  # 与回测一致
        sl_line = entry_price * (1 + 0.05)

        svg = build_chart_svg(
            candles, local_sig, local_entry, local_exit, exit_reason, tp_line, sl_line,
        )

        # 取信号日特征快照 (从 panel_ind 读 sig_* 字段)
        sig_row = panel_ind.iloc[sig_idx]
        sig_close = float(sig_row["close"])
        sig_ma60 = float(sig_row["ma60"]) if pd.notna(sig_row["ma60"]) else None
        sig_up_streak = int(sig_row["up_streak"])
        sig_pct_chg = float(sig_row["pct_chg"]) if pd.notna(sig_row["pct_chg"]) else 0.0
        sig_dif = float(sig_row["dif"]) if pd.notna(sig_row["dif"]) else 0.0
        sig_dea = float(sig_row["dea"]) if pd.notna(sig_row["dea"]) else 0.0
        sig_macd_bar = float(sig_row["macd_bar"]) if pd.notna(sig_row["macd_bar"]) else 0.0
        sig_am60 = float(sig_row["am60"]) if pd.notna(sig_row["am60"]) else 0.0

        tag_color, tag_label = TAG_COLOR.get(exit_reason, ("#888", exit_reason))
        pnl_color = "#26a69a" if pnl_pct > 0 else "#ef5350"
        macd_color = "#26a69a" if sig_dif > 0 and sig_dea > 0 else "#ef5350"
        sig_ma60_str = f"{sig_ma60:.2f}" if sig_ma60 else "N/A"
        is_open = idx <= 3

        card = f"""
<details class="trade" {"open" if is_open else ""}>
  <summary>
    <span class="idx">#{idx}</span>
    <span class="code">{code}</span>
    <span class="dates">{sig_date_est} → {entry_date} → {exit_date}</span>
    <span class="hold">持仓 {hold_days}d</span>
    <span class="tag" style="background:{tag_color}">{tag_label}</span>
    <span class="pnl" style="color:{pnl_color}">{pnl_pct*100:+.2f}%</span>
  </summary>
  <div class="trade-body">
    <div class="features">
      <div class="feat"><div class="lbl">A: close&lt;MA60</div><div class="val">{sig_close:.2f}<span class="op">&lt;</span>{sig_ma60_str}</div></div>
      <div class="feat"><div class="lbl">B: 连阳 [3,10]</div><div class="val">{sig_up_streak} 天</div></div>
      <div class="feat"><div class="lbl">C: pct_chg [2%,6%]</div><div class="val {pnl_color}">{sig_pct_chg*100:+.2f}%</div></div>
      <div class="feat"><div class="lbl">D: DIF&gt;0 &amp; DEA&gt;0 &amp; 柱缩小</div><div class="val {macd_color}">{sig_dif:+.3f}/{sig_dea:+.3f}</div></div>
      <div class="feat"><div class="lbl">DIF/DEA</div><div class="val">{sig_dif:+.4f}/{sig_dea:+.4f}</div></div>
      <div class="feat"><div class="lbl">E: am60 流动性</div><div class="val">{sig_am60/1e8:.2f} 亿</div></div>
      <div class="feat"><div class="lbl">入场价/出场价</div><div class="val">{entry_price:.2f} → {exit_price:.2f}</div></div>
      <div class="feat"><div class="lbl">盈亏 (做空)</div><div class="val {pnl_color}">{pnl_pct*100:+.2f}%</div></div>
    </div>
    <div class="legend">
      <div class="legend-item"><span class="legend-line" style="background:#26a69a"></span>TP {tp_line:.2f}</div>
      <div class="legend-item"><span class="legend-line" style="background:#ef5350"></span>SL {sl_line:.2f}</div>
      <div class="legend-item"><span class="legend-dot" style="background:#42a5f5"></span>MA20</div>
      <div class="legend-item"><span class="legend-line" style="background:#ffa726"></span>MA60</div>
      <div class="legend-item"><span class="legend-dot" style="background:#ffeb3b"></span>S 信号</div>
      <div class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>E 入场</div>
      <div class="legend-item"><span class="legend-dot" style="background:{tag_color}"></span>X 出场</div>
    </div>
    {svg}
  </div>
</details>"""
        cards.append(card)

    # 汇总
    win_rate = sum(1 for t in trades if (t["entry_price"] - t["exit_price"]) / t["entry_price"] > 0) / len(trades)
    avg_pnl = total_pnl / len(trades)

    cards_html = "\n".join(cards)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>v33 回测交易可视化 — 39 笔</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0f1419; color: #e6e6e6; padding: 16px; line-height: 1.45; font-size: 13px;
  }}
  .container {{ max-width: 820px; margin: 0 auto; }}
  h1 {{ color: #f5f5f5; font-size: 20px; margin-bottom: 6px; }}
  .subtitle {{ color: #888; font-size: 12px; margin-bottom: 16px; }}

  .summary {{
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 8px; margin-bottom: 16px;
  }}
  .sum-card {{
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px; padding: 10px;
  }}
  .sum-card .lbl {{ color: #888; font-size: 10px; }}
  .sum-card .val {{ color: #f5f5f5; font-size: 16px; font-weight: 700; margin-top: 2px; }}
  .sum-card .val.gold {{ color: #ffd54f; }}
  .sum-card .val.green {{ color: #26a69a; }}
  .sum-card .val.red {{ color: #ef5350; }}

  details.trade {{
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px; padding: 0; margin-bottom: 8px;
  }}
  details.trade > summary {{
    list-style: none; cursor: pointer; padding: 10px 12px;
    display: flex; align-items: center; gap: 10px;
    border-radius: 6px; user-select: none;
  }}
  details.trade > summary::-webkit-details-marker {{ display: none; }}
  details.trade > summary:hover {{ background: #232b34; }}
  details.trade[open] > summary {{ background: #232b34; border-bottom: 1px solid #2a3540; border-radius: 6px 6px 0 0; }}

  .idx {{ color: #888; font-family: monospace; min-width: 30px; }}
  .code {{ font-weight: 700; color: #f5f5f5; min-width: 90px; }}
  .dates {{ color: #888; font-size: 11px; font-family: monospace; flex: 1; }}
  .hold {{ color: #888; font-size: 11px; }}
  .tag {{
    padding: 2px 8px; border-radius: 3px;
    font-size: 11px; font-weight: 700; color: #000;
  }}
  .pnl {{ font-weight: 700; font-family: monospace; min-width: 70px; text-align: right; }}

  .trade-body {{ padding: 12px; }}
  .features {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 4px; margin-bottom: 8px; font-size: 10px;
  }}
  .feat {{ background: #0f1419; padding: 6px 8px; border-radius: 3px; }}
  .feat .lbl {{ color: #888; font-size: 9px; margin-bottom: 2px; }}
  .feat .val {{ color: #f5f5f5; font-size: 12px; font-weight: 600; font-family: monospace; }}
  .feat .val.green {{ color: #26a69a; }}
  .feat .val.red {{ color: #ef5350; }}
  .feat .op {{ color: #888; margin: 0 2px; }}

  .legend {{
    display: flex; gap: 12px; font-size: 10px; color: #888;
    flex-wrap: wrap; margin-bottom: 6px;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .legend-line {{ width: 14px; height: 2px; }}

  .chart-svg {{ width: 100%; height: auto; display: block; background: #0f1419; border-radius: 4px; }}

  .footer {{
    text-align: center; color: #555; font-size: 11px;
    padding: 20px 0 8px;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>v33_mainboard 回测 — 39 笔交易可视化</h1>
  <div class="subtitle">
    策略: 下跌趋势反弹做空 (v33 五条件) | TP=6% / SL=5% / Time=20d | 数据源: hithink-finance DuckDB |
    指标: signals.compute_panel_indicators (与回测同源)
  </div>

  <div class="summary">
    <div class="sum-card">
      <div class="lbl">交易笔数</div>
      <div class="val gold">{len(trades)}</div>
    </div>
    <div class="sum-card">
      <div class="lbl">胜率</div>
      <div class="val {('green' if win_rate >= 0.5 else 'red')}">{win_rate*100:.1f}%</div>
    </div>
    <div class="sum-card">
      <div class="lbl">TP / SL / Time</div>
      <div class="val" style="font-size:13px">{tp_count} / {sl_count} / {time_count}</div>
    </div>
    <div class="sum-card">
      <div class="lbl">平均单笔盈亏</div>
      <div class="val {('green' if avg_pnl > 0 else 'red')}">{avg_pnl*100:+.2f}%</div>
    </div>
    <div class="sum-card">
      <div class="lbl">最终资金</div>
      <div class="val {('green' if backtest['total_yield'] > 0 else 'red')}">¥{backtest['final_capital']:,.0f}</div>
    </div>
  </div>

  {cards_html}

  <div class="footer">
    v33_mainboard preset | 区间 {backtest['start']} → {backtest['end']} | 总收益 {backtest['total_yield']*100:+.2f}% | 非投资建议
  </div>
</div>
</body>
</html>
"""

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    print(f"\n[✓] HTML 已生成: {OUTPUT_HTML}")
    print(f"    文件大小: {len(html) / 1024:.1f} KB")
    print(f"    交易数: {len(trades)} (TP={tp_count} / SL={sl_count} / time={time_count})")
    con.close()


if __name__ == "__main__":
    main()