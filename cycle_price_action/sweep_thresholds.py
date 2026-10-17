"""cycle_price_action 参数鲁棒性 sweep — 跨 threshold 候选值跑 WFV + DSR。

CLAUDE.md §5 合规:
  - Walk-Forward Validation (使用 core.walkforward.walkforward_windows)
  - Deflated Sharpe Ratio (DSR) 校正多 trial selection bias
  - Bonferroni 校正 per-window p-value

用法:
  python3 -m cycle_price_action.sweep_thresholds --start 2024-01-01 --end 2026-09-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from hiagent_config import get_db_path
from cycle_price_action.backtest import run_backtest
from cycle_price_action.presets import PRESET_V1
from cycle_price_action.walkforward import walkforward_windows
from dna_stats.deflated import deflated_sharpe_ratio, bonferroni_correct


# §5 (附六十 家族核查): 这里原有一个 `WINDOW_TRADING_DAYS = 126` 常数,注释写
# "窗口真实交易日数"。**它不成立**:OOS 窗口长度由 CLI `--test-months` 决定(默认
# **12** 个月 ≈ 243 个交易日),而 126 是 **6** 个月 —— 默认配置下 T 被低估一半,
# DSR 的 `sqrt(T-1)` 随之变小 ⇒ **DSR 系统性偏悲观**。
# 这与附三十二 在 `short_reversal/grid_runner.py` 上修的是**同一个缺陷**
# (用与本次运行无关的常数冒充观测数;那处是 252 vs 242,偏乐观),当时只修了一边。
# 现在改为从库日历按**每个 OOS 窗口**实际取 `count(DISTINCT date)`。

def _oos_trading_days(db_path, test_start, test_end) -> int:
    """OOS 窗口内**真实交易日数** = Sharpe 的收益观测数 T(§5)。

    取库日历的 `count(DISTINCT date)` —— 与引擎侧"某个窗口有多少个收益观测"是
    同一个量。口径保持不变(仍是"**一个**窗口的交易日数";注意 test 窗口之间可能
    重叠,`--roll-months` 默认 6 < `--test-months` 默认 12,故不把各窗口相加当独立
    观测)。这里只把"常数"换成"事实"。

    附三十二 在 `short_reversal/grid_runner.py` 上的处置是"取本次运行的真实 T,
    缺则 fail-fast"。cycle 的 metrics 目前**不发布** T(grep 无 `n_trading_days`),
    故从库日历取;若将来 cycle 发布了 T,应改为优先读它。
    """
    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        row = conn.execute(
            "SELECT count(DISTINCT date) FROM v_daily WHERE date BETWEEN ? AND ?",
            [test_start, test_end],
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row and row[0] else 0


def _sweep_one_threshold(
    threshold: float,
    windows: list,
    db_path: str,
    cash: float,
) -> dict:
    """对单个 threshold 值跑 WFV, 返回 (threshold, sharpes, total_pnl) 摘要。

    Round 24 (2026-09-28, CLAUDE.md §5 truthfulness): walkforward_windows
    返回 (train_start, train_end, test_start, test_end), 其中
    train_end < test_start (OOS)。原实现把 train_start/train_end 当成
    回测区间 → 全 in-sample,DSR/Bonferroni 校正失去意义 (correcting a
    fundamentally in-sample metric)。修复: 用 test_start/test_end 跑
    OOS 回测,DSR/Bonferroni 才能反映真实 trial-selection bias。
    """
    cfg = dict(PRESET_V1)
    cfg["threshold"] = threshold
    sharpes: list[float] = []
    pnls: list[float] = []
    ts: list[int] = []
    window_ts = [_oos_trading_days(db_path, w.test_start, w.test_end) for w in windows]
    for w, _t in zip(windows, window_ts):
        try:
            # §5 OOS: 必须用 test_* (test_start, test_end) — train_* 是 in-sample。
            result = run_backtest(
                db_path=db_path,
                start=w.test_start,
                end=w.test_end,
                cash=cash,
                preset=cfg,
            )
            sharpes.append(float(result.metrics.get("sharpe") or 0.0))
            pnls.append(float(result.metrics.get("total_pnl") or 0.0))
            ts.append(int(_t))
        except (ValueError, KeyError, RuntimeError) as e:
            print(f"  [WARN] threshold={threshold} window={w}: {e}")
            continue
    return {
        "threshold": threshold,
        "sharpes": sharpes,
        "total_pnl": sum(pnls),
        "window_ts": ts,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("cycle_price_action.sweep_thresholds")
    p.add_argument("--db", default=str(get_db_path()))
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--cash", type=float, default=1_000_000)
    p.add_argument(
        "--thresholds",
        default="1.5,2.0,2.5",
        help="comma-separated threshold 候选值 (default: 1.5,2.0,2.5)",
    )
    p.add_argument("--train-months", type=int, default=12)
    p.add_argument("--test-months", type=int, default=12)
    p.add_argument("--roll-months", type=int, default=6)
    args = p.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    windows = walkforward_windows(
        start, end,
        train_months=args.train_months,
        test_months=args.test_months,
        roll_months=args.roll_months,
    )
    thresholds = [float(t) for t in args.thresholds.split(",")]

    print(f"[sweep_thresholds] {len(thresholds)} thresholds × {len(windows)} windows")
    rows = []
    for thr in thresholds:
        summary = _sweep_one_threshold(thr, windows, args.db, args.cash)
        rows.append(summary)
        if summary["sharpes"]:
            print(f"  threshold={thr}: avg_sharpe="
                  f"{sum(summary['sharpes'])/len(summary['sharpes']):.3f} "
                  f"total_pnl={summary['total_pnl']:.2f}")

    # CLAUDE.md §5 DSR: 在 threshold × window 二维 trial 集合上报告 DSR
    if rows:
        # §5 (audit 2026-10-15): 被检验的"最优"必须是**候选之一**,而不是任意一格。
        #
        # 原为 `observed = max(all_sharpes)`,其中 all_sharpes 是 **阈值 × 窗口**
        # 展平后的每一格 —— 于是 max 可能落在某个"某个阈值恰好赶上的某个窗口"上,
        # 而 n_trials 只数**阈值个数**。**max 取 N 项、却按 T < N 折减**,两者描述的
        # 不是同一次选择(与本轮 WF 家族修的是同一个缺陷,方向相反的那一半)。
        #
        # 现在的口径与脚本自己打印的表一致:每个阈值先按窗口**取均值**(窗口是同一
        # 策略在不同数据上,不是独立 trial),再在 T 个阈值均值里取最大 ——
        # "max 取 T 项 + n_trials = T" ✓ 同一次选择。
        per_threshold_mean = {
            float(r["threshold"]): sum(r["sharpes"]) / len(r["sharpes"])
            for r in rows
            if r["sharpes"]
        }
        # §5 (附六十): T 必须是**本次运行**的观测数,不许用常数兜底。
        _all_t = [t for r in rows for t in r.get("window_ts", [])]
        if not _all_t:
            raise ValueError(
                "§5: 取不到任何 OOS 窗口的交易日数 T —— 不许用常数兜底,"
                "那正是本项要修的缺陷(附三十二 同款)"
            )
        # 各窗口长度只差几天(日历),取**均值**即为"一个窗口的交易日数"。
        _observed_t = int(round(sum(_all_t) / len(_all_t)))
        if per_threshold_mean:
            observed = max(per_threshold_mean.values())
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed,
                # n_trials = **扫过的阈值个数**(即上面取 max 的那 T 项),
                # 而不是 阈值 × 窗口 的格数 —— 窗口不是独立试验。
                n_trials=len(thresholds),
                n_returns=_observed_t,
            )
            bonferroni_p = bonferroni_correct(
                p_values=[dsr["dsr_p_value"]],
                n_comparisons=len(thresholds),
            )
            print(
                f"\n§5 DSR | observed_sharpe={observed:.3f} | "
                f"n_trials={len(thresholds)} | T={_observed_t} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"expected_max={dsr['expected_max_sharpe']:.3f} | "
                f"raw_p={dsr['dsr_p_value']:.4f} | "
                f"bonferroni_p={float(bonferroni_p[0]):.4f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
