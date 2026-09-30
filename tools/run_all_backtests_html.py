"""全量回测 4 个策略的所有 preset,聚合到 1 个 HTML 报告。

策略与回测入口:
  - chase_up           Phase 1 (pandas 自循环) → backtest.run_backtest
  - uptrend_pullback   Phase 1                → backtest.run_backtest
  - short_reversal     v3 (backtrader)        → engine.run_backtest_v3
  - cycle_price_action v1 (backtrader)        → backtest.run_backtest

区间:2025-09-08 → 2026-09-08(1 年,apples-to-apples)

输出:
  results/all_strategies_report.html — 单一 HTML 文件,内含:
    - 顶部摘要(策略数 / preset 数 / 总耗时 / 总错误数)
    - 跨策略排序(CAGR / Sharpe / max_dd 三张榜)
    - 4 个策略 section,每个 section:
        * preset 列表与基本参数摘要
        * 指标表(WR / CAGR / Sharpe / DD / 交易笔数 / TP/SL/time)
        * CSS 条形图(CAGR 横向条)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hiagent_config import get_db_path  # noqa: E402

DEFAULT_START = "2025-09-08"
DEFAULT_END = "2026-09-08"

OUT_DIR = REPO / "results"
OUT_HTML = OUT_DIR / "all_strategies_report.html"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy runners
# ---------------------------------------------------------------------------

def _run_chase_up(name: str, db_path: Path, start: str, end: str) -> dict[str, Any]:
    from chase_up.backtest import run_backtest

    res = run_backtest(name, start, end, db_path)
    metrics = res["metrics"]
    trades = res["trades"]
    return {
        "preset": name,
        "trades": int(metrics.get("trades", len(trades) if trades is not None else 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "cagr": float(metrics.get("cagr", 0.0)),
        "sharpe": float(metrics.get("sharpe", 0.0)),
        "max_dd": float(metrics.get("max_dd", 0.0)),
        "final_equity": float(metrics.get("final_equity", 0.0)),
        "total_return": float(metrics.get("total_return", 0.0)),
        "tp_count": int(metrics.get("tp_count", 0)),
        "sl_count": int(metrics.get("sl_count", 0)),
        "time_count": int(metrics.get("time_count", 0)),
        "eod_count": int(metrics.get("eod_count", 0)),
        "avg_hold_days": float(metrics.get("avg_hold_days", 0.0)),
        "max_hold_days": int(metrics.get("max_hold_days", 0)),
        "exposure": float(metrics.get("exposure", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "avg_net_return": float(metrics.get("avg_net_return", 0.0)),
    }


def _run_uptrend_pullback(name: str, db_path: Path, start: str, end: str) -> dict[str, Any]:
    from uptrend_pullback.backtest import run_backtest

    res = run_backtest(name, start, end, db_path)
    metrics = res["metrics"]
    trades = res["trades"]
    return {
        "preset": name,
        "trades": int(metrics.get("trades", len(trades) if trades is not None else 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "cagr": float(metrics.get("cagr", 0.0)),
        "sharpe": float(metrics.get("sharpe", 0.0)),
        "max_dd": float(metrics.get("max_dd", 0.0)),
        "final_equity": float(metrics.get("final_equity", 0.0)),
        "total_return": float(metrics.get("total_return", 0.0)),
        "tp_count": int(metrics.get("tp_count", 0)),
        "sl_count": int(metrics.get("sl_count", 0)),
        "time_count": int(metrics.get("time_count", 0)),
        "eod_count": int(metrics.get("eod_count", 0)),
        "avg_hold_days": float(metrics.get("avg_hold_days", 0.0)),
        "max_hold_days": int(metrics.get("max_hold_days", 0)),
        "exposure": float(metrics.get("exposure", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "avg_net_return": float(metrics.get("avg_net_return", 0.0)),
    }


def _run_short_reversal(name: str, db_path: Path, start: str, end: str) -> dict[str, Any]:
    from short_reversal.engine import run_backtest_v3

    m = run_backtest_v3(name, start, end, db_path)
    return {
        "preset": name,
        "trades": int(m.get("trades_count", 0)),
        "win_rate": float(m.get("win_rate", 0.0)),
        "cagr": float(m.get("cagr", 0.0)),
        "sharpe": float(m.get("sharpe", 0.0)),
        "max_dd": float(m.get("max_dd", 0.0)),
        "final_equity": float(m.get("final_capital", 0.0)),
        "total_return": float(m.get("total_yield", 0.0)),
        "tp_count": int(m.get("tp_count", 0)),
        "sl_count": int(m.get("sl_count", 0)),
        "time_count": int(m.get("time_count", 0)),
        "avg_hold_days": float(m.get("avg_hold_days", 0.0)),
        "avg_pnl": float(m.get("avg_pnl", 0.0)),
    }


def _run_cycle_price_action(name: str, db_path: Path, start: str, end: str) -> dict[str, Any]:
    """cycle_price_action 只有 1 个 preset (v1),跑一遍默认参数。
    """
    from datetime import date as _date

    from cycle_price_action.backtest import run_backtest
    from cycle_price_action.presets import PRESET_V1

    s = _date.fromisoformat(start)
    e = _date.fromisoformat(end)
    result = run_backtest(str(db_path), s, e, preset=dict(PRESET_V1))
    metrics = result.metrics
    initial = 1_000_000
    total_pnl = float(metrics.get("total_pnl", 0.0))
    return {
        "preset": name,
        "trades": int(metrics.get("n_trades", 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "cagr": float(metrics.get("cagr") or 0.0),
        "sharpe": float(metrics.get("sharpe") or 0.0),
        "max_dd": float(metrics.get("max_dd") or 0.0),
        "final_equity": float(initial + total_pnl),
        "total_return": float(total_pnl / initial),
        "avg_hold_days": float(metrics.get("avg_hold_days", 0.0)),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

STRATEGIES: list[dict[str, Any]] = [
    {
        "name": "chase_up",
        "title": "追涨策略 (chase_up, long)",
        "engine": "Phase 1 (pandas 自循环)",
        "description": "突破 + 动量 + MACROSS 三条件叠加,主板追涨。",
        "runner": _run_chase_up,
        "preset_source": lambda: list(_chase_presets()),
    },
    {
        "name": "uptrend_pullback",
        "title": "上升趋势回调策略 (uptrend_pullback, long)",
        "engine": "Phase 1 (pandas 自循环)",
        "description": "上升趋势中 N 连阴回踩 MA60 后的反转做多。",
        "runner": _run_uptrend_pullback,
        "preset_source": lambda: list(_uptrend_presets()),
    },
    {
        "name": "short_reversal",
        "title": "做空反转策略 (short_reversal, short)",
        "engine": "v3 (backtrader 事件驱动)",
        "description": "A/B/C/D 四条件做空反转,主板小盘。",
        "runner": _run_short_reversal,
        "preset_source": lambda: list(_short_presets()),
    },
    {
        "name": "cycle_price_action",
        "title": "周期价格行为策略 (cycle_price_action, long)",
        "engine": "v1 (backtrader 事件驱动)",
        "description": "K线 + 周期 + 日历三维评分共振入场。",
        "runner": _run_cycle_price_action,
        "preset_source": lambda: ["v1"],
    },
]


def _chase_presets() -> list[str]:
    from chase_up.presets import PRESETS
    return list(PRESETS.keys())


def _uptrend_presets() -> list[str]:
    from uptrend_pullback.presets import PRESETS
    return list(PRESETS.keys())


def _short_presets() -> list[str]:
    from short_reversal.presets import PRESETS
    return list(PRESETS.keys())


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_all(start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict[str, Any]:
    db_path = get_db_path()
    if not db_path.exists():
        raise SystemExit(f"DB 不存在: {db_path}")

    logger.info("DB: %s", db_path)
    logger.info("区间: %s → %s", start, end)

    started_dt = datetime.now(timezone.utc)
    overall_t0 = time.time()
    results: dict[str, list[dict[str, Any]]] = {}
    error_count = 0

    for strat in STRATEGIES:
        name = strat["name"]
        runner: Callable[[str, Path, str, str], dict[str, Any]] = strat["runner"]
        presets: list[str] = strat["preset_source"]()
        logger.info("=== %s (%d presets) ===", name, len(presets))
        rows: list[dict[str, Any]] = []
        t0 = time.time()
        for i, preset in enumerate(presets, 1):
            try:
                row = runner(preset, db_path, start, end)
                rows.append(row)
                elapsed = time.time() - t0
                eta = elapsed / i * (len(presets) - i)
                logger.info(
                    "  [%2d/%d] %-55s WR=%5.1f%%  CAGR=%+8.2f%%  "
                    "Sharpe=%5.2f  DD=%6.2f%%  trades=%3d  "
                    "[%5.1fs, ETA %4.1fs]",
                    i, len(presets), preset,
                    row.get('win_rate', 0) * 100,
                    row.get('cagr', 0) * 100,
                    row.get('sharpe', 0),
                    row.get('max_dd', 0) * 100,
                    row.get('trades', 0),
                    elapsed, eta,
                )
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                tb = traceback.format_exc(limit=1).strip().splitlines()
                msg = f"{type(exc).__name__}: {exc}"
                rows.append({
                    "preset": preset,
                    "error": msg,
                    "trace_tail": tb[-1] if tb else msg,
                })
                elapsed = time.time() - t0
                logger.warning(
                    "  [%2d/%d] %-55s FAILED  %s  [%5.1fs]",
                    i, len(presets), preset, msg, elapsed,
                )
        results[name] = rows
        logger.info("  total: %.1fs", time.time() - t0)

    overall_elapsed = time.time() - overall_t0
    return {
        "started_at": started_dt.isoformat(),
        "elapsed_seconds": overall_elapsed,
        "start": start,
        "end": end,
        "db_path": str(db_path),
        "strategies": [
            {
                "name": s["name"],
                "title": s["title"],
                "engine": s["engine"],
                "description": s["description"],
                "rows": results[s["name"]],
            }
            for s in STRATEGIES
        ],
        "error_count": error_count,
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg: #f7f8fb;
  --fg: #0f172a;
  --muted: #64748b;
  --card: #ffffff;
  --border: #e2e8f0;
  --accent: #2563eb;
  --good: #16a34a;
  --bad: #dc2626;
  --warn: #d97706;
  --neutral: #475569;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               "Microsoft YaHei", "Segoe UI", sans-serif;
  margin: 0; padding: 0;
  background: var(--bg); color: var(--fg);
  line-height: 1.55;
}
.wrap { max-width: 1280px; margin: 0 auto; padding: 32px 28px 80px; }
header.top {
  background: linear-gradient(135deg, #1e293b, #0f172a);
  color: #f1f5f9; padding: 28px 32px; border-radius: 12px;
  margin-bottom: 28px;
}
header.top h1 { margin: 0 0 6px; font-size: 22px; }
header.top .meta { color: #cbd5e1; font-size: 13px; }
header.top .meta b { color: #fff; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px; margin-bottom: 28px; }
.kpi { background: var(--card); border: 1px solid var(--border);
       border-radius: 10px; padding: 14px 16px; }
.kpi .label { color: var(--muted); font-size: 12px; letter-spacing: .04em;
              text-transform: uppercase; }
.kpi .value { font-size: 22px; font-weight: 700; color: var(--fg); margin-top: 4px; }

section.strategy {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px 24px;
  margin-bottom: 22px;
  scroll-margin-top: 20px;
}
section.strategy > h2 {
  margin: 0 0 4px; font-size: 18px;
  display: flex; align-items: center; gap: 10px;
}
section.strategy .engine-tag {
  font-size: 11px; padding: 3px 8px; border-radius: 4px;
  background: #dbeafe; color: #1d4ed8; font-weight: 600;
}
section.strategy p.desc {
  margin: 4px 0 14px; color: var(--muted); font-size: 13px;
}

.toc {
  position: sticky; top: 0; z-index: 10;
  background: rgba(247,248,251,0.96);
  backdrop-filter: blur(8px);
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 24px;
  display: flex; gap: 14px; flex-wrap: wrap;
}
.toc a {
  color: var(--neutral); text-decoration: none;
  padding: 5px 10px; border-radius: 6px; font-size: 13px;
  background: #ffffff; border: 1px solid var(--border);
}
.toc a:hover { background: #f1f5f9; }

table {
  border-collapse: collapse; width: 100%; margin-top: 8px;
  font-size: 13px;
}
th, td {
  padding: 7px 10px; border-bottom: 1px solid var(--border);
  text-align: right;
}
th:first-child, td:first-child { text-align: left; }
th {
  background: #f1f5f9; font-weight: 600; color: #334155;
  position: sticky; top: 48px;
}
tr:hover td { background: #f8fafc; }
td.num { font-variant-numeric: tabular-nums; }
td.good { color: var(--good); font-weight: 600; }
td.bad  { color: var(--bad);  font-weight: 600; }
td.neutral { color: var(--neutral); }

.bar-wrap {
  position: relative; background: #e2e8f0; border-radius: 4px;
  height: 18px; min-width: 80px; overflow: hidden;
}
.bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  border-radius: 4px;
}
.bar.neg { background: linear-gradient(90deg, #f87171, #dc2626); }
.bar-label {
  position: absolute; left: 6px; top: 0; bottom: 0;
  display: flex; align-items: center;
  font-size: 11px; color: #fff; font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,.35);
}

.error-row td { color: var(--bad); }

footer { text-align: center; color: var(--muted); font-size: 12px;
         margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); }
"""


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _fmt_num(x: float, d: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:,.{d}f}"


