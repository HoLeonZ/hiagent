"""跳空占比的**普查** (而非代表性抽样) —— §13.135 自己登记的缺口 (§13.136)。

§13.135 只做了每族 **1 个**代表性 preset, 并把它写成"**缺口, 不是普查**"。
本工具把它补上: 逐 preset 算「跳空穿价占比 / 跳空深度 / 跳空成本」。

成本实测 (W2, 单 preset): `chase_up` **4s** · `uptrend_pullback` **4s** ·
`short_reversal` **362s** · `cycle_price_action` **~600s**。
⇒ 两个多头族可**全量**; `short_reversal` (55 个) 只能**抽样**, 且必须**标明是抽样**。

口径
----
* 沿用 `gap_stop_attribution_4engine` 的适配器与方向处理 (空头取负号);
* 止损宽: 走 ATR 分支的 preset 用 `atr_pct × atr_sl_mult` (中位), 否则用 `sl_pct`
  —— §13.135(b) 的教训: **别读那个没被读的键**;
* 「跳空成本」对 `cycle` **不可比** (逐票百万账户, §13.125a), 故该族不报 Σ。

⚠️ §13.90: 本工具**并列四族** ⇒ 静态导入各族 `METRICS_BASIS` 并披露 (不走豁免)。

用法:
    python3 tools/gap_fraction_census.py --families chase_up,uptrend_pullback
    python3 tools/gap_fraction_census.py --families short_reversal --max-per-family 6
    python3 tools/gap_fraction_census.py --families cycle_price_action
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from chase_up.backtest import METRICS_BASIS as _BASIS_CHASE  # noqa: E402
from cycle_price_action.allocator import METRICS_BASIS as _BASIS_CYCLE  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS_SHORT  # noqa: E402
from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402

import gap_stop_attribution_4engine as G  # noqa: E402

_BASIS = {"chase_up": lambda: dict(_BASIS_CHASE),
          "uptrend_pullback": lambda: dict(_BASIS_UPTREND),
          "short_reversal": lambda: dict(_BASIS_SHORT),
          "cycle_price_action": lambda: dict(_BASIS_CYCLE)}


def _presets(fam: str) -> list[str]:
    if fam == "chase_up":
        from chase_up.presets import PRESETS
    elif fam == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
    elif fam == "short_reversal":
        from short_reversal.presets import PRESETS
    else:
        return ["PRESET_V1"]
    return sorted(PRESETS)


def _one(fam: str, preset: str, w0: str, w1: str) -> dict | None:
    import pandas as pd

    p, t, direction = G.ADAPTERS[fam](preset, w0, w1)
    if t is None or len(t) == 0:
        return None
    use_atr = p.get("atr_tp_mult") is not None and p.get("atr_sl_mult") is not None
    if use_atr and "atr_pct" in t.columns:
        sl_eff = t["atr_pct"].astype(float) * float(p["atr_sl_mult"])
        width = float(sl_eff.median())
        sl_des = t["entry_price"] * (1 - direction * sl_eff)
    else:
        width = float(p.get("sl_pct", 0.0))
        sl_des = t["entry_price"] * (1 - direction * width)
    if (t["exit_reason"].astype(str) != "").any():
        sl = t[t["exit_reason"] == "SL"].copy()
    else:
        sl = t[t["exit_price"] <= sl_des + 1e-9].copy()   # cycle: 无 exit_reason, 反推
    if len(sl) == 0:
        return None
    sl["gap"] = ((sl["exit_price"] < sl_des.loc[sl.index] - 1e-9) if direction > 0
                 else (sl["exit_price"] > sl_des.loc[sl.index] + 1e-9))
    sl["extra"] = ((sl_des.loc[sl.index] - sl["exit_price"]) * sl["size"]).abs()
    depth = (sl["extra"] / (sl["entry_price"] * sl["size"])).abs()
    return {"preset": preset, "n": len(t), "n_sl": len(sl), "width": width,
            "gap_frac": float(sl["gap"].mean()),
            "depth_med": float(depth[sl["gap"]].median()) if sl["gap"].any() else float("nan"),
            "gap_cost": float(sl.loc[sl["gap"], "extra"].sum()),
            "net": float(t["net_pnl"].sum())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--families", default="chase_up,uptrend_pullback")
    ap.add_argument("--max-per-family", type=int, default=0, help="0 = 全量")
    ap.add_argument("--w0", default="2024-10-08")
    ap.add_argument("--w1", default="2026-09-18")
    args = ap.parse_args()

    fams = [x.strip() for x in args.families.split(",") if x.strip()]
    print(f"窗口 {args.w0}..{args.w1}\n=== 口径披露 (§13.13/§13.90: 四族同名指标定义不同) ===")
    for f in fams:
        print(f"  {f:<22} {_BASIS[f]()}")
    print("  ⚠️ 可横比的是 **跳空占比 / 深度**(由成交价与 ATR 直接算, 不经指标口径);\n"
          "     `净利` 与 `Σ跳空成本` 各族口径不同, **不可跨族比**。\n")

    for fam in fams:
        names = _presets(fam)
        sampled = False
        if args.max_per_family and len(names) > args.max_per_family:
            step = len(names) / args.max_per_family
            names = [names[int(i * step)] for i in range(args.max_per_family)]
            sampled = True
        print(f"=== {fam}  ({len(names)} 个 preset"
              + (" , **抽样**" if sampled else " , 全量") + ") ===")
        print(f"{'preset':<44} {'n':>5} {'SL':>5} {'止损宽':>8} {'跳空':>7} "
              f"{'深度中位':>8} {'Σ跳空成本':>13} {'净利':>13}")
        rows = []
        for nm in names:
            try:
                r = _one(fam, nm, args.w0, args.w1)
            except Exception as e:  # noqa: BLE001
                print(f"{nm[:44]:<44} **{type(e).__name__}: {str(e)[:40]}**")
                continue
            if r is None:
                print(f"{nm[:44]:<44} {'(无 SL 成交)':>26}")
                continue
            rows.append(r)
            print(f"{nm[:44]:<44} {r['n']:>5} {r['n_sl']:>5} {r['width']:>8.2%} "
                  f"{r['gap_frac']:>7.0%} {r['depth_med']:>8.2%} {r['gap_cost']:>+13,.0f} "
                  f"{r['net']:>+13,.0f}", flush=True)
        if rows:
            gf = np.array([r["gap_frac"] for r in rows])
            wd = np.array([r["width"] for r in rows])
            dp = np.array([r["depth_med"] for r in rows])
            ok = np.isfinite(gf) & np.isfinite(wd)
            corr = (float(np.corrcoef(wd[ok], gf[ok])[0, 1]) if ok.sum() > 2 else float("nan"))
            print(f"  --- 汇总: n={len(rows)}  跳空占比 中位 {np.median(gf):.0%} "
                  f"范围 {gf.min():.0%}–{gf.max():.0%} | "
                  f"止损宽 {wd.min():.2%}–{wd.max():.2%} | "
                  f"深度中位 中位 {np.nanmedian(dp):.2%}")
            print(f"      **corr(止损宽, 跳空占比) = {corr:+.2f}**  "
                  f"⇒ {'几乎无关' if abs(corr) < 0.4 else '有关'} "
                  f"(若无关, 则跳空占比**不由止损宽度决定**)")
            print()

    print("""读法: 若**所有** preset 的跳空占比都落在同一个窄带、且与该 preset 的止损宽无关,
     则 §13.135 那条从"一个 preset"提升为"**该族的属性**", 进而"**日线执行的属性**"。
⚠️ short_reversal / cycle 若为抽样, 结论只能写成"在该抽样内成立", **不得写成普查**。""")


if __name__ == "__main__":
    main()
