"""回测 short_reversal 所有 preset（无 look-ahead 污染的前提下）。

前置：tests/test_short_reversal_no_lookahead.py 全绿 ⇒ LAHEAD-001/FINDING-001
已锁，意味着 panel 内的 entry/exit 都是真实成交（无穿越）。

输出：每个 preset 的关键指标（CAGR / win_rate / max_dd / trade_count /
TP/SL/time 拆分 / hold_days）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/holeon/code/hiagent")

from short_reversal.engine import run_backtest_v3
from short_reversal.presets import PRESETS
from hiagent_config import get_db_path

START = "2025-09-12"
END = "2026-09-12"


def main() -> None:
    db = get_db_path()
    if not db.exists():
        raise SystemExit(f"DB not found at {db}")

    rows = []
    for name in sorted(PRESETS.keys()):
        print(f"=== {name} ===")
        m = run_backtest_v3(name, START, END, db)
        row = {
            "preset": name,
            "trades_count": m["trades_count"],
            "win_rate": round(m["win_rate"], 4),
            "final_capital": round(m["final_capital"], 2),
            "cagr": round(m["cagr"], 4),
            "sharpe": round(m["sharpe"], 4),
            "max_dd": round(m["max_dd"], 4),
            "avg_pnl": round(m["avg_pnl"], 6),
            "avg_hold_days": round(m["avg_hold_days"], 3),
            "tp_count": m["tp_count"],
            "sl_count": m["sl_count"],
            "time_count": m["time_count"],
        }
        rows.append(row)
        print(
            f"  n={row['trades_count']:>4}  CAGR={row['cagr']:>10.4f}  "
            f"win={row['win_rate']:.2%}  DD={row['max_dd']:.2%}  "
            f"Sharpe={row['sharpe']:.2f}  TP/SL/time={row['tp_count']}/{row['sl_count']}/{row['time_count']}  "
            f"hold={row['avg_hold_days']:.2f}d"
        )

    out = Path("/tmp/all_presets_metrics.json")
    out.write_text(
        json.dumps(
            {"start": START, "end": END, "rows": rows},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n>>> WROTE {out}")


if __name__ == "__main__":
    main()