def _cls(v: float, good_if_pos=True) -> str:
    if good_if_pos:
        return "good" if v > 0 else ("bad" if v < 0 else "neutral")
    return "good" if v < 0 else ("bad" if v > 0 else "neutral")


def _render_table(rows: list[dict[str, Any]]) -> str:
    """Render metrics table for one strategy.
    """
    ok_rows = [r for r in rows if "error" not in r]
    err_rows = [r for r in rows if "error" in r]

    body = []
    # Pre-compute CAGR bar scale (positive + negative magnitudes)
    max_abs_cagr = max(
        (abs(r.get("cagr", 0.0)) for r in ok_rows), default=0.0
    ) or 0.01

    for r in ok_rows:
        cagr = r.get("cagr", 0.0)
        sharpe = r.get("sharpe", 0.0)
        max_dd = r.get("max_dd", 0.0)
        win = r.get("win_rate", 0.0)
        n = r.get("trades", 0)
        tp = r.get("tp_count", 0)
        sl = r.get("sl_count", 0)
        tm = r.get("time_count", 0)
        eod = r.get("eod_count", 0)
        eq = r.get("final_equity", 0.0)
        avg_hold = r.get("avg_hold_days", 0.0)

        bar_pct = (abs(cagr) / max_abs_cagr) * 100
        bar_cls = "neg" if cagr < 0 else ""
        bar_html = (
            f'<div class="bar-wrap">'
            f'<div class="bar {bar_cls}" style="width:{bar_pct:.1f}%"></div>'
            f'<span class="bar-label">{_fmt_pct(cagr)}</span>'
            f'</div>'
        )

        body.append(
            f"<tr>"
            f"<td>{escape(r.get('preset', '?'))}</td>"
            f"<td class='num'>{n}</td>"
            f"<td class='num {_cls(win, good_if_pos=True)}'>{_fmt_pct(win)}</td>"
            f"<td class='num'>{bar_html}</td>"
            f"<td class='num {_cls(sharpe, good_if_pos=True)}'>{_fmt_num(sharpe)}</td>"
            f"<td class='num {_cls(max_dd, good_if_pos=False)}'>{_fmt_pct(max_dd)}</td>"
            f"<td class='num'>{_fmt_num(eq, 0)}</td>"
            f"<td class='num'>{tp}/{sl}/{tm}/{eod}</td>"
            f"<td class='num'>{_fmt_num(avg_hold, 1)}d</td>"
            f"</tr>"
        )

    for r in err_rows:
        body.append(
            f"<tr class='error-row'>"
            f"<td>{escape(r.get('preset', '?'))}</td>"
            f"<td colspan='8'>⚠ {escape(r.get('error', ''))}</td>"
            f"</tr>"
        )

    return (
        "<table>"
        "<thead><tr>"
        "<th>preset</th><th>trades</th><th>win_rate</th><th>CAGR</th>"
        "<th>Sharpe</th><th>max_dd</th><th>final_equity</th>"
        "<th>TP/SL/time/EOD</th><th>avg_hold</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>"
    )


