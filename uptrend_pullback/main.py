"""CLI 入口 — 上升趋势回调做多回测。

用法:
  python3 -m uptrend_pullback.main --preset v33_long_reverse_v3 --start 2025-09-08 --end 2026-09-08
  python3 -m uptrend_pullback.main --engine simulate --preset v33_long_reverse_v3 ...   # 自定义事件循环（对照）
  python3 -m uptrend_pullback.main --engine backtrader --no-verify ... # 仅 Phase 1，不跑 backtrader
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from uptrend_pullback.backtest import INITIAL_CAPITAL, run_backtest
from uptrend_pullback.backtrader_engine import run_backtrader_backtest
from core.trade_report import render_trade_report, report_filename
from uptrend_pullback.data import load_panel
from uptrend_pullback.presets import get_preset
from uptrend_pullback.signals import compute_indicators
from uptrend_pullback.universe import load_universe

from hiagent_config import DB_PATH as DEFAULT_DB


# §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv canonical schemas.
# 2026-10-19: 两个元组已上收至 core.trade_schema (单一来源) ——
#   三份拷贝此前逐字节相同, 但没有任何东西拦住它们分岔。见 core/trade_schema.py 的说明。
from core.trade_schema import CASH_WALK_COLS, EQUITY_CURVE_COLS


def _write_per_preset_metrics(
    out_dir: Path,
    metrics: dict,
    preset: str,
) -> Path:
    """Write per-preset audit-trail metrics JSON (§2/§3 Tick 58)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = dict(metrics)
    out = out_dir / f"{preset}_metrics.json"
    out.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    return out


def _write_equity_curve(
    equity_path: Path,
    cash_walk_path: Path,
    equity: pd.DataFrame,
) -> None:
    """Write equity_curve.csv + cash_walk.csv (§2/§3 Tick 51).

    §2 (audit P0-1, 2026-10-15): cash_walk 如实落盘三池;旧实现把
    locked_margin / settling_funds 硬编码为 0、把 total_cash 当作
    free_cash 写出,`nav` 也用重复计入持仓成本的表达式。缺列时显式回退。
    """
    equity_path.parent.mkdir(parents=True, exist_ok=True)
    cash_walk_path.parent.mkdir(parents=True, exist_ok=True)

    eq = equity.copy()
    eq = eq.rename(columns={"holdings": "position_value"})
    eq["drawdown"] = 0.0
    if "equity" in eq.columns:
        peak = eq["equity"].cummax()
        eq["drawdown"] = ((peak - eq["equity"]) / peak).fillna(0.0)
    eq_out = eq[["date", "cash", "position_value", "equity", "drawdown"]]
    eq_out.columns = ["date", "cash", "position_value", "total_equity", "drawdown"]
    eq_out.to_csv(equity_path, index=False)

    _pool_cols = {"free_cash", "locked_margin", "settling_funds"}
    if _pool_cols <= set(eq.columns):
        cw = pd.DataFrame({
            "date": eq["date"],
            "free_cash": eq["free_cash"],
            "locked_margin": eq["locked_margin"],
            "settling_funds": eq["settling_funds"],
            "nav": eq["equity"],
            "total_equity": eq["equity"],
        })
    else:
        # 调用方未提供三池(旧式 equity df):显式回退,不伪造 0。
        cw = pd.DataFrame({
            "date": eq["date"],
            "free_cash": eq["cash"],
            "locked_margin": 0.0,
            "settling_funds": 0.0,
            "nav": eq["equity"],
            "total_equity": eq["equity"],
        })
    cw.to_csv(cash_walk_path, index=False)


