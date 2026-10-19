"""`chase_up` 的 **TP 受控轴** (§13.166) —— 赔付几何在第二个多头族上的那一半。

为什么需要
----------
§13.159 对 chase 的**止损**做了受控轴 (动的是**活键** `atr_sl_mult`; 并证明 `sl_pct`/`tp_pct`
是**影子键** —— 读了然后被 `a * atr_*_mult` 无条件覆盖)。
§13.164 对 **uptrend** 的目标位做了受控轴 (结论: 基线 TP 是**样本内调出来的尖峰**)。
⇒ **chase 的目标位从来没有被单独动过** —— 而它是四族里唯一已有 **2/5 窗为正**的族,
  赔付几何的改善空间在那里最有意义。

判据
----
**只动 `atr_tp_mult`** (活键), 别的一律不动; 5 窗; 同时报**均用资** (承 §13.157/§13.160 的教训)。
并**顺带再证一次影子键**: 固定 `atr_tp_mult`, 只改 `tp_pct` ⇒ 成交清单必须**逐位相同**。

用法:
    python3 tools/tp_width_axis_chase.py
"""
from __future__ import annotations

import argparse
import hashlib
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


def _sig(tr: pd.DataFrame) -> str:
    if tr.empty:
        return "EMPTY"
    cols = [c for c in ("entry_date", "exit_date", "thscode", "size", "entry_price",
                        "exit_price", "exit_reason", "net_pnl") if c in tr.columns]
    return hashlib.sha256(
        pd.util.hash_pandas_object(tr[cols].astype(str), index=False).values.tobytes()
    ).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT)
    ap.add_argument("--tp-mults", type=float, nargs="+", default=[2.0, 3.5, 6.0, 9.0, 12.0])
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"口径披露 (§13.13): chase_up -> {dict(_BASIS)}")
    print(f"preset = {args.preset}")
    print(f"基线: atr_tp_mult={base.get('atr_tp_mult')} (活键)  atr_sl_mult={base.get('atr_sl_mult')} (固定)  "
          f"影子键 tp_pct={base.get('tp_pct')} / sl_pct={base.get('sl_pct')}")

    # ---- 影子键再证 (§13.159) ----
    s1 = _sig(run_backtest({**base, "tp_pct": 0.10}, "2024-10-08", "2026-09-18", DB_PATH)["trades"])
    s2 = _sig(run_backtest({**base, "tp_pct": 0.90}, "2024-10-08", "2026-09-18", DB_PATH)["trades"])
    print(f"\n=== 影子键再证: 只改 tp_pct (0.10 → 0.90) ⇒ {s1} vs {s2} "
          f"{'✅ 逐位相同 (确系影子键)' if s1 == s2 else '⛔ 不同 ⇒ §13.159 的结论在此不成立'}\n")

    hdr = (f"{'tp_mult':>8}{'窗口':<7}{'笔数':>6}{'TP':>5}{'SL':>5}{'time':>6}"
           f"{'收益':>11}{'均用资':>8}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for tp in args.tp_mults:
        p = dict(base); p["atr_tp_mult"] = float(tp)
        for wl, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr, m, eq = r["trades"], r["metrics"], r["equity"]
            util = float((eq["holdings"] / eq["equity"].replace(0, float("nan"))).mean())
            n_tp = int((tr["exit_reason"] == "TP").sum()) if len(tr) else 0
            n_sl = int((tr["exit_reason"] == "SL").sum()) if len(tr) else 0
            n_tm = int((tr["exit_reason"] == "time").sum()) if len(tr) else 0
            ret = float(m["final_equity"]) / CAPITAL - 1.0
            per = float(m.get("avg_net_return", float("nan")))
            print(f"{tp:>8.1f}{wl:<7}{len(tr):>6}{n_tp:>5}{n_sl:>5}{n_tm:>6}"
                  f"{ret:>11.2%}{util:>8.1%}{per:>9.2%}{float(m['max_dd']):>9.2%}")
            rows.append(dict(tp=float(tp), win=wl, n=len(tr), tp_n=n_tp,
                             ret=ret, util=util, per=per, dd=float(m["max_dd"])))
        print()

    print("=== V1 机理自验: TP 命中是否随 atr_tp_mult 变小而上升 ===")
    bad = []
    for wl, _, _ in WINDOWS:
        c = [x["tp_n"] for x in rows if x["win"] == wl]
        if any(c[i] < c[i + 1] for i in range(len(c) - 1)):
            bad.append((wl, c))
    print("  ✅ 五窗全部单调" if not bad else f"  ⚠️ 非单调: {bad}")

    print("\n=== V3: 均用资 (差异是不是「下注变小」的产物) ===")
    for wl, _, _ in WINDOWS:
        b = next(x for x in rows if x["win"] == wl and abs(x["tp"] - base["atr_tp_mult"]) < 1e-9)
        print(f"  {wl:<6} 基线 {b['util']:>6.1%}  " + "  ".join(
            f"{x['util']/max(b['util'],1e-9):>5.2f}×" for x in rows if x["win"] == wl))

    print("\n=== V2: 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wl))
    print("""
读法 (§5): 若有某一档"看起来像候选", **必须**先做 §6.3.3 的**相邻档刀刃检验**
(相邻取值来回变号 ⇒ 响应面是假的), 再看笔数是否够 —— 与 §13.159(h)/§13.164(f) 同一把尺子。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
