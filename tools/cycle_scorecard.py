"""`cycle_price_action` 的「当前代码」记分卡 + 排序规则的随机对照 (§13.125)。

**为什么需要它**: 四族里这一族是**唯一从来没有"用当前代码重打"过**的 ——
§13.110/§13.112 的普查因架构成本跳过了它, 于是它的判定长期建立在 2026-10-16 前后的
代码状态上, 而此后经历 §4 跳空成交修正 / §13.16 / §13.98 / §4 涨跌停守卫等多轮修复。

**它同时重测两条登记** (两条都写在 `cycle_price_action/allocator.py` 的 docstring 里):
  * 「补齐跨股容量层后**各 N 全负**」;
  * 「'取最高分'这条默认规则**劣于随机**」。

两张表
------
(b) 记分卡: 组合层走 `allocator.py` (`run_backtest` 给每只票各起一个百万账户,
    没有组合权益曲线 ⇒ 必须重放)。
(d) 随机对照: 同一个成交集合、同一条容量规则、**只换排序**。
    `allocator._fused` 全仓只被用作排序键 (`allocator.py:97`), 故在不碰仓库的前提下
    把它替换成按 `(entry_date, thscode)` **定值**的确定性随机键 (每 trial 固定种子)
    ⇒ 等价于"每天从候选里随机挑一个"。**这是对照, 不是搜索**: 不选最好的种子,
    只问默认规则落在随机分布的哪个位置。

口径: W2 按 §13.8 截到最后一个干净日 `2026-09-18` (本族读 `v_daily`/hfq ⇒ 属 §13.9
**受影响**那一侧)。`TRADING_DAYS` 由本族自披露的 `METRICS_BASIS` 决定, 脚本不另设。

⚠️ 已知偏乐观项 (`allocator.py` 自陈): 逐笔收益率复用 100 万名义额下的结果 ⇒
扩资时偏乐观; 100 股整手与 §4 成交量上限都让收益率带轻微规模依赖。

用法:
    python3 tools/cycle_scorecard.py              # 两张表
    python3 tools/cycle_scorecard.py --trials 50  # 减少随机 trial
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

import cycle_price_action.allocator as A  # noqa: E402
from cycle_price_action.backtest import run_backtest  # noqa: E402
from cycle_price_action.presets import PRESET_V1  # noqa: E402

INITIAL_CAPITAL = 1_000_000.0
# 末窗末日按 §13.8 截到最后一个**干净日** (因子表止于 2026-09-18)
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
)


def _trading_days(w0: str, w1: str) -> list:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT date FROM v_daily WHERE date BETWEEN ? AND ? ORDER BY date",
            [w0, w1],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _with_fused(trades, days, fused, preset, weights):
    orig = A._fused
    A._fused = fused
    try:
        return A.portfolio_metrics(A.allocate(
            trades, trading_days=days, initial_capital=INITIAL_CAPITAL,
            max_positions=preset["max_positions"], weights=weights,
        ))
    finally:
        A._fused = orig


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--trials", type=int, default=200, help="随机排序的 trial 数")
    args = ap.parse_args()

    preset = dict(PRESET_V1)
    weights = (preset.get("weight_kline", 1.0),
               preset.get("weight_cycle", 0.7),
               preset.get("weight_calendar", 0.5))
    print(f"preset = PRESET_V1  max_positions = {preset['max_positions']}  "
          f"threshold = {preset.get('threshold')}  max_hold = {preset.get('max_hold')}")
    print(f"引擎自披露 METRICS_BASIS = {dict(A.METRICS_BASIS)}\n")

    cache: dict[str, tuple] = {}
    print("=== (b) 记分卡 (当前代码) ===")
    print(f"{'窗口':<5} {'逐笔信号':>8} {'成交':>6} {'容量拒绝率':>10} {'暴露':>7} "
          f"{'组合总收益':>10} {'Sharpe':>8} {'maxDD':>7} {'耗时':>7}")
    for label, w0, w1 in WINDOWS:
        t0 = time.time()
        res = run_backtest(str(DB_PATH), dt.date.fromisoformat(w0),
                           dt.date.fromisoformat(w1), preset=dict(preset))
        days = _trading_days(w0, w1)
        pm = _with_fused(res.trades, days, A._fused, preset, weights)
        cache[label] = (res.trades, days)
        print(f"{label:<5} {len(res.trades):>8} {pm['n_trades']:>6} "
              f"{pm['rejection_rate']:>9.1%} {pm['exposure']:>7.1%} "
              f"{pm['total_return']:>+10.2%} {pm['sharpe']:>+8.2f} "
              f"{pm['max_dd']:>7.3f} {time.time()-t0:>6.0f}s", flush=True)

    print(f"\n=== (d) 排序规则的**同构造随机对照** ({args.trials} trials, 种子固定) ===")
    print(f"{'窗口':<5} {'默认(融合分)':>12} {'随机中位':>10} {'随机均值':>10} "
          f"{'随机 p5..p95':>24} {'默认分位':>9}")
    for label, _w0, _w1 in WINDOWS:
        trades, days = cache[label]
        if not trades:
            print(f"{label:<5} (无成交)"); continue
        base = _with_fused(trades, days, A._fused, preset, weights)["total_return"]
        keys = [(t.entry_date, t.thscode) for t in trades]
        outs = []
        for s in range(args.trials):
            rng = random.Random(s)
            perm = {k: rng.random() for k in keys}
            outs.append(_with_fused(
                trades, days,
                lambda t, w, pm=perm: pm[(t.entry_date, t.thscode)],
                preset, weights)["total_return"])
        outs.sort()
        pct = sum(1 for o in outs if o < base) / len(outs)
        lo, hi = outs[int(0.05 * len(outs))], outs[int(0.95 * len(outs))]
        print(f"{label:<5} {base:>+12.2%} {outs[len(outs)//2]:>+10.2%} "
              f"{sum(outs)/len(outs):>+10.2%} {lo:>+11.2%},{hi:>+11.2%} {pct:>8.1%}")

    print("\n读法 (§5): 这是**对照**不是搜索 —— 不选最好的种子。默认分位要按"
          "「trial 数 × 窗口数」做多重比较后才可引用。")


if __name__ == "__main__":
    main()
