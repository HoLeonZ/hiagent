"""生成单 preset 的 HTML 交易报告 — 每个 trade 一张卡 + K 线 + MACD + 入出场标注。

用法:
  python3 -m chase_up.trade_report \
    --preset chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082 \
    --start 2025-09-19 --end 2026-09-19 \
    --out chase_up/results/trade_report_v19.html
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import numpy as np
import pandas as pd

from chase_up.backtrader_engine import compute_trade_tp_sl, run_backtrader_backtest
from chase_up.data import load_panel
from chase_up.presets import get_preset
from chase_up.signals import compute_indicators, select_entries
from chase_up.universe import load_universe

from hiagent_config import DB_PATH as DEFAULT_DB


# ---------- HTML/SVG 工具 ----------

def _esc(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    return html.escape(str(s))


def _fmt_pct(x: float, digits: int = 2) -> str:
    if x is None or np.isnan(x):
        return "—"
    return f"{x*100:.{digits}f}%"


def _fmt_money(x: float) -> str:
    if x is None or np.isnan(x):
        return "—"
    return f"{x:,.0f}"


def _svg_candles(
    bars: pd.DataFrame,
    *,
    width: int = 720,
    height: int = 280,
    pad: int = 30,
    entry_date,
    exit_date,
    entry_price: float,
    exit_price: float,
    tp_p: float | None = None,
    sl_p: float | None = None,
) -> str:
    """画 K 线 + MA20/MA60/MA120 双线 + entry/exit/TP/SL 标注。"""
    df = bars.copy().reset_index(drop=True)
    if df.empty:
        return "<p>(no bars)</p>"
    n = len(df)
    inner_w = width - pad * 2
    inner_h = height - pad * 2
    lo = float(min(df["low"].min(), entry_price, exit_price))
    if tp_p is not None:
        lo = min(lo, sl_p if sl_p else tp_p)
    hi = float(max(df["high"].max(), entry_price, exit_price))
    if tp_p is not None:
        hi = max(hi, tp_p)
    if sl_p is not None:
        hi = max(hi, sl_p)
    pad_pct = (hi - lo) * 0.05
    lo -= pad_pct
    hi += pad_pct

    def yx(v: float) -> float:
        return pad + inner_h * (1 - (v - lo) / (hi - lo))

    def xx(i: int) -> float:
        return pad + (i + 0.5) * inner_w / n

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'class="chart" preserveAspectRatio="xMidYMid meet">'
    ]
    # 边框 + 网格 (4 条横线)
    parts.append(f'<rect x="{pad}" y="{pad}" width="{inner_w}" height="{inner_h}" '
                 f'fill="#fafafa" stroke="#ddd"/>')
    for k in range(5):
        gy = pad + inner_h * k / 4
        parts.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{pad+inner_w}" y2="{gy:.1f}" '
                     f'stroke="#eaeaea" stroke-width="1"/>')
        gv = hi - (hi - lo) * k / 4
        parts.append(f'<text x="{pad-4}" y="{gy+3:.1f}" font-size="10" '
                     f'fill="#888" text-anchor="end">{gv:.2f}</text>')

    # TP / SL 横线
    if tp_p is not None:
        ty = yx(tp_p)
        parts.append(f'<line x1="{pad}" y1="{ty:.1f}" x2="{pad+inner_w}" y2="{ty:.1f}" '
                     f'stroke="#2e7d32" stroke-dasharray="4 3" stroke-width="1"/>')
        parts.append(f'<text x="{pad+inner_w-4}" y="{ty-3:.1f}" font-size="10" '
                     f'fill="#2e7d32" text-anchor="end">TP {tp_p:.2f}</text>')
    if sl_p is not None:
        sy = yx(sl_p)
        parts.append(f'<line x1="{pad}" y1="{sy:.1f}" x2="{pad+inner_w}" y2="{sy:.1f}" '
                     f'stroke="#c62828" stroke-dasharray="4 3" stroke-width="1"/>')
        parts.append(f'<text x="{pad+inner_w-4}" y="{sy-3:.1f}" font-size="10" '
                     f'fill="#c62828" text-anchor="end">SL {sl_p:.2f}</text>')

    # K 线
    bar_w = max(inner_w / n * 0.7, 1)
    for i, row in df.iterrows():
        x = xx(i)
        yo, yc, yh, yl = yx(row["open"]), yx(row["close"]), yx(row["high"]), yx(row["low"])
        up = row["close"] >= row["open"]
        col = "#c62828" if up else "#2e7d32"  # A 股惯例:红涨绿跌
        parts.append(f'<line x1="{x:.1f}" y1="{yh:.1f}" x2="{x:.1f}" y2="{yl:.1f}" '
                     f'stroke="{col}" stroke-width="1"/>')
        top = min(yo, yc)
        h = max(abs(yc - yo), 1)
        parts.append(f'<rect x="{x-bar_w/2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                     f'height="{h:.1f}" fill="{col}"/>')

    # MA 曲线
    for col_name, color, lw in (("ma20", "#1565c0", 1.2), ("ma60", "#6a1b9a", 1.2),
                                 ("ma120", "#ef6c00", 1.2)):
        if col_name not in df.columns:
            continue
        pts = []
        for i, row in df.iterrows():
            v = row[col_name]
            if pd.notna(v):
                pts.append(f"{xx(i):.1f},{yx(float(v)):.1f}")
        if pts:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                         f'stroke="{color}" stroke-width="{lw}"/>')

    # entry/exit 竖虚线
    if entry_date is not None:
        idx = df.index[df["date"] == pd.Timestamp(entry_date)]
        if len(idx):
            ex = xx(int(idx[0]))
            parts.append(f'<line x1="{ex:.1f}" y1="{pad}" x2="{ex:.1f}" y2="{pad+inner_h}" '
                         f'stroke="#0d47a1" stroke-dasharray="2 2" stroke-width="1.5"/>')
            parts.append(f'<text x="{ex+3:.1f}" y="{pad+10}" font-size="10" '
                         f'fill="#0d47a1">E {entry_price:.2f}</text>')
    if exit_date is not None:
        idx = df.index[df["date"] == pd.Timestamp(exit_date)]
        if len(idx):
            xxv = xx(int(idx[0]))
            parts.append(f'<line x1="{xxv:.1f}" y1="{pad}" x2="{xxv:.1f}" y2="{pad+inner_h}" '
                         f'stroke="#37474f" stroke-dasharray="2 2" stroke-width="1.5"/>')
            parts.append(f'<text x="{xxv+3:.1f}" y="{pad+22}" font-size="10" '
                         f'fill="#37474f">X {exit_price:.2f}</text>')

    # x 轴日期:首/中/末
    for label_i in (0, n // 2, n - 1):
        if 0 <= label_i < n:
            d = df.iloc[label_i]["date"]
            parts.append(f'<text x="{xx(label_i):.1f}" y="{height-pad+12}" font-size="10" '
                         f'fill="#888" text-anchor="middle">{pd.Timestamp(d).strftime("%Y-%m-%d")}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_indicator(
    bars: pd.DataFrame,
    col: str,
    *,
    width: int = 720,
    height: int = 120,
    pad: int = 20,
    color: str = "#1565c0",
    zero_line: bool = False,
    entry_date=None,
    exit_date=None,
) -> str:
    df = bars.copy().reset_index(drop=True)
    if df.empty or col not in df.columns:
        return "<p>(no data)</p>"
    n = len(df)
    inner_w = width - pad * 2
    inner_h = height - pad * 2
    vals = df[col].astype(float).to_numpy()
    finite = vals[np.isfinite(vals)]
    if len(finite) == 0:
        return "<p>(no data)</p>"
    lo, hi = float(np.nanmin(vals)), float(np.nanmax(vals))
    if zero_line:
        lo = min(lo, 0.0)
        hi = max(hi, 0.0)
    if lo == hi:
        hi = lo + 1.0
    pad_v = (hi - lo) * 0.08

    def yx(v):
        return pad + inner_h * (1 - (v - lo) / (hi - lo))

    def xx(i):
        return pad + (i + 0.5) * inner_w / n

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'class="chart">']
    parts.append(f'<rect x="{pad}" y="{pad}" width="{inner_w}" height="{inner_h}" '
                 f'fill="#fafafa" stroke="#ddd"/>')
    if zero_line and lo < 0 < hi:
        zy = yx(0.0)
        parts.append(f'<line x1="{pad}" y1="{zy:.1f}" x2="{pad+inner_w}" y2="{zy:.1f}" '
                     f'stroke="#999" stroke-dasharray="3 3" stroke-width="1"/>')

    pts = []
    for i, v in enumerate(vals):
        if np.isfinite(v):
            pts.append(f"{xx(i):.1f},{yx(float(v)):.1f}")
    if pts:
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                     f'stroke-width="1.4"/>')

    if entry_date is not None:
        idx = df.index[df["date"] == pd.Timestamp(entry_date)]
        if len(idx):
            ex = xx(int(idx[0]))
            parts.append(f'<line x1="{ex:.1f}" y1="{pad}" x2="{ex:.1f}" y2="{pad+inner_h}" '
                         f'stroke="#0d47a1" stroke-dasharray="2 2" stroke-width="1"/>')
    if exit_date is not None:
        idx = df.index[df["date"] == pd.Timestamp(exit_date)]
        if len(idx):
            xv = xx(int(idx[0]))
            parts.append(f'<line x1="{xv:.1f}" y1="{pad}" x2="{xv:.1f}" y2="{pad+inner_h}" '
                         f'stroke="#37474f" stroke-dasharray="2 2" stroke-width="1"/>')

    # y 轴 label
    parts.append(f'<text x="{pad-4}" y="{pad+10}" font-size="10" fill="#888" '
                 f'text-anchor="end">{hi:.3f}</text>')
    parts.append(f'<text x="{pad-4}" y="{pad+inner_h}" font-size="10" fill="#888" '
                 f'text-anchor="end">{lo:.3f}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _svg_macd(
    bars: pd.DataFrame,
    *,
    width: int = 720,
    height: int = 140,
    pad: int = 20,
    entry_date=None,
    exit_date=None,
) -> str:
    """MACD: DIF/DEA 双线 + 柱状。"""
    df = bars.copy().reset_index(drop=True)
    if df.empty or "macd_dif" not in df.columns:
        return "<p>(no MACD)</p>"
    n = len(df)
    inner_w = width - pad * 2
    inner_h = height - pad * 2
    dif = df["macd_dif"].astype(float).to_numpy()
    dea = df["macd_dea"].astype(float).to_numpy()
    bar = df["macd_bar"].astype(float).to_numpy()
    allv = np.concatenate([dif[np.isfinite(dif)], dea[np.isfinite(dea)],
                           bar[np.isfinite(bar)]])
    if len(allv) == 0:
        return "<p>(no MACD)</p>"
    lo = float(np.nanmin(allv))
    hi = float(np.nanmax(allv))
    if lo == hi:
        hi = lo + 1.0
    pad_v = (hi - lo) * 0.05

    def yx(v):
        return pad + inner_h * (1 - (v - lo) / (hi - lo))

    def xx(i):
        return pad + (i + 0.5) * inner_w / n

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'class="chart">']
    parts.append(f'<rect x="{pad}" y="{pad}" width="{inner_w}" height="{inner_h}" '
                 f'fill="#fafafa" stroke="#ddd"/>')

    # 0 线
    if lo < 0 < hi:
        zy = yx(0.0)
        parts.append(f'<line x1="{pad}" y1="{zy:.1f}" x2="{pad+inner_w}" y2="{zy:.1f}" '
                     f'stroke="#999" stroke-dasharray="3 3"/>')

    # 柱
    bw = max(inner_w / n * 0.6, 1)
    for i, b in enumerate(bar):
        if not np.isfinite(b):
            continue
        col = "#c62828" if b >= 0 else "#2e7d32"
        y0 = yx(0.0)
        yb = yx(float(b))
        top = min(y0, yb)
        h = max(abs(yb - y0), 1)
        parts.append(f'<rect x="{xx(i)-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}" fill="{col}"/>')

    # DIF / DEA
    for col_name, color in (("macd_dif", "#1565c0"), ("macd_dea", "#ef6c00")):
        vals = df[col_name].astype(float).to_numpy()
        pts = []
        for i, v in enumerate(vals):
            if np.isfinite(v):
                pts.append(f"{xx(i):.1f},{yx(float(v)):.1f}")
        if pts:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                         f'stroke="{color}" stroke-width="1.3"/>')

    # entry/exit
    for d, dash in ((entry_date, "#0d47a1"), (exit_date, "#37474f")):
        if d is not None:
            idx = df.index[df["date"] == pd.Timestamp(d)]
            if len(idx):
                ex = xx(int(idx[0]))
                parts.append(f'<line x1="{ex:.1f}" y1="{pad}" x2="{ex:.1f}" '
                             f'y2="{pad+inner_h}" stroke="{dash}" '
                             f'stroke-dasharray="2 2" stroke-width="1"/>')

    parts.append(f'<text x="{pad-4}" y="{pad+10}" font-size="10" fill="#888" '
                 f'text-anchor="end">{hi:.3f}</text>')
    parts.append(f'<text x="{pad-4}" y="{pad+inner_h}" font-size="10" fill="#888" '
                 f'text-anchor="end">{lo:.3f}</text>')

    # legend
    legend_y = pad + inner_h + 12
    parts.append(f'<line x1="{pad}" y1="{legend_y}" x2="{pad+15}" y2="{legend_y}" '
                 f'stroke="#1565c0" stroke-width="1.3"/>')
    parts.append(f'<text x="{pad+18}" y="{legend_y+3}" font-size="10" fill="#444">DIF</text>')
    parts.append(f'<line x1="{pad+60}" y1="{legend_y}" x2="{pad+75}" y2="{legend_y}" '
                 f'stroke="#ef6c00" stroke-width="1.3"/>')
    parts.append(f'<text x="{pad+78}" y="{legend_y+3}" font-size="10" fill="#444">DEA</text>')
    parts.append(f'<rect x="{pad+115}" y="{legend_y-3}" width="6" height="6" fill="#c62828"/>')
    parts.append(f'<text x="{pad+124}" y="{legend_y+3}" font-size="10" fill="#444">BAR+</text>')
    parts.append(f'<rect x="{pad+165}" y="{legend_y-3}" width="6" height="6" fill="#2e7d32"/>')
    parts.append(f'<text x="{pad+174}" y="{legend_y+3}" font-size="10" fill="#444">BAR-</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _signal_label(sub: str) -> str:
    mapping = {"A": "A 突破(close>high20_prev+量比)", "B": "B 动量(ret1∈[3%,8%]+MACD扩张)",
               "C": "C 金叉(ma20上穿ma60+量比)"}
    return " + ".join(mapping.get(c, c) for c in str(sub))


def _trade_card(
    trade: pd.Series,
    bars: pd.DataFrame,
    entry_row: pd.Series | None,
    entries: pd.DataFrame,
) -> str:
    """bars 已是 trade 的入场 ±60d 区间。"""
    code = trade["thscode"]
    entry_date = pd.Timestamp(trade["entry_date"])
    exit_date = pd.Timestamp(trade["exit_date"])
    ep = float(trade["entry_price"])
    xp = float(trade["exit_price"])
    net = float(trade["net_pnl"])
    nret = float(trade["net_return"])
    exit_reason = trade.get("exit_reason", "—")
    hold = int(trade["hold_days"])
    size = int(trade["size"])
    sub = trade.get("sub_signal_type", "")
    pnl_color = "#c62828" if net >= 0 else "#2e7d32"  # A 股红涨绿跌

    sig_close = entry_row.get("close") if entry_row is not None else None
    sig_ma20 = entry_row.get("ma20") if entry_row is not None else None
    sig_ma60 = entry_row.get("ma60") if entry_row is not None else None
    sig_ret1 = entry_row.get("ret1") if entry_row is not None else None
    sig_mom120 = entry_row.get("mom120") if entry_row is not None else None
    sig_amount60 = entry_row.get("amount60") if entry_row is not None else None
    sig_atr_pct = entry_row.get("atr_pct") if entry_row is not None else None
    sig_vol_ratio = entry_row.get("vol_ratio") if entry_row is not None else None
    # 子信号分数从 entries 查找(若信号命中)
    sig_score = sig_breakout_score = sig_momentum_score = sig_macross_score = None
    sig_date_for_entries = entry_row["date"] if entry_row is not None else None
    if sig_date_for_entries is not None and not entries.empty:
        hit = entries[(entries["thscode"] == code)
                      & (entries["date"] == sig_date_for_entries)]
        if not hit.empty:
            r = hit.iloc[0]
            sig_score = r.get("score")
            sig_breakout_score = r.get("sig_breakout_score")
            sig_momentum_score = r.get("sig_momentum_score")
            sig_macross_score = r.get("sig_macross_score")

    tp_p, sl_p = compute_trade_tp_sl(
        ep,
        fixed_tp_pct=0.30,  # preset.fallback; 仅用于显示
        fixed_sl_pct=0.05,
        atr_pct=float(trade.get("atr_pct") or np.nan),
        atr_tp_mult=6.0,
        atr_sl_mult=1.75,
    )

    # signal-day MACD/MA snapshot
    sig_macd_html = ""
    if entry_row is not None:
        sig_dif = entry_row.get("macd_dif")
        sig_dea = entry_row.get("macd_dea")
        sig_bar = entry_row.get("macd_bar")
        sig_bar_prev = entry_row.get("macd_bar_prev")
        if sig_dif is not None and sig_dea is not None and sig_bar is not None:
            expanding = (sig_bar_prev is not None and not pd.isna(sig_bar_prev)
                         and sig_bar > sig_bar_prev)
            cls = "pos" if expanding else "neg"
            arrow = "扩张 ▲" if expanding else "收缩 ▼"
            sig_macd_html = f"""
            <div class="sig-macd">
              <div>DIF: <b>{sig_dif:.4f}</b>  DEA: <b>{sig_dea:.4f}</b>  BAR: <b>{sig_bar:.4f}</b></div>
              <div>BAR_prev: {sig_bar_prev if sig_bar_prev is not None else '—'}  →  BAR_now: {sig_bar:.4f}
                   <span class="{cls}">{arrow}</span>
              </div>
            </div>"""

    svg_candle = _svg_candles(
        bars, entry_date=entry_date, exit_date=exit_date,
        entry_price=ep, exit_price=xp, tp_p=tp_p, sl_p=sl_p,
    )
    svg_macd = _svg_macd(bars, entry_date=entry_date, exit_date=exit_date)
    svg_mom = _svg_indicator(bars, "mom120", color="#6a1b9a", entry_date=entry_date, exit_date=exit_date)
    svg_atr = _svg_indicator(bars, "atr_pct", color="#ef6c00", entry_date=entry_date, exit_date=exit_date)
    svg_vol = _svg_indicator(bars, "vol_ratio", color="#00838f", entry_date=entry_date, exit_date=exit_date)

    sig_parts = []
    sig_parts.append(f"<li><b>信号日:</b> {entry_date.strftime('%Y-%m-%d')} ({code})</li>")
    sig_parts.append(f"<li><b>close:</b> {_fmt_money(sig_close)}  vs  MA20 {_fmt_money(sig_ma20)}  MA60 {_fmt_money(sig_ma60)}</li>")
    sig_parts.append(f"<li><b>ret1:</b> {_fmt_pct(sig_ret1)}  <b>mom120:</b> {_fmt_pct(sig_mom120)}  <b>atr%:</b> {_fmt_pct(sig_atr_pct)}  <b>vol_ratio:</b> {sig_vol_ratio if sig_vol_ratio is not None else '—'}</li>")
    sig_parts.append(f"<li><b>amount60:</b> {_fmt_money(sig_amount60)} (门槛 3e7 ~ 3e8)</li>")
    score_str = f"{sig_score:.3f}" if sig_score is not None else "—"
    a_str = f"{sig_breakout_score:.2f}" if sig_breakout_score is not None else "—"
    b_str = f"{sig_momentum_score:.2f}" if sig_momentum_score is not None else "—"
    c_str = f"{sig_macross_score:.2f}" if sig_macross_score is not None else "—"
    sig_parts.append(f"<li><b>score:</b> <span class='hl'>{score_str}</span>  "
                     f"(A:{a_str}  B:{b_str}  C:{c_str})</li>")
    sig_parts.append(f"<li><b>命中子信号:</b> <span class='hl'>{_signal_label(sub)}</span></li>")

    return f"""
    <section class="trade" id="trade-{entry_date.strftime('%Y%m%d')}-{code.replace('.','')}">
      <h2>{code} | {entry_date.strftime('%Y-%m-%d')} → {exit_date.strftime('%Y-%m-%d')} ({hold}d)</h2>
      <div class="trade-meta">
        <div><b>子信号</b>: {_esc(sub) or '—'} — {_signal_label(sub)}</div>
        <div><b>入场</b> T+1 开: {ep:.2f}  →  <b>出场</b> {exit_reason}: {xp:.2f}</div>
        <div><b>TP</b>: {tp_p:.2f}   <b>SL</b>: {sl_p:.2f}   <b>size</b>: {size}</div>
        <div class="pnl" style="color:{pnl_color}">
          net_pnl: {net:>+,.0f}   net_return: {nret*100:+.2f}%   持仓 {hold} 天
        </div>
      </div>

      <h3>信号日指标</h3>
      <ul class="sig-list">{"".join(sig_parts)}</ul>
      {sig_macd_html}

      <h3>K 线 (入场 ±30d)  +  MA20/MA60/MA120  +  TP/SL/Entry/Exit 标注</h3>
      {svg_candle}

      <h3>MACD (DIF / DEA / BAR)</h3>
      {svg_macd}

      <h3>中期动量 mom120 (120 日涨幅)</h3>
      {svg_mom}

      <h3>波动率 atr_pct (ATR14 / close)</h3>
      {svg_atr}

      <h3>量能 vol_ratio (volume / vol_ma20)</h3>
      {svg_vol}
    </section>
    """


def _index_card(trade: pd.Series) -> str:
    ep = float(trade["entry_price"])
    xp = float(trade["exit_price"])
    net = float(trade["net_pnl"])
    nret = float(trade["net_return"])
    exit_reason = trade.get("exit_reason", "—")
    sub = trade.get("sub_signal_type", "")
    color = "#c62828" if net >= 0 else "#2e7d32"
    ed = pd.Timestamp(trade["entry_date"]).strftime('%Y-%m-%d')
    xd = pd.Timestamp(trade["exit_date"]).strftime('%Y-%m-%d')
    code = trade["thscode"]
    anchor = f"trade-{ed.replace('-','')}-{code.replace('.','')}"
    return (
        f"<li><a href='#{anchor}'>{ed} {code}</a> → {xd} "
        f"<span class='reason'>[{_esc(exit_reason)}]</span> "
        f"<span style='color:{color}'>{net:+,.0f} ({nret*100:+.2f}%)</span> "
        f"<span class='sub'>子信号 {_esc(sub) or '—'}</span></li>"
    )


def build_html(
    preset_name: str,
    start: str,
    end: str,
    db_path: Path,
    out_path: Path,
) -> None:
    p = get_preset(preset_name)
    universe = set(load_universe(p["universe"], db_path))
    panel = load_panel(db_path, start, end, universe=universe)
    panel_ind = compute_indicators(panel)

    # 信号
    entries = select_entries(
        panel_ind, start_date=start, end_date=end, **p["signal"]
    )

    # 回测 (with backtrader verify)
    res = run_backtrader_backtest(
        preset_name, start, end, db_path,
        panel_ind=panel_ind, verify=True,
    )
    trades = res["trades"]
    metrics = res["metrics"]

    # 用 panel_ind 索引每只 stock 的 bars (for chart 切片)
    bars_by_code: dict[str, pd.DataFrame] = {}
    for code, sub in panel_ind.groupby("thscode", sort=False):
        bars_by_code[code] = sub.sort_values("date").reset_index(drop=True)

    # entry_row lookup
    entries_idx = entries.set_index(["thscode", "date"]) if not entries.empty else entries

    trade_cards: list[str] = []
    index_items: list[str] = []
    for _, t in trades.sort_values("entry_date").iterrows():
        code = t["thscode"]
        entry_date = pd.Timestamp(t["entry_date"])
        bars_full = bars_by_code.get(code)
        if bars_full is None or bars_full.empty:
            continue
        # 切片:entry_date ± 30d
        lo_d = entry_date - pd.Timedelta(days=30)
        hi_d = pd.Timestamp(t["exit_date"]) + pd.Timedelta(days=5)
        mask = (bars_full["date"] >= lo_d) & (bars_full["date"] <= hi_d)
        bars = bars_full.loc[mask].copy()

        # entry_row: 信号日 = entry_date 之前的最近一个有指标数据的交易日 (T 日)
        # 通常是 entry_date - 1d,但隔周末/节假日会差几天
        entry_row = None
        if not bars_full.empty:
            prior = bars_full[bars_full["date"] < entry_date]
            if not prior.empty:
                entry_row = prior.iloc[-1]

        trade_cards.append(_trade_card(t, bars, entry_row, entries))
        index_items.append(_index_card(t))

    m = metrics
    summary_table = f"""
    <table class="summary">
      <tr><td>区间</td><td>{m['start']} → {m['end']}</td></tr>
      <tr><td>信号数</td><td>{m['signals']}</td></tr>
      <tr><td>交易笔数</td><td>{m['trades']}</td></tr>
      <tr><td>胜率</td><td>{m['win_rate']*100:.1f}%</td></tr>
      <tr><td>总收益</td><td>{m['total_return']*100:+.2f}%</td></tr>
      <tr><td>CAGR</td><td>{m['cagr']*100:+.2f}%</td></tr>
      <tr><td>Sharpe</td><td>{m['sharpe']:.2f}</td></tr>
      <tr><td>Max DD</td><td>{m['max_dd']*100:.2f}%</td></tr>
      <tr><td>平均持仓</td><td>{m['avg_hold_days']:.1f} d (最长 {m['max_hold_days']} d)</td></tr>
      <tr><td>退出分布</td><td>TP={m['tp_count']} SL={m['sl_count']} time={m['time_count']} eod={m['eod_count']}</td></tr>
      <tr><td>盈亏比 / 平均单笔净收益</td><td>{m['profit_factor']:.2f} / {m['avg_net_return']*100:+.2f}%</td></tr>
      <tr><td>期末权益 (初始 1,000,000)</td><td>{m['final_equity']:,.0f}</td></tr>
    </table>"""

    preset_params = f"""
    <table class="params">
      <tr><td>universe</td><td>{p['universe']}</td></tr>
      <tr><td>tp_pct / sl_pct (fallback)</td><td>{p['tp_pct']} / {p['sl_pct']}</td></tr>
      <tr><td>atr_tp_mult / atr_sl_mult</td><td>{p['atr_tp_mult']} / {p['atr_sl_mult']}</td></tr>
      <tr><td>max_hold</td><td>{p['max_hold']}</td></tr>
      <tr><td>max_positions</td><td>{p['max_positions']}</td></tr>
      <tr><td>position_sizing</td><td>{p['position_sizing']}</td></tr>
      <tr><td>signal 子项</td><td><pre>{html.escape(repr(p['signal']))}</pre></td></tr>
    </table>"""

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>Chase Up Trade Report — {preset_name}</title>
<style>
  body {{ font-family: -apple-system, "Helvetica Neue", Arial, "PingFang SC", sans-serif;
         max-width: 820px; margin: 24px auto; padding: 0 12px; color: #222; background: #fff; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #1565c0; padding-bottom: 6px; }}
  h2 {{ font-size: 17px; color: #0d47a1; margin-top: 32px; border-left: 4px solid #1565c0;
        padding-left: 8px; }}
  h3 {{ font-size: 14px; color: #555; margin: 16px 0 6px; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  table.summary td, table.params td {{ padding: 4px 10px; border-bottom: 1px solid #eee; }}
  table.summary td:first-child, table.params td:first-child {{ color: #666; width: 220px; }}
  pre {{ background: #f5f5f5; padding: 6px 8px; font-size: 12px; overflow-x: auto; }}
  .trade {{ border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px;
           margin: 24px 0; background: #fff; }}
  .trade-meta {{ display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px;
                background: #f8f9fa; padding: 8px 10px; border-radius: 4px; }}
  .trade-meta .pnl {{ font-weight: 600; }}
  .sig-list {{ font-size: 13px; padding-left: 20px; line-height: 1.7; }}
  .sig-list .hl {{ background: #fff8e1; padding: 0 4px; border-radius: 3px; }}
  .sig-macd {{ font-size: 13px; color: #444; margin: 6px 0; }}
  .sig-macd .pos {{ color: #c62828; font-weight: 600; }}
  .sig-macd .neg {{ color: #2e7d32; font-weight: 600; }}
  svg.chart {{ display: block; width: 100%; height: auto; max-width: 720px; }}
  ul.trades {{ list-style: none; padding-left: 0; font-size: 13px; line-height: 1.8; }}
  ul.trades li {{ border-bottom: 1px dashed #eee; padding: 2px 0; }}
  ul.trades li .reason {{ color: #666; }}
  ul.trades li .sub {{ color: #888; font-size: 11px; }}
  a {{ color: #1565c0; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>Chase Up 交易报告</h1>
<p><b>Preset:</b> <code>{preset_name}</code><br/>
<b>区间:</b> {start} → {end}</p>

<h2>📊 总体指标</h2>
{summary_table}

<h2>⚙️ Preset 参数</h2>
{preset_params}

<h2>📋 交易清单 ({len(trade_cards)} 笔)</h2>
<ul class="trades">
{''.join(index_items)}
</ul>

<h2>📈 每笔交易明细</h2>
{''.join(trade_cards)}

<hr/>
<p style="color:#888;font-size:11px">生成自 chase_up.trade_report |
K 线 MA / MACD / 量比 ATR 取自 compute_indicators |
回测带 backtrader 撮合验证 (Phase 2)</p>
</body>
</html>
"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"✓ 报告已写入: {out_path}")
    print(f"  - 交易笔数: {len(trade_cards)}")
    print(f"  - 文件大小: {out_path.stat().st_size / 1024:.1f} KB")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 chase_up 单 preset 的 HTML 交易报告")
    ap.add_argument("--preset", required=True)
    ap.add_argument("--start", default="2025-09-19")
    ap.add_argument("--end", default="2026-09-19")
    ap.add_argument("--db-path", default=str(DEFAULT_DB))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out = Path(args.out) if args.out else Path(
        f"chase_up/results/trade_report_{args.preset}.html"
    )
    build_html(args.preset, args.start, args.end, Path(args.db_path), out)


if __name__ == "__main__":
    main()
