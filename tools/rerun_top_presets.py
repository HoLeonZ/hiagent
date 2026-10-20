"""Focused re-run for top-5 selection (2026-10-09).

Scope: re-run only chase_up + uptrend_pullback presets (fast, vectorized
pandas backtests). Reuse 10-08 snapshot for short_reversal + cycle (slow
backtrader backtests, unaffected by R5-R7 plumbing fixes).

Why this scope:
  - R5 (chase_up nav_gate_ratio plumbing): only affects chase_up
  - R6 (chase_up cost-model plumbing): only affects chase_up
  - R7 (uptrend_pullback nav_gate_ratio + cost-model): only affects uptrend
  - short_reversal/cycle have no R5-R7-relevant plumbing changes

Reads existing 10-08 results/all_strategies_report.json for short_reversal
+ cycle, merges with fresh chase_up + uptrend results, writes new report,
and prints top-5 by composite (Sharpe DESC, then CAGR DESC).

Usage:
    python3 -m tools.rerun_top_presets
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hiagent_config import DB_PATH  # noqa: E402

DEFAULT_START = "2025-09-08"
DEFAULT_END = "2026-09-08"
OUT_DIR = REPO / "results"
OLD_REPORT = OUT_DIR / "all_strategies_report.json"
NEW_REPORT = OUT_DIR / "all_strategies_report_rerun.json"
NEW_REPORT_HTML = OUT_DIR / "all_strategies_report_rerun.html"


def _run_chase_up(name: str) -> dict:
    from chase_up.backtest import run_backtest
    res = run_backtest(name, DEFAULT_START, DEFAULT_END, DB_PATH)
    m = res["metrics"]
    return {
        "preset": name,
        "trades": int(m.get("trades", 0)),
        "win_rate": float(m.get("win_rate", 0.0)),
        "cagr": float(m.get("cagr", 0.0)),
        "sharpe": float(m.get("sharpe", 0.0)),
        "max_dd": float(m.get("max_dd", 0.0)),
        "final_equity": float(m.get("final_equity", 0.0)),
        "total_return": float(m.get("total_return", 0.0)),
        # 附七十二:**量纲**与**数据版本**必须随行走 —— 没有它们,TOP-5 那张表
        # 会把"日年化 Sharpe"与"逐笔近似 Sharpe"、以及"今天跑的"与"10-08 快照"
        # 混在一张榜上,而读者无从分辨。
        "sharpe_kind": m.get("sharpe_kind"),
        "data_vintage": "fresh",
    }


def _run_uptrend(name: str) -> dict:
    from uptrend_pullback.backtest import run_backtest
    res = run_backtest(name, DEFAULT_START, DEFAULT_END, DB_PATH)
    m = res["metrics"]
    return {
        "preset": name,
        "trades": int(m.get("trades", 0)),
        "win_rate": float(m.get("win_rate", 0.0)),
        "cagr": float(m.get("cagr", 0.0)),
        "sharpe": float(m.get("sharpe", 0.0)),
        "max_dd": float(m.get("max_dd", 0.0)),
        "final_equity": float(m.get("final_equity", 0.0)),
        "total_return": float(m.get("total_return", 0.0)),
        # 附七十二:**量纲**与**数据版本**必须随行走 —— 没有它们,TOP-5 那张表
        # 会把"日年化 Sharpe"与"逐笔近似 Sharpe"、以及"今天跑的"与"10-08 快照"
        # 混在一张榜上,而读者无从分辨。
        "sharpe_kind": m.get("sharpe_kind"),
        "data_vintage": "fresh",
    }


def _load_old_strategies(names: tuple[str, ...]) -> list[dict]:
    """Load short_reversal + cycle rows from 10-08 snapshot."""
    if not OLD_REPORT.exists():
        return []
    with OLD_REPORT.open() as f:
        old = json.load(f)
    out = []
    for s in old.get("strategies", []):
        if s.get("name") in names:
            for row in s.get("rows", []):
                if "error" not in row:
                    out.append({
                        "preset": row["preset"],
                        "trades": int(row.get("trades", 0)),
                        "win_rate": float(row.get("win_rate", 0.0)),
                        "cagr": float(row.get("cagr", 0.0)),
                        "sharpe": float(row.get("sharpe", 0.0)),
                        "max_dd": float(row.get("max_dd", 0.0)),
                        "final_equity": float(row.get("final_equity", 0.0)),
                        "total_return": float(row.get("total_return", 0.0)),
                        # 快照行的量纲继承旧报告(若无则 None,显示时原样带出)
                        "sharpe_kind": row.get("sharpe_kind"),
                        "data_vintage": OLD_SNAPSHOT_TAG,
                    })
    return out


def main() -> int:
    failures = 0   # §0(附六十三): 失败计数进退出码
    started = datetime.now(timezone.utc)
    t_total = time.time()

    # 1. Fresh chase_up (R5/R6 fix impact)
    from chase_up.presets import PRESETS as CHASE_PRESETS
    chase_rows: list[dict] = []
    print(f"=== chase_up ({len(CHASE_PRESETS)} presets) ===", flush=True)
    t = time.time()
    for i, name in enumerate(CHASE_PRESETS, 1):
        t0 = time.time()
        try:
            row = _run_chase_up(name)
            elapsed = time.time() - t0
            print(f"  [{i:2d}/{len(CHASE_PRESETS)}] {name}: "
                  f"sharpe={row['sharpe']:.2f} cagr={row['cagr']:.1%} "
                  f"dd={row['max_dd']:.1%} n={row['trades']} ({elapsed:.1f}s)",
                  flush=True)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [{i:2d}/{len(CHASE_PRESETS)}] {name}: ERROR {e} ({elapsed:.1f}s)",
                  flush=True)
            failures += 1   # §0(附六十三)
            continue
        chase_rows.append(row)
    print(f"  chase_up total: {time.time() - t:.1f}s", flush=True)

    # 2. Fresh uptrend (R7 fix impact)
    from uptrend_pullback.presets import PRESETS as UP_PRESETS
    up_rows: list[dict] = []
    print(f"\n=== uptrend_pullback ({len(UP_PRESETS)} presets) ===", flush=True)
    t = time.time()
    for i, name in enumerate(UP_PRESETS, 1):
        t0 = time.time()
        try:
            row = _run_uptrend(name)
            elapsed = time.time() - t0
            print(f"  [{i}/{len(UP_PRESETS)}] {name}: "
                  f"sharpe={row['sharpe']:.2f} cagr={row['cagr']:.1%} "
                  f"dd={row['max_dd']:.1%} n={row['trades']} ({elapsed:.1f}s)",
                  flush=True)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [{i}/{len(UP_PRESETS)}] {name}: ERROR {e} ({elapsed:.1f}s)",
                  flush=True)
            failures += 1   # §0(附六十三)
            continue
        up_rows.append(row)
    print(f"  uptrend total: {time.time() - t:.1f}s", flush=True)

    # 3. Reuse 10-08 short_reversal + cycle
    old_rows = _load_old_strategies(("short_reversal", "cycle_price_action"))
    short_rows = [r for r in old_rows
                  if any(r["preset"] == n
                         for n in _short_preset_names())]
    cycle_rows = [r for r in old_rows
                  if r["preset"] == "v1"]
    print(f"\n=== short_reversal (reused 10-08): {len(short_rows)} presets ===", flush=True)
    print(f"=== cycle_price_action (reused 10-08): {len(cycle_rows)} preset ===", flush=True)

    # 4. Combine + rank
    all_rows = chase_rows + up_rows + short_rows + cycle_rows
    print(f"\n=== Total: {len(all_rows)} presets ===", flush=True)

    ranked = rank_presets(all_rows)
    top5 = ranked[:5]
    for line in format_top5(top5, chase_rows, up_rows, short_rows, cycle_rows):
        print(line, flush=True)

    # 5. Write new report JSON
    strategies_payload = [
        {"name": "chase_up", "title": "追涨策略 (chase_up, long)",
         "engine": "Phase 1 (pandas)", "description": "R5/R6 plumbing-aligned",
         "rows": chase_rows},
        {"name": "uptrend_pullback", "title": "上升趋势回调策略",
         "engine": "Phase 1 (pandas)", "description": "R7 plumbing-aligned",
         "rows": up_rows},
        {"name": "short_reversal", "title": "做空反转策略",
         "engine": "v3 (backtrader, slow)", "description": "Reused 10-08 snapshot (R5-R7 not applicable)",
         "rows": short_rows},
        {"name": "cycle_price_action", "title": "周期价格行为策略",
         "engine": "v1 (backtrader, slow)", "description": "Reused 10-08 snapshot (R5-R7 not applicable)",
         "rows": cycle_rows},
    ]
    report = {
        "started_at": started.isoformat(),
        "elapsed_seconds": time.time() - t_total,
        "start": DEFAULT_START,
        "end": DEFAULT_END,
        "db_path": str(DB_PATH),
        "strategies": strategies_payload,
        "error_count": 0,
        "rerun_scope": "chase_up + uptrend_pullback fresh; short_reversal + cycle reused from 10-08",
        "top5": [
            # 附七十二:持久化的榜同样要带**量纲**与**数据版本** ——
            # 这份 JSON 会被下游/人消费,少了这两样,榜首那个数字就无法判断可比性。
            {"rank": i, "preset": r["preset"],
             "strategy": _strategy_of(r["preset"], chase_rows, up_rows, short_rows, cycle_rows),
             "sharpe": r["sharpe"], "cagr": r["cagr"],
             "max_dd": r["max_dd"], "n_trades": r["trades"],
             "sharpe_kind": r.get("sharpe_kind"),
             "data_vintage": r.get("data_vintage")}
            for i, r in enumerate(top5, 1)
        ],
    }
    NEW_REPORT.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote: {NEW_REPORT}", flush=True)
    print(f"Total elapsed: {time.time() - t_total:.1f}s", flush=True)

    # §0 (附六十三): 失败要进退出码(此前是 print(ERROR) → return 0)。
    from core.cli_verdict import cli_verdict

    _attempted = len(CHASE_PRESETS) + len(UP_PRESETS)
    _code, _msg = cli_verdict(
        failures=failures, attempted=_attempted, succeeded=_attempted - failures,
        what="preset 重跑",
    )
    print(f"\n{_msg}", flush=True)
    return _code


#: 旧快照的来源标记(写进行、也印在榜上)。
OLD_SNAPSHOT_TAG = "2026-10-08-snapshot"

_TOP5_CAVEAT = (
    # 附七十三:这一行是**可机检的声称** —— 形如 `(列 方向, 列 方向, …)`,
    # 由 `tests/test_report_self_consistency.py` 解析后与**实际顺序**比对。
    # (改排序键而忘了改这行,正是"标题与表相反"那类缺陷;我刚在隔壁那张表修掉它,
    #  转头自己又造了一遍 —— max_dd 是负数,DESC = 回撤更小者在前。)
    "=== TOP 5 (Sharpe DESC, CAGR DESC, max_dd DESC) ===",
    "⚠ 跨引擎的 Sharpe **不是同一个量**(chase/uptrend: 日年化;short_reversal: 逐笔近似)"
    " ⇒ 按 Sharpe 跨策略排序只在同一引擎内可比(每行的量纲见方括号;"
    "同族的 tools/run_all_backtests_html.py 有同样的警示)。",
    "⚠ 标注 [旧快照] 的行是复用 " + OLD_SNAPSHOT_TAG + " 的数据,"
    "**与今天重跑的行不同源** —— 那段快照早于其后的引擎修复,数字不应与新鲜行并列比较。",
)


def rank_presets(all_rows: list[dict], *, top_n: int | None = None) -> list[dict]:
    """按 Sharpe DESC → CAGR DESC → max_dd ASC 排序(纯函数,便于单测)。

    **不是**"选优建议":它只是把同一批行排序后展示;而下面 `format_top5` 会把这个榜的
    两条可比性限制明确印出来。
    """
    ranked = sorted(
        all_rows,
        key=lambda r: (-(r["sharpe"] if r["sharpe"] is not None else -1e9),
                       -(r["cagr"] if r["cagr"] is not None else -1e9),
                       # 附七十二:`max_dd` 是负数,故**降序**才是"回撤更小者在前"。
                       # 原为升序 ⇒ 平局时把**回撤最大**的排前面(与"TOP"的语义相反)。
                       -(r["max_dd"] if r["max_dd"] is not None else -1e9)),
    )
    return ranked[:top_n] if top_n else ranked


def format_top5(
    top: list[dict],
    chase_rows: list[dict],
    up_rows: list[dict],
    short_rows: list[dict],
    cycle_rows: list[dict],
) -> list[str]:
    """把榜渲染成若干**行**(纯函数,便于单测)。

    每行必须带三样东西,否则这张榜会被误读:
      ① 量纲 `[日年化]` / `[逐笔近似]`(各引擎 Sharpe 不是同一个量);
      ② 数据版本 `[旧快照]`(复用行的数字与新鲜行不同源);
      ③ 上面那两条可比性警示。
    """
    lines = list(_TOP5_CAVEAT)
    for i, r in enumerate(top, 1):
        kind = r.get("sharpe_kind") or "?"
        vintage = r.get("data_vintage") or "?"
        tag = "旧快照" if vintage and vintage != "fresh" else "今日重跑"
        lines.append(
            f"  #{i}  {r['preset']:50s}  "
            f"sharpe={r['sharpe']:6.2f}[{_SHARPE_KIND_LABEL.get(kind, kind)}]  "
            f"cagr={r['cagr']:7.1%}  dd={r['max_dd']:6.1%}  n={r['trades']:4d}  "
            f"[{tag}]  "
            f"strategy={_strategy_of(r['preset'], chase_rows, up_rows, short_rows, cycle_rows)}"
        )
    return lines


#: 量纲的短标签(与 tools/run_all_backtests_html.py 同一套口径)。
_SHARPE_KIND_LABEL = {
    "daily_returns_annualized": "日年化",
    "per_trade_ratio_approx": "逐笔近似",
}


def _short_preset_names() -> set[str]:
    from short_reversal.presets import PRESETS
    return set(PRESETS.keys())


def _strategy_of(preset: str, chase, up, short, cycle) -> str:
    if any(r["preset"] == preset for r in chase):
        return "chase_up"
    if any(r["preset"] == preset for r in up):
        return "uptrend_pullback"
    if any(r["preset"] == preset for r in short):
        return "short_reversal"
    if any(r["preset"] == preset for r in cycle):
        return "cycle_price_action"
    return "?"


if __name__ == "__main__":
    sys.exit(main())
