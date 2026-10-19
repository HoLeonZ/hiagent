"""v33 long mirror 信号 + 长周期 exits 网格搜索。

保留 v33 tp6 的 5 条件做入场信号,exits 用长周期合适的 ATR / 固定宽度。
目标窗口: 2025-09-16 .. 2026-09-16 (过去12个月) CAGR >= 100%
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
from uptrend_pullback.backtrader_engine import run_backtrader_backtest
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.presets import MAX_HOLD_LIMIT
from uptrend_pullback.signals import compute_indicators, select_entries_v33_long_mirror
from dna_stats.deflated import deflated_sharpe_ratio
from core.walkforward import window_trading_days  # §5 窗口交易日数单源 (附八十一)
from core.sweep_axes import (  # §0 网格是否真的在扫 (附八十七)
    DEFAULT_METRIC_KEYS, collapsed_grid_warning,
)
from uptrend_pullback.universe import load_universe

logger = logging.getLogger(__name__)

START, END = "2025-09-16", "2026-09-16"


def _set(cfg: dict, path: str, val) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        cfg.setdefault(head, {})[tail] = val
    else:
        cfg[path] = val


def sweep(base: dict, grid: dict, panel_ind, universe) -> pd.DataFrame:
    """展开 grid → 对每组合跑 simulate_portfolio → 聚合指标。"""
    keys = sorted(grid)
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*(grid[k] for k in keys))]

    rows: list[dict] = []
    for combo in combos:
        cfg = deepcopy(base)
        for k, v in combo.items():
            _set(cfg, k, v)
        if cfg["max_hold"] > MAX_HOLD_LIMIT:
            continue

        entries = select_entries_v33_long_mirror(
            panel_ind,
            start_date=START, end_date=END,
            regime_df=None,
            **{k: v for k, v in cfg["signal"].items() if k != "entry_mode"},
        )
        if entries.empty:
            continue

        trades, equity = simulate_portfolio(
            entries, panel_ind,
            tp_pct=max(cfg["tp_pct"], 0.0001),
            sl_pct=max(cfg["sl_pct"], 0.0001),
            max_hold=cfg["max_hold"], max_positions=cfg["max_positions"],
            start_date=START, end_date=END,
            atr_tp_mult=cfg.get("atr_tp_mult"),
            atr_sl_mult=cfg.get("atr_sl_mult"),
        )
        m = compute_metrics(trades, equity, max_hold=cfg["max_hold"])
        rows.append({**combo, **m, "signals": int(len(entries))})

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
        "tp_pct": 0.0,   # 占位,当 atr 模式时不使用
        "sl_pct": 0.0,
        "max_hold": 8,
        "max_positions": 5,
        "atr_tp_mult": 8.0,
        "atr_sl_mult": 2.5,
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

    # 单一维度 sweep
    grids = {
        "atr_tp_sl": {
            "atr_tp_mult": [4, 6, 8, 10, 12, 15],
            "atr_sl_mult": [1.0, 1.5, 2.0, 2.5, 3.0],
        },
        "max_hold": {
            "max_hold": [5, 8, 10, 15, 20],
        },
        "max_positions": {
            "max_positions": [1, 3, 5, 8, 10],
        },
        "fixed_tp_sl": {
            "tp_pct": [0.05, 0.08, 0.10, 0.15, 0.20, 0.30],
            "sl_pct": [0.02, 0.03, 0.05, 0.07, 0.10],
        },
        # §0 (附八十七): 三个键**必须带 `signal.` 前缀**。
        # 写成顶层(`min_above_ma60_ratio` 等)会被 `_set` 写进 cfg 顶层,而 `sweep()` 只把
        # `cfg["signal"]` 传给 `select_entries_v33_long_mirror` ⇒ 这三个键**从来没被传进去**
        # ⇒ 36 个 combo 产出**逐位相同**的结果,而报表照样印成一张敏感性表。
        # 实测(已落盘的产物 `sweep_v33_long.json`):本网格 36 combo → **1** 个不同结果。
        # 同目录 v2~v5 用的都是 `signal.xxx` 拼法。
        "loosen_signals": {
            "signal.min_above_ma60_ratio": [0.4, 0.5, 0.6, 0.7],
            "signal.pct_chg_low": [-0.10, -0.07, -0.05],
            "signal.pct_chg_high": [-0.02, -0.01, 0.0],
        },
    }

    results: dict[str, pd.DataFrame] = {}
    for name, grid in grids.items():
        print(f"\n=== sweep: {name} ({len(list(itertools.product(*grid.values())))} combos) ===")
        df = sweep(base, grid, panel_ind, universe)
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

    out = Path("uptrend_pullback/results/sweep_v33_long.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {k: v.to_dict(orient="records") for k, v in results.items()},
        indent=2, default=str,
    ))
    print(f"\n已保存: {out}")

    # §0 (附八十七): 网格有没有**真的在扫** —— 塌掉的轴不许被当成敏感性表。
    # 实测本仓库出过两条:①键名漏了 `signal.` 前缀(顶层写法不会被传给信号函数);
    # ②变的是被 base 里别的键**盖住**的参数(atr 模式下的 tp_pct/sl_pct)。
    # 判据落在**观测**(所有 combo 结果是否逐位相同),不依赖对引擎的知识。
    _collapsed = collapsed_grid_warning(
        {_n: _d.to_dict("records") for _n, _d in results.items()}, DEFAULT_METRIC_KEYS
    )
    if _collapsed:
        print(_collapsed)

    # CLAUDE.md §5 Penalty Metrics: 多 trial sweep 必须报告 DSR
    if results:
        all_sharpes: list[float] = []
        for df in results.values():
            if "sharpe" in df.columns:
                vals = df["sharpe"].dropna().tolist()
                all_sharpes.extend(float(v) for v in vals)
        if all_sharpes:
            observed = max(all_sharpes)
            # §5 (附八十二): `n_trials` 是"**试过多少个配置**",不是"有多少个配置产出了信号"。
            # `sweep()` 对没信号的 combo 直接 `continue`(**不落行**)⇒ `len(sharpes)` 少计
            # ⇒ E[max] 偏小 ⇒ **DSR 偏乐观**。§5 Iterative-Tuning Accounting 的原话是
            # "每一次迭代都计入" —— 网格**枚举出 combo 就是在算它的信号**,故枚举数才是
            # "试过多少"。(`observed` 仍取成功者的最大:选择只在有数的配置间发生。)
            _n_tried = sum(len(list(itertools.product(*g.values()))) for g in grids.values())
            _n_ok = int(len(all_sharpes))
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=_n_tried, n_returns=window_trading_days(panel, START, END)
            )
            print(
                f"\n§5 DSR | observed_sharpe={observed:.3f} | "
                f"n_trials={_n_tried} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"expected_max={dsr['expected_max_sharpe']:.3f} | "
                f"p_value={dsr['dsr_p_value']:.4f}"
            )
            # §5 (附九十六): 单一窗口选优**必须自己说清楚** ——
            # 与 附十七 给 chase 两个脚本加的那条同形;那回只覆盖了看到的两处,
            # 本族六个脚本一直没声明(实测:全库 11 个网格脚本里 8 个无声明)。
            print(
                f"  ⚠️ in-sample selection:本榜是在单一窗口 {START} → {END} 上\n"
                f"     从 {_n_ok} 个配置里选出的。DSR 不能替代样本外验证 ——\n"
                f"     要把某个 config 当结论,请用滚动窗口的 uptrend_pullback/wfv_eval.py,\n"
                f"     或在本榜**未参与选择**的窗口上复跑(§5 WFV)。"
            )
            if _n_tried != _n_ok:
                print(
                    f"  ⚠️ 其中 {_n_tried - _n_ok} 个配置**没产出信号**"
                    f"(sweep 里 `entries.empty → continue`)—— 它们同样计入 n_trials"
                    f"(§5:每次迭代都算)"
                )


if __name__ == "__main__":
    main()
