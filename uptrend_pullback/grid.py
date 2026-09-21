"""参数网格搜索 — 仅在样本内窗口上评估，目标年不参与。

用法约束（防过拟合）：
  - windows 必须是样本内年份；目标年（2025-09..2026-09）不得出现在这里
  - 排序目标默认用「各年收益中位数」而非均值，避免被单一暴利年绑架
  - 每个窗口只加载一次面板，所有参数组合复用，故可跑上百组合

���数路径写法：
  "max_positions"          → 顶层字段
  "signal.min_mom120"      → signal 子字典
  "regime.ma_window"       → regime 子字典
"""
from __future__ import annotations

import argparse
import copy
import itertools
import logging
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtest import compute_metrics
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.presets import MAX_HOLD_LIMIT, get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators, select_entries
from uptrend_pullback.universe import load_universe

logger = logging.getLogger(__name__)

# 目标年——禁止出现在调参窗口里
HOLDOUT = ("2025-09-08", "2026-09-08")

GRIDS: dict[str, dict[str, list]] = {
    # 第一阶段：大盘择时（对亏损年影响最大）
    "regime": {
        "regime.ma_window": [20, 40, 60],
        "regime.min_breadth": [0.40, 0.50, 0.55],
        "regime.require_rising": [False, True],
    },
    # 第二阶段：止盈止损宽度
    "stops": {
        "atr_tp_mult": [2.5, 3.0, 4.0, 5.0],
        "atr_sl_mult": [1.5, 2.0, 2.5],
    },
    # 第三阶段：选股严格度
    "signal": {
        "signal.min_mom120": [0.0, 0.10, 0.20],
        "signal.max_pullback": [0.10, 0.14, 0.18],
        "signal.max_down_streak": [3, 5],
    },
    # 第四阶段：并行仓位数
    "slots": {
        "max_positions": [3, 4, 5, 8],
    },
}


def _set_path(cfg: dict, path: str, value) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        if cfg.get(head) is None:
            cfg[head] = {}
        cfg[head][tail] = value
    else:
        cfg[path] = value


def _expand(grid: dict[str, list]) -> list[dict]:
    keys = sorted(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def run_grid(
    base_preset: str | dict,
    grid: dict[str, list],
    windows: list[tuple[str, str]],
    db_path: Path,
    *,
    allow_holdout: bool = False,
) -> pd.DataFrame:
    """对每个参数组合，在所有窗口上回测，返回聚合表。"""
    if not allow_holdout and HOLDOUT in [tuple(w) for w in windows]:
        raise ValueError(
            f"调参窗口包含目标年 {HOLDOUT}；这会导致过拟合。"
            f"如确需评估请显式传 allow_holdout=True"
        )

    base = get_preset(base_preset) if isinstance(base_preset, str) else base_preset
    combos = _expand(grid)
    logger.info("网格: %d 组合 × %d 窗口 = %d 次回测",
                len(combos), len(windows), len(combos) * len(windows))

    universe = set(load_universe(base["universe"], db_path))
    # returns[combo_idx][window_key] = total_return
    returns: list[dict] = [{} for _ in combos]
    trades_n: list[dict] = [{} for _ in combos]

    for start, end in windows:
        try:
            panel = load_panel(db_path, start, end, universe=universe)
        except Exception as e:
            logger.warning("窗口 %s..%s 跳过: %s", start, end, e)
            continue
        panel_ind = compute_indicators(panel)
        regime_cache: dict[tuple, pd.DataFrame] = {}

        for ci, combo in enumerate(combos):
            cfg = copy.deepcopy(base)
            for path, val in combo.items():
                _set_path(cfg, path, val)
            if cfg["max_hold"] > MAX_HOLD_LIMIT:
                raise ValueError(f"max_hold={cfg['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

            reg = None
            if cfg.get("regime"):
                rkey = tuple(sorted(cfg["regime"].items()))
                if rkey not in regime_cache:
                    regime_cache[rkey] = compute_regime(panel_ind, **cfg["regime"])
                reg = regime_cache[rkey]

            entries = select_entries(
                panel_ind, start_date=start, end_date=end, regime_df=reg, **cfg["signal"]
            )
            trades_df, equity_df = simulate_portfolio(
                entries, panel_ind,
                tp_pct=cfg["tp_pct"], sl_pct=cfg["sl_pct"],
                max_hold=cfg["max_hold"], max_positions=cfg["max_positions"],
                start_date=start, end_date=end,
                atr_tp_mult=cfg.get("atr_tp_mult"), atr_sl_mult=cfg.get("atr_sl_mult"),
            )
            m = compute_metrics(trades_df, equity_df, max_hold=cfg["max_hold"])
            returns[ci][start] = m["total_return"]
            trades_n[ci][start] = m["trades"]

        logger.info("窗口 %s..%s 完成", start, end)
        del panel, panel_ind, regime_cache

    rows = []
    for ci, combo in enumerate(combos):
        r = pd.Series(returns[ci], dtype=float)
        if r.empty:
            continue
        rows.append({
            **combo,
            "median_ret": r.median(),
            "mean_ret": r.mean(),
            "worst_ret": r.min(),
            "best_ret": r.max(),
            "n_positive": int((r > 0).sum()),
            "n_windows": int(len(r)),
            "avg_trades": float(pd.Series(trades_n[ci]).mean()),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        ["median_ret", "worst_ret"], ascending=[False, False]
    ).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="样本内参数网格搜索")
    ap.add_argument("--preset", default="v33_long_reverse_v14")
    ap.add_argument("--grid", default="regime", choices=sorted(GRIDS))
    ap.add_argument("--first-year", type=int, default=2017)
    ap.add_argument("--last-year", type=int, default=2025, help="不含目标年")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    windows = [
        (f"{y}-09-08", f"{y + 1}-09-08") for y in range(args.first_year, args.last_year)
    ]
    print(f"样本内窗口: {windows[0][0]} .. {windows[-1][1]}  ({len(windows)} 年)")

    df = run_grid(args.preset, GRIDS[args.grid], windows, Path(args.db_path))
    show = df.head(args.top).copy()
    for c in ("median_ret", "mean_ret", "worst_ret", "best_ret"):
        show[c] = (show[c] * 100).round(2)
    print(show.to_string(index=False))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"\n已保存: {args.out}")


if __name__ == "__main__":
    main()
