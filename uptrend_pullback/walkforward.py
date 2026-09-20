"""滚动窗口验证 — 同一套参数在多个独立年份上的表现。

用途：识别过拟合与未来函数。若某参数只在单一年份出色、其余年份崩溃，
即为拟合噪声；若所有年份都异常优异，通常说明代码里有未来函数。
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

logger = logging.getLogger(__name__)

RESULT_COLS = [
    "start", "end", "trades", "win_rate", "total_return",
    "sharpe", "max_dd", "avg_hold_days", "max_hold_days",
    "tp_count", "sl_count", "time_count", "signals",
]


def yearly_windows(first_year: int, last_year: int, month_day: str = "09-08") -> list[tuple[str, str]]:
    """生成 [first_year..last_year] 的逐年窗口，起止日对齐 month_day。"""
    return [
        (f"{y}-{month_day}", f"{y + 1}-{month_day}")
        for y in range(first_year, last_year)
    ]


def run_windows(
    preset: str | dict,
    windows: list[tuple[str, str]],
    db_path: Path,
) -> pd.DataFrame:
    """对每个窗口独立跑一次回测（各自加载数据与预热）。"""
    p = get_preset(preset) if isinstance(preset, str) else preset
    universe = set(load_universe(p["universe"], db_path))

    rows = []
    for start, end in windows:
        try:
            panel = load_panel(db_path, start, end, universe=universe)
        except Exception as e:  # 数据不足的早期年份
            logger.warning("窗口 %s..%s 加载失败: %s", start, end, e)
            continue
        panel_ind = compute_indicators(panel)
        reg = compute_regime(panel_ind, **p["regime"]) if p.get("regime") else None

        res = run_backtest(p, start, end, db_path, panel_ind=panel_ind, regime_df=reg)
        m = res["metrics"]
        rows.append({k: m.get(k) for k in RESULT_COLS})
        logger.info("%s..%s → %+.2f%%", start, end, m["total_return"] * 100)

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
    ap = argparse.ArgumentParser(description="逐年滚动验证")
    ap.add_argument("--preset", default="v33_long_reverse_v3")
    ap.add_argument("--first-year", type=int, default=2017)
    ap.add_argument("--last-year", type=int, default=2026)
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    windows = yearly_windows(args.first_year, args.last_year)
    df = run_windows(args.preset, windows, Path(args.db_path))

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
