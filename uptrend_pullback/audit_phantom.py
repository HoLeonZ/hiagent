"""uptrend_pullback preset trades.csv phantom TP/SL 批量审计 (CLAUDE.md §3).

phantom 定义: trade exit_price ≈ qfq_open (前复权 open) 而 raw_open 显著不同。
CLAUDE.md §3 铁律: ALWAYS use raw_close for limit-order triggers / SL / 物理 cash
mark-to-market (含 entry fill)。phantom TP/SL = 此铁律的违反。

与 chase_up/audit_phantom.py 同构 (Layout A, panel 同时含 raw_* 与 qfq 列)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"


def audit_trades_csv(csv_path: Path) -> dict:
    """对单个 trades.csv 跑 phantom 检测。"""
    if not csv_path.exists():
        return {"preset": csv_path.stem, "status": "no_csv"}

    trades = pd.read_csv(csv_path)
    if trades.empty:
        return {"preset": csv_path.stem, "trades": 0, "phantom": 0, "status": "empty"}

    con = duckdb.connect(DB_PATH, read_only=True)
    phantom_count = 0
    phantom_examples = []

    for _, t in trades.iterrows():
        row = con.execute(
            """
            SELECT q.open AS qfq_open, q.low AS qfq_low, q.high AS qfq_high,
                   r.open AS raw_open, r.low AS raw_low, r.high AS raw_high
            FROM v_daily_qfq q
            LEFT JOIN raw_kline_daily r ON q.thscode=r.thscode AND q.date=r.date
            WHERE q.thscode=? AND q.date=?
            """,
            [t["thscode"], str(t["exit_date"])[:10]],
        ).fetchone()
        if row is None:
            continue
        qo, ql, qh, ro, rl, rh = row
        if any(x is None for x in (qo, ql, qh, ro, rl, rh)):
            continue
        ep = float(t["exit_price"])
        if abs(ep - qo) < 0.01 and abs(qo - ro) > 0.5:
            phantom_count += 1
            if len(phantom_examples) < 3:
                phantom_examples.append(
                    f"  {t['thscode']} entry={str(t['entry_date'])[:10]} "
                    f"exit={str(t['exit_date'])[:10]} reason={t.get('exit_reason', '')} "
                    f"ep={ep:.4f} qfq_open={qo:.4f} raw_open={ro:.4f}"
                )

    con.close()
    return {
        "preset": csv_path.stem,
        "trades": len(trades),
        "phantom": phantom_count,
        "examples": phantom_examples,
        "status": "ok",
    }


def main():
    """审计所有 uptrend_pullback/results/*_trades.csv。"""
    results_dir = ROOT / "uptrend_pullback" / "results"
    csv_files = sorted(results_dir.glob("*_trades.csv"))

    print(f"审计 {len(csv_files)} 个 trades.csv:")
    print("=" * 80)

    total_trades = 0
    total_phantom = 0

    for csv_path in csv_files:
        result = audit_trades_csv(csv_path)
        if result["status"] == "no_csv":
            print(f"{result['preset']:<40} [NO CSV]")
            continue
        elif result["status"] == "empty":
            print(f"{result['preset']:<40} [EMPTY]")
            continue

        phantom = result["phantom"]
        trades = result["trades"]
        total_trades += trades
        total_phantom += phantom
        marker = "✓" if phantom == 0 else "✗"
        print(
            f"{result['preset']:<40} trades={trades:>3} phantom={phantom:>3} {marker}"
        )
        if phantom > 0:
            for ex in result["examples"]:
                print(ex)

    print("=" * 80)
    print(f"总计: trades={total_trades} phantom={total_phantom}")
    print(f"phantom ratio: {100*total_phantom/max(total_trades,1):.2f}%")


if __name__ == "__main__":
    main()