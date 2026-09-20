"""滚动窗口验证 — 同一套参数在多个独立时间窗口上的表现 (沿用 uptrend_pullback/walkforward.py 口径)。

目的:识别过拟合与未来函数。若某参数只在主窗口出色、子窗口崩溃,即为拟合噪声;
若所有窗口都异常优异,通常说明代码里有未来函数。
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from chase_up.backtest import run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe

from hiagent_config import DB_PATH

logger = logging.getLogger(__name__)

RESULT_COLS = [
    "start", "end", "trades", "win_rate", "total_return",
    "cagr", "sharpe", "max_dd", "avg_hold_days", "max_hold_days",
    "tp_count", "sl_count", "time_count", "signals",
]


def monthly_windows(
    start_month: str,
    end_month: str,
    window_months: int = 2,
    step_months: int = 0,
) -> list[tuple[str, str]]:
    """生成 [start_month, end_month) 内的月级窗口,日期形如 'YYYY-MM-DD'。"""
    step = step_months if step_months > 0 else window_months
    sy, sm = map(int, start_month.split("-"))
    ey, em = map(int, end_month.split("-"))
    cur_y, cur_m = sy, sm
    out = []
    while True:
        end_y, end_m = cur_y, cur_m + window_months
        while end_m > 12:
            end_m -= 12
            end_y += 1
        if (end_y, end_m) > (ey, em):
            break
        out.append((f"{cur_y:04d}-{cur_m:02d}-01", f"{end_y:04d}-{end_m:02d}-01"))
        cur_m += step
        while cur_m > 12:
            cur_m -= 12
            cur_y += 1
    return out


def run_windows(
    preset: str | dict,
    windows: list[tuple[str, str]],
    db_path: Path,
    engine: str = "simulate",
) -> pd.DataFrame:
    """对每个窗口独立跑一次回测(各自加载数据与预热)。"""
    from chase_up.presets import get_preset
    p = get_preset(preset) if isinstance(preset, str) else preset
    universe = set(load_universe(p["universe"], db_path))

    if engine == "backtrader":
        from chase_up.backtrader_engine import run_backtrader_backtest
        _runner = run_backtrader_backtest
    else:
        _runner = run_backtest

    rows = []
    for start, end in windows:
        try:
            panel = load_panel(db_path, start, end, universe=universe)
        except Exception as e:
            logger.warning("窗口 %s..%s 加载失败: %s", start, end, e)
            continue
        panel_ind = compute_indicators(panel)

        res = _runner(p, start, end, db_path, panel_ind=panel_ind)
        m = res["metrics"]
        rows.append({k: m.get(k) for k in RESULT_COLS})
        logger.info("%s..%s → %+.2f%%", start, end, m["total_return"] * 100)

        del panel, panel_ind, res

    return pd.DataFrame(rows, columns=RESULT_COLS)


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "（无结果）"
    r = df["total_return"]
    return (
        f"窗口数 {len(df)} | 盈利窗 {int((r > 0).sum())}/{len(df)} | "
        f"中位 {r.median()*100:+.2f}% | 均值 {r.mean()*100:+.2f}% | "
        f"最差 {r.min()*100:+.2f}% | 最好 {r.max()*100:+.2f}%"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="chase_up 滚动窗口验证")
    ap.add_argument("--preset", default="chase_v1_atr_tp4_sl1")
    ap.add_argument("--engine", choices=("simulate", "backtrader"), default="simulate")
    ap.add_argument("--start-month", default="2017-09")
    ap.add_argument("--end-month", default="2026-09")
    ap.add_argument("--window-months", type=int, default=12,
                    help="主回测窗口长度(月)")
    ap.add_argument("--step-months", type=int, default=0,
                    help="滚动步长;0=不重叠=window-months")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    windows = monthly_windows(
        args.start_month, args.end_month,
        window_months=args.window_months, step_months=args.step_months,
    )
    print(f"[mode] {args.window_months}m 窗口, 步长 {args.step_months or args.window_months}m, "
          f"共 {len(windows)} 窗")
    print(f"[engine] {args.engine}")

    df = run_windows(args.preset, windows, Path(args.db_path), engine=args.engine)

    show = df.copy()
    for c in ("win_rate", "total_return", "max_dd"):
        show[c] = (show[c] * 100).round(2)
    show["cagr"] = (show["cagr"] * 100).round(2)
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