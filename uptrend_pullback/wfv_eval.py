"""preset 评估器:滚动窗口 + DSR(§5 的**迭代期**工具)。

> ⚠️ 2026-10-18 更正(附七十四):此前首行写的是「**§5 合规**的 preset 评估器 —
> **WFV** + DSR」。而本工具的窗口来自 `monthly_windows`(滚动、**无 train/test 划分**;
> 默认 2 月窗 / 1 月步 ⇒ 相邻窗重叠 50%),严格说它是**样本内**评估。
> §5 要求的 WFV 是「with strict **out-of-sample** testing windows」—— 那需要**划分**,
> 本工具没有;它有的是"操作者自己换 `--start-month/--end-month`"的人工约定。
> 因此现在:**`--window-role` 是必需参数**(iteration / holdout)并写进产物,
> 好让搜索日志能分清哪一行是结论期的;而"要不要把划分做进代码"是待你定的**口径**问题。

把「某个 candidate 到底比现有 preset 好不好」变成一条可复现命令:

  1. 在滚动窗口上跑 WFV (默认 23 个 2-month 窗口, 1m 步 —— 与 presets.py 里
     v19/v20 的记录口径一致)
  2. 用 dna_stats.walkforward_report.format_walkforward_stats 做 DSR/Bonferroni
  3. 输出一行 JSON, 供 search log 追加

为什么要这么设计 (CLAUDE.md §5):
  - 不做「网格搜索取最高 Sharpe」: 本工具一次只评估**一个** candidate, 由人工/agent
    逐个决定下一个试什么 (因子下钻), 避免挑选偏差被网格掩盖。
  - n_trials 必须由调用方显式传入, 且等于**到此为止累计试过的配置数**(含手动
    试错和评估窗口的改动)。DSR 用它做选择偏差折算。
  - holdout 窗口不参与任何迭代, 只在最终下结论时跑一次。

用法:
  # 单一 preset
  python3 -m uptrend_pullback.wfv_eval --preset v33_long_reverse_v19 --n-trials 1

  # 由 base preset 派生 candidate (因子下钻用: 只写增量)
  python3 -m uptrend_pullback.wfv_eval --base v33_long_reverse_v19 \\
      --overrides '{"tp_pct": 0.28, "signal.min_mom120": 0.20}' \\
      --label cand_mom020 --n-trials 12

  # 指定窗口范围 (迭代期 用 train 段; 最终结论 用 holdout 段)
  python3 -m uptrend_pullback.wfv_eval --preset v33_long_reverse_v19 \\
      --start-month 2024-09 --end-month 2026-03 --n-trials 1

输出: 一行 JSON 到 stdout (末行), 前面是人类可读摘要。
"""
from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy
from pathlib import Path

from hiagent_config import DB_PATH

from core.walkforward import monthly_windows
from dna_stats.walkforward_report import format_walkforward_stats
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


def build_parser() -> argparse.ArgumentParser:
    """命令行解析器(**抽出来是为了可测** —— 尤其"哪些参数是必需的"这件事,
    必须能被守卫行为性地验证,而不是靠人读代码)。

    附七十四:`--n-trials`(§5 迭代计数)与 `--window-role`(§5 样本外声明)都是
    **必需**参数 —— §5 的这两半都落在"调用方必须显式声明"上。
    """
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--preset", help="PRESETS 里的 preset 名")
    src.add_argument("--base", help="作为起点的 preset 名 (配合 --overrides)")
    ap.add_argument("--overrides", default="{}", help="JSON: 点路径 -> 值")
    ap.add_argument("--label", default="", help="写入 JSON 的标签")
    # §5 (附七十四): 本工具**无法**自行验证 OOS —— 它能做的是**要求操作者声明**
    # 这段区间扮演什么角色,并把它写进产物。与 `--n-trials` 同法(那个也是必需的):
    # §5 的"迭代计数"与"样本外"两半,都落在"调用方必须显式声明"上。
    # 理由:仅靠注释里的约定("迭代期用 train 段,结论用 holdout 段"),
    # **搜索日志里分不出哪一行是 holdout** —— 而 §5 要的正是"结论必须来自 OOS"。
    ap.add_argument(
        "--window-role", required=True, choices=("iteration", "holdout"),
        help="这段区间扮演什么角色:iteration(迭代期,可以反复看)或 holdout(结论期)",
    )
    ap.add_argument("--n-trials", type=int, required=True,
                    help="§5 累计试过的配置数 (含本次); DSR 的选择偏差折算用")
    ap.add_argument("--start-month", default=DEFAULT_START_MONTH)
    ap.add_argument("--end-month", default=DEFAULT_END_MONTH)
    ap.add_argument("--engine", default="simulate", choices=("simulate", "backtrader"))
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

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
          f"({len(windows)} windows, engine={args.engine}) "
          f"role={args.window_role}")
    # §5 (附七十四): 说清**这次评估是什么**。本工具的窗口来自 `monthly_windows`
    # (滚动、无 train/test 划分;默认 2 月窗 / 1 月步 ⇒ 相邻窗重叠 50%),故严格说
    # 它是**样本内**评估 —— 适合"迭代期",**不能**直接当作结论。
    # 此前文档把它称作 "§5 合规的 preset 评估器 — WFV + DSR",而 OOS 只靠注释里的
    # 人工约定("迭代期用 train 段; 结论用 holdout 段")⇒ 产物里**没有**任何标记能把
    # 两者分开。现在:角色是**必需参数**并写进产物。
    _role_note = (
        "迭代期评估(可反复看)" if args.window_role == "iteration"
        else "结论期评估(应只跑一次;此后再改 candidate 则本行不再有效)"
    )
    print(f"  ⚠ 窗口为滚动**无划分**(默认 2 月窗 / 1 月步 ⇒ 重叠 50%)⇒ 本次是"
          f"**样本内**评估:{_role_note}。§5 的 OOS 要求靠**操作者声明角色**+"
          f"角色随产物落盘来守,不靠注释里的约定。")
    print(format_walkforward_stats(df, n_comparisons=args.n_trials))
    print(df.to_string(index=False))

    record = {
        "label": args.label or base_name,
        "base": base_name,
        "overrides": overrides,
        "start_month": args.start_month,
        "end_month": args.end_month,
        "engine": args.engine,
        "n_trials": args.n_trials,
        # §5 (附七十四): 角色随产物落盘 —— 搜索日志里从此能分出哪一行是 holdout。
        "window_role": args.window_role,
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