def _fmt(metrics: dict) -> str:
    m = metrics
    return "\n".join([
        f"preset        : {m.get('preset', 'custom')}",
        f"区间          : {m['start']} → {m['end']}",
        f"信号数        : {m['signals']}",
        f"交易笔数      : {m['trades']}   胜率: {m['win_rate']*100:.1f}%",
        f"期末权益      : {m['final_equity']:,.0f}  (初始 {INITIAL_CAPITAL:,.0f})",
        f"总收益        : {m['total_return']*100:+.2f}%",
        f"年化 CAGR     : {m['cagr']*100:+.2f}%",
        f"Sharpe        : {m['sharpe']:.2f}",
        f"最大回撤      : {m['max_dd']*100:.2f}%",
        f"平均持仓天数  : {m['avg_hold_days']:.1f}  (最长 {m['max_hold_days']})",
        f"退出分布      : TP={m['tp_count']} SL={m['sl_count']} "
        f"time={m['time_count']} eod={m['eod_count']}",
        f"平均单笔净收益: {m['avg_net_return']*100:+.2f}%   盈亏比: {m['profit_factor']:.2f}",
        f"平均仓位占用  : {m['exposure']*100:.1f}%",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="uptrend_pullback 回测入口")
    parser.add_argument("--preset", default="v33_long_reverse_v19")
    parser.add_argument("--start", default="2025-09-08")
    parser.add_argument("--end", default="2026-09-08")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="uptrend_pullback/results/backtest.json")
    parser.add_argument("--save-trades", default="")
    parser.add_argument(
        "--engine",
        choices=("backtrader", "simulate"),
        default="backtrader",
        help="回测引擎：backtrader（默认，Phase 1 + backtrader Phase 2 验证）"
             " / simulate（自定义事件循环，对照用）",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="仅跑 Phase 1（portfolio.py），跳过 backtrader 验证（仅 --engine backtrader 生效）",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 统一交易报告: Control Plane 加载 panel_ind 并传入引擎(与回测零偏差)
    _p = get_preset(args.preset)
    _universe = set(load_universe(_p["universe"], Path(args.db_path), asof_date=args.start))
    _panel_ind = compute_indicators(
        load_panel(Path(args.db_path), args.start, args.end, universe=_universe)
    )

    if args.engine == "simulate":
        res = run_backtest(args.preset, args.start, args.end, Path(args.db_path),
                           panel_ind=_panel_ind)
    else:
        res = run_backtrader_backtest(
            args.preset, args.start, args.end, Path(args.db_path),
            verify=not args.no_verify, panel_ind=_panel_ind,
        )
    metrics, trades = res["metrics"], res["trades"]
    metrics["engine"] = args.engine + (
        "" if args.engine == "simulate" else (" (no-verify)" if args.no_verify else "")
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )

    # §2/§3 Tick 58 GREEN: per-preset metrics audit trail.
    _write_per_preset_metrics(out.parent, metrics, preset=args.preset)

    # §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv.
    equity_df = res.get("equity") if isinstance(res, dict) else None
    if isinstance(equity_df, pd.DataFrame) and not equity_df.empty:
        _write_equity_curve(
            out.parent / "equity_curve.csv",
            out.parent / "cash_walk.csv",
            equity_df,
        )

    if args.save_trades:
        tp = Path(args.save_trades)
        tp.parent.mkdir(parents=True, exist_ok=True)
        trades.assign(
            entry_date=lambda d: d["entry_date"].astype(str),
            exit_date=lambda d: d["exit_date"].astype(str),
        ).to_csv(tp, index=False)
        print(f"逐笔交易已保存: {tp}")

    # 统一交易 HTML 报告(每个 preset 回测结束自动生成; results/ 已 gitignored §7)
    _traded = sorted(set(trades["thscode"])) if len(trades) else []
    _bars = {
        c: g.reset_index(drop=True)
        for c, g in _panel_ind[_panel_ind["thscode"].isin(_traded)].groupby("thscode")
    }
    _report = render_trade_report(
        trades=trades, bars_by_code=_bars, preset=args.preset,
        window=(args.start, args.end),
        out_path=out.parent / report_filename(args.preset),
        ma_cols=("ma5", "ma10", "ma20", "ma60", "ma120"),
        macd_cols=("macd_dif", "macd_dea", "macd_bar"),
        line_cols=("atr_pct",),
    )
    print(f"HTML 报告: {_report}")

    print(_fmt(metrics))
    print(f"\n指标已保存: {out}")


if __name__ == "__main__":
    main()