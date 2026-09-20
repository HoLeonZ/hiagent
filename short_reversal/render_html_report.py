"""HTML report generator for short_reversal backtest results.

Generates two HTML files (one per preset):
  1. 全部交易明细 (signal/entry/exit points + P&L + inline K-line context)
  2. 100 个交易日内的各类指标趋势 (rolling DD, win rate, exit reason mix, etc.)

数据来自 trades.json + DuckDB K-line（v_daily_hfq 表）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from hiagent_config import get_db_path

# 12 个月窗口的起始日期（用于反推 trade 日期）
DEFAULT_WINDOW_START = "2025-09-16"
DEFAULT_WINDOW_END = "2026-09-16"


def find_db() -> str | None:
    """返回当前生效的 DuckDB 路径;不存在则返回 None。"""
    p = get_db_path()
    return str(p) if p.exists() else None


# K 线缓存：code -> DataFrame
_KLINE_CACHE: dict[str, pd.DataFrame] = {}


def fetch_klines(codes: list[str], window_start: str, window_end: str,
                 pad_days: int = 60) -> dict[str, pd.DataFrame]:
    """批量拉取 K 线（每个 code 拉 [window_start - pad, window_end + pad] 范围）。

    Returns: {thscode: DataFrame(date, open, high, low, close, volume, amount)}

    NOTE: 使用 v_daily（原始未复权），与 backtrader engine 数据源保持一致，
    避免 HFQ 复权因子造成的 entry_price 不匹配。
    """
    db = find_db()
    if db is None:
        print("WARN: no DuckDB found, K-line context unavailable")
        return {}

    start = (pd.Timestamp(window_start) - pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(window_end) + pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")

    codes_uniq = list(set(codes))
    if not codes_uniq:
        return {}

    con = duckdb.connect(db, read_only=True)
    try:
        # 分批拉（避免 IN 子句过大）
        chunk_size = 200
        all_dfs = []
        for i in range(0, len(codes_uniq), chunk_size):
            chunk = codes_uniq[i:i + chunk_size]
            codes_str = ",".join(f"'{c}'" for c in chunk)
            sql = (
                f"SELECT thscode, date, open, high, low, close, volume, amount "
                f"FROM v_daily "
                f"WHERE thscode IN ({codes_str}) "
                f"AND date BETWEEN '{start}' AND '{end}' "
                f"ORDER BY thscode, date"
            )
            df = con.execute(sql).df()
            all_dfs.append(df)
        full = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    finally:
        con.close()

    out: dict[str, pd.DataFrame] = {}
    for code, g in full.groupby("thscode"):
        out[code] = g.reset_index(drop=True)
        _KLINE_CACHE[code] = out[code]
    return out


def get_signal_price(klines: dict, code: str, signal_date: pd.Timestamp) -> float | None:
    """T 日信号价 = T 日 close（决策时已知）。"""
    df = klines.get(code)
    if df is None:
        return None
    row = df[df["date"] == signal_date]
    if row.empty:
        return None
    return float(row["close"].iloc[0])


def get_entry_price(klines: dict, code: str, signal_date: pd.Timestamp) -> float | None:
    """T+1 日入场价 = T+1 日 open（实际成交价）。"""
    df = klines.get(code)
    if df is None:
        return None
    target = signal_date + pd.tseries.offsets.BDay(1)
    row = df[df["date"] == target]
    if row.empty:
        # 取 signal_date 之后下一个交易日
        future = df[df["date"] > signal_date]
        if future.empty:
            return None
        return float(future["open"].iloc[0])
    return float(row["open"].iloc[0])


def get_kline_window(klines: dict, code: str, signal_date: pd.Timestamp,
                     n_before: int = 3, n_after: int = 5) -> pd.DataFrame:
    """取 signal_date ± N 根 K 线窗口（用于内嵌展示）。"""
    df = klines.get(code)
    if df is None:
        return pd.DataFrame()
    # 找到 signal_date 在 df 中的索引
    idx_list = df.index[df["date"] >= signal_date].tolist()
    if not idx_list:
        return pd.DataFrame()
    start_idx = max(0, idx_list[0] - n_before)
    end_idx = min(len(df), idx_list[0] + n_after + 1)
    return df.iloc[start_idx:end_idx].reset_index(drop=True)


def load_trades(json_path: Path) -> dict:
    """加载 trades.json。"""
    with open(json_path) as f:
        return json.load(f)


def build_trade_dates(trades: list[dict], klines: dict,
                      window_start: str, window_end: str) -> list[dict]:
    """给每笔交易推算 entry_date / exit_date（用 K-line 反推真实日期）。

    策略：每笔 trade 的 thscode + entry_price 在 v_daily 中匹配候选 entry bar
    → 对每个候选 entry bar, 校验其后第 hold_days 个 BDay 的 K-line:
        - reason='TP':  要求 exit_price ∈ [low, high]（tp_p intraday 或 open gap-down）
        - reason='SL':  要求 exit_price ∈ [low, high] 或 sl_p < low（gap-up 合法 backtrader 约定）
        - reason='time': 要求 exit_price ∈ [low, high]（xp = close）
    → 优先选 in_window 候选; 同窗口内选最早满足的（与 engine 串行撮合一致）

    不变量：entry_price 来自 engine 的 float(d.open[0]), K-line 也来自 v_daily,
    所以 entry bar 的 open 应严格 = entry_price（容差 ±0.001 防浮点 round）。
    校验失败 → fallback 按 index 推（与旧版兼容）, 但会打印 WARN。
    """
    start = pd.Timestamp(window_start)
    end = pd.Timestamp(window_end)
    out = []
    unmatched = 0
    for i, t in enumerate(trades):
        code = t["thscode"]
        ep = float(t["entry_price"])
        xp = float(t["exit_price"])
        hd = int(t["hold_days"])
        reason = t.get("exit_reason", "TP")
        # 从 trade 自身反推 sl_p（preset 的 sl_pct 不可知, 但 xp == sl_p 一定成立）
        # 仅当 reason='SL' 时有意义: xp = ep * (1 + sl_pct) → sl_pct = (xp - ep) / ep
        sl_p = xp if reason == "SL" else None
        df = klines.get(code)
        signal_date, entry_date, exit_date = None, None, None
        if df is not None and not df.empty:
            # 主匹配：open ≈ entry_price（容差 0.001 防 float round）
            mask = (df["open"] >= ep - 0.001) & (df["open"] <= ep + 0.001)
            candidates = df[mask]
            if not candidates.empty:
                in_window = candidates[
                    (candidates["date"] >= start - pd.Timedelta(days=60)) &
                    (candidates["date"] <= end + pd.Timedelta(days=60))
                ]
                pool = in_window if not in_window.empty else candidates
                # 按日期排序, 依次校验每个候选, 第一个通过的胜出
                picked = None
                for _, cand in pool.sort_values("date").iterrows():
                    cand_entry = cand["date"]
                    # 推第 hd 个 BDay
                    future_dates = df[df["date"] > cand_entry]["date"].tolist()
                    if len(future_dates) < hd:
                        continue
                    cand_exit = future_dates[hd - 1]
                    exit_bar = df[df["date"] == cand_exit]
                    if exit_bar.empty:
                        continue
                    low = float(exit_bar["low"].iloc[0])
                    high = float(exit_bar["high"].iloc[0])
                    # 校验
                    if reason == "SL":
                        # SL: exit_price = sl_p; 允许 sl_p < low (gap-up)
                        valid = (low <= xp <= high) or (abs(xp - sl_p) < 1e-6 and xp < low)
                    else:
                        # TP / time: exit_price ∈ [low, high]
                        valid = (low <= xp <= high)
                    if valid:
                        picked = (cand_entry, cand_exit)
                        break
                if picked is not None:
                    entry_date, exit_date = picked
                else:
                    # 所有候选都不通过校验 → 退化选最早的 in_window 候选 (兜底)
                    fallback = pool.sort_values("date").iloc[0]
                    entry_date = fallback["date"]
                    exit_date = entry_date + pd.tseries.offsets.BDay(hd)
            if entry_date is None:
                # 没有任何 open ≈ ep 的候选 → fallback 按 index 推
                unmatched += 1
                entry_date = start + pd.tseries.offsets.BDay(i)
            signal_date = entry_date - pd.tseries.offsets.BDay(1)
            if exit_date is None:
                exit_date = entry_date + pd.tseries.offsets.BDay(hd)
        else:
            unmatched += 1
            entry_date = start + pd.tseries.offsets.BDay(i)
            signal_date = entry_date - pd.tseries.offsets.BDay(1)
            exit_date = entry_date + pd.tseries.offsets.BDay(hd)
        out.append({**t, "_signal_date": signal_date.strftime("%Y-%m-%d") if signal_date is not None else "N/A",
                    "_entry_date": entry_date.strftime("%Y-%m-%d") if entry_date is not None else "N/A",
                    "_exit_date": exit_date.strftime("%Y-%m-%d") if exit_date is not None else "N/A",
                    "_idx": i})
    if unmatched > 0:
        print(f"WARN: {unmatched}/{len(trades)} trades could not be matched to K-lines, "
              f"using fallback dates")
    return out


def compute_rolling_metrics(trades: list[dict], window: int = 100) -> pd.DataFrame:
    """计算 100 个交易日内的滚动指标。

    Returns DataFrame with columns:
      - idx: 交易序号
      - cum_pnl: 累计 net（复利）
      - rolling_n: 窗口内笔数
      - rolling_win_rate
      - rolling_avg_net
      - rolling_tp_pct / rolling_sl_pct / rolling_time_pct
      - rolling_avg_hold_days
    """
    df = pd.DataFrame(trades)
    # 计算每笔 net 的复利路径
    df["cum_pnl"] = (1 + df["net"]).cumprod()
    df["rolling_n"] = df.index.to_series().rolling(window, min_periods=10).count()
    df["rolling_win_rate"] = df["net"].gt(0).rolling(window, min_periods=10).mean()
    df["rolling_avg_net"] = df["net"].rolling(window, min_periods=10).mean()
    df["rolling_avg_hold"] = df["hold_days"].rolling(window, min_periods=10).mean()
    df["rolling_tp_pct"] = (
        df["exit_reason"].eq("TP").rolling(window, min_periods=10).mean()
    )
    df["rolling_sl_pct"] = (
        df["exit_reason"].eq("SL").rolling(window, min_periods=10).mean()
    )
    df["rolling_time_pct"] = (
        df["exit_reason"].eq("time").rolling(window, min_periods=10).mean()
    )
    return df


def compute_drawdown(equity: pd.Series) -> tuple[pd.Series, pd.Series]:
    """计算 (drawdown_series, peak_series)。"""
    peak = equity.cummax()
    dd = (peak - equity) / peak
    return dd, peak


def render_trades_html(preset_name: str, summary: dict, trades: list[dict],
                       klines: dict, out_path: Path) -> None:
    """生成交易明细 HTML（带 signal/entry/exit 标记 + 内嵌 K 线）。"""
    n = len(trades)
    tp_n = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_n = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_n = sum(1 for t in trades if t["exit_reason"] == "time")
    wr = sum(1 for t in trades if t["net"] > 0) / n if n else 0
    avg_pnl = sum(t["net"] for t in trades) / n if n else 0
    avg_hold = sum(t["hold_days"] for t in trades) / n if n else 0

    rows = []
    for t in trades:
        net = t["net"]
        net_pct = net * 100
        net_color = "#16a34a" if net > 0 else ("#dc2626" if net < 0 else "#6b7280")
        reason = t["exit_reason"]
        reason_color = {
            "TP": "#16a34a", "SL": "#dc2626", "time": "#6b7280"
        }.get(reason, "#000")

        # 真实信号价 / 入场价 / 离场价（从 K-line 反推）
        code = t["thscode"]
        signal_date = pd.Timestamp(t["_signal_date"]) if t["_signal_date"] != "N/A" else None
        entry_date = pd.Timestamp(t["_entry_date"]) if t["_entry_date"] != "N/A" else None
        exit_date = pd.Timestamp(t["_exit_date"]) if t["_exit_date"] != "N/A" else None
        sig_p = get_signal_price(klines, code, entry_date - pd.tseries.offsets.BDay(1)) if entry_date else None
        ent_p = get_entry_price(klines, code, entry_date - pd.tseries.offsets.BDay(1)) if entry_date else None
        exit_p = t["exit_price"]

        sig_str = f"{sig_p:.4f}".rstrip("0").rstrip(".") if sig_p is not None else "—"
        ent_str = f"{ent_p:.4f}".rstrip("0").rstrip(".") if ent_p is not None else "—"
        exit_str = f"{exit_p:.4f}".rstrip("0").rstrip(".")

        # 内嵌 K 线窗口
        kline_html = ""
        if entry_date:
            win = get_kline_window(klines, code, entry_date, n_before=3, n_after=5)
            if not win.empty:
                kline_rows = []
                for _, bar in win.iterrows():
                    bar_date = pd.Timestamp(bar["date"])
                    if entry_date and bar_date == entry_date:
                        # entry bar → 高亮黄
                        bg = "#fef9c3"
                        marker = " ⬅ ENTRY"
                    elif exit_date and bar_date == exit_date:
                        bg = "#fce7f3"
                        marker = " ⬅ EXIT"
                    else:
                        bg = "white"
                        marker = ""
                    is_up = bar["close"] >= bar["open"]
                    clr = "#16a34a" if is_up else "#dc2626"
                    kline_rows.append(
                        f'<tr style="background:{bg}">'
                        f'<td style="font-family:monospace">{bar["date"]}{marker}</td>'
                        f'<td style="text-align:right">{bar["open"]:.2f}</td>'
                        f'<td style="text-align:right">{bar["high"]:.2f}</td>'
                        f'<td style="text-align:right">{bar["low"]:.2f}</td>'
                        f'<td style="text-align:right;color:{clr};font-weight:bold">{bar["close"]:.2f}</td>'
                        f'<td style="text-align:right">{int(bar["volume"]):,}</td>'
                        f'</tr>'
                    )
                kline_html = f"""<details style="margin:8px 0;padding:8px;background:#f9fafb;border-radius:4px">