def _render_cross_strategy(report: dict[str, Any]) -> str:
    """Aggregate cross-strategy ranking tables (CAGR / Sharpe / max_dd).

    修复 (R527 audit): 之前用 preset 名反查 strategy 名,在 cycle_price_action
    的 "v1" 这种命名下会误归属 — 已切到 (strategy_name, row) tuple 配对。
    """
    # (strategy_name, strategy_title, row) 三元组; 标题直接绑定, 消除反查歧义。
    all_rows: list[tuple[str, str, dict[str, Any]]] = []
    for s in report["strategies"]:
        for r in s["rows"]:
            if "error" not in r:
                all_rows.append((s["name"], s["title"], r))

    def render_rank(sort_key: str, top_n: int = 8, ascending: bool = False) -> str:
        rows = sorted(
            [(sn, st, r) for sn, st, r in all_rows
             if sort_key in r and r[sort_key] is not None],
            key=lambda t: t[2][sort_key],
            reverse=not ascending,
        )[:top_n]
        body = []
        for i, (sn, st, r) in enumerate(rows, 1):
            body.append(
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{escape(st)}</td>"
                f"<td>{escape(r['preset'])}</td>"
                f"<td class='num'>{_fmt_pct(r.get('win_rate', 0))}</td>"
                f"<td class='num'>{_fmt_pct(r.get('cagr', 0))}</td>"
                f"<td class='num'>{_fmt_num(r.get('sharpe', 0))}</td>"
                f"<td class='num'>{_fmt_pct(r.get('max_dd', 0))}</td>"
                f"<td class='num'>{r.get('trades', 0)}</td>"
                f"</tr>"
            )
        return (
            f"<table>"
            f"<thead><tr>"
            f"<th>#</th><th>策略</th><th>preset</th>"
            f"<th>win_rate</th><th>CAGR</th><th>Sharpe</th>"
            f"<th>max_dd</th><th>trades</th>"
            f"</tr></thead>"
            f"<tbody>{''.join(body)}</tbody>"
            f"</table>"
        )

    cagr_top = render_rank("cagr", top_n=8)
    sharpe_top = render_rank("sharpe", top_n=8)
    dd_best = render_rank("max_dd", top_n=8, ascending=True)

    return (
        "<section class='strategy'><h2>🏆 跨策略排名(TOP-8)</h2>"
        "<p class='desc'>⚠ short_reversal 因 CAGR 体量级差异(数千%),"
        "CAGR/Sharpe 榜会被其包揽; max_dd 升序榜更有跨策略可比性。"
        "</p>"
        "<h3 style='margin:14px 0 4px;font-size:14px;color:#475569;'>按 CAGR 排序</h3>"
        + cagr_top +
        "<h3 style='margin:18px 0 4px;font-size:14px;color:#475569;'>按 Sharpe 排序</h3>"
        + sharpe_top +
        "<h3 style='margin:18px 0 4px;font-size:14px;color:#475569;'>按 max_dd (升序,回撤最小) 排序</h3>"
        + dd_best +
        "</section>"
    )


