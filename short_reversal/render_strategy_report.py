"""v33 动能衰减版策略综合报告 → 单 HTML 文件。

内容:
  1. 策略规则 (五条件 + 出场 + 撮合)
  2. 指标公式
  3. 反-穿越红线状态
  4. 1 年回测结果 (11 笔) vs 旧版 (39 笔) 对比
  5. 11 笔交易明细 (K线 + MACD SVG)
  6. 决策遗留物 (golden 过时、up_streak leaky)

输出: short_reversal/results/strategy_report.html
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from short_reversal.render_trades_html import (
    PRE_SIG_DAYS, POST_EXIT_DAYS, load_panel_for_trade, build_chart_svg,
)
from short_reversal.signals import compute_panel_indicators

DB_PATH = Path("/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb")
RESULTS_DIR = Path(__file__).parent / "results"
BACKTEST_JSON = RESULTS_DIR / "backtest.json"
LEGACY_BACKTEST_JSON = Path("/Users/holeon/code/hiagent/short_reversal/_legacy/results/backtest.json")
GOLDEN_JSON = Path("/Users/holeon/code/hiagent/tests/golden/v33_mainboard_trades.json")
OUTPUT_HTML = RESULTS_DIR / "strategy_report.html"


def build_strategy_card() -> str:
    return """
<div class="card">
  <div class="card-title">入场规则 (A ∧ B ∧ C ∧ D ∧ E)</div>
  <div class="rules">
    <div class="rule">
      <span class="tag tag-a">A</span>
      <div class="rule-body">
        <div class="rule-name">下跌趋势</div>
        <div class="rule-formula"><code>close &lt; MA60</code></div>
        <div class="rule-note">60 日均线下方确认空头格局</div>
      </div>
    </div>
    <div class="rule">
      <span class="tag tag-b">B</span>
      <div class="rule-body">
        <div class="rule-name">连阳累积</div>
        <div class="rule-formula"><code>up_streak ∈ [3, 10]</code></div>
        <div class="rule-note">3~10 根连续阳线,反弹已展开但未超长</div>
      </div>
    </div>
    <div class="rule">
      <span class="tag tag-c">C</span>
      <div class="rule-body">
        <div class="rule-name">当日反弹幅度</div>
        <div class="rule-formula"><code>pct_chg ∈ [2%, 6%]</code></div>
        <div class="rule-note">单日涨幅介于温和到强势</div>
      </div>
    </div>
    <div class="rule highlight">
      <span class="tag tag-d">D</span>
      <div class="rule-body">
        <div class="rule-name">MACD 动能衰减 <span class="badge badge-new">动能衰减版</span></div>
        <div class="rule-formula"><code>DIF &gt; 0 ∧ DEA &gt; 0 ∧ |macd_bar| 在缩小</code></div>
        <div class="rule-note">
          MACD 仍在零轴上方区域,但柱状绝对值正在缩短 — 反弹动能开始衰减
          (<code>|macd_bar_t| &lt; |macd_bar_{t-1}|</code>)
        </div>
      </div>
    </div>
    <div class="rule">
      <span class="tag tag-e">E</span>
      <div class="rule-body">
        <div class="rule-name">流动性窗口</div>
        <div class="rule-formula"><code>am60 ∈ [3e7, 3e8]</code></div>
        <div class="rule-note">60 日均成交额 3000 万 ~ 3 亿,剔除冷门 + 剔除过热</div>
      </div>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-title">出场规则</div>
  <div class="exit-grid">
    <div class="exit-card exit-tp">
      <div class="exit-label">止盈 TP</div>
      <div class="exit-formula">entry × (1 - tp_pct)</div>
      <div class="exit-meta">tp_pct = 0.06 (6%)</div>
    </div>
    <div class="exit-card exit-sl">
      <div class="exit-label">止损 SL</div>
      <div class="exit-formula">entry × (1 + sl_pct)</div>
      <div class="exit-meta">sl_pct = 0.05 (5%)</div>
    </div>
    <div class="exit-card exit-time">
      <div class="exit-label">时间出场</div>
      <div class="exit-formula">持仓 ≥ max_hold</div>
      <div class="exit-meta">max_hold = 20 个交易日</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-title">撮合规则 (legacy 奇偶约定)</div>
  <div class="meta-grid">
    <div class="meta-item"><span class="lbl">入场延迟</span><span class="val">信号日后 T+2 开盘</span></div>
    <div class="meta-item"><span class="lbl">出场触发</span><span class="val">基于 T+1 日 high/low,限价撮合</span></div>
    <div class="meta-item"><span class="lbl">持仓约束</span><span class="val">全局单 key 锁,满仓单只</span></div>
    <div class="meta-item"><span class="lbl">撮合价</span><span class="val">TP/SL 触及即按阈值价成交 (非下根 open)</span></div>
    <div class="meta-item"><span class="lbl">整手</span><span class="val">100 股整数倍</span></div>
    <div class="meta-item"><span class="lbl">佣金/印花税</span><span class="val">万 2.5 / 万 1</span></div>
    <div class="meta-item"><span class="lbl">融券利率</span><span class="val">8.6% 年化按日扣</span></div>
    <div class="meta-item"><span class="lbl">初始资金</span><span class="val">¥1,000,000</span></div>
  </div>