<summary style="cursor:pointer;font-weight:bold;color:#374151">
  K 线 ({code}) — entry 前 3 根 + 后 5 根，共 {len(win)} 根
</summary>
<table class="kline" style="margin-top:8px">
<thead><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th style="color:#16a34a">收盘</th><th>成交量</th></tr></thead>
<tbody>{''.join(kline_rows)}</tbody>
</table>
</details>"""

        rows.append(f"""
<tr class="trade-row" data-code="{code}" data-reason="{reason}" data-net="{'pos' if net>0 else ('neg' if net<0 else 'zero')}">
  <td style="text-align:center">{t["_idx"] + 1}</td>
  <td><code>{code}</code></td>
  <td style="text-align:center">{t["_signal_date"]}</td>
  <td style="text-align:right">{sig_str}</td>
  <td style="text-align:right">{ent_str}</td>
  <td style="text-align:center">{t["_exit_date"]}</td>
  <td style="text-align:right">{exit_str}</td>
  <td style="text-align:center"><span style="color:{reason_color};font-weight:bold">{reason}</span></td>
  <td style="text-align:right">{t["size"]:,}</td>
  <td style="text-align:center">{t["hold_days"]}</td>
  <td style="text-align:right;color:{net_color};font-weight:bold">{net_pct:+.4f}%</td>
