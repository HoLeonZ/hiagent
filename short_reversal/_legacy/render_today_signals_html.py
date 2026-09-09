"""
今日 (2026-09-08) 8 只 v33 信号 → HTML 可视化 (K线 + MACD + 信号标记)

每只股票展示:
- 信号日前 50 天 → 信号日后 5 天 (含今日)
- K线 + MA20 / MA60
- MACD (DIF / DEA / 柱)
- S = 信号日 (今日)
- 估算入场点 = 今日收盘 (实际明日开盘)
- 估算 TP/SL 线 (基于今日收盘)
"""
import json
from pathlib import Path

import pandas as pd
import duckdb

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
OUTPUT_DIR = Path(__file__).parent / "results"
TP_PCT = 0.06
SL_PCT = 0.05


def build_chart_svg(candles, sig_idx, entry_idx, exit_idx, exit_reason, tp_line, sl_line):
    """生成 K线 + MA + MACD 组合 SVG.

    candles: list of {date, open, high, low, close, ma20, ma60, dif, dea, macd_bar}
    sig_idx: 信号日索引 (画 S 标记)
    entry_idx: 入场日索引 (画 E 标记, 估算 = sig_idx)
    exit_idx: 出场日索引 (此处为 None, 画 X 示意)
    """
    W = 720
    H_KLINE = 200
    H_MACD = 100
    PAD_L = 50
    PAD_R = 60
    PAD_T = 12
    PAD_B = 20
    CHART_GAP = 18

    candle_w_total = W - PAD_L - PAD_R
    n = len(candles)
    candle_w = candle_w_total / n * 0.7
    bar_gap = candle_w_total / n * 0.3

    # 价格范围 (K线)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ma20_vals = [c["ma20"] for c in candles if c["ma20"] is not None]
    ma60_vals = [c["ma60"] for c in candles if c["ma60"] is not None]
    all_prices = highs + lows + ma20_vals + ma60_vals + [tp_line, sl_line, candles[sig_idx]["close"]]
    p_min, p_max = min(all_prices), max(all_prices)
    p_range = p_max - p_min if p_max > p_min else 1.0
    p_min -= p_range * 0.05
    p_max += p_range * 0.05

    # MACD 范围
    dif_vals = [c["dif"] for c in candles if c["dif"] is not None]
    dea_vals = [c["dea"] for c in candles if c["dea"] is not None]
    bar_vals = [c["macd_bar"] for c in candles if c["macd_bar"] is not None]
    if bar_vals:
        m_min = min(min(dif_vals), min(dea_vals), min(bar_vals))
        m_max = max(max(dif_vals), max(dea_vals), max(bar_vals))
        m_range = m_max - m_min if m_max > m_min else 1.0
        m_min -= m_range * 0.1
        m_max += m_range * 0.1
    else:
        m_min, m_max = -1, 1

    def x_of(i):
        return PAD_L + candle_w_total * (i + 0.5) / n

    def y_of_price(p):
        return PAD_T + (p_max - p) / (p_max - p_min) * H_KLINE

    def y_of_macd(v):
        m_top = PAD_T + H_KLINE + CHART_GAP
        return m_top + (m_max - v) / (m_max - m_min) * H_MACD

    parts = []

    # ===== K线区背景网格 =====
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H_KLINE + PAD_T + PAD_B}" fill="#0f1419"/>')

    # 价格水平线 (5 条)
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

    # ===== MA60 / MA20 折线 =====
    def line_path(field, color, w):
        path = []
        started = False
        for i, c in enumerate(candles):
            v = c[field]
            if v is None:
                continue
            x = x_of(i)
            y = y_of_price(v)
            if not started:
                path.append(f"M{x:.1f},{y:.1f}")
                started = True
            else:
                path.append(f"L{x:.1f},{y:.1f}")
        return f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="{w}" fill="none" opacity="0.85"/>'

    parts.append(line_path("ma60", "#ffa726", 1.5))
    parts.append(line_path("ma20", "#42a5f5", 1.2))

    # ===== K线 =====
    for i, c in enumerate(candles):
        x = x_of(i)
        is_up = c["close"] >= c["open"]
        color = "#26a69a" if is_up else "#ef5350"
        # 影线
        y_h = y_of_price(c["high"])
        y_l = y_of_price(c["low"])
        y_o = y_of_price(c["open"])
        y_c = y_of_price(c["close"])
        parts.append(f'<line x1="{x:.1f}" y1="{y_h:.1f}" x2="{x:.1f}" y2="{y_l:.1f}" stroke="{color}" stroke-width="1"/>')
        # 实体
        y_top = min(y_o, y_c)
        y_bot = max(y_o, y_c)
        h = max(y_bot - y_top, 1)
        parts.append(f'<rect x="{x-candle_w/2:.1f}" y="{y_top:.1f}" width="{candle_w:.1f}" height="{h:.1f}" '
                     f'fill="{color}" stroke="{color}"/>')

    # ===== 信号日 S 标记 =====
    sig_x = x_of(sig_idx)
    sig_y = y_of_price(candles[sig_idx]["close"])
    parts.append(f'<line x1="{sig_x:.1f}" y1="{PAD_T}" x2="{sig_x:.1f}" y2="{PAD_T+H_KLINE}" '
                 f'stroke="#ffeb3b" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>')
    parts.append(f'<circle cx="{sig_x:.1f}" cy="{sig_y:.1f}" r="5" fill="#ffeb3b" stroke="#000" stroke-width="1"/>')
    parts.append(f'<text x="{sig_x+8:.1f}" y="{sig_y-8:.1f}" fill="#ffeb3b" font-size="11" font-weight="700">S</text>')

    # ===== X 坐标日期 =====
    for i, c in enumerate(candles):
        if i % max(n // 8, 1) == 0 or i == sig_idx:
            x = x_of(i)
            parts.append(f'<text x="{x:.1f}" y="{H_KLINE+PAD_T+12}" fill="#888" font-size="8" '
                         f'text-anchor="middle" font-family="monospace">{c["date"][5:]}</text>')

    # ===== MACD 区 =====
    m_top = PAD_T + H_KLINE + CHART_GAP
    parts.append(f'<line x1="{PAD_L}" y1="{m_top}" x2="{W-PAD_R}" y2="{m_top}" stroke="#2a3540" stroke-width="0.5"/>')
    # 0 轴
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

    # DIF / DEA 折线
    parts.append(line_path("dif", "#42a5f5", 1.2).replace("M", "M").replace('y_of_price', 'y_of_macd'))
    # 简单重建 DIF/DEA 折线 (因为 line_path 用了 y_of_price)
    def macd_line_path(field, color, w):
        path = []
        started = False
        for i, c in enumerate(candles):
            v = c[field]
            if v is None:
                continue
            x = x_of(i)
            y = y_of_macd(v)
            if not started:
                path.append(f"M{x:.1f},{y:.1f}")
                started = True
            else:
                path.append(f"L{x:.1f},{y:.1f}")
        return f'<path d="{" ".join(path)}" stroke="{color}" stroke-width="{w}" fill="none" opacity="0.9"/>'

    parts.append(macd_line_path("dif", "#42a5f5", 1.2))
    parts.append(macd_line_path("dea", "#ffa726", 1.2))

    # MACD 数值范围标记
    for i in [0, 1, 2]:
        if i == 2:
            v = m_max
            y = PAD_T + H_KLINE + CHART_GAP + 2
        elif i == 1:
            v = (m_max + m_min) / 2
            y = y_of_macd(v)
        else:
            v = m_min
            y = PAD_T + H_KLINE + CHART_GAP + H_MACD - 4
        parts.append(f'<text x="{W-PAD_R+4}" y="{y:.1f}" fill="#666" font-size="9" font-family="monospace">{v:.3f}</text>')

    # MACD 区信号日竖线
    parts.append(f'<line x1="{sig_x:.1f}" y1="{m_top}" x2="{sig_x:.1f}" y2="{m_top+H_MACD}" '
                 f'stroke="#ffeb3b" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>')

    return (
        f'<svg viewBox="0 0 {W} {PAD_T + H_KLINE + CHART_GAP + H_MACD + PAD_B}" '
        f'class="chart-svg">{"".join(parts)}</svg>'
    )


def main():
    with open(OUTPUT_DIR / "today_signals.json") as f:
        data = json.load(f)

    con = duckdb.connect(DB_PATH, read_only=True)
    today_str = data["signal_date"]
    today_dt = pd.to_datetime(today_str)

    print(f"生成 8 只股票 K线 + MACD + 信号 HTML...")
    print(f"信号日 = {today_str}")

    cards = []
    for idx, sig in enumerate(data["signals"], 1):
        code = sig["thscode"]
        sig_close = sig["close"]

        sql = f"""
        SELECT date, open, high, low, close, amount
        FROM v_daily
        WHERE thscode = '{code}'
        ORDER BY date
        """
        df = con.execute(sql).fetchdf()
        df["date"] = pd.to_datetime(df["date"])

        # 计算特征
        df["ma20"] = df["close"].rolling(20, min_periods=20).mean()
        df["ma60"] = df["close"].rolling(60, min_periods=60).mean()
        df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
        df["dif"] = df["ema12"] - df["ema26"]
        df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
        df["macd_bar"] = 2 * (df["dif"] - df["dea"])

        # 找信号日索引
        sig_idx_list = df.index[df["date"] == today_dt].tolist()
        if not sig_idx_list:
            continue
        sig_idx = sig_idx_list[0]

        # 取信号日前 50 天 ~ 信号日后 5 天 (含今日)
        start_idx = max(0, sig_idx - 50)
        end_idx = min(len(df) - 1, sig_idx + 5)
        sub = df.iloc[start_idx:end_idx + 1].reset_index(drop=True)
        local_sig_idx = sig_idx - start_idx

        candles = []
        for i, row in sub.iterrows():
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

        tp_line = sig_close * (1 - TP_PCT)
        sl_line = sig_close * (1 + SL_PCT)

        svg = build_chart_svg(candles, local_sig_idx, local_sig_idx + 1 if local_sig_idx + 1 < len(candles) else None,
                              None, "TP", tp_line, sl_line)

        # 特征卡片
        sig_bar_cls = "red" if sig["macd_bar"] < 0 else "green"
        card = f"""
<div class="trade">
  <div class="trade-header">
    <div>
      <div class="trade-title">#{idx} {code} <span class="sig-badge">S 信号日</span></div>
      <div class="trade-meta">收盘 {sig_close:.2f} → 估开仓价 {sig_close:.2f} → TP {tp_line:.2f} / SL {sl_line:.2f}</div>
    </div>
    <div class="trade-tag tag-signal">做空</div>
  </div>
  <div class="features">
    <div class="feat"><div class="lbl">close/MA60</div><div class="val">{sig_close:.2f}/{sig['ma60']:.2f}</div></div>
    <div class="feat"><div class="lbl">今日涨幅</div><div class="val green">+{sig['pct_chg_pct']:.2f}%</div></div>
    <div class="feat"><div class="lbl">连阳数</div><div class="val">{sig['up_streak']}d</div></div>
    <div class="feat"><div class="lbl">DIF</div><div class="val red">{sig['dif']:.4f}</div></div>
    <div class="feat"><div class="lbl">DEA</div><div class="val red">{sig['dea']:.4f}</div></div>
    <div class="feat"><div class="lbl">MACD柱</div><div class="val {sig_bar_cls}">{sig['macd_bar']:.4f}</div></div>
    <div class="feat"><div class="lbl">am60</div><div class="val">{sig['am60_yi']:.2f}亿</div></div>
  </div>
  <div class="chart-row">
    <div class="legend">
      <div class="legend-item"><span class="legend-dot" style="background:#ef5350"></span>跌</div>
      <div class="legend-item"><span class="legend-dot" style="background:#26a69a"></span>涨</div>
      <div class="legend-item"><span class="legend-line" style="background:#42a5f5"></span>MA20</div>
      <div class="legend-item"><span class="legend-line" style="background:#ffa726"></span>MA60</div>
      <div class="legend-item"><span class="legend-line" style="background:#26a69a"></span>-- TP</div>
      <div class="legend-item"><span class="legend-line" style="background:#ef5350"></span>-- SL</div>
      <div class="legend-item"><span class="legend-dot" style="background:#ffeb3b"></span>S 信号日</div>
    </div>
    {svg}
  </div>
</div>"""
        cards.append(card)

    # 总览头部
    cards_html = "\n".join(cards)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>今日 v33 信号 — 8 只做空候选</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0f1419; color: #e6e6e6; padding: 16px; line-height: 1.45; font-size: 13px;
  }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #f5f5f5; font-size: 20px; margin-bottom: 6px; }}
  .subtitle {{ color: #888; font-size: 12px; margin-bottom: 16px; }}

  .summary {{
    display: grid; grid-template-columns: repeat(4, 1fr);
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

  .trade {{
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px; padding: 12px; margin-bottom: 14px;
  }}
  .trade-header {{
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 8px;
  }}
  .trade-title {{ font-size: 14px; font-weight: 700; color: #f5f5f5; }}
  .trade-meta {{ font-size: 11px; color: #888; margin-top: 2px; }}
  .trade-tag {{
    display: inline-block; padding: 3px 8px;
    border-radius: 3px; font-size: 11px; font-weight: 700;
  }}
  .tag-signal {{ background: #7f1d1d; color: #ffab91; }}
  .sig-badge {{
    background: #ffeb3b; color: #000;
    padding: 1px 6px; border-radius: 3px;
    font-size: 10px; font-weight: 700;
    margin-left: 4px;
  }}

  .features {{
    display: grid; grid-template-columns: repeat(7, 1fr);
    gap: 4px; margin-bottom: 8px; font-size: 10px;
  }}
  .feat {{ background: #0f1419; padding: 5px 6px; border-radius: 3px; }}
  .feat .lbl {{ color: #888; font-size: 9px; }}
  .feat .val {{ color: #f5f5f5; font-size: 11px; font-weight: 600; margin-top: 1px; }}
  .feat .val.green {{ color: #26a69a; }}
  .feat .val.red {{ color: #ef5350; }}

  .chart-row {{ display: flex; flex-direction: column; gap: 4px; }}
  .chart-svg {{ width: 100%; height: auto; display: block; background: #0f1419; border-radius: 4px; }}
  .legend {{
    display: flex; gap: 10px; font-size: 10px; color: #888;
    flex-wrap: wrap;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 3px; }}
  .legend-dot {{ width: 8px; height: 8px; border-radius: 1px; }}
  .legend-line {{ width: 12px; height: 2px; }}

  .footer {{
    text-align: center; color: #555; font-size: 11px;
    padding: 20px 0 8px;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>v33 信号 — 今日 ({today_str}) 触发, 明日开盘做空</h1>
  <div class="subtitle">
    策略: 下跌趋势反弹做空 (MACD柱转红) | TP=6% / SL=5% / Time=30 | 数据源: hithink-finance (2026-09-08 收盘)
  </div>

  <div class="summary">
    <div class="sum-card">
      <div class="lbl">信号日</div>
      <div class="val gold">{today_str}</div>
    </div>
    <div class="sum-card">
      <div class="lbl">触发信号</div>
      <div class="val gold">{len(data['signals'])} 只</div>
    </div>
    <div class="sum-card">
      <div class="lbl">明日开盘</div>
      <div class="val">2026-09-09</div>
    </div>
    <div class="sum-card">
      <div class="lbl">操作</div>
      <div class="val green">开盘做空</div>
    </div>
  </div>

  {cards_html}

  <div class="footer">
    v33 (柱转红) | TP=6% / SL=5% | 排除: 沪深300 / 中证500 / 金融 | 非投资建议
  </div>
</div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "today_signals_visualization.html"
    with open(output_path, "w") as f:
        f.write(html)

    print(f"\n[✓] HTML 已生成: {output_path}")
    print(f"    文件大小: {len(html) / 1024:.1f} KB")
    print(f"    访问: http://localhost:8765/today_signals_visualization.html")

    con.close()


if __name__ == "__main__":
    main()
