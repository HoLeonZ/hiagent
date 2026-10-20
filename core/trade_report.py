"""统一交易 HTML 报告渲染器 — 纯函数，零 DB/网络 I/O。

spec: docs/superpowers/specs/2026-10-11-unified-trade-html-report-design.md
CLAUDE.md §6: 渲染层属 Strategy/Inference 侧纯函数，无网络/DB 访问。

输入均由调用方（各引擎 main.py，Control Plane）准备：
  trades:          canonical TRADE_COLS DataFrame（可带额外列，用 trade_extra_cols 声明）
  bars_by_code:    {thscode: DataFrame(date, open, high, low, close[, volume, 指标列...])}
                   价格口径由调用方决定（与成交口径一致），渲染器原样绘制
  preset / window: 报告元信息（window = (start, end) 字符串对）
  out_path:        输出 HTML 路径
  ma_cols:         K 线主图叠加均线列名（缺失列自动跳过）
  macd_cols:       (dif, dea, bar) 三元组 → MACD 副图；None 跳过
  line_cols:       通用折线副图列（如 atr_pct）
  trade_extra_cols: trades 上的额外标量列，在交易卡片中展示（如 cycle 三维分数）

输出：单个 HTML（ECharts CDN 引入），返回写入路径。
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"
BAR_PAD_BEFORE_DAYS = 75  # 入场前回望（覆盖 MA60 暖机 + 趋势上下文）
BAR_PAD_AFTER_DAYS = 15   # 出场后余量


def report_filename(preset: str, ts: datetime | None = None) -> str:
    """统一命名：<preset>_report_<timestamp>.html（spec §架构）。"""
    ts = ts or datetime.now()
    return f"{preset}_report_{ts:%Y%m%d_%H%M%S}.html"


def _esc(s) -> str:
    return html.escape(str(s))


def _num(v, digits: int = 2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if np.isnan(f) else f"{f:,.{digits}f}"


def _pct(v, digits: int = 2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if np.isnan(f) else f"{f * 100:+.{digits}f}%"


def _slice_bars(bars: pd.DataFrame, entry_date, exit_date) -> pd.DataFrame:
    bars = bars.copy()
    bars["date"] = pd.to_datetime(bars["date"])
    lo = pd.Timestamp(entry_date) - pd.Timedelta(days=BAR_PAD_BEFORE_DAYS)
    hi = pd.Timestamp(exit_date) + pd.Timedelta(days=BAR_PAD_AFTER_DAYS)
    return bars[(bars["date"] >= lo) & (bars["date"] <= hi)].reset_index(drop=True)


def _col_series(df: pd.DataFrame, col: str) -> list:
    return [None if pd.isna(v) else round(float(v), 4) for v in df[col]]


def _chart_payload(
    trade: pd.Series,
    bars_by_code: dict[str, pd.DataFrame],
    ma_cols: tuple[str, ...],
    macd_cols: tuple[str, str, str] | None,
    line_cols: tuple[str, ...],
) -> dict | None:
    """单笔交易的图表数据；无 K 线返回 None（调用方降级为文字提示）。"""
    df_all = bars_by_code.get(str(trade["thscode"]))
    if df_all is None or df_all.empty:
        return None
    df = _slice_bars(df_all, trade["entry_date"], trade["exit_date"])
    if df.empty:
        return None
    payload: dict = {
        "dates": [str(pd.Timestamp(d).date()) for d in df["date"]],
        # ECharts candlestick 数据序: [open, close, low, high]
        "ohlc": [[round(float(r.open), 3), round(float(r.close), 3),
                  round(float(r.low), 3), round(float(r.high), 3)]
                 for r in df.itertuples()],
        "entry": {"date": str(pd.Timestamp(trade["entry_date"]).date()),
                  "price": round(float(trade["entry_price"]), 3)},
        "exit": {"date": str(pd.Timestamp(trade["exit_date"]).date()),
                 "price": round(float(trade["exit_price"]), 3)},
    }
    if "volume" in df.columns:
        payload["volume"] = _col_series(df, "volume")
    mas = {c: _col_series(df, c) for c in ma_cols if c in df.columns}
    if mas:
        payload["mas"] = mas
    if macd_cols and all(c in df.columns for c in macd_cols):
        payload["macd"] = {c: _col_series(df, c) for c in macd_cols}
    lines = {c: _col_series(df, c) for c in line_cols if c in df.columns}
    if lines:
        payload["lines"] = lines
    return payload


#: §5 (audit 2026-10-15) Attribution Mandate —— CLAUDE.md §5 verbatim:
#:   "Headline returns MUST be reported alongside benchmark-relative excess
#:    return (index or style basket). Pure style-beta replication MUST NOT be
#:    presented as alpha."
#:
#: 本地行情库**没有任何指数序列**(`dim_symbol.asset_type` 全为 a-share)——
#: 但**这不等于"归因不可计算"**(2026-10-18 更正,附六十二):§5 允许
#: 「index **or style basket**」,而**风格篮子**这一支已经落地并在每次回测里发布 ——
#: `core/benchmark.py` 的「该窗口 PIT 宇宙等权买入持有」,产物带
#: `benchmark_kind / benchmark_return / benchmark_members / excess_return`。
#: 此前这段文字写的是"归因暂不可计算",它把**指数那一支**的缺口说成了**整条 §5 要求**
#: 的缺口 —— 读报告的人因此会以为 §5 没被满足,而实际上只是**换了一支基准**。
#: §5 真正禁止的是"把裸绝对收益当 alpha 呈现",这一点仍然必须显式标注。
UNATTRIBUTED_NOTICE = (
    "未归因(CLAUDE.md §5):本报告展示的是绝对收益,不含**指数**基准相对超额 —— "
    "本地行情库无指数序列。**但这不等于 §5 未满足**:风格篮子基准"
    "(该窗口 PIT 宇宙等权买入持有)已随回测产物发布 —— 见该次运行的 metrics 里的 "
    "benchmark_kind / benchmark_return / excess_return;指数基准的补齐机制见 "
    "core/benchmark.py 与 dna_stats/attribution.py。"
)


def _summary_html(trades: pd.DataFrame, preset: str, window: tuple[str, str]) -> str:
    n = len(trades)
    net = trades["net_pnl"].astype(float) if n else pd.Series(dtype=float)
    wins = int((net > 0).sum())
    win_rate = wins / n if n else 0.0
    total_net = float(net.sum()) if n else 0.0
    avg_ret = float(trades["net_return"].astype(float).mean()) if n else 0.0
    return (
        '<section class="summary">'
        f"<h1>{_esc(preset)} — 交易报告</h1>"
        f"<p>回测窗口: {_esc(window[0])} → {_esc(window[1])} ｜ "
        f"交易数: {n} ｜ 胜率: {win_rate * 100:.1f}% ｜ "
        f"总净收益: {total_net:,.0f} ｜ 平均单笔净收益率: {avg_ret * 100:+.2f}%</p>"
        f'<p class="attribution">{_esc(UNATTRIBUTED_NOTICE)}</p>'
        "</section>"
    )


_TABLE_COLS = (
    "entry_date", "exit_date", "thscode", "exit_reason",
    "entry_price", "exit_price", "size", "hold_days",
    "gross_pnl", "fees", "net_pnl", "net_return",
    "atr_pct", "sub_signal_type",
)


def _fmt_cell(col: str, v) -> str:
    if col in ("entry_price", "exit_price"):
        return _num(v)
    if col in ("gross_pnl", "fees", "net_pnl"):
        return _num(v, 0)
    if col in ("net_return", "atr_pct"):
        return _pct(v)
    if v is None or pd.isna(v):
        return ""
    return _esc(v)


def _trades_table_html(trades: pd.DataFrame, extra_cols: tuple[str, ...]) -> str:
    cols = ([c for c in _TABLE_COLS if c in trades.columns]
            + [c for c in extra_cols if c in trades.columns])
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    rows = []
    for _, t in trades.iterrows():
        tds = "".join(f"<td>{_fmt_cell(c, t[c])}</td>" for c in cols)
        try:
            win = float(t["net_pnl"]) > 0
        except (TypeError, ValueError):
            win = False
        rows.append(f'<tr class="{"win" if win else "loss"}">{tds}</tr>')
    return ('<table class="trades"><thead><tr>' + head + "</tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _card_html(
    i: int,
    trade: pd.Series,
    payload: dict | None,
    extra_cols: tuple[str, ...],
) -> tuple[str, dict | None]:
    code = _esc(trade["thscode"])
    extras = " ｜ ".join(
        f"{_esc(c)}: {_esc(round(float(trade[c]), 4))}"
        for c in extra_cols
        if c in trade.index and pd.notna(trade[c])
    )
    entry_d = str(pd.Timestamp(trade['entry_date']).date())
    exit_d = str(pd.Timestamp(trade['exit_date']).date())
    head = (
        f"#{i + 1} {code} ｜ {_esc(entry_d)} → {_esc(exit_d)} ｜ "
        f"{_esc(trade.get('exit_reason', '') or '—')} ｜ "
        f"入场 {_num(trade['entry_price'])} / 出场 {_num(trade['exit_price'])} ｜ "
        f"净收益率 {_pct(trade['net_return'])}"
        + (f" ｜ {extras}" if extras else "")
    )
    if payload is None:
        return (f'<details class="card"><summary>{head}</summary>'
                '<p class="nodata">(无 K 线数据)</p></details>'), None
    cid = f"chart_{i}"
    return (f'<details class="card"><summary>{head}</summary>'
            f'<div id="{cid}" class="chart"></div></details>',
            {"id": cid, "data": payload})


_JS = r"""
const MA_COLORS = {ma5:'#9e9e9e',ma10:'#78909c',ma20:'#42a5f5',ma60:'#ffa726',ma120:'#ab47bc'};

