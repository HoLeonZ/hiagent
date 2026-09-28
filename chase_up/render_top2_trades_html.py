"""Render top-2 chase_up presets (chase_v18, chase_v19) trades as HTML.

Output:
  - chase_up/results/v18_trades.html
  - chase_up/results/v19_trades.html

Per-trade section includes K-line (with MA20/MA60 overlay), volume,
and MACD subchart with entry/exit markers. Same ECharts pattern as
chase_up/render_v3_trades_html.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chase_up.backtest import run_backtest
from chase_up.presets import PRESETS
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from chase_up.data import load_panel
from hiagent_config import DB_PATH

TOP2 = [
    "chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082",
    "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082",
]

START = "2025-09-19"
END = "2026-09-19"
WINDOW_BEFORE = 30
WINDOW_AFTER = 10

RESULTS_DIR = Path("/Users/holeon/code/hiagent/chase_up/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_panel_for(preset: str) -> pd.DataFrame:
    p = PRESETS[preset]
    universe = set(load_universe(p["universe"], DB_PATH, asof_date=START))
    panel = load_panel(DB_PATH, START, END, universe=universe)
    return compute_indicators(panel)


def _fetch_window(panel: pd.DataFrame, thscode: str, entry_date, exit_date) -> pd.DataFrame:
    code_panel = panel[panel["thscode"] == thscode].sort_values("date").reset_index(drop=True)
    if code_panel.empty:
        return code_panel
    e_lo = entry_date - pd.Timedelta(days=WINDOW_BEFORE)
    e_hi = exit_date + pd.Timedelta(days=WINDOW_AFTER)
    mask = (code_panel["date"] >= e_lo) & (code_panel["date"] <= e_hi)
    return code_panel.loc[mask].reset_index(drop=True)


def _echarts_option(window: pd.DataFrame, trade: dict) -> dict:
    dates = [d.strftime("%Y-%m-%d") for d in window["date"]]
    kline = [
        [float(r.open), float(r.close), float(r.low), float(r.high)]
        for r in window.itertuples()
    ]
    panel2 = window.copy()
    panel2["ma20"] = panel2["close"].rolling(20).mean()
    panel2["ma60"] = panel2["close"].rolling(60).mean()

    def _series_line(col: str, name: str, color: str):
        return {
            "name": name,
            "type": "line",
            "data": [None if pd.isna(v) else float(v) for v in panel2[col]],
            "smooth": True,
            "lineStyle": {"width": 1, "color": color},
            "showSymbol": False,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
        }

    volumes = [
        {
            "value": float(r.volume) if not pd.isna(r.volume) else 0,
            "itemStyle": {"color": "#ef232a" if r.close >= r.open else "#14b143"},
        }
        for r in window.itertuples()
    ]

    macd_bar = [
        {
            "value": float(r.macd_bar) if not pd.isna(r.macd_bar) else 0,
            "itemStyle": {"color": "#ef232a" if r.macd_bar >= 0 else "#14b143"},
        }
        for r in window.itertuples()
    ]
    dif = [None if pd.isna(v) else float(v) for v in window["macd_dif"]]
    dea = [None if pd.isna(v) else float(v) for v in window["macd_dea"]]

    entry_date_str = trade["entry_date"].strftime("%Y-%m-%d")
    exit_date_str = trade["exit_date"].strftime("%Y-%m-%d")
    entry_price = trade["entry_price"]
    exit_price = trade["exit_price"]

    try:
        entry_idx = dates.index(entry_date_str)
    except ValueError:
        entry_idx = None
    try:
        exit_idx = dates.index(exit_date_str)
    except ValueError:
        exit_idx = None

    marklines = []
    if entry_idx is not None:
        marklines.append(
            {"yAxis": entry_price,
             "label": {"formatter": f"Entry {entry_price:.2f}", "color": "#fa8c16", "position": "end"},
             "lineStyle": {"color": "#fa8c16", "type": "dashed", "width": 1}}
        )
        marklines.append(
            {"xAxis": entry_idx,
             "label": {"formatter": "买入", "color": "#fa8c16", "position": "end"},
             "lineStyle": {"color": "#fa8c16", "type": "dashed", "width": 1}}
        )
    if exit_idx is not None:
        marklines.append(
            {"yAxis": exit_price,
             "label": {"formatter": f"Exit {exit_price:.2f}", "color": "#722ed1", "position": "end"},
             "lineStyle": {"color": "#722ed1", "type": "dashed", "width": 1}}
        )
        marklines.append(
            {"xAxis": exit_idx,
             "label": {"formatter": "卖出", "color": "#722ed1", "position": "end"},
             "lineStyle": {"color": "#722ed1", "type": "dashed", "width": 1}}
        )

    return {
        "animation": False,
        "title": {
            "text": (
                f"{trade['thscode']}  {entry_date_str} → {exit_date_str}  "
                f"({trade['exit_reason']})  net {trade['net_pnl']:+,.0f} ({trade['net_return']*100:+.2f}%)"
            ),
            "subtext": (
                f"起始资金 ¥{trade.get('cash_before', 0):>13,.0f}  →  "
                f"结束资金 ¥{trade.get('cash_after', 0):>13,.0f}  "
                f"(Δ ¥{trade['cash_after'] - trade['cash_before']:+,.0f})"
            ),
            "left": "center",
            "textStyle": {"fontSize": 13},
            "subtextStyle": {"fontSize": 11, "color": "#666"},
        },
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "legend": {"data": ["K线", "MA20", "MA60", "VOL", "DIF", "DEA", "MACD"], "top": 30},
        "axisPointer": {"link": [{"xAxisIndex": "all"}]},
        "grid": [
            {"left": "8%", "right": "8%", "height": "52%"},
            {"left": "8%", "right": "8%", "top": "72%", "height": "14%"},
            {"left": "8%", "right": "8%", "top": "88%", "height": "12%"},
        ],
        "xAxis": [
            {"type": "category", "data": dates, "scale": True, "boundaryGap": False,
             "axisLabel": {"fontSize": 9}, "splitLine": {"show": False},
             "axisPointer": {"z": 100}},
            {"type": "category", "data": dates, "gridIndex": 1, "scale": True, "boundaryGap": False,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "splitLine": {"show": False}, "axisPointer": {"z": 100}},
            {"type": "category", "data": dates, "gridIndex": 2, "scale": True, "boundaryGap": False,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "splitLine": {"show": False}, "axisPointer": {"label": {"show": True, "formatter": "MACD"}}, "z": 100},
        ],
        "yAxis": [
            {"scale": True, "splitArea": {"show": True},
             "splitLine": {"show": True, "lineStyle": {"color": "#eee"}},
             "markLine": {"data": marklines}},
            {"scale": True, "gridIndex": 1, "splitNumber": 2,
             "axisLabel": {"fontSize": 9}, "axisLine": {"show": False},
             "axisTick": {"show": False}, "splitLine": {"show": False}},
            {"scale": True, "gridIndex": 2, "splitNumber": 2,
             "axisLabel": {"fontSize": 9}, "axisLine": {"show": False},
             "axisTick": {"show": False}, "splitLine": {"show": False}},
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": [0, 1, 2], "start": 30, "end": 100},
            {"show": True, "xAxisIndex": [0, 1, 2], "type": "slider", "bottom": 8,
             "start": 30, "end": 100, "height": 14},
        ],
        "series": [
            {
                "name": "K线", "type": "candlestick", "data": kline,
                "itemStyle": {"color": "#ef232a", "color0": "#14b143",
                              "borderColor": "#ef232a", "borderColor0": "#14b143"},
                "markLine": {"symbol": "none", "data": marklines, "silent": True},
            },
            _series_line("ma20", "MA20", "#faad14"),
            _series_line("ma60", "MA60", "#1890ff"),
            {"name": "VOL", "type": "bar", "data": volumes, "xAxisIndex": 1, "yAxisIndex": 1},
            {"name": "DIF", "type": "line", "data": dif,
             "xAxisIndex": 2, "yAxisIndex": 2,
             "lineStyle": {"width": 1, "color": "#fa8c16"}, "showSymbol": False},
            {"name": "DEA", "type": "line", "data": dea,
             "xAxisIndex": 2, "yAxisIndex": 2,
             "lineStyle": {"width": 1, "color": "#722ed1"}, "showSymbol": False},
            {"name": "MACD", "type": "bar", "data": macd_bar,
             "xAxisIndex": 2, "yAxisIndex": 2},
        ],
    }


def _fmt_date(x):
    return x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)


def _table_row(i: int, t: dict, cash_before: float, cash_after: float) -> str:
    color = "#14b143" if t["exit_reason"] == "TP" else (
        "#ef232a" if t["exit_reason"] == "SL" else "#8c8c8c"
    )
    cash_color = "#14b143" if cash_after >= cash_before else "#ef232a"
    return (
        f"<tr style='cursor:pointer' onclick=\"document.getElementById('trade-{i+1}').scrollIntoView({{behavior:'smooth'}})\">"
        f"<td class='center'>{i+1}</td>"
        f"<td>{_fmt_date(t['entry_date'])}</td><td>{_fmt_date(t['exit_date'])}</td>"
        f"<td>{t['thscode']}</td>"
        f"<td style='color:{color};font-weight:600'>{t['exit_reason']}</td>"
        f"<td>{t['sub_signal_type']}</td>"
        f"<td class='num'>{t['entry_price']:.2f}</td>"
        f"<td class='num'>{t['exit_price']:.2f}</td>"
        f"<td class='num'>{t['hold_days']}</td>"
        f"<td class='num'>{t['size']:,}</td>"
        f"<td class='num'>{t['atr_pct']*100:.2f}%</td>"
        f"<td class='num' style='color:{color}'>{t['net_pnl']:+,.0f}</td>"
        f"<td class='num' style='color:{color}'>{t['net_return']*100:+.2f}%</td>"
        f"<td class='num'>{cash_before:>13,.0f}</td>"
        f"<td class='num' style='color:{cash_color};font-weight:600'>{cash_after:>13,.0f}</td>"
        f"</tr>"
    )


def _cash_before_after(initial_capital: float, trades: pd.DataFrame) -> list[tuple[float, float]]:
    cash = float(initial_capital)
    out: list[tuple[float, float]] = []
    for row in trades.itertuples():
        cash_before = cash
        cash_after = cash_before + float(row.net_pnl)
        out.append((cash_before, cash_after))
        cash = cash_after
    return out


def render_one(preset: str) -> None:
    """Render trades for one preset into its own HTML file."""
    from chase_up.backtest import INITIAL_CAPITAL

    short = preset.split("_")[1]  # "v18" or "v19"
    out_html = RESULTS_DIR / f"{short}_trades.html"

    print(f"\n=== Rendering {preset} ===")
    res = run_backtest(preset, START, END, DB_PATH)
    trades = res["trades"]
    metrics = res["metrics"] if "metrics" in res else res
    panel = _load_panel_for(preset)

    cash_trace = _cash_before_after(INITIAL_CAPITAL, trades)
    print(f"  Loaded {len(trades)} trades + panel for {panel['thscode'].nunique()} stocks")

    chart_options = []
    for i, row in enumerate(trades.itertuples(), 1):
        cash_before, cash_after = cash_trace[i - 1]
        t = {
            "entry_date": row.entry_date, "exit_date": row.exit_date,
            "thscode": row.thscode, "exit_reason": row.exit_reason,
            "entry_price": row.entry_price, "exit_price": row.exit_price,
            "size": row.size, "net_pnl": row.net_pnl, "net_return": row.net_return,
            "sub_signal_type": row.sub_signal_type, "atr_pct": row.atr_pct,
            "cash_before": cash_before, "cash_after": cash_after,
        }
        win = _fetch_window(panel, t["thscode"], t["entry_date"], t["exit_date"])
        if win.empty:
            chart_options.append(None)
            continue
        chart_options.append(_echarts_option(win, t))
        if i % 10 == 0:
            print(f"  chart {i}/{len(trades)} built")

    summary_html = []
    for k in ("preset", "start", "end", "trades", "win_rate", "cagr", "sharpe",
              "max_dd", "tp_count", "sl_count", "time_count", "eod_count",
              "final_equity", "exposure"):
        if k in metrics:
            v = metrics[k]
            if isinstance(v, float) and 0 < abs(v) < 1 and k != "preset":
                if k == "win_rate":
                    v = f"{v*100:.2f}%"
                elif k in ("cagr", "max_dd"):
                    v = f"{v*100:+.2f}%"
                else:
                    v = f"{v:.4f}"
            summary_html.append(
                f"<div class='metric'><div class='k'>{k}</div><div class='v'>{v}</div></div>"
            )

    table_rows = "\n".join(_table_row(
        i,
        {
            "entry_date": r.entry_date, "exit_date": r.exit_date,
            "thscode": r.thscode, "exit_reason": r.exit_reason,
            "sub_signal_type": r.sub_signal_type,
            "entry_price": r.entry_price, "exit_price": r.exit_price,
            "hold_days": r.hold_days, "size": r.size, "atr_pct": r.atr_pct,
            "net_pnl": r.net_pnl, "net_return": r.net_return,
        },
        cash_before, cash_after,
    ) for i, ((cash_before, cash_after), r) in enumerate(zip(cash_trace, trades.itertuples())))

    trade_sections = []
    for i, opt in enumerate(chart_options, 1):
        if opt is None:
            trade_sections.append(
                f"<section id='trade-{i}' class='trade'><h3>#{i}</h3>"
                f"<p style='color:#999'>⚠ K-line window not available</p></section>"
            )
            continue
        trade_sections.append(
            f"<section id='trade-{i}' class='trade'>"
            f"<div id='chart-{i}' style='width:100%;height:520px'></div>"
            f"<script type='text/json' id='opt-{i}'>{json.dumps(opt, default=str)}</script>"
            f"</section>"
        )

    chart_init = "\n".join(
        f"echarts.init(document.getElementById('chart-{i}')).setOption(JSON.parse(document.getElementById('opt-{i}').textContent));"
        for i, opt in enumerate(chart_options, 1) if opt is not None
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{preset} — Trades Report</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:24px;color:#222;background:#fafafa}}
header{{background:#fff;padding:24px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.05);margin-bottom:16px}}
h1{{margin:0 0 8px;font-size:22px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-top:12px}}
.metric{{background:#f5f5f5;padding:10px;border-radius:4px}}
.metric .k{{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px}}
.metric .v{{font-size:16px;font-weight:600;color:#222;margin-top:4px}}
nav.toc{{background:#fff;padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:13px}}
nav.toc a{{color:#1890ff;text-decoration:none;margin-right:12px}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:12px;margin-bottom:24px;table-layout:fixed}}
th,td{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;font-variant-numeric:tabular-nums}}
th{{background:#fafafa;font-weight:600;color:#666;position:sticky;top:0;z-index:2}}
th.num,td.num{{text-align:right}}
th.center,td.center{{text-align:center}}
tr:hover{{background:#f0f7ff}}
section.trade{{background:#fff;padding:16px;border-radius:8px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
section.trade h3{{margin:0 0 8px;font-size:13px;color:#666}}
.legend{{display:flex;gap:12px;font-size:11px;color:#888;margin-bottom:16px;padding:8px;background:#fff;border-radius:4px}}
.legend span::before{{content:"●";margin-right:4px}}
.legend .tp::before{{color:#14b143}}
.legend .sl::before{{color:#ef232a}}
.legend .time::before{{color:#8c8c8c}}
</style>
</head>
<body>
<header>
  <h1>chase_up — {preset}</h1>
  <div style="font-size:12px;color:#888">回测区间 {START} → {END}  · 初始资金 1,000,000  · 信号总数 {metrics.get('signals','?')}</div>
  <div class="metrics">{"".join(summary_html)}</div>
  <div class="legend">
    <span class="tp">TP 止盈</span><span class="sl">SL 止损</span><span class="time">time 超时</span>
  </div>
</header>

<nav class="toc">
  <strong>汇总表 ↓</strong>
</nav>

<table>
<colgroup>
<col style="width:36px"><col><col><col style="width:96px"><col style="width:48px">
<col style="width:56px"><col class="num"><col class="num"><col class="num" style="width:48px">
<col class="num" style="width:80px"><col class="num" style="width:64px"><col class="num"><col class="num">
<col class="num"><col class="num">
</colgroup>
<thead><tr>
<th>#</th><th>入场</th><th>出场</th><th>代码</th><th>原因</th>
<th>子信号</th><th class="num">入场价</th><th class="num">出场价</th><th class="num">持仓日</th>
<th class="num">股数</th><th class="num">ATR%</th><th class="num">净盈亏</th><th class="num">净收益</th>
<th class="num">起始资金</th><th class="num">结束资金</th>
</tr></thead>
<tbody>
{table_rows}
</tbody>
</table>

<h2 style="margin-top:32px">逐笔交易 (K线 + MACD)</h2>
<p style="font-size:12px;color:#888">每段对应上表一行 — 点击图表可缩放/平移；橙线=入场价/日，紫线=出场价/日。</p>

{"".join(trade_sections)}

<script>
{chart_init}
window.addEventListener('resize', () => {{
  document.querySelectorAll('[id^=chart-]').forEach(el => echarts.getInstanceByDom(el)?.resize());
}});
</script>
</body>
</html>"""

    out_html.write_text(html, encoding="utf-8")
    size_kb = out_html.stat().st_size / 1024
    print(f"\n✓ Written {out_html} ({size_kb:.1f} KB, {len(trades)} trades, "
          f"{sum(1 for o in chart_options if o is not None)} charts)")


def main() -> None:
    for preset in TOP2:
        render_one(preset)


if __name__ == "__main__":
    main()
