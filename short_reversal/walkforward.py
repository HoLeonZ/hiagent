"""short_reversal 滚动窗口回测 — 同一套 preset 在多个独立窗口上的表现。

用途：识别短期 preset 的稳定性，跨最近 N 个月切成等长窗口分别回测。
窗口之间不重叠（步长 = 窗口长度），每窗独立拉取 universe 与指标 warmup。

CLAUDE.md §5 合规：4-engine 共用 core.walkforward 窗口生成 API。
末尾按 preset 报告 DSR (Deflated Sharpe Ratio) 校正多 window 的 selection bias。
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH
from core.walkforward import walkforward_windows as core_walkforward_windows  # noqa: F401
from dna_stats.deflated import deflated_sharpe_ratio

from short_reversal.engine import run_backtest_v3

logger = logging.getLogger(__name__)

RESULT_COLS = [
    "preset", "start", "end",
    "trades_count", "win_rate", "total_yield", "cagr",
    "sharpe", "max_dd", "avg_pnl", "avg_hold_days",
    "tp_count", "sl_count", "time_count",
    "final_capital",
]


def build_windows(
    start: str,
    end: str,
    window_months: int = 2,
    step_months: int | None = None,
) -> list[tuple[str, str]]:
    """生成 [start, end) 内月级窗口（YYYY-MM-DD 字符串）。

    step_months 默认 = window_months（非重叠）。
    """
    step = step_months if (step_months is not None and step_months > 0) else window_months
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    out: list[tuple[str, str]] = []
    cur = s
    while True:
        win_end = cur + pd.DateOffset(months=window_months)
        if win_end > e:
            break
        out.append((cur.strftime("%Y-%m-%d"), win_end.strftime("%Y-%m-%d")))
        cur = cur + pd.DateOffset(months=step)
    return out


def run_windows(
    preset: str,
    windows: list[tuple[str, str]],
    db_path: Path,
    min_bars: int = 150,
) -> pd.DataFrame:
    """对每个窗口独立跑一次 run_backtest_v3，返回每窗 metrics。

    min_bars 默认 150 而不是引擎默认的 200:
      2-month 窗口 panel 跨度约 9-10 个月,跨春节假期的 panel 每只票最多只有
      ~197 trading days,会被 <200 门槛全部跳过(实测 window 3 在 2025-01-18
      → 2025-03-18 panel 范围时,5338 只主板票 0 只通过)。指标 NaN gate 兜底,
      放宽门槛不会引入未来函数,只是更慢暖机。
    """
    rows: list[dict] = []
    for start, end in windows:
        logger.info("[%s] 跑 %s .. %s", preset, start, end)
        m = run_backtest_v3(preset, start, end, db_path, min_bars=min_bars)
        row = {"preset": preset}
        for k in RESULT_COLS:
            if k == "preset":
                continue
            row[k] = m.get(k)
        rows.append(row)
        logger.info(
            "[%s] %s..%s → n=%d 胜率=%.1f%% 收益=%+.2f%% CAGR=%+.2f%% DD=%.2f%%",
            preset, start, end,
            row["trades_count"], row["win_rate"] * 100,
            row["total_yield"] * 100, row["cagr"] * 100,
            row["max_dd"] * 100,
        )
    return pd.DataFrame(rows, columns=RESULT_COLS)


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "（无结果）"
    parts = []
    for preset, sub in df.groupby("preset"):
        ty = sub["total_yield"]
        cagr = sub["cagr"]
        wr = sub["win_rate"]
        n = sub["trades_count"]
        parts.append(
            f"[{preset}]\n"
            f"  窗数 {len(sub)} | 总交易 {int(n.sum())} | 平均每窗交易 {n.mean():.1f}\n"
            f"  收益: 盈利窗 {int((ty > 0).sum())}/{len(sub)} | "
            f"中位 {ty.median()*100:+.2f}% | 均值 {ty.mean()*100:+.2f}% | "
            f"最差 {ty.min()*100:+.2f}% | 最好 {ty.max()*100:+.2f}%\n"
            f"  CAGR(年化,2 月窗会剧烈放大): 中位 {cagr.median()*100:+.2f}% | "
            f"最差 {cagr.min()*100:+.2f}% | 最好 {cagr.max()*100:+.2f}%\n"
            f"  胜率: 均值 {wr.mean()*100:.1f}% | 最低 {wr.min()*100:.1f}% | 最高 {wr.max()*100:.1f}%\n"
            f"  MaxDD(年化): 均值 {sub['max_dd'].mean()*100:.2f}% | 最深 {sub['max_dd'].max()*100:.2f}%"
        )
    return "\n\n".join(parts)


def _format_window_table(df: pd.DataFrame) -> pd.DataFrame:
    show = df.copy()
    for c in ("win_rate", "total_yield", "cagr", "max_dd"):
        show[c] = (show[c] * 100).round(2)
    show["sharpe"] = show["sharpe"].round(2)
    show["avg_hold_days"] = show["avg_hold_days"].round(2)
    return show


def main() -> None:
    ap = argparse.ArgumentParser(description="short_reversal 滚动窗口回测")
    ap.add_argument(
        "--preset", action="append", required=True,
        help="preset 名，可重复传（例：--preset a --preset b）",
    )
    ap.add_argument("--start", default="2024-09-18")
    ap.add_argument("--end", default="2026-09-18")
    ap.add_argument("--window-months", type=int, default=2)
    ap.add_argument("--step-months", type=int, default=0,
                    help="0 = 与 window-months 等长（非重叠）")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    step = args.step_months if args.step_months > 0 else args.window_months
    windows = build_windows(
        args.start, args.end,
        window_months=args.window_months, step_months=step,
    )
    print(
        f"[mode] 覆盖 {args.start} → {args.end}, "
        f"{args.window_months} 月/窗, 步长 {step} 月, 共 {len(windows)} 窗"
    )
    for i, (s, e) in enumerate(windows, 1):
        print(f"  窗 {i:2d}: {s} → {e}")
    print(f"[presets] {args.preset}")

    db_path = Path(args.db_path)

    all_dfs = []
    for preset in args.preset:
        print(f"\n=== preset: {preset} ===")
        df = run_windows(preset, windows, db_path)
        print(_format_window_table(df).to_string(index=False))
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)
    print("\n" + summarize(combined))

    # CLAUDE.md §5 Penalty Metrics: 多 window sweep 必须报告 DSR
    for preset, sub in combined.groupby("preset"):
        sharpes = sub["sharpe"].dropna().astype(float).tolist()
        if not sharpes:
            continue
        observed = max(sharpes)
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed, n_trials=len(sharpes), n_returns=252,
        )
        print(
            f"\n§5 DSR for {preset} | observed_sharpe={observed:.3f} | "
            f"n_windows={len(sharpes)} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(out_path, index=False)
        print(f"\n已保存: {out_path}")


if __name__ == "__main__":
    main()