</div>

<div class="card">
  <div class="card-title">指标公式</div>
  <div class="formula-grid">
    <div><code>MA20  = rolling(20).mean(close)</code></div>
    <div><code>MA60  = rolling(60).mean(close)</code></div>
    <div><code>EMA12 = ewm(span=12, adjust=False).mean(close)</code></div>
    <div><code>EMA26 = ewm(span=26, adjust=False).mean(close)</code></div>
    <div><code>DIF   = EMA12 - EMA26</code></div>
    <div><code>DEA   = ewm(span=9, adjust=False).mean(DIF)</code></div>
    <div><code>macd_bar = 2 × (DIF - DEA)</code></div>
    <div><code>pct_chg  = (close - prev_close) / prev_close</code> <span class="anti-leak">shift(1)</span></div>
    <div><code>am60     = rolling(60).mean(amount)</code></div>
  </div>
</div>
"""


def build_anti_leak_card() -> str:
    return """
<div class="card card-warn">
  <div class="card-title">⚠️ 反-穿越红线状态 (待用户决策)</div>
  <div class="leak-list">
    <div class="leak-row">
      <div class="leak-dot dot-warn"></div>
      <div class="leak-body">
        <div class="leak-title">D 条件: 已修正 ✅</div>
        <div class="leak-desc">
          旧实现 <code>macd_bar &lt; 0</code> 仅为静态符号判定,与策略意图不符。<br>
          2026-09-09 改为 <code>DIF &gt; 0 ∧ DEA &gt; 0 ∧ |macd_bar| 在缩小</code> — 动能衰减判定。
        </div>
      </div>
    </div>
    <div class="leak-row">
      <div class="leak-dot dot-warn"></div>
      <div class="leak-body">
        <div class="leak-title">up_streak: leaky 模式未修 ⚠️</div>
        <div class="leak-desc">
          <code>signals.py:48-51</code> 仍用 <code>down_break.cumsum()</code> 跨股票累加,
          股票 A 的阴线会把股票 B 的 <code>up_id</code> 组向后推。<br>
          当时为了 39/39 byte-parity 保留 leaky;但 D 条件修复已破 parity,
          leaky 失去存在理由 — 建议回归 canonical <code>(up_day &amp; ~prev_up).cumsum()</code>。
        </div>
      </div>
    </div>
    <div class="leak-row">
      <div class="leak-dot dot-warn"></div>
      <div class="leak-body">
        <div class="leak-title">golden file: 已过时 ⚠️</div>
        <div class="leak-desc">
          <code>tests/golden/v33_mainboard_trades.json</code> 锁定的 39 笔已不再代表当前策略。<br>
          parity test 默认 <code>@pytest.mark.skipif</code>(需 DuckDB),不挡 pytest,但作为决策遗留物需用户后续处理。
        </div>
      </div>
    </div>
  </div>
</div>
"""


def build_backtest_summary_card(new: dict) -> str:
    """11 笔动能衰减版 vs 39 笔旧版对比。"""
    trades = new["trades"]
    n = len(trades)
    tp_n = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_n = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_n = sum(1 for t in trades if t["exit_reason"] == "time")
    wins = sum(1 for t in trades if (t["entry_price"] - t["exit_price"]) / t["entry_price"] > 0)
    win_rate = wins / n if n > 0 else 0
    avg_pnl = sum((t["entry_price"] - t["exit_price"]) / t["entry_price"] for t in trades) / n

    def cls(v: float, ref: float) -> str:
        return "delta-pos" if v > ref else "delta-neg" if v < ref else "delta-zero"

    return f"""