function buildOption(d) {
  const panels = ['main'];
  if (d.volume && d.volume.length) panels.push('volume');
  if (d.macd) panels.push('macd');
  if (d.lines) panels.push('lines');
  const n = panels.length;
  const mainH = n === 1 ? 88 : 44;
  const subH = n === 1 ? 0 : (88 - mainH - 2 * (n - 1)) / (n - 1);
  const grids = [], xAxes = [], yAxes = [], series = [];
  const giOf = {};
  let top = 4;
  panels.forEach((p, gi) => {
    giOf[p] = gi;
    const h = p === 'main' ? mainH : subH;
    grids.push({left: 64, right: 72, top: top + '%', height: h + '%'});
    xAxes.push({type: 'category', data: d.dates, gridIndex: gi,
                axisLabel: {show: gi === n - 1}, axisLine: {onZero: false}});
    yAxes.push({scale: true, gridIndex: gi, splitNumber: 2});
    top += h + 2;
  });
  const marks = [
    {coord: [d.entry.date, d.entry.price], value: '入', itemStyle: {color: '#1565c0'}},
    {coord: [d.exit.date, d.exit.price], value: '出', itemStyle: {color: '#6a1b9a'}}
  ];
  const sigIdx = d.dates.indexOf(d.entry.date) - 1;
  if (sigIdx >= 0) {
    marks.push({coord: [d.dates[sigIdx], d.ohlc[sigIdx][1]], value: '信',
                itemStyle: {color: '#ef6c00'}});
  }
  series.push({type: 'candlestick', name: 'K', data: d.ohlc,
               xAxisIndex: 0, yAxisIndex: 0,
               itemStyle: {color: '#c62828', color0: '#2e7d32',
                           borderColor: '#c62828', borderColor0: '#2e7d32'},
               markPoint: {symbolSize: 32, data: marks}});
  Object.entries(d.mas || {}).forEach(([name, vals]) => {
    series.push({type: 'line', name: name.toUpperCase(), data: vals,
                 xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false,
                 lineStyle: {width: 1.2, color: MA_COLORS[name] || '#607d8b'}});
  });
  if (giOf.volume !== undefined) {
    series.push({type: 'bar', name: 'VOL', data: d.volume,
                 xAxisIndex: giOf.volume, yAxisIndex: giOf.volume,
                 itemStyle: {color: '#b0bec5'}});
  }
  if (giOf.macd !== undefined) {
    const gi = giOf.macd, keys = Object.keys(d.macd);
    series.push({type: 'bar', name: keys[2], data: d.macd[keys[2]],
                 xAxisIndex: gi, yAxisIndex: gi, itemStyle: {color: '#ef9a9a'}});
    series.push({type: 'line', name: keys[0], data: d.macd[keys[0]],
                 xAxisIndex: gi, yAxisIndex: gi, showSymbol: false,
                 lineStyle: {width: 1.1, color: '#42a5f5'}});
    series.push({type: 'line', name: keys[1], data: d.macd[keys[1]],
                 xAxisIndex: gi, yAxisIndex: gi, showSymbol: false,
                 lineStyle: {width: 1.1, color: '#ffa726'}});
  }
  if (giOf.lines !== undefined) {
    const gi = giOf.lines;
    Object.entries(d.lines).forEach(([name, vals]) => {
      series.push({type: 'line', name: name, data: vals,
                   xAxisIndex: gi, yAxisIndex: gi, showSymbol: false,
                   smooth: true, lineStyle: {width: 1.1}});
    });
  }
  return {animation: false, grid: grids, xAxis: xAxes, yAxis: yAxes,
          series: series, tooltip: {trigger: 'axis'},
          axisPointer: {link: [{xAxisIndex: 'all'}]},
          dataZoom: [{type: 'inside', xAxisIndex: panels.map((_, i) => i)}]};
}

