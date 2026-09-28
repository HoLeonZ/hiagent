"""v33 long mirror 信号 + 长周期 exits 网格搜索 v2。

修复 v1 的 _set() bug (key 无 . 前缀时进顶层而非 signal/regime 子层)。
新增 position_sizing=all_in/kelly + max_positions 组合;测试全仓 + 1 slot 复利模式。
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtest import compute_metrics
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.signals import compute_indicators, select_entries_v33_long_mirror
from dna_stats.deflated import deflated_sharpe_ratio
from uptrend_pullback.universe import load_universe

logger = logging.getLogger(__name__)

START, END = "2025-09-16", "2026-09-16"


def _set(cfg: dict, path: str, val) -> None:
    """set helper: 'a.b.c' → cfg['a']['b']['c']; 'foo' → cfg['foo'].

    注意: 信号/regime 子字段必须写 'signal.x' / 'regime.x' (带点)。
    """
    if "." in path:
        head, tail = path.split(".", 1)
        cfg.setdefault(head, {})[tail] = val
    else:
        cfg[path] = val


def sweep(base: dict, grid: dict, panel_ind, *, max_signals: int = 5000) -> pd.DataFrame:
    """展开 grid → 每组合跑 simulate_portfolio → 聚合指标。"""
    keys = sorted(grid)
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*(grid[k] for k in keys))]

    rows: list[dict] = []
    for combo in combos:
        cfg = deepcopy(base)
        for k, v in combo.items():
            _set(cfg, k, v)

        sig_kwargs = {k: v for k, v in cfg["signal"].items() if k != "entry_mode"}
        entries = select_entries_v33_long_mirror(
            panel_ind,
            start_date=START, end_date=END,
            regime_df=None,
            **sig_kwargs,
        )
        if entries.empty:
            continue
        if len(entries) > max_signals:
            # 极端宽松信号 → 信号太多会拖慢 sweep,截断到 top-N by score
            entries = entries.nlargest(max_signals, "score")

        kwargs = dict(
            tp_pct=max(cfg["tp_pct"], 0.0001),
            sl_pct=max(cfg["sl_pct"], 0.0001),
            max_hold=cfg["max_hold"],
            max_positions=cfg["max_positions"],
            start_date=START, end_date=END,
            atr_tp_mult=cfg.get("atr_tp_mult"),
            atr_sl_mult=cfg.get("atr_sl_mult"),
        )
        ps = cfg.get("position_sizing", "equal")
        if ps != "equal":
            kwargs["position_sizing"] = ps
        if ps == "kelly":
            kwargs["kelly_fraction"] = cfg.get("kelly_fraction", 0.25)

        trades, equity = simulate_portfolio(entries, panel_ind, **kwargs)
        m = compute_metrics(trades, equity, max_hold=cfg["max_hold"])
        rows.append({
            **{k: v for k, v in combo.items()},
            **m, "signals": int(len(entries)),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        "cagr", ascending=False
    ).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    print(f"[load] {START} .. {END}")
    base = {
        "universe": "mainboard_only",
        "tp_pct": 0.10,
        "sl_pct": 0.03,
        "max_hold": 10,
        "max_positions": 5,
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.07,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
        },
    }

    universe = set(load_universe(base["universe"], Path(args.db_path), asof_date=START))
    panel = load_panel(Path(args.db_path), START, END, universe=universe)
    panel_ind = compute_indicators(panel)

    grids = {
        # 关闭 ATR 模式,直接扫固定 TP/SL
        "fixed_tp_sl": {
            "tp_pct": [0.06, 0.10, 0.15, 0.20, 0.25, 0.30],
            "sl_pct": [0.01, 0.02, 0.03, 0.05, 0.07],
        },
        "max_hold": {
            "max_hold": [5, 8, 10, 15, 20],
        },
        "max_positions": {
            "max_positions": [3, 5, 8, 10, 15, 20, 30],
        },
        # 单仓全仓复利 (max_positions=1, all_in)
        "all_in": {
            "position_sizing": ["all_in"],
            "max_positions": [1],
            "tp_pct": [0.06, 0.10, 0.15, 0.20],
            "sl_pct": [0.01, 0.02, 0.03, 0.05],
            "max_hold": [5, 10, 20],
        },
        # Kelly 半仓 (max_positions=1, kelly_fraction=0.25)
        "kelly": {
            "position_sizing": ["kelly"],
            "kelly_fraction": [0.10, 0.20, 0.30, 0.50],
            "max_positions": [1],
            "tp_pct": [0.10, 0.15, 0.20],
            "sl_pct": [0.02, 0.03, 0.05],
            "max_hold": [5, 10, 20],
        },
        # 信号条件放宽 (向上突破 + ret1 负值)
        "loosen": {
            "signal.min_above_ma60_ratio": [0.3, 0.4, 0.5, 0.6],
            "signal.pct_chg_low": [-0.10, -0.07, -0.05],
        },
        # 信号条件收紧 (提升信噪比)
        "tighten": {
            "signal.min_above_ma60_ratio": [0.6, 0.7, 0.8, 0.9],
            "signal.min_down_streak": [3, 4, 5],
            "signal.max_down_streak": [7, 10, 15],
        },
    }

    results: dict[str, pd.DataFrame] = {}
    for name, grid in grids.items():
        combos = list(itertools.product(*grid.values()))
        print(f"\n=== sweep: {name} ({len(combos)} combos) ===")
        df = sweep(base, grid, panel_ind)
        if df.empty:
            print("  no signals")
            continue
        results[name] = df
        show = df.head(args.top).copy()
        for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
                  "avg_net_return", "exposure"):
            if c in show.columns:
                if c in ("cagr", "win_rate", "max_dd", "total_return",
                         "avg_net_return", "exposure"):
                    show[c] = (show[c] * 100).round(2)
                else:
                    show[c] = show[c].round(2)
        cols = [c for c in (
            list(grid.keys()) + ["signals", "trades", "cagr", "win_rate",
                                  "tp_count", "sl_count", "time_count",
                                  "max_dd", "sharpe", "avg_hold_days",
                                  "exposure", "final_equity"]
        ) if c in show.columns]
        print(show[cols].to_string(index=False))

    out = Path("uptrend_pullback/results/sweep_v33_long_v2.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {k: v.to_dict(orient="records") for k, v in results.items()},
        indent=2, default=str,
    ))
    print(f"\n已保存: {out}")

    # CLAUDE.md §5 Penalty Metrics: 多 trial sweep 必须报告 DSR
    if results:
        all_sharpes: list[float] = []
        for df in results.values():
            if "sharpe" in df.columns:
                vals = df["sharpe"].dropna().tolist()
                all_sharpes.extend(float(v) for v in vals)
        if all_sharpes:
            observed = max(all_sharpes)
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=len(all_sharpes), n_returns=252
            )
            print(
                f"\n§5 DSR | observed_sharpe={observed:.3f} | "
                f"n_trials={len(all_sharpes)} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"expected_max={dsr['expected_max_sharpe']:.3f} | "
                f"p_value={dsr['p_value']:.4f}"
            )


if __name__ == "__main__":
    main()