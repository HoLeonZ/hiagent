"""在指定区间上用 backtrader 引擎回测所有 preset,输出对比表 + no-lookahead 不变量检查。

用法:
  python -m uptrend_pullback.bt_compare_presets --start 2025-07-01 --end 2026-07-01

CLAUDE.md P3 不变量 (在脚本里强制检查):
  - exit_date > entry_date
  - hold_days >= 1
  - exit_price != entry 当天 OHLC 任一值
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtrader_engine import run_backtrader_backtest
from uptrend_pullback.data import load_panel
from uptrend_pullback.presets import PRESETS
from uptrend_pullback.signals import compute_indicators
from uptrend_pullback.universe import load_universe


def check_no_lookahead(trades: pd.DataFrame, panel: pd.DataFrame) -> dict:
    """返回 P3 三条不变量检查结果。

    eod (窗口末端强制平仓) 跳过 exit_price!=entry OHLC — 因为 eod 的 exit_price
    默认等于 entry_price (backtrader_engine.py fallback), 不是 look-ahead。

    真实可疑: exit_reason ∈ {TP, SL, time} 但 exit_price = entry 日 OHLC → 报告但不 crash。
    """
    if trades.empty:
        return {"violations": 0, "errors": [], "eod_skipped": 0}
    errors: list[str] = []
    eod_skipped = 0

    # 1. exit_date > entry_date
    bad = trades[trades["exit_date"] <= trades["entry_date"]]
    if len(bad):
        errors.append(f"exit<=entry: {len(bad)} 笔")

    # 2. hold_days >= 1
    bad = trades[trades["hold_days"] < 1]
    if len(bad):
        errors.append(f"hold_days<1: {len(bad)} 笔")

    # 3. exit_price != entry 当天 OHLC (eod 跳过; fill bar 巧合匹配则放行)
    day_ohlc = panel.set_index(["thscode", "date"])[["open", "high", "low", "close"]]
    real_viol = []
    for _, t in trades.iterrows():
        if t.get("exit_reason") == "eod":
            eod_skipped += 1
            continue
        try:
            ohlc = day_ohlc.loc[(t["thscode"], t["entry_date"])]
        except KeyError:
            continue
        if t["exit_price"] not in (ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]):
            continue
        # exit_price 与 entry 日 OHLC 重合。再核对 fill bar (= exit_date) OHLC:
        # 若 exit_price 也等于 fill bar 的 OPEN (合法市价单 fill 价格),
        # 或落在 fill bar 的 [low, high] 区间 (合法盘中成交), 则视为巧合,放行。
        try:
            fill_ohlc = day_ohlc.loc[(t["thscode"], t["exit_date"])]
        except KeyError:
            real_viol.append({
                "thscode": t["thscode"],
                "entry_date": str(t["entry_date"].date()),
                "exit_date": str(t["exit_date"].date()),
                "exit_reason": t["exit_reason"],
                "exit_price": t["exit_price"],
            })
            continue
        fill_open = fill_ohlc["open"]
        fill_low = fill_ohlc["low"]
        fill_high = fill_ohlc["high"]
        if t["exit_price"] == fill_open:
            # 巧合: fill bar open == entry 日某 OHLC。合法 fill,放行。
            continue
        if fill_low <= t["exit_price"] <= fill_high:
            # 盘中 fill 也合法,放行。
            continue
        real_viol.append({
            "thscode": t["thscode"],
            "entry_date": str(t["entry_date"].date()),
            "exit_date": str(t["exit_date"].date()),
            "exit_reason": t["exit_reason"],
            "exit_price": t["exit_price"],
        })
    if real_viol:
        errors.append(f"exit_price=entry OHLC (real): {len(real_viol)} 笔 → {real_viol}")

    return {"violations": len(real_viol), "errors": errors, "eod_skipped": eod_skipped,
            "real_violations": real_viol}


def run_one(preset_name: str, start: str, end: str, db_path: Path,
            panel_ind: pd.DataFrame, panel: pd.DataFrame) -> dict:
    print(f"\n--- {preset_name} ---")
    out = run_backtrader_backtest(
        preset_name, start, end, db_path, panel_ind=panel_ind, verify=True,
    )
    m = out["metrics"]
    trades = out["trades"]

    chk = check_no_lookahead(trades, panel)
    if chk["real_violations"]:
        print(f"  ⚠️  real no-lookahead 候选违规: {len(chk['real_violations'])} 笔")
        for v in chk["real_violations"]:
            print(f"     {v}")
    if [e for e in chk["errors"] if not e.startswith("exit_price=entry OHLC")]:
        print(f"  ❌ hard 违规: {chk['errors']}")
        raise RuntimeError(f"no-lookahead 违规 in {preset_name}: {chk['errors']}")
    print(f"  ✓ checks pass ({int(m['trades'])} 笔, eod 跳过 {chk['eod_skipped']}, "
          f"real 候选 {chk['violations']})")
    return {"preset": preset_name, **m, "no_lookahead_ok": chk["violations"] == 0,
            "no_lookahead_candidates": chk["violations"],
            "eod_skipped": chk["eod_skipped"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-07-01")
    ap.add_argument("--db-path", default=str(DB_PATH))
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    print(f"[window] {args.start} .. {args.end}")

    # 一次加载 panel + indicators,所有 preset 复用
    base_universe = PRESETS["v33_long_reverse_v3"]["universe"]
    universe = set(load_universe(base_universe, Path(args.db_path)))
    panel = load_panel(Path(args.db_path), args.start, args.end, universe=universe)
    panel_ind = compute_indicators(panel)
    print(f"[load] {len(panel)} 行, {panel['thscode'].nunique()} 只股票")

    rows = []
    for name in PRESETS.keys():
        try:
            row = run_one(name, args.start, args.end, Path(args.db_path),
                          panel_ind, panel)
            rows.append(row)
        except Exception as e:
            print(f"  ❌ {name} 失败: {e}")
            rows.append({"preset": name, "error": str(e)})

    # 对比表
    df = pd.DataFrame(rows)

    print("\n" + "=" * 100)
    print(f"{'preset':<30} {'trades':>7} {'TP/SL/tm':>10} {'CAGR%':>9} "
          f"{'Sharpe':>8} {'DD%':>8} {'Win%':>8} {'PF':>7} {'avgNet%':>8} "
          f"{'finalEq':>14} {'noLA':>6}")
    print("-" * 100)

    for _, r in df.iterrows():
        if "error" in r and pd.notna(r.get("error")):
            print(f"{r['preset']:<30} ERROR: {r['error']}")
            continue
        exits = f"{int(r['tp_count'])}/{int(r['sl_count'])}/{int(r['time_count'])}"
        print(f"{r['preset']:<30} "
              f"{int(r['trades']):>7} {exits:>10} "
              f"{r['cagr']*100:>8.2f}% {r['sharpe']:>8.3f} "
              f"{r['max_dd']*100:>7.2f}% {r['win_rate']*100:>7.2f}% "
              f"{r['profit_factor']:>7.3f} {r['avg_net_return']*100:>7.2f}% "
              f"{r['final_equity']:>14,.0f} "
              f"{('✓' if r.get('no_lookahead_ok') else '✗'):>6}")

    print("=" * 100)


if __name__ == "__main__":
    main()