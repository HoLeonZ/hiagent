"""**独立复现** §13.208 那条"少切换帮忙"的读数 (§13.214)。

为什么必须独立复现
------------------
§13.208 在五窗上量到: 把**笔数**压低 ⇒ **残差 (数量通道) 5/5 为正** —— 那是整条出场线上
**唯一**跨窗稳定的正向读数。但它**只用了一种机制**: ATR 档 (宽 TP + 宽 SL ⇒ 持仓久 ⇒
后续入场被跳过)。**一个只由一种机制支撑的读数, 在换机制之前不算成立。**

本工具换一个**与出场几何无关**的机制: 收紧**市场宽度闸门** (`regime.min_breadth`)。
它直接减少"允许入场的日子", **不碰 tp/sl**。

⚠️ **两种机制不可假定等价**
* ATR 档: **因为占着仓位所以跳过后继入场** (入场集合随**持有状态**变);
* 闸门:   **因为在场外所以没得入场**     (入场集合随**市场状态**变)。
  本节测的就是这两者是不是同一个"数量通道"。

口径
----
逐窗比较 `基线` / `ATR 档` / `min_breadth ∈ {0.55, 0.65, 0.75}`, 各做**完整重模拟** (净):
`笔数` · `净 Σ` · `净/笔` · `暴露 = Σ持有日 ÷ 窗内交易日` · 以及
**残差 (数量通道) = 完整重模拟的差 − 同批入场 (基线入场) 的净几何差**。

⚠️ **残差混着"各臂自有股数"** (§13.200(g) 登记的缺陷) ⇒ 只作**定性方向**读, **不当量用**;
⚠️ **不选档、不报哪一档最好** (§5); §13.114 已记 `min_breadth` 轴非单调且窗口特异;
⚠️ `IND`/`IS2` 重叠 ⇒ 独立单位 ≈ 4。

用法:
    python3 tools/count_channel_replication.py
    python3 tools/count_channel_replication.py --breadths 0.45,0.55,0.65,0.75
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

# 复用 §13.199 那套既有工具的重放 (单一来源, 不重写)
sys.path.insert(0, str(ROOT / "tools"))
from same_entries_exit_policy_cf import (  # noqa: E402
    ATR_FLOOR, ATR_CAP, ATR_SL_MULT, ATR_TP_MULT, ATR_MAX_HOLD,
    WINDOWS, _signal_day_atr, _replay, entry_fee, exit_fee,
)

DEFAULT_PRESET = "v33_long_reverse_v22"


def _net_full(preset: dict, panel, w0: str, w1: str) -> tuple[float, int, float]:
    """完整重模拟 ⇒ (净 Σ, 笔数, Σ持有日)。"""
    res = run_backtest(dict(preset), w0, w1, DB_PATH, panel_ind=panel)
    tr = pd.DataFrame(res["trades"])
    net = float(res["metrics"]["final_equity"]) - 1_000_000.0
    hold = (float(pd.to_numeric(tr["hold_days"], errors="coerce").sum())
            if len(tr) and "hold_days" in tr.columns else 0.0)
    return net, len(tr), hold


def _geom_atr_fixed(bars: dict, trb: pd.DataFrame, preset: dict) -> float:
    """**基线入场**上、逐笔 ATR 出场政策的**净几何** Σ (异质政策 ⇒ 必须逐笔重放)。"""
    sl, mh = float(preset["sl_pct"]), int(preset["max_hold"])
    tot = 0.0
    for t in trb.itertuples():
        d = bars.get(t.thscode)
        if d is None:
            continue
        a = _signal_day_atr(d, t.entry_date, ATR_FLOOR, ATR_CAP)
        if a is None:
            r = _replay(d, t.entry_date, float(t.entry_price), float(preset["tp_pct"]), sl, mh)
        else:
            r = _replay(d, t.entry_date, float(t.entry_price),
                        ATR_TP_MULT * a, ATR_SL_MULT * a, ATR_MAX_HOLD)
        if r is None:
            continue
        px, size, e0 = float(r[1]), int(t.size), float(t.entry_price)
        tot += (px - e0) * size - entry_fee(e0, size) - exit_fee(px, size)
    return tot


def _geom_base_fixed(bars: dict, trb: pd.DataFrame, preset: dict) -> float:
    """**基线入场**上、**基线**出场政策的净几何 Σ (同质 ⇒ 可一次算)。"""
    tp, sl, mh = (float(preset["tp_pct"]), float(preset["sl_pct"]), int(preset["max_hold"]))
    tot = 0.0
    for t in trb.itertuples():
        d = bars.get(t.thscode)
        if d is None:
            continue
        r = _replay(d, t.entry_date, float(t.entry_price), tp, sl, mh)
        if r is None:
            continue
        px, size, e0 = float(r[1]), int(t.size), float(t.entry_price)
        tot += (px - e0) * size - entry_fee(e0, size) - exit_fee(px, size)
    return tot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT_PRESET)
    ap.add_argument("--breadths", default=None, help="逗号分隔; 第一个必须是基线值")
    args = ap.parse_args()

    base_p = dict(get_preset(args.preset))
    b0 = float(base_p["regime"]["min_breadth"])
    bs = ([float(x) for x in args.breadths.split(",")] if args.breadths
          else [b0, 0.55, 0.65, 0.75])
    if abs(bs[0] - b0) > 1e-12:
        raise SystemExit(f"⛔ 第一个取值 {bs[0]} 必须等于基线 min_breadth {b0} (它是内检档)。")

    atr_p = dict(base_p)
    atr_p.update(atr_tp_mult=ATR_TP_MULT, atr_sl_mult=ATR_SL_MULT, max_hold=ATR_MAX_HOLD)

    print(f"preset={args.preset}  基线 min_breadth={b0}")
    print("机制 A = ATR 档 (占着仓位 ⇒ 跳过后继入场) · 机制 B = 收紧宽度闸门 (在场外 ⇒ 没得入场)")
    print("⚠️ 两者**不可假定等价**; 本工具就是测这个的。\n")

    rows = {}
    for win, (w0, w1) in WINDOWS.items():
        preset = dict(base_p)
        uni = set(load_universe(preset["universe"], DB_PATH, asof_date=w0))
        panel = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        days = int(panel["date"].nunique())
        bars = {c: s.reset_index(drop=True) for c, s in panel.groupby("thscode", sort=False)}

        nb, tb, hb = _net_full(preset, panel, w0, w1)
        na, ta, ha = _net_full(atr_p, panel, w0, w1)
        # ⚠️ 只有机制 A 能算"同批入场的几何差" (它从**基线入场**出发);
        #    机制 B **换了一批入场** ⇒ 它的残差**无法**与 A 的残差同尺比。
        #    ⇒ **不造那个不可比的数**; 改用**两个都直接测得到的量**:
        #    `Δ笔数` 与 `Δ净`。若"少切换帮忙"是一般性质 ⇒ `Δ笔数<0 ⇒ Δ净>0` 应当普遍成立。
        trb = pd.DataFrame(run_backtest(dict(preset), w0, w1, DB_PATH,
                                        panel_ind=panel)["trades"]).copy()
        trb["entry_date"] = pd.to_datetime(trb["entry_date"])
        g_atr = _geom_atr_fixed(bars, trb, preset)
        g_base = _geom_base_fixed(bars, trb, preset)
        out = {"基线": (nb, tb, hb, 0.0),
               "ATR": (na, ta, ha, (ta - tb) - (g_atr - g_base))}

        for v in bs[1:]:
            pv = dict(preset)
            rg = dict(pv["regime"])
            rg["min_breadth"] = v
            pv["regime"] = rg
            nv, tv, hv = _net_full(pv, panel, w0, w1)
            out[f"闸门{v:.2f}"] = (nv, tv, hv, float("nan"))   # 残差对 B **不可算**
        del panel
        # ★ 内检 = §13.199 自己那条自检: **在基线入场上重放基线政策必须复现引擎的净 Σ**。
        #   不通过 ⇒ 重放/费用写错了 ⇒ 本窗作废 (与本册"判据自带自检"的规矩一致)。
        ok = abs(g_base - tb) < 1.0
        print(f"  {win}: 内检 {'✅' if ok else '⛔ **不过 ⇒ 本窗作废**'} "
              f"(基线入场上的基线政策净 Σ {g_base:>+13,.0f} vs 引擎 {tb:>+13,.0f}, 差 {g_base - tb:>+9,.0f})")
        if not ok:
            continue
        rows[win] = (days, out)

    print(f"\n  === 笔数 (机制 A vs B) ===")
    print(f"  {'窗口':<7}" + "".join(f"{k:>14}" for k in rows[next(iter(rows))][1]))
    for win, (days, out) in rows.items():
        print(f"  {win:<7}" + "".join(f"{v[1]:>14}" for v in out.values()))

    print(f"\n  === Δ笔数 / Δ净 (两个都是**直接测量**, 都可跨机制比) ===")
    keys = list(rows[next(iter(rows))][1])
    print(f"  {'窗口':<7}" + "".join(f"{k:>26}" for k in keys[1:]))
    for win, (days, out) in rows.items():
        nb, tb = out["基线"][0], out["基线"][1]
        cells = ""
        for k in keys[1:]:
            n_, t_ = out[k][0], out[k][1]
            cells += f"{n_ - nb:>+9} /{t_ - tb:>+15,.0f}"
        print(f"  {win:<7}{cells}")
    print("  ⇒ 每格是「Δ笔数 / Δ净」")

    print(f"\n  === 「笔数降了 ⇒ 净涨了吗」的一致性 ===")
    agree = tot = 0
    for win, (days, out) in rows.items():
        nb, tb = out["基线"][0], out["基线"][1]
        for k in keys[1:]:
            dn, dt = out[k][0] - nb, out[k][1] - tb
            if dn == 0:
                continue
            tot += 1
            if (dn < 0) == (dt > 0):
                agree += 1
    print(f"    **{agree}/{tot}** 个 (窗 × 变体) 上「少笔数 ⇒ 高净额」成立")
    for k in keys[1:]:
        pos = sum(1 for _, out in rows.values() if out[k][1] > out["基线"][1])
        nfew = sum(1 for _, out in rows.values() if out[k][0] < out["基线"][0])
        print(f"    {k:<12} 笔数 < 基线的窗 **{nfew}/{len(rows)}** · 净额 > 基线的窗 **{pos}/{len(rows)}**")
    print("""  读法: 若两个机制**一致** (笔数降 ⇒ 净涨普遍成立) ⇒ §13.208 是**关于数量的一般性质**;
  若只有 ATR 一致 ⇒ 那个读数**只属于 ATR 机制**, 措辞必须收窄到机制。
  ⚠️ **不报哪一档最好** (§5: §13.114 已记该轴非单调且窗口特异)。""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