REPORT.charts.forEach(cd => {
  const el = document.getElementById(cd.id);
  if (el) echarts.init(el).setOption(buildOption(cd.data));
});
"""

_PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>__TITLE__</title>
<script src="__CDN__"></script>
<style>
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;color:#222}
.summary{border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin-bottom:16px;background:#fafafa}
.summary h1{font-size:18px;margin:0 0 8px}
table.trades{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:16px}
table.trades th,table.trades td{border:1px solid #e0e0e0;padding:4px 6px;text-align:right;white-space:nowrap}
table.trades th{background:#f5f5f5}
tr.win td{color:#c62828}
tr.loss td{color:#2e7d32}
details.card{border:1px solid #e0e0e0;border-radius:8px;margin-bottom:8px;padding:6px 10px}
details.card summary{cursor:pointer;font-size:13px}
.chart{width:100%;height:480px}
.nodata{color:#999}
</style></head><body>
__SUMMARY__
__TABLE__
__CARDS__
<script>
const REPORT = __CHARTS_JSON__;
__JS__
</script>
</body></html>"""


def render_trade_report(
    *,
    trades: pd.DataFrame,
    bars_by_code: dict[str, pd.DataFrame],
    preset: str,
    window: tuple[str, str],
    out_path: Path,
    ma_cols: tuple[str, ...] = (),
    macd_cols: tuple[str, str, str] | None = None,
    line_cols: tuple[str, ...] = (),
    trade_extra_cols: tuple[str, ...] = (),
) -> Path:
    """渲染统一交易 HTML 报告，返回写入路径。纯函数，零 DB/网络 I/O。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cards: list[str] = []
    charts: list[dict] = []
    for i, (_, t) in enumerate(trades.iterrows()):
        payload = _chart_payload(t, bars_by_code, ma_cols, macd_cols, line_cols)
        card, chart = _card_html(i, t, payload, trade_extra_cols)
        cards.append(card)
        if chart is not None:
            charts.append(chart)

    page = (_PAGE
            .replace("__TITLE__", _esc(preset) + " — 交易报告")
            .replace("__CDN__", ECHARTS_CDN)
            .replace("__SUMMARY__", _summary_html(trades, preset, window))
            .replace("__TABLE__", _trades_table_html(trades, trade_extra_cols))
            .replace("__CARDS__", "\n".join(cards))
            .replace("__CHARTS_JSON__", json.dumps({"charts": charts},
                                                   ensure_ascii=False)
                                          .replace("</", "<\\/"))
            .replace("__JS__", _JS))
    out_path.write_text(page, encoding="utf-8")
    return out_path
