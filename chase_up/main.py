"""CLI 入口 — 追涨策略回测。

用法:
  python3 -m chase_up.main --preset chase_v1_atr_tp4_sl1 --start 2025-09-19 --end 2026-09-19
  python3 -m chase_up.main --engine simulate --preset chase_v1_atr_tp4_sl1 ...
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from chase_up.backtest import INITIAL_CAPITAL, run_backtest
from chase_up.backtrader_engine import run_backtrader_backtest
from core.trade_report import render_trade_report, report_filename
# §2/§3 (2026-10-19, §13.22): equity_curve.csv / cash_walk.csv 的列**必须**取自
# core.trade_schema —— 此前本文件把两个元组**本地抄了一份**(且它们从未被引用),
# 而真正写盘的两处列名列的是**内联字面量** ⇒ 规范 schema 在本文件里出现了**三遍**。
from core.trade_schema import CASH_WALK_COLS, EQUITY_CURVE_COLS
from chase_up.data import load_panel
from chase_up.presets import get_preset
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe

from hiagent_config import DB_PATH as DEFAULT_DB


def _write_per_preset_metrics(
    out_dir: Path,
    metrics: dict,
    preset: str,
) -> Path:
    """Write per-preset audit-trail metrics JSON (§2/§3 Tick 58).

    Single-overwrite `backtest.json` only retains the LAST preset run;
    this writer creates `results/<preset>_metrics.json` so every preset
    run leaves an audit trail (forward-defense against
    [[cash-walk-and-metrics-provenance-gap]]).
    """
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

    `equity` is a DataFrame from `chase_up.portfolio.simulate_portfolio`
    with columns: date, cash, holdings, equity, free_cash, locked_margin,
    settling_funds.

    §2 (audit P0-1, 2026-10-15): cash_walk 如实落盘三池。旧实现把
    locked_margin / settling_funds 硬编码为 0,并把 total_cash 当作
    free_cash 写出 —— 三池隔离在产物层完全不可见,任何基于 cash_walk
    的对账都退化为单池;`nav` 也曾用 total_cash + 持仓市值(重复计入
    持仓成本)计算。缺列时显式回退,不静默填 0。
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
    # 列名取自单一来源 (core.trade_schema) —— 顺序与规范元组逐字节相同 ⇒ 输出未变。
    eq_out.columns = list(EQUITY_CURVE_COLS)
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
    # 显式按规范元组取列 ⇒ 以后 core 改列名时这里会跟着走, 不再靠"字典正好是这个顺序"。
    cw = cw[list(CASH_WALK_COLS)]
    cw.to_csv(cash_walk_path, index=False)


def _fmt(metrics: dict) -> str:
    m = metrics
    # 无亏损笔数的窗口 `profit_factor` 无定义 (main 的 compute_metrics 返回 None),
    # 直接 `:.2f` 会 TypeError —— 显式显示 n/a。
    _pf = m["profit_factor"]
    _pf_txt = "n/a" if _pf is None else f"{_pf:.2f}"
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
        f"平均单笔净收益: {m['avg_net_return']*100:+.2f}%   盈亏比: {_pf_txt}",
        f"平均仓位占用  : {m['exposure']*100:.1f}%",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="chase_up 追涨回测入口")
    parser.add_argument("--preset", default="chase_v1_atr_tp4_sl1")
    parser.add_argument("--start", default="2025-09-19")
    parser.add_argument("--end", default="2026-09-19")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="chase_up/results/backtest.json")
    parser.add_argument("--save-trades", default="")
    parser.add_argument(
        "--engine",
        choices=("backtrader", "simulate"),
        default="backtrader",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="仅跑 Phase 1,跳过 backtrader 验证",
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

    # §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv (if engine
    # returned an `equity` DataFrame on res). chase_up.backtrader_engine
    # does not yet return equity — this is a forward-compatible hook.
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
        ma_cols=("ma20", "ma60", "ma120"),
        macd_cols=("macd_dif", "macd_dea", "macd_bar"),
        line_cols=("atr_pct",),
    )
    print(f"HTML 报告: {_report}")

    print(_fmt(metrics))
    print(f"\n指标已保存: {out}")


if __name__ == "__main__":
    main()