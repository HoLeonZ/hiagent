"""uptrend_pullback 反向思路 Monte-Carlo 调参。

借鉴 short_reversal/grid_runner 的「沿参数轴枚举」思路，但改成：
  - 以 v33_long_reverse_v19 为锚点
  - 在 [min, max] 区间内随机扰动每个参数
  - 跑 N 次（默认 100）随机采样
  - 用 2m×12 步 滚动 walk-forward（共 24m）评估每个候选
  - 按综合分排序，输出 top-K

评估窗口：
  起 2024-09-08（最近 24m 开始）
  终 2026-09-08
  每窗 2m, 步 1m → 共 22 窗（不是 12 步，详见 monthly_windows）。

综合分（与 v33 邻域 sweep 同口径）：
  score = median_ret + 0.1 * sharpe - max_dd

用法：
  python3 -m uptrend_pullback.iter_reverse \\
      --iter 100 --top 10 --engine simulate --seed 42
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import random
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.presets import MAX_HOLD_LIMIT, get_preset  # noqa: E402
from uptrend_pullback.walkforward import monthly_windows, run_windows  # noqa: E402

# §5 (附六十六): 这里原有 `WINDOW_TRADING_DAYS_PER_MONTH = 21`,把 T 估成
# `21 × window_months`,理由写的是"取自仓库既有口径:walk-forward 家族用 6 个月 =
# 126 个交易日,即 126/6 = 21"。
#
# 那个"既有口径"**本身就是一个猜**(见附六十:`126` 被当成"6 个月"写死,而窗口长度是
# CLI 参数)—— 于是这里用**另一个猜**给这个猜背书。两个数都不是从运行里来的。
# 实测偏差:A 股实际月均 ≈ 20.25 个交易日(243/12)⇒ T 约 **+4% 偏乐观**
# (与附三十二 那次 252 vs 242 同量级、同方向)。
#
# 现直接取引擎发布的真实观察数 `n_daily_returns`(附六十六),不再估。

logger = logging.getLogger(__name__)


# --- 反向扰动空间（基于 v33_long_reverse_v19 邻域） ---
PERTURB_SPACE: dict[str, tuple] = {
    # signal 子字典字段
    "signal.min_above_ma60_ratio": (0.55, 0.75, float),
    "signal.min_mom120":           (0.10, 0.25, float),
    "signal.close_ma60_buffer":    (0.00, 0.05, float),
    "signal.min_down_streak":      (2, 5, int),
    "signal.max_down_streak":      (8, 15, int),
    # 注: pct_chg_low 应比 pct_chg_high 更负（low < high 数值上），即更深回调
    "signal.pct_chg_low":          (-0.10, -0.05, float),
    "signal.pct_chg_high":         (-0.035, -0.015, float),
    # 顶层字段
    "tp_pct":                      (0.25, 0.40, float),
    "sl_pct":                      (0.020, 0.035, float),
    "max_hold":                    (10, 20, int),
}


def _set_path(cfg: dict, path: str, value) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        cfg.setdefault(head, {})[tail] = value
    else:
        cfg[path] = value


def _get_path(cfg: dict, path: str):
    if "." in path:
        head, tail = path.split(".", 1)
        return cfg.get(head, {}).get(tail)
    return cfg.get(path)


def sample_preset(base: dict, rng: random.Random) -> dict:
    """从 base 出发，按 PERTURB_SPACE 随机扰动每个字段。"""
    cfg = copy.deepcopy(base)

    # 对每个轴独立采样
    for path, (lo, hi, typ) in PERTURB_SPACE.items():
        cur = _get_path(cfg, path)
        if cur is None:
            continue
        # 50% 概率扰动,50% 概率保持（保证不过度偏移）
        if rng.random() < 0.5:
            continue
        if typ is int:
            v = rng.randint(int(lo), int(hi))
        else:
            v = rng.uniform(lo, hi)
            # 把价格字段约束到 4 位小数
            if path in ("tp_pct", "sl_pct", "pct_chg_low", "pct_chg_high"):
                v = round(v, 4)
            else:
                v = round(v, 4)
        _set_path(cfg, path, v)

    # 强约束
    sig = cfg["signal"]
    if sig["min_down_streak"] > sig["max_down_streak"]:
        sig["min_down_streak"], sig["max_down_streak"] = (
            sig["max_down_streak"], sig["min_down_streak"])
    if sig["pct_chg_low"] > sig["pct_chg_high"]:
        # pct_chg_low 必须更负（数值更小），如果反了则交换
        sig["pct_chg_low"], sig["pct_chg_high"] = sig["pct_chg_high"], sig["pct_chg_low"]

    if cfg["max_hold"] > MAX_HOLD_LIMIT:
        cfg["max_hold"] = MAX_HOLD_LIMIT
    return cfg


def _mean_window_returns(windows: list[dict]) -> int | None:
    """各窗口 `n_daily_returns` 的均值(四舍五入)—— 即 DSR 的 T。

    **取均值而不是求和**:2 月窗 / 1 月步之间**重叠**,相加会把不独立的东西当独立、
    反而低估标准误;单窗口径在方向上偏保守,符合 §0(与附六十/六十四 同口径)。

    窗口缺该键 ⇒ 返回 None(由调用方 fail-fast,**不许用"每月天数 × 月数"的估计兜底**)。
    """
    ts = [int(w["n_daily_returns"]) for w in windows if w.get("n_daily_returns") is not None]
    if not ts:
        return None
    return int(round(sum(ts) / len(ts)))


def score_windows(
    cfg: dict,
    windows: list[tuple[str, str]],
    db_path: Path,
    engine: str,
) -> dict:
    """跑一组窗口，返回聚合指标 + 每窗明细。"""
    try:
        df = run_windows(cfg, windows, db_path, engine=engine)
    except (duckdb.Error, ValueError, KeyError) as e:
        return {"error": str(e)[:120], "windows": []}
    if df.empty:
        return {"error": "no result", "windows": []}

    r = df["total_return"]
    s = df["sharpe"]
    d = df["max_dd"]

    median_ret = float(r.median())
    mean_ret = float(r.mean())
    worst_ret = float(r.min())
    best_ret = float(r.max())
    sharpe_med = float(s.median())
    avg_dd = float(d.mean())
    worst_dd = float(d.max())
    n_pos = int((r > 0).sum())
    n_total = int(len(df))
    avg_trades = float(df["trades"].mean()) if "trades" in df.columns else 0.0

    # 综合分（与 grid.py run_grid 排序一致: median_ret 优先, worst_ret 次之）
    score = median_ret + 0.1 * sharpe_med - avg_dd

    return {
        "score": score,
        "median_ret": median_ret,
        "mean_ret": mean_ret,
        "worst_ret": worst_ret,
        "best_ret": best_ret,
        "sharpe_med": sharpe_med,
        "avg_dd": avg_dd,
        "worst_dd": worst_dd,
        "n_pos": n_pos,
        "n_total": n_total,
        "avg_trades": avg_trades,
        "windows": df.assign(
            start=df["start"].astype(str), end=df["end"].astype(str),
        ).to_dict(orient="records"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="uptrend_pullback 反向 Monte-Carlo 调参")
    ap.add_argument("--iter", type=int, default=100, help="随机扰动次数")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--engine", choices=("simulate", "backtrader"), default="simulate")
    ap.add_argument("--start-month", default="2024-09")
    ap.add_argument("--end-month", default="2026-09")
    ap.add_argument("--window-months", type=int, default=2)
    ap.add_argument("--step-months", type=int, default=1)
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    rng = random.Random(args.seed)
    base = get_preset("v33_long_reverse_v19")

    windows = monthly_windows(
        args.start_month, args.end_month,
        window_months=args.window_months, step_months=args.step_months,
    )
    print(f"[mode] 反向 Monte-Carlo: {args.iter} 次迭代 × {len(windows)} 个 2m 窗口 "
          f"({args.start_month}..{args.end_month}, 步 {args.step_months}m)")
    print(f"[engine] {args.engine}")
    print(f"[base] v33_long_reverse_v19 (current Pareto opt)")

    rows: list[dict] = []
    t_start = time.time()
    for i in range(args.iter):
        cfg = sample_preset(base, rng)
        t0 = time.time()
        res = score_windows(cfg, windows, Path(args.db_path), args.engine)
        dt = time.time() - t0
        if "error" in res:
            if not args.quiet:
                print(f"  [{i+1:>3}/{args.iter}] [{dt:>5.1f}s] ERR: {res['error']}", flush=True)
            continue
        row = {
            "iter": i + 1,
            "cfg": cfg,
            "score": res["score"],
            "median_ret": res["median_ret"],
            "mean_ret": res["mean_ret"],
            "worst_ret": res["worst_ret"],
            "best_ret": res["best_ret"],
            "sharpe_med": res["sharpe_med"],
            "avg_dd": res["avg_dd"],
            "worst_dd": res["worst_dd"],
            "n_pos": res["n_pos"],
            "n_total": res["n_total"],
            "avg_trades": res["avg_trades"],
            "elapsed_s": dt,
            # 附六十六:把该配置的**窗口观测数**在评分时就折成一个标量带上
            # (row 是从 res 里挑键重建的,原来的 `windows` 明细不会进 row)。
            "n_daily_returns": _mean_window_returns(res.get("windows") or []),
        }
        rows.append(row)
        if not args.quiet and ((i + 1) % 5 == 0 or i + 1 == args.iter):
            elapsed = time.time() - t_start
            eta = elapsed / (i + 1) * (args.iter - i - 1)
            print(
                f"  [{i+1:>3}/{args.iter}] [{dt:>5.1f}s, "
                f"eta={eta/60:>4.1f}m] "
                f"score={res['score']:>+7.4f} "
                f"med={res['median_ret']*100:>+7.2f}% "
                f"sharpe={res['sharpe_med']:>+5.2f} "
                f"avg_dd={res['avg_dd']*100:>+6.2f}% "
                f"n+={res['n_pos']}/{res['n_total']} "
                f"avg_tr={res['avg_trades']:.1f}",
                flush=True,
            )

    if not rows:
        print("\n[!] 全部迭代失败,无结果")
        return

    # 综合分排序
    rows.sort(key=lambda r: (-r["score"], -r["median_ret"], -r["worst_ret"]))
    print("\n=== TOP-{} (按 score=median+0.1*sharpe-avg_dd) ===".format(args.top))
    print(f"{'rank':>4} {'score':>8} {'med%':>8} {'mean%':>8} {'worst%':>8} "
          f"{'sharpe':>7} {'avg_dd%':>8} {'worst_dd%':>10} {'n+':>4} {'avg_tr':>7}")
    for rank, r in enumerate(rows[:args.top], 1):
        print(
            f"{rank:>4} {r['score']:>+8.4f} {r['median_ret']*100:>+8.2f} "
            f"{r['mean_ret']*100:>+8.2f} {r['worst_ret']*100:>+8.2f} "
            f"{r['sharpe_med']:>+7.2f} {r['avg_dd']*100:>+8.2f} "
            f"{r['worst_dd']*100:>+10.2f} {r['n_pos']:>4} {r['avg_trades']:>7.2f}",
        )

    # ================= §5 Penalty Metrics =================
    # (audit 2026-10-15) 这是一个**多 trial 搜索**(默认 100 次迭代),而此前它只打印
    # TOP-K、**没有任何惩罚指标** —— 违反 §5 verbatim:
    #   "Evaluation scripts must output DSR or apply Bonferroni corrections when
    #    reporting backtest results from multi-parameter sweeps."
    # 同仓库的姊妹脚本 `uptrend_pullback/sweep_v33_long.py` 是有的,这个漏了。
    #
    # 口径(与仓库既有约定一致):
    #   observed = **被选中那个配置**的窗口中位 Sharpe(即 rank-1 那一行);
    #   n_trials = **实际评分的配置数**(§5 Iterative-Tuning Accounting 要的是累计
    #              试验数,不是窗口数)—— 用 len(rows) 而不是 args.iter,因为失败的
    #              迭代并没有被评分;
    #   n_returns = 单窗交易日数。
    #
    # ⚠️ 仍须说清楚:TOP-K 是在**同一批窗口**上选出来的(selection in-sample)。
    # DSR 量化的正是"从 k 个配置里挑最好"带来的虚高,但**它不能代替样本外验证**。
    # 要把某个 config 当作结论,必须另外跑 OOS —— 见 `wfv_eval.py` 的 train/test 划分。
    try:
        from dna_stats.deflated import bonferroni_correct, deflated_sharpe_ratio

        observed = float(rows[0]["sharpe_med"])
        n_trials = len(rows)
        # 附六十六:T 取自本次运行(每个窗口的 `n_daily_returns`,引擎发布;
        # 见 uptrend_pullback/backtest.py),在评分时已折成标量带上。
        n_returns = rows[0].get("n_daily_returns")
        if n_returns is None:
            raise ValueError(
                "§5: 取不到窗口的真实观察数(n_daily_returns)—— 不许用"
                "「每月天数 × 月数」的估计兜底,那正是本项要修的缺陷(附六十六)"
            )
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed, n_trials=n_trials, n_returns=n_returns,
        )
        bonf = bonferroni_correct(
            p_values=[dsr["dsr_p_value"]], n_comparisons=n_trials,
        )
        print(
            f"\n§5 DSR(rank-1 配置) | observed_sharpe={observed:+.3f} | "
            f"n_trials={n_trials}(实际评分的配置数) | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"raw_p={dsr['dsr_p_value']:.4f} | "
            f"bonferroni_p={float(bonf[0]):.4f}"
        )
        print(
            f"  ⚠️ in-sample selection:TOP-K 是在上面这 {len(windows)} 个窗口上选出的。\n"
            f"     DSR 只量化「从 {n_trials} 个配置里挑最好」的虚高,**不等于**样本外验证 ——\n"
            f"     要把某个 config 当结论,请走 uptrend_pullback/wfv_eval.py 的 train/test 划分。"
        )
    except ImportError as exc:  # pragma: no cover - 仅在缺 dna_stats 时
        print(f"\n[!] §5 惩罚指标不可用({exc})—— 结果**不得**作为结论引用")

    # 输出 top-K 参数对比
    print("\n=== TOP-{} preset diff vs v19 base ===".format(args.top))
    for rank, r in enumerate(rows[:args.top], 1):
        cfg = r["cfg"]
        sig = cfg["signal"]
        diffs = []
        for path, _ in PERTURB_SPACE.items():
            cur = _get_path(cfg, path)
            base_v = _get_path(base, path)
            if cur != base_v:
                diffs.append(f"{path}={cur}")
        diffs_s = " | ".join(diffs) if diffs else "(= base v19)"
        print(f"  #{rank} iter={r['iter']}: {diffs_s}")

    # 落盘
    out_path = Path(args.out) if args.out else (
        ROOT / "uptrend_pullback" / "results"
        / f"iter_reverse_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "config": {
            "iter": args.iter,
            "engine": args.engine,
            "seed": args.seed,
            "start_month": args.start_month,
            "end_month": args.end_month,
            "window_months": args.window_months,
            "step_months": args.step_months,
            "base_preset": "v33_long_reverse_v19",
        },
        "windows": [{"start": s, "end": e} for s, e in windows],
        "results": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    print(f"\n[→] 落盘 {out_path} ({len(rows)} runs)")

    # 把 top-1 也单独 dump 出来便于 promote
    if rows:
        top1_path = out_path.with_name(out_path.stem + "_top1.json")
        top1_path.write_text(json.dumps({
            "rank": 1,
            "iter": rows[0]["iter"],
            "score": rows[0]["score"],
            "metrics": {k: rows[0][k] for k in (
                "median_ret", "mean_ret", "worst_ret", "best_ret",
                "sharpe_med", "avg_dd", "worst_dd",
                "n_pos", "n_total", "avg_trades",
            )},
            "preset": rows[0]["cfg"],
        }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[→] top-1 单独落盘 {top1_path}")


if __name__ == "__main__":
    main()