<div class="card">
  <div class="card-title">1 年回测对比 (2025-09-09 → 2026-09-09)</div>
  <table class="compare">
    <thead>
      <tr>
        <th>指标</th>
        <th>旧版 (macd_bar&lt;0)</th>
        <th>动能衰减版 (新)</th>
        <th>Δ</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>命中笔数</td>
        <td>39</td>
        <td>{n}</td>
        <td class="{cls(n, 39)}">{n-39:+d}</td>
      </tr>
      <tr>
        <td>TP / SL / Time</td>
        <td>20 / 18 / 1</td>
        <td>{tp_n} / {sl_n} / {time_n}</td>
        <td>—</td>
      </tr>
      <tr>
        <td>胜率</td>
        <td>53.8%</td>
        <td>{win_rate*100:.1f}%</td>
        <td class="{cls(win_rate, 0.538)}">{(win_rate-0.538)*100:+.1f}pp</td>
      </tr>
      <tr>
        <td>Sharpe</td>
        <td>0.94</td>
        <td>{new['sharpe']:.2f}</td>
        <td class="{cls(new['sharpe'], 0.94)}">{new['sharpe']-0.94:+.2f}</td>
      </tr>
      <tr>
        <td>最终资金</td>
        <td>¥993,022</td>
        <td>¥{new['final_capital']:,.0f}</td>
        <td class="{cls(new['final_capital'], 993022)}">¥{new['final_capital']-993022:+,.0f}</td>
      </tr>
      <tr>
        <td>总收益</td>
        <td>-0.70%</td>
        <td>{new['total_yield']*100:+.2f}%</td>
        <td class="{cls(new['total_yield'], -0.007)}">{(new['total_yield']+0.007)*100:+.2f}pp</td>
      </tr>
      <tr>
        <td>平均单笔 PnL</td>
        <td>+0.18%</td>
        <td>{avg_pnl*100:+.2f}%</td>
        <td class="{cls(avg_pnl, 0.0018)}">{(avg_pnl-0.0018)*100:+.2f}pp</td>
      </tr>
    </tbody>
  </table>
  <div class="interpret">
    <div class="interp-title">解读</div>
    <ul>
      <li><b>胜率 +9.8pp</b> + <b>Sharpe +0.13</b> → 信号质量真实改善,样本选择更精准</li>
      <li><b>命中 39 → 11 (-72%)</b> → D 条件收紧导致信号稀疏,A 股 1 年内满足"动能衰减中"的标的本身就不多</li>
      <li><b>总收益 -0.70% → -8.04%</b> → 样本锐减后,单笔 4 笔 SL 的拖累被放大(总损失贡献 ~15% 资金)</li>
      <li><b>建议</b>:拉长回测窗口至 3~5 年看 Sharpe 稳定性;或放松 D 为"红柱缩小"也算命中(更宽松版)</li>
    </ul>
  </div>
