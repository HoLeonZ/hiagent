"""v3 backtest CLI 入口。

跑 v3 事件驱动引擎（无 look-ahead），输出 metrics JSON。
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import pandas as pd

from core.dual_price import portfolio_nav
from core.trade_report import render_trade_report, report_filename
from core.trade_schema import TRADE_COLS
from short_reversal.engine import run_backtest_v3
from short_reversal.render_trade_detail import compute_indicators
from short_reversal.report_data import load_bars_by_code

from hiagent_config import DB_PATH as DEFAULT_DB

logger = logging.getLogger(__name__)


# §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv canonical schemas.
EQUITY_CURVE_COLS = ("date", "cash", "position_value",
                     "total_equity", "drawdown")
CASH_WALK_COLS = ("date", "free_cash", "locked_margin",
                  "settling_funds", "nav", "total_equity")


#: `*_metrics.json` 里**不得**出现的明细键:每个大列表都有自己的产物
#: (`trades` → trades.csv;逐 bar 曲线 → equity_curve.csv)。留在这里会让
#: metrics JSON 变成"又一个明细文件",与 Tick 58 的约定相悖。
_METRICS_DETAIL_KEYS = ("trades", "equity_curve")


def _strip_trades_for_json(metrics: dict) -> dict:
    """剥掉 metrics 里的**明细大列表**,只留聚合键,供 JSON dump。

    per-preset metrics JSON MUST carry **aggregate keys only**(Tick 58
    [[backtest-metrics-canonical-schema-2026-09-23]]):明细有自己的产物 ——
    `trades` 进 trades.csv(14 列规范),逐 bar 曲线进 equity_curve.csv。

    2026-10-17:`equity_curve` 也一并剥掉。它此前不在 metrics 里(付三十八 才把
    它接进来当 writer 的输入通道),于是**顺手**流进了这个 JSON —— 200 行曲线
    塞进"聚合指标"文件,正是本条约定要防的事。`_write_equity_curve` 用的是调用方
    另传的 `eq_rows`,不受影响。
    """
    return {k: v for k, v in metrics.items() if k not in _METRICS_DETAIL_KEYS}


def _write_per_preset_metrics(
    out_dir: Path,
    metrics: dict,
    preset: str,
) -> Path:
    """Write per-preset audit-trail metrics JSON (§2/§3 Tick 58).

    Strips the embedded `trades` list (huge, redundant with trades.csv).
    Single-overwrite `backtest.json` is preserved for back-compat.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _strip_trades_for_json(metrics)
    out = out_dir / f"{preset}_metrics.json"
    out.write_text(
        json.dumps(safe, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )
    return out


def _write_equity_curve(
    equity_path: Path,
    cash_walk_path: Path,
    equity_rows: list[dict] | object,
) -> None:
    """Write equity_curve.csv + cash_walk.csv (§2/§3 Tick 51).

    Accepts the `result_holder["equity_curve"]` list-of-dicts that
    Phase3V3Strategy populates per-bar (now including the **three pools**).

    §2 (audit 2026-10-15): 此前这里把 `locked_margin` / `settling_funds` 写死为 0、
    把 `free_cash` 填成 `cash`,理由是"等 H5.1 落地三池"。**但三池早已落地**
    (策略 `__init__` 里就有 free/locked/settling,并由 `settle()` 维护) ——
    零值不是简化,是**产出与账本不符的数据**。故改为如实落盘;缺字段即 fail-fast,
    不再用 0 兜底(§0:不允许静默降级)。
    """
    equity_path.parent.mkdir(parents=True, exist_ok=True)
    cash_walk_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(equity_rows or [])
    with equity_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(EQUITY_CURVE_COLS))
        w.writeheader()
        for row in rows:
            cash = float(row.get("cash", 0.0))
            holdings_value = float(row.get("holdings_value", 0.0))
            total_equity = float(row.get("equity", cash + holdings_value))
            w.writerow({
                "date": row.get("date"),
                "cash": cash,
                "position_value": holdings_value,
                "total_equity": total_equity,
                "drawdown": float(row.get("drawdown", 0.0)),
            })
    with cash_walk_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CASH_WALK_COLS))
        w.writeheader()
        for row in rows:
            missing = [k for k in ("free_cash", "locked_margin", "settling_funds")
                       if k not in row]
            if missing:
                raise KeyError(
                    f"§2: equity row 缺三池字段 {missing}(date={row.get('date')!r})—— "
                    "无法如实落盘 cash_walk。旧实现在这里补 0,那会让产物与账本不符。"
                )
            free_cash = float(row["free_cash"])
            locked = float(row["locked_margin"])
            settling = float(row["settling_funds"])
            holdings_value = float(row.get("holdings_value", 0.0))
            total_equity = float(row.get("equity", free_cash + locked + settling
                                        + holdings_value))
            w.writerow({
                "date": row.get("date"),
                "free_cash": free_cash,
                "locked_margin": locked,
                "settling_funds": settling,
                # §2: NAV 走**规范单源** `portfolio_nav`(= free + settling + 持仓市值)。
                # ⚠️ `locked_margin` **不计入** —— 它是持仓的**成本基础**,而
                # holdings_value 是同一持仓的**市值**;两者相加会把仓位计两次
                # (这正是审计 P0-1 那个缺陷)。三池仍各自如实落盘,只是不进 NAV。
                "nav": portfolio_nav(free_cash, settling, holdings_value),
                "total_equity": total_equity,
            })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="short_reversal v3 事件驱动 backtest（无 look-ahead）"
    )
    parser.add_argument("--preset", default="v33_mainboard_tp6_sl005_mh5_realistic")
    parser.add_argument("--start", default="2025-09-12")
    parser.add_argument("--end", default="2026-09-12")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument(
        "--out",
        default="short_reversal/results/backtest.json",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB 不存在: {db_path}")

    m = run_backtest_v3(args.preset, args.start, args.end, db_path)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Aggregate-only metrics JSON (Tick 58 GREEN): strip embedded
    # per-trade list. The legacy `backtest.json` is the single-overwrite
    # last-run snapshot — keep it for back-compat.
    out_path.write_text(
        json.dumps(_strip_trades_for_json(m), indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )

    # §2/§3 Tick 58 GREEN: per-preset metrics audit trail.
    _write_per_preset_metrics(out_path.parent, m, preset=args.preset)

    # 统一交易 HTML 报告(每个 preset 回测结束自动生成; results/ 已 gitignored §7)
    _trades = pd.DataFrame(m.get("trades") or [], columns=list(TRADE_COLS))
    _codes = sorted(set(_trades["thscode"])) if len(_trades) else []
    _bars = {
        c: compute_indicators(df)
        for c, df in load_bars_by_code(db_path, _codes, args.start, args.end).items()
    }
    _report = render_trade_report(
        trades=_trades, bars_by_code=_bars, preset=args.preset,
        window=(args.start, args.end),
        out_path=out_path.parent / report_filename(args.preset),
        ma_cols=("ma5", "ma10", "ma20", "ma60"),
        macd_cols=("macd_dif", "macd_dea", "macd_bar"),
    )
    print(f"HTML 报告: {_report}")

    # §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv (driven by
    # the per-bar equity_curve list that Phase3V3Strategy populates
    # into result_holder).
    eq_rows = m.get("equity_curve") if isinstance(m, dict) else None
    if not eq_rows:
        # §0/§7 (audit 2026-10-16): "不写产物"必须**出声**。此前这里静默跳过,
        # 于是"没写"与"写了但为空"不可区分 —— 而真实成因是 metrics 里根本没有
        # `equity_curve` 这个键(已修:单腿路径现在带上了)。集成 preset 会是
        # 显式 None(多子组合曲线未聚合),那是**已知且可解释**的缺口。
        logger.warning(
            "§7: 本次运行没有逐 bar 权益曲线(equity_curve=%r),"
            "故不写 equity_curve.csv / cash_walk.csv", eq_rows,
        )
    if eq_rows:
        _write_equity_curve(
            out_path.parent / "equity_curve.csv",
            out_path.parent / "cash_walk.csv",
            eq_rows,
        )

    print(f"preset: {m['preset']}")
    print(
        f"trades: {m['trades_count']}, win_rate: {m['win_rate'] * 100:.1f}%"
    )
    print(
        f"final_capital: {m['final_capital']:.2f}, "
        f"total_yield: {m['total_yield'] * 100:+.2f}%"
    )
    print(f"cagr: {m['cagr'] * 100:+.2f}%, sharpe: {m['sharpe']:.2f}, "
          f"max_dd: {m['max_dd'] * 100:.2f}%")
    print(f"TP/SL/time: {m['tp_count']}/{m['sl_count']}/{m['time_count']}")
    print(f"输出: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())