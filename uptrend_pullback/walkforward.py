"""滚动窗口验证 — 同一套参数在多个独立年份上的表现。

用途：识别过拟合与未来函数。若某参数只在单一年份出色、其余年份崩溃，
即为拟合噪声；若所有年份都异常优异，通常说明代码里有未来函数。

2026-09-23 迁移: monthly_windows + yearly_windows 重新导出 core.walkforward
共用 API, 4-engine 共享同一份窗口生成代码 (CLAUDE.md §5)。
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtest import run_backtest
from uptrend_pullback.data import load_panel
from uptrend_pullback.presets import get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators
from uptrend_pullback.universe import load_universe

# 4-engine 共用 WFV 窗口生成 (CLAUDE.md §5)
from core.walkforward import (  # noqa: F401
    monthly_windows as monthly_windows,
    yearly_windows as yearly_windows,
)

logger = logging.getLogger(__name__)

RESULT_COLS = [
    "start", "end", "trades", "win_rate", "total_return",
    "sharpe", "max_dd", "avg_hold_days", "max_hold_days",
    "tp_count", "sl_count", "time_count", "signals",
]


def run_windows(
    preset: str | dict,
    windows: list[tuple[str, str]],
    db_path: Path,
    engine: str = "simulate",
) -> pd.DataFrame:
    """对每个窗口独立跑一次回测（各自加载数据与预热）。

    engine:
      - "simulate"    — 直接调用 uptrend_pullback.backtest.run_backtest（pandas 自循环）
      - "backtrader"  — 调用 uptrend_pullback.backtrader_engine 的 AStockBroker 验证
    """
    p = get_preset(preset) if isinstance(preset, str) else preset
    universe = set(load_universe(p["universe"], db_path))

    if engine == "backtrader":
        from uptrend_pullback.backtrader_engine import run_backtrader_backtest
        _runner = run_backtrader_backtest
    else:
        _runner = run_backtest

    rows = []
    for start, end in windows:
        try:
            panel = load_panel(db_path, start, end, universe=universe)
        except Exception as e:  # 数据不足的早期年份
            logger.warning("窗口 %s..%s 加载失败: %s", start, end, e)
            continue
        panel_ind = compute_indicators(panel)
        reg = compute_regime(panel_ind, **p["regime"]) if p.get("regime") else None

        res = _runner(p, start, end, db_path, panel_ind=panel_ind, regime_df=reg)
        m = res["metrics"]
        rows.append({k: m.get(k) for k in RESULT_COLS})
        logger.info("%s..%s → %+.2f%%", start, end, m["total_return"] * 100)

        # 释放 panel 内存
        del panel, panel_ind, reg, res

    return pd.DataFrame(rows, columns=RESULT_COLS)


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "（无结果）"
    r = df["total_return"]
    return (
        f"窗口数 {len(df)} | 盈利年 {int((r > 0).sum())}/{len(df)} | "
        f"中位 {r.median()*100:+.2f}% | 均值 {r.mean()*100:+.2f}% | "
        f"最差 {r.min()*100:+.2f}% | 最好 {r.max()*100:+.2f}%"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="滚动窗口验证")
    ap.add_argument("--preset", default="v33_long_reverse_v19")
    ap.add_argument("--engine", choices=("simulate", "backtrader"), default="simulate")
    # 年级窗口（向后兼容）
    ap.add_argument("--first-year", type=int, default=2017)
    ap.add_argument("--last-year", type=int, default=2026)
    # 月级窗口
    ap.add_argument("--start-month", default="", help="YYYY-MM, 启动月级窗口")
    ap.add_argument("--end-month", default="", help="YYYY-MM, 结束月级窗口")
    ap.add_argument("--window-months", type=int, default=2)
    ap.add_argument("--step-months", type=int, default=0,
                    help="0 = 不重叠 (= window-months)")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.start_month and args.end_month:
        step = args.step_months if args.step_months > 0 else args.window_months
        windows = monthly_windows(
            args.start_month, args.end_month,
            window_months=args.window_months, step_months=step,
        )
        print(f"[mode] 月级窗口: {args.window_months} 月/窗, "
              f"步长 {step} 月, 共 {len(windows)} 窗")
    else:
        windows = yearly_windows(args.first_year, args.last_year)
        print(f"[mode] 年级窗口: {args.first_year}..{args.last_year} = {len(windows)} 窗")
    print(f"[engine] {args.engine}")

    df = run_windows(args.preset, windows, Path(args.db_path), engine=args.engine)

    show = df.copy()
    for c in ("win_rate", "total_return", "max_dd"):
        show[c] = (show[c] * 100).round(2)
    show["sharpe"] = show["sharpe"].round(2)
    show["avg_hold_days"] = show["avg_hold_days"].round(1)
    print(show.to_string(index=False))
    print("\n" + summarize(df))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"\n已保存: {args.out}")


if __name__ == "__main__":
    main()
