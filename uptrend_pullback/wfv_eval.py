"""§5 合规的 preset 评估器 — WFV + DSR。

把「某个 candidate 到底比现有 preset 好不好」变成一条可复现命令:

  1. 在滚动窗口上跑 WFV (默认 23 个 2-month 窗口, 1m 步 —— 与 presets.py 里
     v19/v20 的记录口径一致)
  2. 用 dna_stats.walkforward_report.format_walkforward_stats 做 DSR/Bonferroni
  3. 输出一行 JSON, 供 search log 追加

为什么要这么设计 (CLAUDE.md §5):
  - 不做「网格搜索取最高 Sharpe」: 本工具一次只评估**一个** candidate, 由人工/agent
    逐个决定下一个试什么 (因子下钻), 避免挑选偏差被网格掩盖。
  - n_trials = **到此为止累计试过的配置数**(含手动试错和评估窗口的改动)。
    ⚠️ §13.104 (2026-10-19): 它**默认取 preset 自己的 `n_comparisons`** ——
    §5 的 Iterative-Tuning Accounting 早就把这条账记在那里了 (v19=19, v20=100,
    v21=121, **v22=162**), 但在此之前**没有任何消费者** (这正是 §13.82 记的那处)。
    本文件此前把 `--n-trials` 做成**必填**, 而下面的示例教人传 `1` / `12`
    —— **两个都不是该 preset 的累积暴露** ⇒ **文档教的用法违反 §5**。
    ⇒ 现在: 不传就用 preset 的值; 显式传则覆盖, **但覆盖成什么会被打印出来**。
  - holdout 窗口不参与任何迭代, 只在最终下结论时跑一次。

用法:
  # 单一 preset —— 不传 --n-trials, 自动用 preset 的 n_comparisons (§13.104)
  python3 -m uptrend_pullback.wfv_eval --preset v33_long_reverse_v22

  # 由 base preset 派生 candidate (因子下钻: 累积暴露 = base 的 + 本轮)
  python3 -m uptrend_pullback.wfv_eval --base v33_long_reverse_v19 \\
      --overrides '{"tp_pct": 0.28, "signal.min_mom120": 0.20}' \\
      --label cand_mom020 --n-trials 19     # 若本轮新增 k 次评估, 传 19+k

  # 指定窗口范围 (迭代期 用 train 段; 最终结论 用 holdout 段)
  python3 -m uptrend_pullback.wfv_eval --preset v33_long_reverse_v22 \\
      --start-month 2024-09 --end-month 2026-03

输出: 一行 JSON 到 stdout (末行), 前面是人类可读摘要。
"""
from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy
from pathlib import Path

import duckdb

from hiagent_config import DB_PATH

from core.walkforward import monthly_windows
from dna_stats.walkforward_report import format_walkforward_stats
from uptrend_pullback.backtest import TRADING_DAYS as UP_TRADING_DAYS
from uptrend_pullback.presets import get_preset
from uptrend_pullback.walkforward import run_windows

# presets.py 中 v19/v20 的记录口径: 2-month 窗口, 1-month 步, 2024-09..2026-09 => 23 窗口
DEFAULT_START_MONTH = "2024-09"
DEFAULT_END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 1

logger = logging.getLogger("wfv_eval")


def _apply_overrides(cfg: dict, overrides: dict[str, object]) -> dict:
    """把 {'signal.min_mom120': 0.2} 这类点路径写入 cfg (返回新 dict)。"""
    out = deepcopy(cfg)
    for path, val in overrides.items():
        if "." in path:
            head, tail = path.split(".", 1)
            out.setdefault(head, {})[tail] = val
        else:
            out[path] = val
    return out


def _resolve_n_trials(cli_value: int | None, cfg: dict) -> tuple[int, str]:
    """§13.104: 决定 DSR 的选择偏差折算用哪个 `n_trials`, 并**报出来源**。

    §5 的 Iterative-Tuning Accounting 要求这个数 = **到此为止累计试过的配置数**。
    本 preset 把它记在自己的 `n_comparisons` 里 (v19=19, v20=100, v21=121, **v22=162**)。

    ⚠️ 此前 `--n-trials` 是**必填**, 而 docstring 的示例教人传 `--n-trials 1` / `12`
    —— **两个都不是该 preset 的累积暴露** ⇒ **文档教的用法违反 §5**。
    这也正是 §13.82 记的那处: "`n_comparisons` 是只写字段, 没有任何消费者"。

    ⇒ 改为: **默认取 preset 自己的 `n_comparisons`**; CLI 仍可覆盖 (派生 candidate 时用),
    但**覆盖成什么必须被打印出来**, 不得静默。
    """
    if cli_value is not None:
        return int(cli_value), "CLI --n-trials (显式覆盖)"
    n = int(cfg.get("n_comparisons", 1))
    return n, "preset 的 n_comparisons (§5 累积暴露)"


