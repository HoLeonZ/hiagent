"""chase_up preset trades.csv phantom TP/SL 批量审计 (CLAUDE.md §3).

phantom 定义: trade exit_price ≈ qfq_open (前复权 open) 而 raw_open 显著不同,
且 raw_close 模式下 portfolio.py 用 raw_open entry — exit 与 entry 价格域不一致。

CLAUDE.md §3 铁律: ALWAYS use raw_close for limit-order triggers / SL / 物理 cash
mark-to-market (含 entry fill)。phantom TP/SL = 此铁律的违反。
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
        # exit_date 取 exit_date 列 (signal date), 实际 exit 是 next bar open
        # backtrader: actual_exit_price = order.executed.price (= bar N+1 open)
        # phantom: exit_price ≈ qfq_open (前复权) 而 raw_open 显著不同
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
        # phantom SL/TP: exit ≈ qfq_open AND qfq_open ≠ raw_open (gap > 0.5)
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
    """审计所有 chase_up/results/*_trades.csv。"""
    results_dir = ROOT / "chase_up" / "results"
    csv_files = sorted(results_dir.glob("*_trades.csv"))

    print(f"审计 {len(csv_files)} 个 trades.csv:")
    print("=" * 80)

    total_trades = 0
    total_phantom = 0
    no_csv_count = 0

    for csv_path in csv_files:
        result = audit_trades_csv(csv_path)
        if result["status"] == "no_csv":
            no_csv_count += 1
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

    # 也检查没 CSV 的 preset
    all_presets = [
        "v1", "v1a", "v1b", "v1c", "v2", "v3", "v4",
        "v5", "v6", "v7", "v8", "v9", "v10", "v11",
        "v12", "v13", "v14", "v15", "v16", "v17", "v18", "v19",
    ]
    csv_names = {p.stem.replace("_trades", "") for p in csv_files}
    missing = [p for p in all_presets if p not in csv_names]
    if missing:
        print(f"\n未生成 trades.csv 的 preset ({len(missing)}/{len(all_presets)}):")
        for p in missing:
            print(f"  - {p}")


if __name__ == "__main__":
    main()