</div>
"""


def build_trades_section(con: duckdb.DuckDBPyConnection, trades: list) -> str:
    cards = []
    for idx, trade in enumerate(trades, 1):
        code = trade["thscode"]
        entry_date = trade["entry_date"]
        exit_date = trade["exit_date"]
        entry_price = trade["entry_price"]
        exit_price = trade["exit_price"]
        exit_reason = trade["exit_reason"]
        hold_days = trade["hold_days"]

        pnl_pct = (entry_price - exit_price) / entry_price
        sig_date_est = (pd.Timestamp(entry_date) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        if pd.Timestamp(sig_date_est) >= pd.Timestamp(entry_date):
            sig_date_est = (pd.Timestamp(entry_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        panel = load_panel_for_trade(con, code, sig_date_est, entry_date, exit_date)
        if panel.empty:
            continue

        panel_ind = compute_panel_indicators(panel)

        def find_idx(target_date_str: str, direction: str) -> int | None:
            target = pd.Timestamp(target_date_str)
            if direction == "le":
                cands = panel_ind[panel_ind["date"] <= target]
                return int(cands.index[-1]) if not cands.empty else None
            else:
                cands = panel_ind[panel_ind["date"] >= target]
                return int(cands.index[0]) if not cands.empty else None

        sig_idx = find_idx(sig_date_est, "le")
        entry_idx = find_idx(entry_date, "ge")
        exit_idx = find_idx(exit_date, "ge")
        if sig_idx is None or entry_idx is None or exit_idx is None:
            continue

        view_start = max(0, sig_idx - PRE_SIG_DAYS)
        view_end = min(len(panel_ind) - 1, exit_idx + 5)
        sub = panel_ind.iloc[view_start:view_end + 1].reset_index(drop=True)
        local_sig = sig_idx - view_start
        local_entry = entry_idx - view_start
        local_exit = exit_idx - view_start

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

        tp_line = entry_price * (1 - 0.06)
        sl_line = entry_price * (1 + 0.05)
        svg = build_chart_svg(candles, local_sig, local_entry, local_exit, exit_reason, tp_line, sl_line)

        sig_row = panel_ind.iloc[sig_idx]
        sig_close = float(sig_row["close"])
        sig_ma60 = float(sig_row["ma60"]) if pd.notna(sig_row["ma60"]) else None
        sig_up_streak = int(sig_row["up_streak"])
        sig_pct_chg = float(sig_row["pct_chg"]) if pd.notna(sig_row["pct_chg"]) else 0.0
        sig_dif = float(sig_row["dif"]) if pd.notna(sig_row["dif"]) else 0.0
        sig_dea = float(sig_row["dea"]) if pd.notna(sig_row["dea"]) else 0.0
        sig_macd_bar = float(sig_row["macd_bar"]) if pd.notna(sig_row["macd_bar"]) else 0.0
        sig_am60 = float(sig_row["am60"]) if pd.notna(sig_row["am60"]) else 0.0
        prev_row_macd = float(panel_ind.iloc[sig_idx - 1]["macd_bar"]) if sig_idx > 0 and pd.notna(panel_ind.iloc[sig_idx - 1]["macd_bar"]) else 0.0

        cond_d_ok = sig_dif > 0 and sig_dea > 0 and abs(sig_macd_bar) < abs(prev_row_macd)

        tag_color = {"TP": "#26a69a", "SL": "#ef5350", "time": "#ffa726"}.get(exit_reason, "#888")
        tag_label = {"TP": "止盈", "SL": "止损", "time": "时间出场"}.get(exit_reason, exit_reason)
        pnl_color = "#26a69a" if pnl_pct > 0 else "#ef5350"
        sig_ma60_str = f"{sig_ma60:.2f}" if sig_ma60 else "N/A"

        cards.append(f"""
<details class="trade" {"open" if idx <= 3 else ""}>
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
      <div class="feat"><div class="lbl">A: close&lt;MA60</div><div class="val">{sig_close:.2f}&lt;{sig_ma60_str}</div></div>
      <div class="feat"><div class="lbl">B: 连阳 [3,10]</div><div class="val">{sig_up_streak}</div></div>
      <div class="feat"><div class="lbl">C: pct_chg [2%,6%]</div><div class="val">{sig_pct_chg*100:+.2f}%</div></div>
      <div class="feat"><div class="lbl">D: DIF&gt;0 &amp; DEA&gt;0 &amp; 柱缩小</div><div class="val {('green' if cond_d_ok else 'red')}">{sig_dif:+.3f}/{sig_dea:+.3f} | {abs(sig_macd_bar):.3f}&lt;{abs(prev_row_macd):.3f}</div></div>
      <div class="feat"><div class="lbl">E: am60 流动性</div><div class="val">{sig_am60/1e8:.2f} 亿</div></div>
      <div class="feat"><div class="lbl">入场价/出场价</div><div class="val">{entry_price:.2f} → {exit_price:.2f}</div></div>
      <div class="feat"><div class="lbl">盈亏 (做空)</div><div class="val {pnl_color}">{pnl_pct*100:+.2f}%</div></div>
    </div>
    {svg}
  </div>
</details>""")

    return f"""
<div class="card">
  <div class="card-title">{len(cards)} 笔交易明细 <span class="subtitle-tag">(默认展开前 3 笔)</span></div>
  <div class="trades-list">
    {''.join(cards)}
  </div>
