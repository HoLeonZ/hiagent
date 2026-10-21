"""`uptrend_pullback` 的 **`max_positions` 轴** —— 本册 §9 自陈"被误判为死路"的那一格 (§13.157)。

为什么这一格是**开的**
----------------------
§9 那张表的**第一行**写着:
> **逐笔 E[R]**(`tail_objective`) | 对**分散化**不敏感 —— 加仓让每笔变小、期望不变,
> 组合波动与回撤下降 | `short_reversal` 与 `uptrend_pullback` 的 `max_positions>1`
> **都被误判为死路**

而那条判决的**具体实验** (`v58_mp_2` / `v58_mp_4`) 是 **`short_reversal`** 上的,
且 §13.24 已查明: **那个族根本没有并发计数闸门** ⇒ `max_positions` 只当 sizing 除数,
实测声明 2 而并发峰值 **15** ⇒ **"N 槽并行"从未实现**。
⇒ 对 `uptrend_pullback`, 这条轴**从来没有在闸门真的存在时被测过**。
(闸门在 `portfolio.py`: `if len(positions) >= max_positions: break`。)

⚠️ 而 `position_sizing="all_in"` 在 N>1 下**不是**"N 个等额槽":
`slot_value = cash_only`(不除 N) ⇒ 第一笔就吃光现金 ⇒ 名义 N 槽、实际仍 1 槽
—— **§13.24 的同一个陷阱换了一层**。所以本轴必须用 `position_sizing="equal"`
(它才做 `cash_only / max_positions`)。基线 N=1 的 `all_in ≡ equal` 已被 §13.128(c) 钉过。

本工具**自己验它声称的机理**(§13.94 的教训: 刚写的东西更要实证)
------------------------------------------------------------------------
对每一格打印 **实测最大并发**; 并且:
* 若 `max_concurrent > N` ⇒ 闸门失效 (报红);
* 若 N>1 却全程 `max_concurrent == 1` ⇒ **轴根本没开** ("注入不响"的第①类),
  这时"N 无效"什么也没证明。

用法:
    python3 tools/max_positions_axis_uptrend.py
    python3 tools/max_positions_axis_uptrend.py --preset v33_long_reverse_v22 --max-n 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402
from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402

WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def max_concurrent(trades: pd.DataFrame) -> int:
    """持仓并发的**日频峰值** (每笔按 `entry_date..exit_date` 占一个槽)。

    ⚠️ 这是从**成交清单**反推的代理量, 不是引擎内部的计数器 —— 但正是 §13.24
    那个失败模式要用它来抓 (声明 N 而实开更多)。
    """
    if trades.empty:
        return 0
    e = pd.to_datetime(trades["entry_date"])
    x = pd.to_datetime(trades["exit_date"])
    days = pd.Index(sorted(set(e) | set(x)))
    best = 0
    for d in days:
        # ⚠️ 出场**当日**不计入持仓: 引擎是「先平后开」(第 1 步出场 / 第 2 步开仓),
        # 出场当日的槽位**已经空出来**。第一版写成 `x >= d` ⇒ 同日换手被重复计一次
        # ⇒ 基线 N=1 也报"并发峰值 2 / 闸门破" 20/20 —— **判据错了, 不是引擎错了**。
        best = max(best, int(((e <= d) & (x > d)).sum()))
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--max-n", type=int, default=4)
    args = ap.parse_args()

    base = get_preset(args.preset)
    # §13.13/§13.90: 本工具报的是 `uptrend_pullback` 一族的 `max_dd` / 收益 ——
    # **这四个量跨族不可比** ⇒ 静态披露本族口径 (尽管本工具**不跨族并列**)。
    print(f"口径披露 (§13.13): uptrend_pullback -> {dict(_BASIS_UPTREND)}")
    print(f"preset = {args.preset}")
    print(f"基线: max_positions={base.get('max_positions')} "
          f"position_sizing={base.get('position_sizing')} "
          f"position_fraction={base.get('position_fraction')}")

    configs: list[tuple[str, dict]] = [("N=1 all_in (基线)",
                                        {"max_positions": 1, "position_sizing": "all_in"})]
    for n in range(2, args.max_n + 1):
        configs.append((f"N={n} equal", {"max_positions": n, "position_sizing": "equal"}))

    print("\n⚠️ `equal` 才做 `cash_only / max_positions`; `all_in` 在 N>1 下名义多槽、实际 1 槽"
          " (§13.24 的陷阱)。\n")
    hdr = (f"{'配置':<16}{'窗口':<6}{'笔数':>6}{'并发峰':>7}{'声明N':>6}"
           f"{'闸门':>6}{'收益':>11}{'均用资':>8}{'每笔均':>9}{'暴露':>7}{'maxDD':>9}")
    print(hdr)
    print("-" * len(hdr))

    rows: list[dict] = []
    for label, ov in configs:
        p = dict(base)
        p.update(ov)
        declared = int(p["max_positions"])
        for wlabel, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr = r["trades"]
            m = r["metrics"]
            mc = max_concurrent(tr)
            ret = float(m["final_equity"]) / 1_000_000.0 - 1.0
            gate = "OK" if mc <= declared else "**破**"
            # 均用资 = mean(holdings/equity): 把「下注大小」从「边际」里分出来。
            eq = r["equity"]
            util = float((eq["holdings"] / eq["equity"].replace(0, float("nan"))).mean())
            per = float(m.get("avg_net_return", float("nan")))
            print(f"{label:<16}{wlabel:<6}{len(tr):>6}{mc:>7}{declared:>6}"
                  f"{gate:>6}{ret:>11.2%}{util:>8.1%}{per:>9.2%}"
                  f"{float(m['exposure']):>7.1%}{float(m['max_dd']):>9.2%}")
            rows.append(dict(cfg=label, win=wlabel, n=len(tr), mc=mc,
                             declared=declared, ret=ret, util=util, per=per,
                             exposure=float(m["exposure"]),
                             max_dd=float(m["max_dd"])))

    print("\n=== 机理自验 (§13.94: 工具先证明它读的是它声称的量) ===")
    bad = [x for x in rows if x["mc"] > x["declared"]]
    print(f"  闸门破格格数: {len(bad)}  " + ("**报红**" if bad else "✅ 全部 mc ≤ 声明 N"))
    opened = [x for x in rows if x["declared"] > 1 and x["mc"] > 1]
    if not opened:
        print("  ⛔ **轴根本没开**: 所有 N>1 格的并发峰值都是 1 ⇒ 「N 无效」什么也没证明")
    else:
        print(f"  ✅ 轴确实开了: {len(opened)}/{len([x for x in rows if x['declared'] > 1])} "
              f"个 N>1 格出现了 >1 的并发")

    print("\n=== ⚠️ 归一化: 把「用资」除掉, 看是不是只剩下注大小 (§0 悲观默认) ===")
    for wlabel, _, _ in WINDOWS:
        b = next(x for x in rows if x["win"] == wlabel and x["declared"] == 1)
        print(f"  {wlabel:<6} 基线用资 {b['util']:>6.1%} / 每笔均 {b['per']:>+7.2%}")
        for x in rows:
            if x["win"] == wlabel and x["declared"] > 1:
                print(f"         {x['cfg']:<12} 用资 {x['util']:>6.1%} / 每笔均 {x['per']:>+7.2%}"
                      f"   (用资比 {x['util']/max(b['util'],1e-9):>5.2f}×)")

    print("\n=== 逐窗看: N>1 相对基线的**符号** (§5: 只报符号与计数, 不做跨档排名) ===")
    for wlabel, _, _ in WINDOWS:
        b = next(x for x in rows if x["win"] == wlabel and x["declared"] == 1)
        line = [f"  {wlabel:<6} 基线 {b['ret']:>8.2%}"]
        for x in rows:
            if x["win"] == wlabel and x["declared"] > 1:
                line.append(f"{x['cfg']} {x['ret']-b['ret']:>+8.2%}")
        print("   ".join(line))
    print("""
读法 (§5): 本工具**不**回答"哪一档最好"; 它回答的是
  ① 这条轴在闸门真的存在时**是否被打开过** (并发峰值);
  ② 各 N 下**各窗口收益的符号**——若两窗要求相反方向的 N, 那与 §13.126 对 cycle
     的发现同形 (系统性窗口依赖, 排除不掉), 而不是噪声刀刃。
⚠️ 每次运行的档数都计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
