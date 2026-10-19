"""`chase_up` 的 `max_positions` 轴 (§13.160) —— §9 那张表的**逐族**复核, 本轮换 chase。

为什么这一格是开的
------------------
§9 那张"尺子对什么不敏感"表的第一行说: **逐笔 E[R] 尺子对分散化不敏感** ⇒
`uptrend_pullback` 与 `short_reversal` 的 `max_positions>1` **都被误判为死路**。
§13.157 已在 **uptrend** 上受控复核过 (轴是活的)。**chase 从未做过**:
§13.24 只说它"**全 22 个 preset 都是 N=1**", 并记下它有闸门 (`portfolio.py:555`)。
⇒ 「chase 的 N 轴」是那张表里**唯一还没被受控检验的多头族格子**。

⚠️ 与 §13.157 同一条陷阱: `all_in` 在 N>1 下 `slot_value = cash_only` (不除 N)
⇒ 第一笔吃光现金 (再由 `budget = min(slot_value, free_cash)` 兜住) ⇒ **名义多槽、实际 1 槽**。
必须用 `position_sizing="equal"` (`:547` 才做 `cash_only / max_positions`)。

⚠️ 并且 chase 的止损/目标走 **ATR 分支** (§13.159: `sl_pct`/`tp_pct` 是**影子键**)
⇒ 本轴**保持活键不动** (`atr_sl_mult`/`atr_tp_mult` 取基线值), 只动槽位数与 sizing。

判据的自我证伪 (两个, 都跑在真实引擎上)
--------------------------------------
* **闸门**: 实测并发峰值必须 ≤ 声明 N; 否则闸门失效 (报红)。
* **轴是否真的开了**: N>1 的格必须出现 >1 的并发; 若全程恒为 1 ⇒ 轴没开, "N 无效"什么也没证明。

用法:
    python3 tools/max_positions_axis_chase.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from chase_up.backtest import METRICS_BASIS as _BASIS  # noqa: E402
from chase_up.backtest import run_backtest  # noqa: E402
from chase_up.presets import get_preset  # noqa: E402

CAPITAL = 1_000_000.0
DEFAULT = "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082"
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def max_concurrent(trades: pd.DataFrame) -> int:
    """日频并发峰值 (⚠️ 出场**当日不计入**: 引擎先平后开, 出场日槽位已空出)。"""
    if trades.empty:
        return 0
    e = pd.to_datetime(trades["entry_date"])
    x = pd.to_datetime(trades["exit_date"])
    best = 0
    for d in pd.Index(sorted(set(e) | set(x))):
        best = max(best, int(((e <= d) & (x > d)).sum()))
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT)
    ap.add_argument("--max-n", type=int, default=4)
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"口径披露 (§13.13): chase_up -> {dict(_BASIS)}")
    print(f"preset = {args.preset}")
    print(f"基线: max_positions={base.get('max_positions')} "
          f"position_sizing={base.get('position_sizing')}  "
          f"活键 atr_sl_mult={base.get('atr_sl_mult')} atr_tp_mult={base.get('atr_tp_mult')}\n")

    configs = [("N=1 all_in (基线)", {"max_positions": 1, "position_sizing": "all_in"})]
    for n in range(2, args.max_n + 1):
        configs.append((f"N={n} equal", {"max_positions": n, "position_sizing": "equal"}))

    hdr = (f"{'配置':<17}{'窗口':<6}{'笔数':>6}{'并发峰':>7}{'声明N':>6}{'闸门':>6}"
           f"{'收益':>11}{'均用资':>8}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for label, ov in configs:
        p = dict(base); p.update(ov)
        n_dec = int(p["max_positions"])
        for wlabel, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr, m, eq = r["trades"], r["metrics"], r["equity"]
            mc = max_concurrent(tr)
            util = float((eq["holdings"] / eq["equity"].replace(0, float("nan"))).mean())
            ret = float(m["final_equity"]) / CAPITAL - 1.0
            per = float(m.get("avg_net_return", float("nan")))
            print(f"{label:<17}{wlabel:<6}{len(tr):>6}{mc:>7}{n_dec:>6}"
                  f"{('OK' if mc <= n_dec else '**破**'):>6}{ret:>11.2%}{util:>8.1%}"
                  f"{per:>9.2%}{float(m['max_dd']):>9.2%}")
            rows.append(dict(cfg=label, win=wlabel, n=len(tr), mc=mc, declared=n_dec,
                             ret=ret, util=util, per=per, dd=float(m["max_dd"])))
        print()

    print("=== 机理自验 ===")
    bad = [x for x in rows if x["mc"] > x["declared"]]
    print(f"  闸门破格格数: {len(bad)}  " + ("**报红**" if bad else "✅ 全部 mc ≤ 声明 N"))
    op = [x for x in rows if x["declared"] > 1 and x["mc"] > 1]
    tot_hi = [x for x in rows if x["declared"] > 1]
    print(f"  轴是否真的开了: {len(op)}/{len(tot_hi)} 个 N>1 格出现 >1 并发"
          + ("" if op else "  ⛔ **轴没开** ⇒ 「N 无效」什么也没证明"))

    print("\n=== R2: max_dd 是否随 N 改善 ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(
            f"{x['dd']:>8.1%}" for x in rows if x["win"] == wlabel))

    print("\n=== R4: 均用资 (把「下注大小」与「边际」分开) ===")
    for wlabel, _, _ in WINDOWS:
        b = next(x for x in rows if x["win"] == wlabel and x["declared"] == 1)
        print(f"  {wlabel:<6} 基线 {b['util']:>6.1%}  " + "  ".join(
            f"{x['util']/max(b['util'],1e-9):>6.2f}×" for x in rows
            if x["win"] == wlabel and x["declared"] > 1))

    print("\n=== R3: 逐窗符号 (§5: 不报「哪档最好」, 只看正号) ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(
            f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wlabel))
    print("""
读法 (§5): 本表回答 ① 轴在闸门真的存在时**是否被打开过**; ② 各 N 下**各窗收益的正号**。
     若不存在任何一档让五窗全为正 ⇒ 该轴不是机会 (与 §13.126/§13.157 的判定口径一致)。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
