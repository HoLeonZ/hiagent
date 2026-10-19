"""把 §13.136 那句「跳空占比与止损宽度**无关**」放在**受控单 preset 轴**上复核 (§13.158)。

为什么需要 (§13.136 自己留下的混淆)
------------------------------------
§13.136 的普查取 **26 个 preset**, 止损宽度跨 **150 倍**, 结论是
> 「跳空穿价占比 20%–57%, 而**与止损宽度无关** (合并 corr **+0.03**)」，
> 「它是日线执行的属性, 不是止损的属性」。

⚠️ 但那是**跨 preset** 的比较 —— 止损宽度在那些 preset 里与**信号/持有期/目标位**
**同时**变化 ⇒ 那个 +0.03 **证明不了"与止损宽度无关"**, 它只说明"在这些 preset 之间看不出关系"。
**受控的版本只有一个**: 同一个 preset, **只**动 `sl_pct`, 别的一律不动。

判据: 跳空可以从**成交清单**直接认出来 (§4)
--------------------------------------------
止损价 = `entry_price × (1 − sl_pct)` (§13.129: TP/SL **锚在成交价**上)。
* **盘中触及** ⇒ 成交价**恰好**是止损价;
* **跳空穿价** ⇒ 开盘已在止损之下 ⇒ 成交价**低于**止损价。
⇒ `exit_price < stop_px` 即跳空, **不需要重跑引擎的 bar 循环**。

于是本工具能报出 §13.136 **没报**的两件事:
* **跳空占比** (`n_gap / n_sl`) 在受控轴上到底动不动;
* **跳空成本** (`Σ (stop_px − exit_price) × size / 初始资金`) —— 每笔、以及占权益的比例。

用法:
    python3 tools/stop_width_sensitivity.py
    python3 tools/stop_width_sensitivity.py --sl-pcts 0.021 0.05 0.10 0.20 0.50
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


def gap_stats(trades: pd.DataFrame, sl_pct: float) -> dict:
    """从成交清单认跳空穿价 (§4: 盘中触及成交在止损价, 跳空成交在开盘=止损之下)。"""
    if trades.empty:
        return dict(n=0, n_sl=0, n_gap=0, share=float("nan"),
                    depth=float("nan"), cost_pct=float("nan"))
    t = trades.copy()
    stop_px = t["entry_price"] * (1.0 - sl_pct)
    sl = t["exit_reason"] == "SL"
    n_sl = int(sl.sum())
    if n_sl == 0:
        return dict(n=len(t), n_sl=0, n_gap=0, share=float("nan"),
                    depth=float("nan"), cost_pct=0.0)
    # ⚠️ 用相对容差: 盘中触及的成交价**恰好**等于止损价 (浮点相等不可靠)。
    gap = sl & (t["exit_price"] < stop_px * (1.0 - 1e-9))
    n_gap = int(gap.sum())
    under = (stop_px[gap] - t["exit_price"][gap])
    depth = float((under / t["entry_price"][gap]).mean()) if n_gap else float("nan")
    cost = float((under * t["size"][gap]).sum())
    return dict(n=len(t), n_sl=n_sl, n_gap=n_gap,
                share=(n_gap / n_sl) if n_sl else float("nan"),
                depth=depth, cost_pct=cost / CAPITAL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--sl-pcts", type=float, nargs="+",
                    default=[0.021, 0.05, 0.10, 0.20, 0.50])
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"口径披露 (§13.13): uptrend_pullback -> {dict(_BASIS)}")
    print(f"preset = {args.preset}   基线 sl_pct = {base['sl_pct']}   "
          f"tp_pct = {base['tp_pct']}   max_hold = {base['max_hold']}")
    print("**受控**: 只动 `sl_pct`, 别的一律不动 (信号/持有期/目标位/仓位全部固定)。\n")

    hdr = (f"{'sl_pct':>8}{'窗口':<7}{'笔数':>6}{'SL':>5}{'TP':>5}{'time':>6}"
           f"{'跳空':>5}{'跳空占比':>9}{'跳空深度':>9}{'跳空成本':>10}"
           f"{'每笔跳空':>10}{'收益':>11}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    for slp in args.sl_pcts:
        p = dict(base); p["sl_pct"] = float(slp)
        for wlabel, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr, m = r["trades"], r["metrics"]
            g = gap_stats(tr, float(slp))
            n_tp = int((tr["exit_reason"] == "TP").sum()) if len(tr) else 0
            n_tm = int((tr["exit_reason"] == "time").sum()) if len(tr) else 0
            per_gap = (g["cost_pct"] / g["n"]) if g["n"] else float("nan")
            ret = float(m["final_equity"]) / CAPITAL - 1.0
            print(f"{slp:>8.3f}{wlabel:<7}{g['n']:>6}{g['n_sl']:>5}{n_tp:>5}{n_tm:>6}"
                  f"{g['n_gap']:>5}{g['share']:>9.1%}{g['depth']:>9.2%}"
                  f"{g['cost_pct']:>10.2%}{per_gap:>10.3%}{ret:>11.2%}"
                  f"{float(m.get('avg_net_return', float('nan'))):>9.2%}"
                  f"{float(m['max_dd']):>9.2%}")
            rows.append(dict(sl=float(slp), win=wlabel, **g, tp=n_tp, tm=n_tm,
                             ret=ret, per=float(m.get("avg_net_return", float("nan"))),
                             dd=float(m["max_dd"])))
        print()

    print("=== 机理自验 (§13.94: 工具先证明它读的是它声称的量) ===")
    ok = True
    for wlabel, _, _ in WINDOWS:
        sub = [x for x in rows if x["win"] == wlabel]
        cnts = [x["n_sl"] for x in sub]
        mono = all(cnts[i] >= cnts[i + 1] for i in range(len(cnts) - 1))
        if not mono:
            ok = False
            print(f"  ⛔ {wlabel}: SL 笔数不随止损变宽单调下降 {cnts} ⇒ 旋钮可能没接上")
    print("  ✅ SL 笔数在所有窗口随止损变宽单调下降 ⇒ 旋钮确实接在止损上"
          if ok else "  ⚠️ 见上")

    print("\n=== P2 的受控复核: 跳空占比到底动不动? ===")
    for wlabel, _, _ in WINDOWS:
        sub = [x for x in rows if x["win"] == wlabel]
        shares = "  ".join(f"{x['share']:>6.1%}" for x in sub)
        per = "  ".join(f"{x['cost_pct']:>6.2%}" for x in sub)
        print(f"  {wlabel:<6} 占比 {shares}   | 总成本 {per}")

    print("\n=== 逐窗符号 (§5: 不报「哪档最好」, 只报符号与计数) ===")
    for wlabel, _, _ in WINDOWS:
        sub = [x for x in rows if x["win"] == wlabel]
        line = "  ".join(f"{x['ret']:>+8.2%}" for x in sub)
        print(f"  {wlabel:<6} {line}")
    print("""
读法: 若**跳空占比随止损变宽而下降**, 则 §13.136 那句「与止损宽度无关」是**跨 preset 混淆**的
      产物 (那个 corr +0.03 把信号/持有期/目标位的共变一起算进去了), 应**收窄措辞**为
      「在**这些 preset 之间**看不出关系」; 真正的受控结论以本表为准。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
