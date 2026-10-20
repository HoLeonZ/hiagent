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

import duckdb
import pandas as pd

from hiagent_config import DB_PATH

from core.walkforward import window_trading_days  # §5 窗口交易日数单源
from dna_stats.deflated import deflated_sharpe_ratio  # §5 Penalty Metrics
from uptrend_pullback.backtest import compute_metrics
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.presets import MAX_HOLD_LIMIT, get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators, select_entries_for_preset
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

    universe = set(load_universe(
        base["universe"], db_path, asof_date=windows[0][0]
    ))
    # returns[combo_idx][window_key] = total_return
    returns: list[dict] = [{} for _ in combos]
    trades_n: list[dict] = [{} for _ in combos]
    #: §5 Penalty Metrics 用:每 (combo, 窗口) 的 Sharpe。
    sharpes: list[dict] = [{} for _ in combos]
    #: DSR 的 `n_returns` = **评估过的交易日并集**。
    #: 不是"各窗之和" —— 窗口是 `(y-09-08, y+1-09-08)` 首尾相接,**边界日被两个窗口同时包含**,
    #: 直接相加会多算最多 `len(windows)-1` 天;而 T 偏大 ⇒ DSR **偏乐观**(附八十一 量过同款)。
    _day_union: set = set()
    #: **实际评估过的**窗口(形如 `(start, end)`)—— 用于 §5 那句"这是样本内多少窗"的声明。
    #: 单独记 span 而不是复用 `returns` 的 key:key 只有起点,单窗时会显示成 `2024-09-08 .. 2024-09-08`。
    _eval_spans: list[tuple[str, str]] = []

    for start, end in windows:
        try:
            panel = load_panel(db_path, start, end, universe=universe)
        except (duckdb.Error, ValueError, KeyError) as e:
            # §0 Fail-Fast narrowed: WFV window load is known to drop
            # early years with insufficient data. Keep warn-log + continue
            # so a single missing window does not abort the whole sweep,
            # but only catch data-shape exceptions. Programming errors /
            # MemoryError propagate.
            logger.warning("窗口 %s..%s 跳过: %s", start, end, e)
            continue
        # 逐窗仍以 `window_trading_days` 为准(单源),并在此核对"并集用的谓词"与它一致 ——
        # 否则本文件会悄悄长出第二套窗口长度口径。
        _w_days = window_trading_days(panel, start, end)
        _w_dates = set(
            panel.loc[
                (panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end)),
                "date",
            ]
        )
        if len(_w_dates) != _w_days:
            raise ValueError(
                f"§5: 窗口 {start}..{end} 的天数与单源 {_w_days} 不一致({len(_w_dates)}) —— "
                "本文件的并集口径与 core.walkforward 已经分叉"
            )
        _day_union |= _w_dates
        _eval_spans.append((start, end))
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

            # §6 单源 (附一百零九):分派规则收在 `signals.select_entries_for_preset`。
            entries = select_entries_for_preset(
                panel_ind, signal=cfg["signal"], start_date=start, end_date=end, regime_df=reg
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
            sharpes[ci][start] = m["sharpe"]

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

    # CLAUDE.md §5 Penalty Metrics:多参数网格**必须**报 DSR 或 Bonferroni。
    # 本脚本此前**一项都没有**(而它的孪生兄弟 `short_reversal/grid_runner.py` 早已补上 ⇒
    # 族内不对称,附一百零九)。口径与 `uptrend_pullback/sweep_v33_long.py` 逐字一致:
    #   observed = 全部 (combo, 窗口) 里**成功者**的最大 Sharpe(选择只在有数的配置间发生);
    #   n_trials = **枚举出的** combo 数(附八十二:没信号的 combo 不出现在 rows 里,
    #              但"枚举出它"就算试过,用 rows 长度会把 DSR 报乐观);
    #   n_returns = 评估过的交易日**并集**(见上方 `_day_union` 的注释)。
    all_sharpes = [s for per in sharpes for s in per.values() if pd.notna(s)]
    if all_sharpes and _day_union:
        _observed = max(all_sharpes)
        _dsr = deflated_sharpe_ratio(
            observed_sharpe=_observed, n_trials=len(combos), n_returns=len(_day_union),
        )
        print(
            f"\n§5 DSR | observed_sharpe={_observed:.3f} | "
            f"n_trials={len(combos)} | n_returns={len(_day_union)} | "
            f"deflated_sharpe={_dsr['deflated_sharpe']:.3f} | "
            f"expected_max={_dsr['expected_max_sharpe']:.3f} | "
            f"p_value={_dsr['dsr_p_value']:.4f}"
        )
        # §5 (附九十六 那条同形):选优必须**自己说清楚**它是样本内的 ——
        # DSR 校正的是"从 k 个里挑最好"的选择偏差,**不能**替代样本外验证。
        print(
            f"  ⚠️ in-sample selection:本榜是在 {len(rows)} 个配置 × "
            f"{len(_eval_spans)} 个**样本内年度窗**({_eval_spans[0][0]} .. {_eval_spans[-1][1]})上、"
            "按「各年中位收益」排出的;目标年未参与。DSR 不等于样本外验证 —— "
            "要把某个 config 当结论,请在**未参与选择**的窗口上复跑(§5 WFV)。"
        )

    return df.sort_values(
        ["median_ret", "worst_ret"], ascending=[False, False]
    ).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="样本内参数网格搜索")
    ap.add_argument("--preset", default="v33_long_reverse_v19")
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
