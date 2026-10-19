"""当前最优的 **TP 受控轴** (§13.164) —— 赔付几何的另一半。

为什么需要 (§13.158 只做了止损)
--------------------------------
§13.133/§13.134 把病灶定位在「**赔付几何** (止损 2.1% / 目标 26.3%) × 成本」;
§13.158 对**止损**做了受控轴 (结论: 加宽单调变坏, 紧止损是承重结构)。
而**目标位从来没被单独动过** —— 历史 `sweep_v33_long_v*` 都是**联合**扫参 (§5 禁止重做),
受控的单轴从来没有。§13.130 又指出 W2 的头条由 **3 笔**撑着, 而那几笔正是 **TP 命中**。

判据
----
**只动 `tp_pct`**, 别的一律不动; 5 窗; 同时报**均用资** (承 §13.157/§13.160 的教训:
先证明差异不是"下注大小"的产物)。

用法:
    python3 tools/tp_width_sensitivity.py
    python3 tools/tp_width_sensitivity.py --tp-pcts 0.10 0.15 0.2628 0.40 0.60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import METRICS_BASIS as _BASIS  # noqa: E402
from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402

CAPITAL = 1_000_000.0
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--tp-pcts", type=float, nargs="+",
                    default=[0.10, 0.15, 0.2628, 0.40, 0.60])
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"口径披露 (§13.13): uptrend_pullback -> {dict(_BASIS)}")
    print(f"preset = {args.preset}   基线 tp_pct = {base['tp_pct']}   "
          f"sl_pct = {base['sl_pct']} (固定)   max_hold = {base['max_hold']} (固定)")
    print("**受控**: 只动 `tp_pct`, 别的一律不动。\n")

    hdr = (f"{'tp_pct':>8}{'窗口':<7}{'笔数':>6}{'TP':>5}{'SL':>5}{'time':>6}"
           f"{'收益':>11}{'均用资':>8}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for tp in args.tp_pcts:
        p = dict(base); p["tp_pct"] = float(tp)
        for wl, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr, m, eq = r["trades"], r["metrics"], r["equity"]
            util = float((eq["holdings"] / eq["equity"].replace(0, float("nan"))).mean())
            n_tp = int((tr["exit_reason"] == "TP").sum()) if len(tr) else 0
            n_sl = int((tr["exit_reason"] == "SL").sum()) if len(tr) else 0
            n_tm = int((tr["exit_reason"] == "time").sum()) if len(tr) else 0
            ret = float(m["final_equity"]) / CAPITAL - 1.0
            per = float(m.get("avg_net_return", float("nan")))
            print(f"{tp:>8.4f}{wl:<7}{len(tr):>6}{n_tp:>5}{n_sl:>5}{n_tm:>6}"
                  f"{ret:>11.2%}{util:>8.1%}{per:>9.2%}{float(m['max_dd']):>9.2%}")
            rows.append(dict(tp=float(tp), win=wl, n=len(tr), tp_n=n_tp, sl_n=n_sl,
                             tm_n=n_tm, ret=ret, util=util, per=per,
                             dd=float(m["max_dd"])))
        print()

    print("=== U1 机理自验: TP 命中笔数是否随 tp 收窄而上升 ===")
    bad = []
    for wl, _, _ in WINDOWS:
        c = [x["tp_n"] for x in rows if x["win"] == wl]      # 按 tp 升序 ⇒ 命中数应单调降
        if any(c[i] < c[i + 1] for i in range(len(c) - 1)):
            bad.append((wl, c))
    print("  ✅ 五窗全部单调 (tp 越窄命中越多) ⇒ 旋钮接在目标位上" if not bad
          else f"  ⚠️ 非单调: {bad}")

    print("\n=== U4: 均用资 (差异是不是「下注大小」的产物) ===")
    for wl, _, _ in WINDOWS:
        b = next(x for x in rows if x["win"] == wl and abs(x["tp"] - base["tp_pct"]) < 1e-9)
        print(f"  {wl:<6} 基线 {b['util']:>6.1%}  " + "  ".join(
            f"{x['util']/max(b['util'],1e-9):>5.2f}×" for x in rows if x["win"] == wl))

    print("\n=== U3: 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wl))
    print("""
读法 (§5): 本工具不回答"哪档最好"; 它回答 ① 旋钮是否接在目标位上 ② **各窗收益的符号** ——
     若不存在任何一档让 W2 与 IND 同时为正, 则这条轴不是机会 (与 §13.126/§13.157/§13.160 同口径)。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