</tr>
<tr class="trade-kline-row">
  <td colspan="11" style="padding:0 8px 8px 8px;background:#fafafa">{kline_html}</td>
</tr>""")
    rows_html = "\n".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{preset_name} — 交易明细</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 20px; background: #f9fafb; color: #111827; }}
h1 {{ color: #1e3a8a; margin-bottom: 4px; }}
h2 {{ color: #1e40af; border-bottom: 2px solid #93c5fd; padding-bottom: 4px; margin-top: 32px; }}
.summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
.card {{ background: white; padding: 16px; border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.card .label {{ font-size: 12px; color: #6b7280; }}
.card .value {{ font-size: 20px; font-weight: bold; color: #1e3a8a; margin-top: 4px; }}
.legend {{ display: flex; gap: 16px; margin: 8px 0; font-size: 13px; flex-wrap: wrap; }}
.legend span {{ display: inline-block; padding: 2px 8px; border-radius: 4px; }}
.legend .signal {{ background: #ddd6fe; }}
.legend .entry {{ background: #fef9c3; }}
.legend .exit-bar {{ background: #fce7f3; }}
.legend .tp {{ background: #16a34a; color: white; }}
.legend .sl {{ background: #dc2626; color: white; }}
.legend .time {{ background: #6b7280; color: white; }}
table {{ width: 100%; border-collapse: collapse; background: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-size: 13px; }}
th {{ background: #1e40af; color: white; padding: 8px;
      font-weight: 600; vertical-align: middle; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #e5e7eb;
      vertical-align: middle; font-variant-numeric: tabular-nums; }}
/* Use > tbody > tr > td:nth-child() to avoid leaking into nested kline tables
   (a nested table's first td is also :nth-child(1) of its row). */
table#trade-table > tbody > tr > td:nth-child(1) {{ text-align: center; }}
table#trade-table > tbody > tr > td:nth-child(2) {{ text-align: left; font-variant-numeric: normal; }}
table#trade-table > tbody > tr > td:nth-child(3),
table#trade-table > tbody > tr > td:nth-child(6),
table#trade-table > tbody > tr > td:nth-child(8) {{ text-align: center; }}
/* columns 4,5,7,9,10,11 keep right-align (default from inline style) */
tr.trade-row:hover td {{ background: #f3f4f6; }}
caption {{ text-align: left; font-weight: bold; padding: 8px; color: #374151; }}
.filter-row {{ margin: 12px 0; }}
.filter-row input, .filter-row select {{ padding: 6px; border: 1px solid #d1d5db;
                                         border-radius: 4px; font-size: 13px; }}
table.kline {{ font-size: 11px; box-shadow: none; }}
table.kline th {{ background: #4b5563; padding: 4px 8px; text-align: right;
                  vertical-align: middle; }}
table.kline th:first-child {{ text-align: left; }}
table.kline td {{ padding: 2px 6px; border-bottom: 1px solid #e5e7eb;
                  vertical-align: middle; text-align: right;
                  font-variant-numeric: tabular-nums; }}
table.kline td:first-child {{ text-align: left; font-variant-numeric: normal; }}
details {{ font-size: 12px; }}
</style>
</head>
<body>

<h1>{preset_name} — 交易明细 + K 线</h1>
<p style="color:#6b7280">回测窗口: {summary["start"]} → {summary["end"]} · 共 {n} 笔交易 · K 线源: v_daily_hfq (复权)</p>

<div class="legend">
  <span class="signal">信号日: T 日收盘（决策时已知）</span>
  <span class="entry">入场: T+1 日 open（实际成交价）</span>
  <span class="exit-bar">离场日: open/TP/SL/time 触发日</span>
  <span class="tp">TP: 收盘价跌穿 TP 阈值</span>
  <span class="sl">SL: 收盘价涨穿 SL 阈值</span>
  <span class="time">time: 持有 max_hold 天到期</span>
</div>

<div class="summary">
  <div class="card"><div class="label">最终资金</div>
    <div class="value">¥{summary["final_capital"]:,.2f}</div></div>
  <div class="card"><div class="label">CAGR</div>
    <div class="value" style="color:#16a34a">{summary["cagr"]*100:+.2f}%</div></div>
  <div class="card"><div class="label">最大回撤</div>
    <div class="value" style="color:#dc2626">{summary["max_dd"]*100:.2f}%</div></div>
  <div class="card"><div class="label">Sharpe</div>
    <div class="value">{summary["sharpe"]:.2f}</div></div>
  <div class="card"><div class="label">胜率</div>
    <div class="value">{wr*100:.2f}% ({sum(1 for t in trades if t["net"]>0)}/{n})</div></div>
  <div class="card"><div class="label">TP / SL / time</div>
    <div class="value">{tp_n} / {sl_n} / {time_n}</div></div>
  <div class="card"><div class="label">单笔均净利</div>
    <div class="value" style="color:{'#16a34a' if avg_pnl>0 else '#dc2626'}">{avg_pnl*100:+.4f}%</div></div>
  <div class="card"><div class="label">平均持仓</div>
    <div class="value">{avg_hold:.2f} 天</div></div>
</div>

<h2>逐笔明细（点击展开 K 线）</h2>

<div class="filter-row">
  <input id="filter-code" placeholder="过滤股票代码…" style="width:160px">
  <select id="filter-reason">
    <option value="">全部出场原因</option>
    <option value="TP">TP</option>
    <option value="SL">SL</option>
    <option value="time">time</option>
  </select>
  <select id="filter-net">
    <option value="">全部 P&L</option>
    <option value="pos">盈利</option>
    <option value="neg">亏损</option>
  </select>
  <span style="font-size:13px;color:#6b7280">共 <span id="visible-count">{n}</span> 笔</span>
</div>

<table id="trade-table">
<thead>
<tr>
  <th style="text-align:center;width:48px">#</th>
  <th style="text-align:left;width:96px">代码</th>
  <th style="text-align:center">信号日(T)</th>
  <th style="text-align:right">信号价</th>
  <th style="text-align:right">入场价(T+1 open)</th>
  <th style="text-align:center">离场日</th>
  <th style="text-align:right">离场价</th>
  <th style="text-align:center;width:80px">出场原因</th>
  <th style="text-align:right">张数</th>
  <th style="text-align:center">持仓天数</th>
  <th style="text-align:right">净收益率</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<script>
const filterCode = document.getElementById('filter-code');
const filterReason = document.getElementById('filter-reason');
const filterNet = document.getElementById('filter-net');
const visibleCount = document.getElementById('visible-count');
function applyFilter() {{
  const code = filterCode.value.trim().toLowerCase();
  const reason = filterReason.value;
  const net = filterNet.value;
  const tbody = document.querySelector('#trade-table tbody');
  const rowPairs = tbody.querySelectorAll('tr.trade-row');
  let visible = 0;
  rowPairs.forEach(r => {{
    const next = r.nextElementSibling;
    const c = r.dataset.code.toLowerCase();
    const rea = r.dataset.reason;
    const n = r.dataset.net;
    const show = (!code || c.includes(code)) &&
                 (!reason || rea === reason) &&
                 (!net || net === n);
    r.style.display = show ? '' : 'none';
    if (next && next.classList.contains('trade-kline-row')) {{
      next.style.display = show ? '' : 'none';
    }}
    if (show) visible++;
  }});
  visibleCount.textContent = visible;
}}
filterCode.addEventListener('input', applyFilter);
filterReason.addEventListener('change', applyFilter);
filterNet.addEventListener('change', applyFilter);
</script>

</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def render_trend_html(preset_name: str, summary: dict, trades: list[dict],
                      out_path: Path, window: int = 100) -> None:
    """生成 100 个交易日内的滚动指标 HTML。"""
    df = compute_rolling_metrics(trades, window=window)
    n = len(df)

    # 累计权益曲线
    equity = df["cum_pnl"].fillna(1.0).values
    dd_series, peak_series = compute_drawdown(pd.Series(equity))
    df["dd"] = dd_series
    df["peak"] = peak_series

    # 取 100 笔窗口的样本
    sample = df.iloc[window-1:].copy()

    # 转换为 SVG 折线图的数据点
    def make_path(xs: list, ys: list, width: int = 700, height: int = 200,
                  pad: int = 30, color: str = "#1e40af",
                  fill: str = "#dbeafe") -> str:
        if not xs:
            return ""
        x_min, x_max = min(xs), max(xs)
        y_min, y_min_raw = min(ys), min(ys)
        y_max = max(ys)
        if y_max == y_min:
            y_max = y_min + 1
        # 归一化
        def nx(x):
            return pad + (x - x_min) / (x_max - x_min) * (width - 2 * pad)
        def ny(y):
            return height - pad - (y - y_min) / (y_max - y_min) * (height - 2 * pad)
        pts = [(nx(x), ny(y)) for x, y in zip(xs, ys)]
        path = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        # 填充区域
        fill_path = path + f" L {pts[-1][0]:.2f},{height - pad} L {pts[0][0]:.2f},{height - pad} Z"
        return (f'<path d="{fill_path}" fill="{fill}" opacity="0.4"/>'
                f'<path d="{path}" stroke="{color}" stroke-width="2" fill="none"/>')

    # 4 张子图：累计权益 / 最大回撤 / 滚动胜率 / 出场原因分布
    idx = sample.index.tolist()
    cum_pnl = sample["cum_pnl"].tolist()
    dd = sample["dd"].tolist()
    win_rate = sample["rolling_win_rate"].fillna(0).tolist()
    tp = sample["rolling_tp_pct"].fillna(0).tolist()
    sl = sample["rolling_sl_pct"].fillna(0).tolist()
    ttime = sample["rolling_time_pct"].fillna(0).tolist()

    equity_path = make_path(idx, cum_pnl, color="#16a34a", fill="#bbf7d0")
    dd_path = make_path(idx, dd, color="#dc2626", fill="#fecaca")
    win_path = make_path(idx, [w * 100 for w in win_rate], color="#1e40af", fill="#dbeafe")

    # 出场原因堆叠柱状图（每 20 笔一个点）
    bucket_size = 20
    buckets = []
    for i in range(0, n, bucket_size):
        chunk = df.iloc[i:i + bucket_size]
        if len(chunk) == 0:
            continue
        buckets.append({
            "idx": i + len(chunk) // 2,
            "tp": chunk["exit_reason"].eq("TP").mean() * 100,
            "sl": chunk["exit_reason"].eq("SL").mean() * 100,
            "time": chunk["exit_reason"].eq("time").mean() * 100,
            "n": len(chunk),
        })
    # 堆叠柱图 SVG
    bar_width = 12
    chart_h = 200
    chart_w = 700
    pad = 30
    if buckets:
        max_x = max(b["idx"] for b in buckets)
        min_x = min(b["idx"] for b in buckets)
        def bx(x):
            return pad + (x - min_x) / max(max_x - min_x, 1) * (chart_w - 2 * pad)
        bars = []
        for b in buckets:
            x = bx(b["idx"]) - bar_width / 2
            tp_h = b["tp"] / 100 * (chart_h - 2 * pad)
            sl_h = b["sl"] / 100 * (chart_h - 2 * pad)
            time_h = b["time"] / 100 * (chart_h - 2 * pad)
            y_base = chart_h - pad
            y_tp = y_base - tp_h
            y_sl = y_tp - sl_h
            y_time = y_sl - time_h
            bars.append(
                f'<rect x="{x:.1f}" y="{y_time:.1f}" width="{bar_width}" '
                f'height="{time_h:.1f}" fill="#6b7280"/>'
                f'<rect x="{x:.1f}" y="{y_sl:.1f}" width="{bar_width}" '
                f'height="{sl_h:.1f}" fill="#dc2626"/>'
                f'<rect x="{x:.1f}" y="{y_tp:.1f}" width="{bar_width}" '
                f'height="{tp_h:.1f}" fill="#16a34a"/>'
            )
        bars_svg = "\n".join(bars)
    else:
        bars_svg = ""

    # 表格：最近 100 笔的关键指标
    last100 = df.tail(100)
    table_rows = []
    for _, r in last100.iterrows():
        wr = (r["rolling_win_rate"] or 0) * 100
        wr_color = "#16a34a" if wr > 50 else "#dc2626"
        table_rows.append(f"""