def render_html(report: dict[str, Any]) -> str:
    total_presets = sum(len(s["rows"]) for s in report["strategies"])
    ok_presets = sum(
        sum(1 for r in s["rows"] if "error" not in r) for s in report["strategies"]
    )
    elapsed = report["elapsed_seconds"]
    started_at = report["started_at"]

    # KPI cards
    kpis = [
        ("策略数", len(report["strategies"])),
        ("preset 总数", total_presets),
        ("成功", ok_presets),
        ("失败", report["error_count"]),
        ("区间", f"{report['start']} → {report['end']}"),
        ("总耗时", f"{elapsed:.1f}s"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='label'>{escape(l)}</div>"
        f"<div class='value'>{escape(str(v))}</div></div>"
        for l, v in kpis
    )

    # TOC
    toc = "<nav class='toc'>" + "".join(
        '<a href="#s-{n}">{t}</a>'.format(
            n=escape(s["name"]), t=escape(s["title"])
        )
        for s in report["strategies"]
    )
    toc += "<a href=\"#s-rank\">🏆 跨策略排名</a></nav>"

    # Strategy sections
    sections = []
    for s in report["strategies"]:
        section = (
            f"<section class='strategy' id='s-{escape(s['name'])}'>"
            f"<h2>{escape(s['title'])} "
            f"<span class='engine-tag'>{escape(s['engine'])}</span></h2>"
            f"<p class='desc'>{escape(s['description'])} "
            f"| 共 {len(s['rows'])} 个 preset "
            f"| 成功 {sum(1 for r in s['rows'] if 'error' not in r)} "
            f"| 失败 {sum(1 for r in s['rows'] if 'error' in r)}</p>"
            f"{_render_table(s['rows'])}"
            f"</section>"
        )
        sections.append(section)

    rank_section = (
        f"<section class='strategy' id='s-rank'>"
        f"{_render_cross_strategy(report)}"
        f"</section>"
    )

    body_html = "".join(sections) + rank_section

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>全量回测报告 — All Strategies ({report['start']} → {report['end']})</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>📊 全量回测报告 — All Strategies</h1>
    <div class="meta">
      区间: <b>{escape(report['start'])} → {escape(report['end'])}</b>
      &nbsp;|&nbsp; 启动: <b>{escape(started_at)}</b>
      &nbsp;|&nbsp; 耗时: <b>{elapsed:.1f}s</b>
      &nbsp;|&nbsp; DB: <b>{escape(report['db_path'])}</b>
    </div>
  </header>

  <div class="kpis">{kpi_html}</div>

  {toc}

  {body_html}

  <footer>
    Generated by tools/run_all_backtests_html.py · {datetime.now(timezone.utc).isoformat()}
  </footer>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """CLI 参数 — 机构级 reproducibility 必备(同一窗口 / 同一 DB 必复现)。"""
    p = argparse.ArgumentParser(
        description="全量回测 4 个策略, 聚合到 1 个 HTML 报告。"
    )
    p.add_argument("--start", default=DEFAULT_START,
                   help=f"起始日 YYYY-MM-DD (default: {DEFAULT_START})")
    p.add_argument("--end", default=DEFAULT_END,
                   help=f"截止日 YYYY-MM-DD (default: {DEFAULT_END})")
    p.add_argument("--db", type=Path, default=None,
                   help="DuckDB 路径 (默认走 hiagent_config + DNA_STRAT_DB)")
    p.add_argument("--out", type=Path, default=OUT_HTML,
                   help="HTML 输出路径 (default: results/all_strategies_report.html)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args = _parse_args()

    if args.db is not None:
        import os
        os.environ["DNA_STRAT_DB"] = str(args.db)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_html = args.out

    report = run_all(start=args.start, end=args.end)
    html = render_html(report)

    out_html.write_text(html, encoding="utf-8")
    logger.info("HTML written: %s (%d bytes)", out_html, len(html))

    # 同时输出 raw JSON, 便于下游工具消费
    json_path = out_html.with_suffix(".json")
    json_path.write_text(
        json.dumps(report, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("JSON written: %s", json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())