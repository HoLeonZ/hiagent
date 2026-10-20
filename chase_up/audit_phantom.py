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

# §0/§6 单源 (附一百一十一): 本文件此前**绕过** `hiagent_config` 硬编码库路径 ——
# 后果不只是"换机器就废":它**忽略 `DNA_STRAT_DB` 覆盖**(测试与我的批次都靠它指库),
# 于是这个工具会静默连到**另一个库**上去。路径的唯一来源是 `hiagent_config`(它自己
# 用 `Path.home()` 拼默认值并读环境变量)。
from hiagent_config import DB_PATH

#: (附一百零六) 判据用**相对**差,不用绝对元值 —— 后者与股价量级耦合,低价股上会静默失效。
#: `exit` 与该复权域的相对差在此以内 ⇒ 认为"这个出场价取自那个域"。
_PRICE_MATCH_REL = 1e-4
#: 该复权域与原始域的相对差**超过**它,才值得把"落在该域"当成 phantom
#: (低于它说明那天本来就没复权,两个域相同 —— 落在这里也不构成跨域)。
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
        # exit_date 取 exit_date 列 (signal date), 实际 exit 是 next bar open
        # backtrader: actual_exit_price = order.executed.price (= bar N+1 open)
        # phantom: exit_price ≈ qfq_open (前复权) 而 raw_open 显著不同
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
        # §3 (附一百零六): 判据改成**相对**阈值,并且**两个复权域都查**。
        #
        # 旧判据是 `abs(ep - qo) < 0.01 and abs(qo - ro) > 0.5` —— **两个阈值都是绝对元值**。
        # 实测它的代价:价格 [0,5) 元的票里 **56.4%** 的(票,日)有复权差异,而 `|qfq-raw|>0.5`
        # 只覆盖 **12.55%** ⇒ **77% 的错配对它不可见**;5~20 元档也漏掉约一半。
        #
        # 另一个盲区:只比对 qfq。而**今天的信号域是 hfq**(附七十六/一百零二)——
        # 实测过一个"exit = hfq_open"的样本:旧判据**不报**。
        #
        # 判据现在是"**exit 落入任一复权域、且该域与原始域显著不同**" ——
        # 三个域都取相对差,与股价量级无关。
        if ro is None or ro <= 0:
            continue
        for name, adj_open in (("qfq", qo), ("hfq", ho)):
            if adj_open is None or adj_open <= 0:
                continue
            gap_adj_vs_raw = abs(adj_open / ro - 1.0)
            if gap_adj_vs_raw <= _MIN_ADJ_GAP_REL:
                continue           # 该复权域与原始域几乎相同 ⇒ 落在这里也不算 phantom
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
    if total_trades == 0:
        # §0 非空转钳制(附五十八):**0 个输入 ≠ "0% phantom"**。
        # 此前这里写 `100*total_phantom/max(total_trades,1)` —— `max(...,1)` 正是
        # 那个"静默的零":它把"没有数据可审"变成一个看起来干净的成功率,而
        # `results/` 按 §7 必须 gitignored ⇒ **fresh clone 里它恒为 0.00%**。
        print("phantom ratio: **N/A** —— 没有可审计的成交表,本工具**未做任何审计**。")
        print("这不是通过:先用 `--save-trades` 产出 *_trades.csv 再跑。")
    else:
        print(f"phantom ratio: {100*total_phantom/total_trades:.2f}%")

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

    # 退出码:0=审过且干净;1=**没有输入**(空转,不得当作通过);2=审出 phantom
    if total_trades == 0:
        return 1
    return 0 if total_phantom == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())