</div>
"""


def main() -> None:
    if not BACKTEST_JSON.exists():
        raise SystemExit(f"未找到 {BACKTEST_JSON}, 请先运行 python3 -m short_reversal.main")

    with BACKTEST_JSON.open() as f:
        new = json.load(f)
    trades = new["trades"]
    print(f"读取 {len(trades)} 笔交易")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    strategy_card = build_strategy_card()
    anti_leak_card = build_anti_leak_card()
    summary_card = build_backtest_summary_card(new)
    trades_card = build_trades_section(con, trades)
    con.close()

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>v33 动能衰减版 — 策略综合报告</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0f1419; color: #e6e6e6; padding: 16px; line-height: 1.5; font-size: 13px;
  }}
  .container {{ max-width: 820px; margin: 0 auto; }}

  h1 {{ color: #f5f5f5; font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 12px; margin-bottom: 16px; }}

  .card {{
    background: #1a2026; border: 1px solid #2a3540;
    border-radius: 8px; padding: 16px; margin-bottom: 12px;
  }}
  .card-warn {{ border-left: 3px solid #ffa726; }}
  .card-title {{ color: #f5f5f5; font-size: 14px; font-weight: 700; margin-bottom: 12px; }}
  .subtitle-tag {{ color: #888; font-size: 11px; font-weight: 400; }}

  /* 规则卡 */
  .rules {{ display: flex; flex-direction: column; gap: 8px; }}
  .rule {{
    display: flex; gap: 10px; align-items: flex-start;
    background: #0f1419; border-radius: 4px; padding: 10px;
  }}
  .rule.highlight {{ border: 1px solid #ffa726; background: #1f1810; }}
  .rule .tag {{
    flex-shrink: 0; width: 28px; height: 28px; border-radius: 4px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 13px; color: #000;
  }}
  .tag-a {{ background: #42a5f5; }}
  .tag-b {{ background: #66bb6a; }}
  .tag-c {{ background: #ab47bc; }}
  .tag-d {{ background: #ffa726; }}
  .tag-e {{ background: #ef5350; }}
  .rule-body {{ flex: 1; }}
  .rule-name {{ color: #f5f5f5; font-size: 13px; font-weight: 600; margin-bottom: 2px; }}
  .rule-formula {{ color: #ffd54f; font-size: 12px; font-family: monospace; margin-bottom: 2px; }}
  .rule-note {{ color: #888; font-size: 11px; }}
  .badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-left: 6px; }}
  .badge-new {{ background: #ffa726; color: #000; font-weight: 700; }}

  /* 出场卡 */
  .exit-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
  .exit-card {{ background: #0f1419; padding: 12px; border-radius: 4px; border-left: 3px solid; }}
  .exit-tp {{ border-color: #26a69a; }}
  .exit-sl {{ border-color: #ef5350; }}
  .exit-time {{ border-color: #ffa726; }}
  .exit-label {{ color: #f5f5f5; font-size: 12px; font-weight: 700; }}
  .exit-formula {{ color: #ffd54f; font-size: 12px; font-family: monospace; margin: 4px 0; }}
  .exit-meta {{ color: #888; font-size: 11px; }}

  /* 撮合 + 指标 */
  .meta-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }}
  .meta-item {{ background: #0f1419; padding: 8px 12px; border-radius: 4px; display: flex; justify-content: space-between; }}
  .meta-item .lbl {{ color: #888; font-size: 11px; }}
  .meta-item .val {{ color: #f5f5f5; font-size: 12px; font-weight: 600; }}

  .formula-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }}
  .formula-grid > div {{ background: #0f1419; padding: 6px 10px; border-radius: 3px; font-size: 11px; }}
  .formula-grid code {{ color: #ffd54f; font-family: monospace; }}
  .anti-leak {{ color: #26a69a; font-size: 10px; margin-left: 4px; }}

  /* 反-穿越 */
  .leak-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .leak-row {{ display: flex; gap: 10px; align-items: flex-start; background: #0f1419; padding: 10px; border-radius: 4px; }}
  .leak-dot {{ flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; }}
  .dot-warn {{ background: #ffa726; }}
  .dot-ok {{ background: #26a69a; }}
  .leak-title {{ color: #f5f5f5; font-size: 13px; font-weight: 700; margin-bottom: 4px; }}
  .leak-desc {{ color: #aaa; font-size: 11px; line-height: 1.6; }}
  .leak-desc code {{ color: #ffd54f; font-family: monospace; }}

  /* 对比表 */
  table.compare {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  table.compare th {{ color: #888; font-weight: 600; text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3540; }}
  table.compare td {{ color: #f5f5f5; padding: 8px; border-bottom: 1px solid #1f2933; }}
  table.compare td:first-child {{ color: #888; }}
  .delta-pos {{ color: #26a69a; font-weight: 700; }}
  .delta-neg {{ color: #ef5350; font-weight: 700; }}
  .delta-zero {{ color: #888; }}

  .interpret {{ margin-top: 12px; background: #0f1419; padding: 12px; border-radius: 4px; }}
  .interp-title {{ color: #ffd54f; font-size: 12px; font-weight: 700; margin-bottom: 6px; }}
  .interpret ul {{ list-style: none; padding-left: 0; }}
  .interpret li {{ color: #aaa; font-size: 12px; padding: 3px 0; line-height: 1.6; }}
  .interpret li b {{ color: #f5f5f5; }}

  /* 交易明细 */
  .trades-list {{ display: flex; flex-direction: column; gap: 6px; }}
  details.trade {{ background: #0f1419; border: 1px solid #2a3540; border-radius: 4px; }}
  details.trade > summary {{
    list-style: none; cursor: pointer; padding: 8px 12px;
    display: flex; align-items: center; gap: 8px; user-select: none; border-radius: 4px;
  }}
  details.trade > summary::-webkit-details-marker {{ display: none; }}
  details.trade > summary:hover {{ background: #1a2026; }}
  details.trade[open] > summary {{ background: #1a2026; border-bottom: 1px solid #2a3540; border-radius: 4px 4px 0 0; }}
  .idx {{ color: #888; font-family: monospace; min-width: 30px; font-size: 11px; }}
  .code {{ font-weight: 700; color: #f5f5f5; min-width: 90px; font-size: 12px; }}
  .dates {{ color: #888; font-size: 10px; font-family: monospace; flex: 1; }}
  .hold {{ color: #888; font-size: 10px; }}
  .tag {{ padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; color: #000; }}
  .pnl {{ font-weight: 700; font-family: monospace; min-width: 60px; text-align: right; font-size: 12px; }}

  .trade-body {{ padding: 10px; }}
  .features {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 8px; }}
  .feat {{ background: #1a2026; padding: 5px 8px; border-radius: 3px; }}
  .feat .lbl {{ color: #888; font-size: 9px; margin-bottom: 1px; }}
  .feat .val {{ color: #f5f5f5; font-size: 11px; font-weight: 600; font-family: monospace; }}
  .feat .val.green {{ color: #26a69a; }}
  .feat .val.red {{ color: #ef5350; }}
  .chart-svg {{ width: 100%; height: auto; display: block; background: #0f1419; border-radius: 4px; }}

  .footer {{ text-align: center; color: #555; font-size: 11px; padding: 16px 0 8px; }}
  .footer .warn {{ color: #ffa726; }}
</style>
</head>
<body>
<div class="container">
  <h1>v33 动能衰减版 — 策略综合报告</h1>
  <div class="subtitle">
    区间 {new['start']} → {new['end']} | D 条件 2026-09-09 修正 |
    标的: 沪深主板 | 撮合: T+2 开盘入 + 限价 TP/SL
  </div>

  {strategy_card}
  {summary_card}
  {trades_card}
  {anti_leak_card}

  <div class="footer">
    <span class="warn">⚠</span> v33_mainboard preset | 总收益 {new['total_yield']*100:+.2f}% |
    Sharpe {new['sharpe']:.2f} | 非投资建议
  </div>
</div>
</body>
</html>
"""

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    print(f"\n[✓] 综合报告已生成: {OUTPUT_HTML}")
    print(f"    文件大小: {len(html) / 1024:.1f} KB")
    print(f"    策略卡片: 4 (入场/出场/撮合/指标)")
    print(f"    回测对比: 1y 新旧对照")
    print(f"    交易明细: {len(trades)} 笔 (默认展开前 3)")
    print(f"    反-穿越红线: 3 项状态")


if __name__ == "__main__":
    main()