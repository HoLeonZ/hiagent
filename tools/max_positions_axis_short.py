"""`short_reversal` 的 `max_positions` 轴 (§13.161) —— 四个族里**最后一个**。

为什么这一格是开的
------------------
§9 的"尺子不敏感"表第一行点名两个族; §13.157 (uptrend) 与 §13.160 (chase) 已受控复核
⇒ **`short_reversal` 是最后一族**。而且它的历史判决恰好有一次**无效实验**:
§3.1 曾把「提高 `max_positions`(N=2/N=4)」判为"更好", 而 §13.24 查明那次
**该族没有并发计数闸门** —— 实测 `v58_mp_2` 并发峰值 **15** (声明 2)。
⇒ 本节要回答的第一件事就是: **闸门现在到底在不在** (S1)。

⚠️ 与另两族的**结构性差别** (必须写清, 否则会读错)
* 本族**没有 `position_sizing` 键**: N>1 时引擎**自动**把每笔改成 `free_cash / max_positions`
  (`replay_strategy_v3.py`: `if self.p.max_positions > 1: target_value = free_cash / N`)
  ⇒ 不存在 §13.24/§13.157 那个"`all_in` 名义多槽实际 1 槽"的陷阱, 但**也不可分开调节**;
* 本族**只有 3/55 个 preset** 能上这条轴: `sl_cooldown_days > 0` 与 `max_positions > 1`
  被引擎 **fail-fast** 拒绝 (冷却期状态是**全局单变量**, 为 N=1 设计)
  ⇒ N>1 的适用范围**结构性地**小于另两族 (本工具报出这一条)。

用法:
    python3 tools/max_positions_axis_short.py
    python3 tools/max_positions_axis_short.py --base v58_mp_2 --ns 1 2 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from short_reversal import presets as P  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS  # noqa: E402
from short_reversal.engine import run_backtest_v3  # noqa: E402

CAPITAL = 1_000_000.0
WINDOWS: tuple[tuple[str, str, str], ...] = (
    # ⚠️ 末窗末日按 §13.8 截到最后一个**干净日** `2026-09-18` (因子表止于此;
    # 本族读 hfq ⇒ §13.9 的假暴跌区必须避开)。第一版我误用了 `2025-03-31`,
    # 那既不是本族的规范窗、也让它与 uptrend/chase 的 W2 不可比。
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
)


def max_concurrent(trades: pd.DataFrame) -> int:
    """日频并发峰值 (⚠️ 出场当日不计: 引擎先平后开, 出场日槽位已空出)。"""
    if trades is None or len(trades) == 0:
        return 0
    e = pd.to_datetime(trades["entry_date"])
    x = pd.to_datetime(trades["exit_date"])
    best = 0
    for d in pd.Index(sorted(set(e) | set(x))):
        best = max(best, int(((e <= d) & (x > d)).sum()))
    return best


def utilisation(trades: pd.DataFrame, eq_rows: list) -> float:
    """均用资 = Σ(开仓名义 = entry_price × size) / NAV, 按 equity 曲线逐日取均值。

    ⚠️ 本族的 `equity_curve` 里 `holdings_value` 是**未实现盈亏**(`(entry − close) × size`),
    **不是持仓名义** ⇒ 不能直接拿它当"用了多少钱" (§13.160 的均用资在另两族是
    `holdings/equity`, 那里是真市值)。所以本族必须**从成交清单反推名义**。
    """
    if not eq_rows or trades is None or len(trades) == 0:
        return float("nan")
    eq = pd.DataFrame(eq_rows)
    if "date" not in eq or "equity" not in eq:
        return float("nan")
    eq = eq.dropna(subset=["date", "equity"])
    if eq.empty:
        return float("nan")
    e = pd.to_datetime(trades["entry_date"])
    x = pd.to_datetime(trades["exit_date"])
    notional = (trades["entry_price"].astype(float) * trades["size"].astype(float)).to_numpy()
    vals = []
    for d, nav in zip(pd.to_datetime(eq["date"]), eq["equity"].astype(float)):
        if not nav or nav != nav or nav <= 0:
            continue
        open_mask = (e <= d) & (x > d)
        vals.append(float(notional[open_mask.to_numpy()].sum()) / float(nav))
    return float(sum(vals) / len(vals)) if vals else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="v58_mp_2")
    ap.add_argument("--ns", type=int, nargs="+", default=[1, 2, 4])
    args = ap.parse_args()

    print(f"口径披露 (§13.13): short_reversal -> {dict(_BASIS)}")
    base = dict(P.PRESETS[args.base])
    print(f"base preset = {args.base}; 只覆盖 max_positions ∈ {args.ns}, 其余一律不动")
    print(f"  tp_pct={base.get('tp_pct')} sl_pct={base.get('sl_pct')} "
          f"sl_cooldown_days={base.get('sl_cooldown_days', '<未声明>')} "
          f"position_fraction={base.get('position_fraction')}\n")

    # §5 记录的运行时注入做法 (不写 repo): PRESETS 里放一个临时键。
    hdr = (f"{'N':>3}{'窗口':<6}{'笔数':>6}{'并发峰':>7}{'闸门':>6}{'收益':>11}"
           f"{'均用资':>8}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for n in args.ns:
        name = f"__tmp_mp{n}"
        P.PRESETS[name] = {**base, "max_positions": int(n)}
        for wlabel, w0, w1 in WINDOWS:
            r = run_backtest_v3(name, w0, w1, DB_PATH)
            # ⚠️ `run_backtest_v3` **返回的就是 metrics**(不是 {"metrics": ...}) ——
            # 第一版照 uptrend/chase 的形状写 `r["metrics"]` ⇒ KeyError (已修)。
            tr = r["trades"]
            tdf = pd.DataFrame(tr) if tr else pd.DataFrame(
                columns=["entry_date", "exit_date", "entry_price", "size"])
            mc = max_concurrent(tdf)
            util = utilisation(tdf, r.get("equity_curve", []))
            ret = float(r["final_capital"]) / CAPITAL - 1.0
            per = float(r.get("avg_pnl", float("nan")))
            gate = "OK" if mc <= int(n) else "**破**"
            assert "tp_count" in r and "sl_count" in r, "返回体缺计数键 —— 判据会读到空值"
            print(f"{n:>3}{wlabel:<6}{len(tdf):>6}{mc:>7}{gate:>6}"
                  f"{ret:>11.2%}{util:>8.1%}{per:>9.2%}{float(r['max_dd']):>9.2%}")
            rows.append(dict(n=int(n), win=wlabel, cnt=len(tdf),
                             mc=mc, ret=ret, util=util, per=per, dd=float(r["max_dd"])))
        print()
        P.PRESETS.pop(name, None)

    print("=== S1 机理自验: 闸门到底在不在 ===")
    bad = [x for x in rows if x["mc"] > x["n"]]
    print(f"  闸门破格格数: {len(bad)}  " + ("**⛔ 报红: 闸门缺失或失效**" if bad
          else "✅ 全部 mc ≤ 声明 N ⇒ §13.24 那笔债已还清"))
    op = [x for x in rows if x["n"] > 1 and x["mc"] > 1]
    print(f"  轴是否真的开了: {len(op)}/{len([x for x in rows if x['n'] > 1])} 个 N>1 格出现 >1 并发")

    print("\n=== S3: max_dd 是否随 N 改善 ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(f"{x['dd']:>8.1%}" for x in rows if x["win"] == wlabel))
    print("\n=== S2: 均用资 (与 chase 对照: 那一族塌到 0.39×) ===")
    for wlabel, _, _ in WINDOWS:
        b = next((x for x in rows if x["win"] == wlabel and x["n"] == 1), None)
        if not b or not (b["util"] == b["util"]):
            print(f"  {wlabel:<6} (无 N=1 基线或 equity 不可用)"); continue
        print(f"  {wlabel:<6} 基线 {b['util']:>6.1%}  " + "  ".join(
            f"{x['util']/max(b['util'],1e-9):>6.2f}×" for x in rows
            if x["win"] == wlabel and x["n"] > 1))
    print("\n=== S4: 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wlabel))
    print("""
⚠️ **适用范围 (结构性)**: 本族 `sl_cooldown_days > 0` 与 `max_positions > 1` 被 fail-fast 拒绝
   (冷却期状态是全局单变量) ⇒ 只有 52/55 个 preset 能上这条轴 —— **N>1 在本族的适用面天生更窄**。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
