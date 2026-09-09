"""
v33 TP=6% HTML 生成器

- 自包含 (数据全部内联)
- 32 笔交易全部展示, 2 列网格
- 每笔: 顶部信息 + K线 + MACD 双图 (共用 X 轴, 紧凑布局)
- 月度收益小卡片
"""
import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "results"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>v33 策略 — TP=6% 全部 32 笔交易</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0f1419; color: #e6e6e6; padding: 16px;
    line-height: 1.45; font-size: 13px;
  }
  .container { max-width: 1600px; margin: 0 auto; }
  h1 { color: #f5f5f5; font-size: 22px; margin-bottom: 6px; }
  .subtitle { color: #888; font-size: 12px; margin-bottom: 16px; }
  .summary {
    display: grid; grid-template-columns: repeat(6, 1fr);
    gap: 10px; margin-bottom: 20px;
  }
  .summary-card {
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px; padding: 10px 14px;
  }
  .summary-card .label { font-size: 11px; color: #888; }
  .summary-card .value { font-size: 18px; font-weight: 700; margin-top: 2px; }
  .summary-card .value.green { color: #26a69a; }
  .summary-card .value.red { color: #ef5350; }

  .monthly {
    display: flex; gap: 6px; flex-wrap: wrap;
    margin-bottom: 20px; padding: 10px;
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px;
  }
  .month-cell {
    flex: 1; min-width: 80px; padding: 6px 8px;
    background: #0f1419; border-radius: 4px;
    text-align: center; font-size: 11px;
  }
  .month-cell .ml { color: #888; }
  .month-cell .mn { color: #b0b0b0; font-size: 13px; font-weight: 600; }
  .month-cell .mp.green { color: #26a69a; font-weight: 600; }
  .month-cell .mp.red { color: #ef5350; font-weight: 600; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .trade {
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 6px; padding: 10px;
  }
  .trade-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 6px;
  }
  .trade-title { font-size: 13px; font-weight: 600; color: #f5f5f5; }
  .trade-meta { font-size: 10px; color: #888; }
  .trade-tag {
    display: inline-block; padding: 2px 8px;
    border-radius: 3px; font-size: 10px; font-weight: 700;
  }
  .tag-tp { background: #1b5e20; color: #a5d6a7; }
  .tag-sl { background: #7f1d1d; color: #ffab91; }
  .tag-time { background: #5d4037; color: #ffcc80; }

  .features {
    display: grid; grid-template-columns: repeat(7, 1fr);
    gap: 4px; margin-bottom: 6px;
    font-size: 10px;
  }
  .feat {
    background: #0f1419; padding: 4px 6px;
    border-radius: 3px;
  }
  .feat .lbl { color: #888; font-size: 9px; }
  .feat .val { color: #f5f5f5; font-size: 11px; font-weight: 600; }
  .feat .val.green { color: #26a69a; }
  .feat .val.red { color: #ef5350; }

  .chart-row { display: flex; flex-direction: column; gap: 4px; }
  .chart-svg { width: 100%; height: auto; display: block; }
  .legend {
    display: flex; gap: 8px; font-size: 9px; color: #888;
    margin-bottom: 2px; padding-left: 2px;
  }
  .legend-item { display: flex; align-items: center; gap: 3px; }
  .legend-dot { width: 8px; height: 8px; border-radius: 1px; }
  .legend-line { width: 12px; height: 2px; }
  .footer {
    text-align: center; color: #555; font-size: 11px;
    padding: 20px 0 8px;
  }
</style>
</head>
<body>
<div class="container">
  <h1>v33 策略 — TP=6% 全部 32 笔交易</h1>
  <div class="subtitle">
    下跌趋势反弹做空 (柱转红) | TP=6% / SL=5% / Time=30 | 12 个月 (2025-09 ~ 2026-09)
  </div>

  <div class="summary" id="summary"></div>
  <div class="monthly" id="monthly"></div>
  <div class="grid" id="grid"></div>

  <div class="footer">
    v33 | 数据源: hithink-finance DuckDB | 范围: 2025-09 至 2026-09 | 非沪深300/中证500/金融板块
  </div>
</div>

<script>
const TRADES_DATA = __DATA_JSON__;
const METRICS = __METRICS_JSON__;

function fmt(n, digits=2) {
  if (n === null || n === undefined || isNaN(n)) return "-";
  return Number(n).toFixed(digits);
}

function buildSummary() {
  const el = document.getElementById("summary");
  const cards = [
    {label: "总收益", value: (METRICS.total_yield * 100).toFixed(2) + "%", cls: METRICS.total_yield >= 0 ? "green" : "red"},
    {label: "笔数", value: METRICS.trades, cls: ""},
    {label: "胜率", value: (METRICS.win_rate * 100).toFixed(1) + "%", cls: "green"},
    {label: "最大回撤", value: (METRICS.max_dd * 100).toFixed(2) + "%", cls: "red"},
    {label: "笔均收益", value: (METRICS.avg_pnl * 100).toFixed(2) + "%", cls: METRICS.avg_pnl >= 0 ? "green" : "red"},
    {label: "平均持仓", value: METRICS.avg_hold.toFixed(1) + "d", cls: ""},
  ];
  el.innerHTML = cards.map(c => `
    <div class="summary-card">
      <div class="label">${c.label}</div>
      <div class="value ${c.cls}">${c.value}</div>
    </div>
  `).join("");
}

function buildMonthly() {
  const el = document.getElementById("monthly");
  const months = METRICS.monthly;
  const keys = Object.keys(months).sort();
  el.innerHTML = keys.map(k => {
    const m = months[k];
    const pnlCls = m.pnl_sum >= 0 ? "green" : "red";
    return `<div class="month-cell">
      <div class="ml">${k}</div>
      <div class="mn">${m.n}笔 / ${(m.wins/m.n*100).toFixed(0)}%胜</div>
      <div class="mp ${pnlCls}">${(m.pnl_sum*100).toFixed(2)}%</div>
    </div>`;
  }).join("");
}

function buildCandleChart(trade, W, H) {
  const candles = trade.candles;
  const padL = 4, padR = 36, padT = 8, padB = 14;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  let allPrices = [];
  candles.forEach(c => {
    if (c.ma20 !== null) allPrices.push(c.ma20);
    if (c.ma60 !== null) allPrices.push(c.ma60);
    allPrices.push(c.high, c.low);
  });
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const padP = (maxP - minP) * 0.05;
  const pMin = minP - padP;
  const pMax = maxP + padP;

  const n = candles.length;
  const slotW = innerW / n;
  const candleW = Math.max(slotW * 0.65, 1);

  const yOf = (price) => padT + innerH - (price - pMin) / (pMax - pMin) * innerH;
  const xOf = (i) => padL + slotW * i + slotW / 2;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" preserveAspectRatio="xMidYMid meet">`;

  for (let k = 0; k <= 3; k++) {
    const y = padT + innerH * k / 3;
    const price = pMax - (pMax - pMin) * k / 3;
    svg += `<line x1="${padL}" y1="${y}" x2="${padL + innerW}" y2="${y}" stroke="#2a3540" stroke-width="0.4"/>`;
    svg += `<text x="${padL + innerW + 2}" y="${y + 2.5}" font-size="8" fill="#888">${price.toFixed(2)}</text>`;
  }

  let ma60Path = "";
  candles.forEach((c, i) => {
    if (c.ma60 === null) return;
    const x = xOf(i);
    const y = yOf(c.ma60);
    ma60Path += (ma60Path ? " L" : "M") + x.toFixed(1) + "," + y.toFixed(1);
  });
  if (ma60Path) svg += `<path d="${ma60Path}" stroke="#ffa726" stroke-width="1" fill="none"/>`;

  let ma20Path = "";
  candles.forEach((c, i) => {
    if (c.ma20 === null) return;
    const x = xOf(i);
    const y = yOf(c.ma20);
    ma20Path += (ma20Path ? " L" : "M") + x.toFixed(1) + "," + y.toFixed(1);
  });
  if (ma20Path) svg += `<path d="${ma20Path}" stroke="#42a5f5" stroke-width="1" fill="none"/>`;

  candles.forEach((c, i) => {
    const x = xOf(i);
    const isUp = c.close >= c.open;
    const color = isUp ? "#ef5350" : "#26a69a";
    const yH = yOf(c.high);
    const yL = yOf(c.low);
    const yO = yOf(c.open);
    const yC = yOf(c.close);
    const top = Math.min(yO, yC);
    const bot = Math.max(yO, yC);
    const h = Math.max(bot - top, 0.5);
    svg += `<line x1="${x}" y1="${yH}" x2="${x}" y2="${yL}" stroke="${color}" stroke-width="0.8"/>`;
    svg += `<rect x="${x - candleW / 2}" y="${top}" width="${candleW}" height="${h}" fill="${color}" stroke="${color}"/>`;
  });

  // Signal/entry/exit markers
  const sigX = xOf(trade.sig_idx);
  const entryX = xOf(trade.entry_idx);
  const exitX = trade.exit_idx !== null ? xOf(trade.exit_idx) : null;

  svg += `<line x1="${sigX}" y1="${padT}" x2="${sigX}" y2="${padT + innerH}" stroke="#ffeb3b" stroke-width="0.9" stroke-dasharray="3 2"/>`;
  svg += `<text x="${sigX}" y="${padT + 6}" text-anchor="middle" font-size="8" font-weight="700" fill="#ffeb3b">S</text>`;

  svg += `<line x1="${entryX}" y1="${padT}" x2="${entryX}" y2="${padT + innerH}" stroke="#ab47bc" stroke-width="0.9" stroke-dasharray="2 2"/>`;
  svg += `<text x="${entryX}" y="${padT + 6}" text-anchor="middle" font-size="8" font-weight="700" fill="#ab47bc">E</text>`;

  if (exitX !== null) {
    svg += `<line x1="${exitX}" y1="${padT}" x2="${exitX}" y2="${padT + innerH}" stroke="#26a69a" stroke-width="0.9" stroke-dasharray="2 2"/>`;
    svg += `<text x="${exitX}" y="${padT + 6}" text-anchor="middle" font-size="8" font-weight="700" fill="#26a69a">X</text>`;
  }

  const dateStep = Math.max(1, Math.floor(n / 6));
  candles.forEach((c, i) => {
    if (i % dateStep !== 0 && i !== n - 1) return;
    const x = xOf(i);
    svg += `<text x="${x}" y="${padT + innerH + 9}" text-anchor="middle" font-size="7" fill="#666">${c.date.slice(5)}</text>`;
  });

  svg += "</svg>";
  return svg;
}

function buildMacdChart(trade, W, H) {
  const candles = trade.candles;
  const padL = 4, padR = 36, padT = 6, padB = 14;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  let maxBar = 0;
  candles.forEach(c => {
    if (c.macd_bar !== null) maxBar = Math.max(maxBar, Math.abs(c.macd_bar));
    if (c.dif !== null) maxBar = Math.max(maxBar, Math.abs(c.dif));
    if (c.dea !== null) maxBar = Math.max(maxBar, Math.abs(c.dea));
  });
  const yLimit = maxBar * 1.1;

  const n = candles.length;
  const slotW = innerW / n;
  const barW = Math.max(slotW * 0.7, 1);

  const yOf = (v) => padT + innerH / 2 - v / yLimit * (innerH / 2);
  const yZero = yOf(0);
  const xOf = (i) => padL + slotW * i + slotW / 2;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" preserveAspectRatio="xMidYMid meet">`;

  svg += `<line x1="${padL}" y1="${yZero}" x2="${padL + innerW}" y2="${yZero}" stroke="#4fc3f7" stroke-width="0.8"/>`;
  svg += `<text x="${padL + innerW + 2}" y="${yZero + 2.5}" font-size="8" fill="#4fc3f7">0</text>`;

  for (let k = 1; k <= 2; k++) {
    const vUp = yLimit * k / 2;
    const yUp = yOf(vUp);
    const yDn = yOf(-vUp);
    svg += `<line x1="${padL}" y1="${yUp}" x2="${padL + innerW}" y2="${yUp}" stroke="#2a3540" stroke-width="0.4"/>`;
    svg += `<line x1="${padL}" y1="${yDn}" x2="${padL + innerW}" y2="${yDn}" stroke="#2a3540" stroke-width="0.4"/>`;
    svg += `<text x="${padL + innerW + 2}" y="${yUp + 2.5}" font-size="7" fill="#888">+${vUp.toFixed(2)}</text>`;
    svg += `<text x="${padL + innerW + 2}" y="${yDn + 2.5}" font-size="7" fill="#888">${(-vUp).toFixed(2)}</text>`;
  }

  let difPath = "";
  let deaPath = "";
  candles.forEach((c, i) => {
    if (c.dif !== null) difPath += (difPath ? " L" : "M") + xOf(i).toFixed(1) + "," + yOf(c.dif).toFixed(1);
    if (c.dea !== null) deaPath += (deaPath ? " L" : "M") + xOf(i).toFixed(1) + "," + yOf(c.dea).toFixed(1);
  });
  if (difPath) svg += `<path d="${difPath}" stroke="#ffa726" stroke-width="1.2" fill="none"/>`;
  if (deaPath) svg += `<path d="${deaPath}" stroke="#42a5f5" stroke-width="1.2" fill="none"/>`;

  candles.forEach((c, i) => {
    if (c.macd_bar === null) return;
    const x = xOf(i);
    const yB = yOf(c.macd_bar);
    const top = Math.min(yB, yZero);
    const bot = Math.max(yB, yZero);
    const h = Math.max(bot - top, 0.4);
    const color = c.macd_bar >= 0 ? "#ef5350" : "#26a69a";
    svg += `<rect x="${x - barW / 2}" y="${top}" width="${barW}" height="${h}" fill="${color}" opacity="0.85"/>`;
  });

  const sigX = xOf(trade.sig_idx);
  const entryX = xOf(trade.entry_idx);
  const exitX = trade.exit_idx !== null ? xOf(trade.exit_idx) : null;

  svg += `<line x1="${sigX}" y1="${padT}" x2="${sigX}" y2="${padT + innerH}" stroke="#ffeb3b" stroke-width="0.9" stroke-dasharray="3 2"/>`;
  svg += `<text x="${sigX}" y="${padT + 5}" text-anchor="middle" font-size="8" font-weight="700" fill="#ffeb3b">S</text>`;
  svg += `<line x1="${entryX}" y1="${padT}" x2="${entryX}" y2="${padT + innerH}" stroke="#ab47bc" stroke-width="0.9" stroke-dasharray="2 2"/>`;
  svg += `<text x="${entryX}" y="${padT + 5}" text-anchor="middle" font-size="8" font-weight="700" fill="#ab47bc">E</text>`;
  if (exitX !== null) {
    svg += `<line x1="${exitX}" y1="${padT}" x2="${exitX}" y2="${padT + innerH}" stroke="#26a69a" stroke-width="0.9" stroke-dasharray="2 2"/>`;
    svg += `<text x="${exitX}" y="${padT + 5}" text-anchor="middle" font-size="8" font-weight="700" fill="#26a69a">X</text>`;
  }

  svg += "</svg>";
  return svg;
}

function buildTradeCard(trade, idx) {
  const exitTagCls = trade.exit_reason === "TP" ? "tag-tp"
                     : trade.exit_reason === "SL" ? "tag-sl" : "tag-time";
  const exitLabel = trade.exit_reason === "TP" ? `TP+${(trade.pnl*100).toFixed(2)}%`
                     : trade.exit_reason === "SL" ? `SL-${Math.abs(trade.pnl*100).toFixed(2)}%`
                     : `time${trade.pnl >= 0 ? '+' : ''}${(trade.pnl*100).toFixed(2)}%`;

  const sigBar = trade.sig_macd_bar;
  const sigBarCls = sigBar < 0 ? "green" : "red";

  const features = `
    <div class="feat"><div class="lbl">信号</div><div class="val">${trade.sig_date.slice(5)}</div></div>
    <div class="feat"><div class="lbl">代码</div><div class="val">${trade.thscode}</div></div>
    <div class="feat"><div class="lbl">close/MA60</div><div class="val">${fmt(trade.sig_close)}/${fmt(trade.sig_ma60)}</div></div>
    <div class="feat"><div class="lbl">DIF/DEA</div><div class="val ${trade.sig_dif < 0 ? 'red' : 'green'}">${fmt(trade.sig_dif,3)}/${fmt(trade.sig_dea,3)}</div></div>
    <div class="feat"><div class="lbl">MACD柱</div><div class="val ${sigBarCls}">${fmt(sigBar,3)}</div></div>
    <div class="feat"><div class="lbl">连阳/涨幅</div><div class="val green">${trade.sig_up_streak}d/${fmt(trade.sig_pct_chg,2)}%</div></div>
    <div class="feat"><div class="lbl">出场</div><div class="val">${trade.exit_date.slice(5)} ${trade.exit_day}d</div></div>
  `;

  const candleLegend = `
    <div class="legend">
      <div class="legend-item"><span class="legend-dot" style="background:#ef5350"></span>涨</div>
      <div class="legend-item"><span class="legend-dot" style="background:#26a69a"></span>跌</div>
      <div class="legend-item"><span class="legend-line" style="background:#42a5f5"></span>MA20</div>
      <div class="legend-item"><span class="legend-line" style="background:#ffa726"></span>MA60</div>
      <div class="legend-item"><span class="legend-line" style="background:#ffeb3b"></span>S信号</div>
      <div class="legend-item"><span class="legend-line" style="background:#ab47bc"></span>E入场</div>
      <div class="legend-item"><span class="legend-line" style="background:#26a69a"></span>X出场</div>
    </div>
  `;

  return `
    <div class="trade">
      <div class="trade-header">
        <div>
          <div class="trade-title">#${idx + 1} ${trade.thscode}</div>
          <div class="trade-meta">入场 ${trade.entry_date} @ ${fmt(trade.entry_price)} → 出场 ${trade.exit_price.toFixed(2)}</div>
        </div>
        <div class="trade-tag ${exitTagCls}">${exitLabel}</div>
      </div>
      <div class="features">${features}</div>
      <div class="chart-row">
        ${candleLegend}
        ${buildCandleChart(trade, 760, 200)}
        ${buildMacdChart(trade, 760, 140)}
      </div>
    </div>
  `;
}

buildSummary();
buildMonthly();
document.getElementById("grid").innerHTML =
  TRADES_DATA.map((t, i) => buildTradeCard(t, i)).join("");
</script>
</body>
</html>
"""


def main():
    chart_path = OUTPUT_DIR / "chart_data_v33_tp6.json"
    meta_path = OUTPUT_DIR / "trades_v33_tp6_meta.json"

    with open(chart_path, "r") as f:
        chart_data = json.load(f)
    with open(meta_path, "r") as f:
        meta = json.load(f)

    html = HTML_TEMPLATE
    html = html.replace("__DATA_JSON__", json.dumps(chart_data, ensure_ascii=False, indent=1))
    html = html.replace("__METRICS_JSON__", json.dumps(meta["metrics"], ensure_ascii=False, indent=1))

    output_path = OUTPUT_DIR / "trades_visualization_v33_tp6.html"
    with open(output_path, "w") as f:
        f.write(html)

    print(f"HTML 已生成: {output_path}")
    print(f"大小: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"交易数: {len(chart_data)}")
    print(f"指标: 收益={meta['metrics']['total_yield']*100:+.2f}%, "
          f"胜率={meta['metrics']['win_rate']*100:.1f}%, "
          f"MaxDD={meta['metrics']['max_dd']*100:.2f}%, "
          f"平均持仓={meta['metrics']['avg_hold']:.1f}d")


if __name__ == "__main__":
    main()