def _trading_days_per_window(windows: list[tuple[str, str]], db_path: Path) -> int:
    """§13.102: 每个窗口**实测**的交易日数 (各窗均值, 四舍五入)。

    报告器 `format_walkforward_stats` 需要它来估 DSR 的 `n_returns`, 而这个量
    **无法从窗口日期推出** (日历天 ≠ 交易日)。此前报告器里写死 `63`, 注释写
    「~63 trading days/month」—— 而**任何月份都没有 63 个交易日**, 一个 2 月窗口
    实测只有 **44** 个 ⇒ `n_returns` 被高估 43% ⇒ DSR 偏高 (乐观方向)。
    ⇒ 改为由**知道 windows 的调用方**从库里数出来, 报告器不再猜。
    """
    counts: list[int] = []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        for start, end in windows:
            n = con.execute(
                "SELECT COUNT(DISTINCT date) FROM raw_kline_daily "
                "WHERE date >= ? AND date < ?",
                [start, end],
            ).fetchone()[0]
            if n:
                counts.append(int(n))
    finally:
        con.close()
    if not counts:
        raise ValueError(
            "§13.102: 所有窗口都数不到交易日 ⇒ 无法估 n_returns。"
            "**不静默退回一个常数** (§0): 请检查窗口日期与 DB 覆盖。"
        )
    return int(round(sum(counts) / len(counts)))


def _summarize(df) -> dict:
    if df.empty:
        return {}
    r = df["total_return"]
    return {
        "windows": int(len(df)),
        "profitable": int((r > 0).sum()),
        "median_return": float(r.median()),
        "mean_return": float(r.mean()),
        "worst_return": float(r.min()),
        "best_return": float(r.max()),
        "median_sharpe": float(df["sharpe"].median()),
        "mean_sharpe": float(df["sharpe"].mean()),
        "avg_dd": float(df["max_dd"].mean()),
        "worst_dd": float(df["max_dd"].min()),
        "avg_trades": float(df["trades"].mean()),
        "total_trades": int(df["trades"].sum()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--preset", help="PRESETS 里的 preset 名")
    src.add_argument("--base", help="作为起点的 preset 名 (配合 --overrides)")
    ap.add_argument("--overrides", default="{}", help="JSON: 点路径 -> 值")
    ap.add_argument("--label", default="", help="写入 JSON 的标签")
    ap.add_argument("--n-trials", type=int, default=None,
                    help="§5 累计试过的配置数 (含本次)。**默认取 preset 的 n_comparisons** (§13.104); 仅派生 candidate 时需显式覆盖")
    ap.add_argument("--start-month", default=DEFAULT_START_MONTH)
    ap.add_argument("--end-month", default=DEFAULT_END_MONTH)
    ap.add_argument("--engine", default="simulate", choices=("simulate", "backtrader"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    base_name = args.preset or args.base
    cfg = get_preset(base_name)
    overrides = json.loads(args.overrides)
    if overrides:
        cfg = _apply_overrides(cfg, overrides)

    windows = monthly_windows(args.start_month, args.end_month,
                              window_months=WINDOW_MONTHS, step_months=STEP_MONTHS)
    db = Path(DB_PATH)
    logger.warning("WFV: %d 窗口 %s..%s engine=%s label=%s",
                   len(windows), args.start_month, args.end_month,
                   args.engine, args.label or base_name)

    df = run_windows(cfg, windows, db, engine=args.engine)
    stats = _summarize(df)

    print(f"[{args.label or base_name}] {args.start_month}..{args.end_month} "
          f"({len(windows)} windows, engine={args.engine})")
    n_trials, n_src = _resolve_n_trials(args.n_trials, cfg)
    logger.warning("§13.104: n_trials = %d (来源: %s)", n_trials, n_src)
    tdpw = _trading_days_per_window(list(windows), db)
    logger.warning("§13.102: 每窗实测交易日数 = %d (用于估 n_returns)", tdpw)
    # §13.102(①): 本族的 Sharpe 是用 `TRADING_DAYS = 243` 年化的 (§13.13 表里那条可量化的
    # 差), 而报告器默认 252 ⇒ 拿 243 年化的 Sharpe 去除 √252 会把 z 压低 1.8% (方向: 保守)。
    # ⇒ 把**本族自己的**常数传进去, 让"年化"与"去 年化"用同一个数。
    print(format_walkforward_stats(
        df, n_comparisons=n_trials, trading_days_per_window=tdpw,
        trading_days_per_year=UP_TRADING_DAYS,
    ))
    print(df.to_string(index=False))

    record = {
        "label": args.label or base_name,
        "base": base_name,
        "overrides": overrides,
        "start_month": args.start_month,
        "end_month": args.end_month,
        "engine": args.engine,
        "n_trials": n_trials,
        "n_trials_source": n_src,
        "stats": stats,
        # 关键参数快照, 便于事后复现 candidate
        "params": {k: cfg[k] for k in
                   ("tp_pct", "sl_pct", "max_hold", "max_positions",
                    "position_sizing", "price_source_for_execution") if k in cfg},
        "signal": cfg.get("signal"),
    }
    print("WFV_RECORD " + json.dumps(record, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
