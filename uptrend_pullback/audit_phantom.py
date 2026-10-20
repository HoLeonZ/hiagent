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

#: (附一百零七) 判据用**相对**差,不用绝对元值 —— 后者与股价量级耦合,低价股上静默失效。
_PRICE_MATCH_REL = 1e-4
_MIN_ADJ_GAP_REL = 5e-3


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
                   h.open AS hfq_open,
                   r.open AS raw_open, r.low AS raw_low, r.high AS raw_high
            FROM v_daily_qfq q
            LEFT JOIN raw_kline_daily r ON q.thscode=r.thscode AND q.date=r.date
            LEFT JOIN v_daily_hfq h ON q.thscode=h.thscode AND q.date=h.date
            WHERE q.thscode=? AND q.date=?
            """,
            [t["thscode"], str(t["exit_date"])[:10]],
        ).fetchone()
        if row is None:
            continue
        qo, ql, qh, ho, ro, rl, rh = row
        if any(x is None for x in (qo, ql, qh, ro, rl, rh)):
            continue
        ep = float(t["exit_price"])
        # §3 (附一百零七): 判据改成**相对**阈值,并且**两个复权域都查** ——
        # 与 chase_up/audit_phantom.py 的同款修复(本工具自称与它"同构")。
        # 旧判据 `abs(ep - qo) < 0.01 and abs(qo - ro) > 0.5` 两个阈值都是**绝对元值**、且只比 qfq:
        # 实测低价股([0,5) 元)有复权差异的行占 56.4%,而绝对阈值只覆盖 12.55% ⇒ 77% 不可见;
        # 而今天的**信号域是 hfq**,那类错误它压根不看。
        if ro is None or ro <= 0:
            continue
        for name, adj_open in (("qfq", qo), ("hfq", ho)):
            if adj_open is None or adj_open <= 0:
                continue
            gap_adj_vs_raw = abs(adj_open / ro - 1.0)
            if gap_adj_vs_raw <= _MIN_ADJ_GAP_REL:
                continue
            if abs(ep / adj_open - 1.0) < _PRICE_MATCH_REL:
                phantom_count += 1
                if len(phantom_examples) < 3:
                    phantom_examples.append(
                        f"  {t['thscode']} entry={str(t['entry_date'])[:10]} "
                        f"exit={str(t['exit_date'])[:10]} reason={t.get('exit_reason', '')} "
                        f"ep={ep:.4f} {name}_open={adj_open:.4f} raw_open={ro:.4f} "
                        f"(相对差 {gap_adj_vs_raw:.2%})"
                    )
                break

    con.close()
    return {
        "preset": csv_path.stem,
        "trades": len(trades),
        "phantom": phantom_count,
        "examples": phantom_examples,
        "status": "ok",
    }


def main() -> int:
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
    if total_trades == 0:
        # §0 非空转钳制(附五十八):0 个输入 ≠ "0% phantom"(见 chase_up 同处的说明)。
        print("phantom ratio: **N/A** —— 没有可审计的成交表,本工具**未做任何审计**。")
        print("这不是通过:先用 `--save-trades` 产出 *_trades.csv 再跑。")
    else:
        print(f"phantom ratio: {100*total_phantom/total_trades:.2f}%")
    if total_trades == 0:
        return 1
    return 0 if total_phantom == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())