<tr>
  <td style="text-align:right">{int(r.name) + 1}</td>
  <td style="text-align:right">{r["cum_pnl"]:.4f}</td>
  <td style="text-align:right;color:#dc2626">{r["dd"] * 100 if pd.notna(r["dd"]) else 0:.2f}%</td>
  <td style="text-align:right;color:{wr_color}">{wr:.1f}%</td>
  <td style="text-align:right">{r["rolling_tp_pct"] * 100 if pd.notna(r["rolling_tp_pct"]) else 0:.1f}%</td>
  <td style="text-align:right">{r["rolling_sl_pct"] * 100 if pd.notna(r["rolling_sl_pct"]) else 0:.1f}%</td>
  <td style="text-align:right">{r["rolling_time_pct"] * 100 if pd.notna(r["rolling_time_pct"]) else 0:.1f}%</td>
</tr>""")
    table_html = "\n".join(table_rows)

    # 关键指标摘要
    cum_return = (equity[-1] - 1) * 100 if len(equity) else 0
    max_dd = dd_series.max() * 100 if len(dd_series) else 0
    avg_wr = df["rolling_win_rate"].dropna().mean() * 100
    final_wr = df["rolling_win_rate"].iloc[-1] * 100

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{preset_name} — 100 笔滚动指标趋势</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 20px; background: #f9fafb; color: #111827; }}
h1 {{ color: #1e3a8a; margin-bottom: 4px; }}
h2 {{ color: #1e40af; border-bottom: 2px solid #93c5fd; padding-bottom: 4px; margin-top: 32px; }}
.summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
.card {{ background: white; padding: 16px; border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.card .label {{ font-size: 12px; color: #6b7280; }}
.card .value {{ font-size: 20px; font-weight: bold; color: #1e3a8a; margin-top: 4px; }}
.chart {{ background: white; padding: 16px; border-radius: 8px; margin: 16px 0;
         box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.chart h3 {{ margin-top: 0; color: #374151; }}
table {{ width: 100%; border-collapse: collapse; background: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); font-size: 12px; }}
th {{ background: #1e40af; color: white; padding: 6px; text-align: right; }}
td {{ padding: 4px 6px; border-bottom: 1px solid #e5e7eb; }}
.legend-bar {{ display: inline-block; width: 12px; height: 12px; vertical-align: middle;
               margin-right: 4px; }}
</style>
</head>
<body>

<h1>{preset_name} — 100 笔滚动指标趋势</h1>
<p style="color:#6b7280">窗口大小: {window} 笔 · 总交易: {n} 笔 · 起始: {summary["start"]} · 截止: {summary["end"]}</p>

<div class="summary">
  <div class="card"><div class="label">累计收益</div>
    <div class="value" style="color:#16a34a">{cum_return:+.2f}%</div></div>
  <div class="card"><div class="label">最大回撤</div>
    <div class="value" style="color:#dc2626">{max_dd:.2f}%</div></div>
  <div class="card"><div class="label">平均滚动胜率</div>
    <div class="value">{avg_wr:.1f}%</div></div>
  <div class="card"><div class="label">末期滚动胜率</div>
    <div class="value">{final_wr:.1f}%</div></div>
</div>

<h2>累计复利权益曲线</h2>
<div class="chart">
  <h3>1 + ∏(1 + net_t)（基准=1）</h3>
  <svg width="700" height="200" viewBox="0 0 700 200">
    <line x1="30" y1="170" x2="670" y2="170" stroke="#e5e7eb"/>
    <line x1="30" y1="30" x2="30" y2="170" stroke="#e5e7eb"/>
    {equity_path}
  </svg>
</div>

<h2>滚动最大回撤（NAV-based）</h2>
<div class="chart">
  <h3>(peak - equity) / peak，{window} 笔滚动</h3>
  <svg width="700" height="200" viewBox="0 0 700 200">
    <line x1="30" y1="170" x2="670" y2="170" stroke="#e5e7eb"/>
    <line x1="30" y1="30" x2="30" y2="170" stroke="#e5e7eb"/>
    {dd_path}
  </svg>
</div>

<h2>滚动胜率（{window} 笔窗口）</h2>
<div class="chart">
  <h3>窗口内 net > 0 的比例</h3>
  <svg width="700" height="200" viewBox="0 0 700 200">
    <line x1="30" y1="30" x2="670" y2="30" stroke="#e5e7eb"/>
    <line x1="30" y1="100" x2="670" y2="100" stroke="#e5e7eb" stroke-dasharray="4"/>
    <line x1="30" y1="170" x2="670" y2="170" stroke="#e5e7eb"/>
    <line x1="30" y1="30" x2="30" y2="170" stroke="#e5e7eb"/>
    {win_path}
  </svg>
</div>

<h2>出场原因分布（每 {bucket_size} 笔一个柱）</h2>
<div class="chart">
  <h3>
    <span class="legend-bar" style="background:#16a34a"></span>TP
    <span class="legend-bar" style="background:#dc2626"></span>SL
    <span class="legend-bar" style="background:#6b7280"></span>time
  </h3>
  <svg width="700" height="200" viewBox="0 0 700 200">
    <line x1="30" y1="30" x2="670" y2="30" stroke="#e5e7eb"/>
    <line x1="30" y1="170" x2="670" y2="170" stroke="#e5e7eb"/>
    <line x1="30" y1="30" x2="30" y2="170" stroke="#e5e7eb"/>
    {bars_svg}
  </svg>
</div>

<h2>最近 100 笔滚动指标快照</h2>
<table>
<thead>
<tr>
  <th>序号</th><th>累计权益</th><th>DD</th><th>胜率</th>
  <th>TP%</th><th>SL%</th><th>time%</th>
</tr>
</thead>
<tbody>
{table_html}
</tbody>
</table>

</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True,
                    help="preset name (used to find trades.json)")
    ap.add_argument("--output-dir", default="short_reversal/results")
    ap.add_argument("--window-start", default=DEFAULT_WINDOW_START)
    ap.add_argument("--window-end", default=DEFAULT_WINDOW_END)
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    json_path = out_dir / f"{args.preset}.json"
    if not json_path.exists():
        raise FileNotFoundError(json_path)

    data = load_trades(json_path)
    trades_raw = data["trades"]

    # Fetch K-line context for all unique codes
    codes = sorted({t["thscode"] for t in trades_raw})
    print(f"Fetching K-lines for {len(codes)} unique codes...")
    klines = fetch_klines(codes, args.window_start, args.window_end)
    print(f"Loaded K-lines for {len(klines)}/{len(codes)} codes")

    trades = build_trade_dates(trades_raw, klines, args.window_start, args.window_end)

    trades_html = out_dir / f"{args.preset}_trades.html"
    trend_html = out_dir / f"{args.preset}_trend.html"
    render_trades_html(args.preset, data, trades, klines, trades_html)
    render_trend_html(args.preset, data, trades, trend_html)
    print(f"Generated: {trades_html}")
    print(f"Generated: {trend_html}")


if __name__ == "__main__":
    main()