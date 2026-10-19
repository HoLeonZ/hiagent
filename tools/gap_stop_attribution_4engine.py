"""跳空穿价占比 —— **四族横向** (§13.135)。

§13.134 在 `uptrend_pullback` 上量出: 中位跳空深度 ≈ 止损宽度 ⇒ **下行由跳空分布决定**。
本节问: 这是**那一族的属性**, 还是**日线级止损策略在本库的通病**?

可检验的结构性预测
------------------
四族的止损宽度差了两个数量级:
    uptrend v22 **2.1%** · chase v3 **5%** · cycle **5%** · short_reversal **0.05%**
⇒ 若"跳空占比由止损宽度决定"成立, 则**止损越窄, 跳空占比越高**。
(short_reversal 的 0.05% 意味着它在**任何**隔夜跳动下都是跳空出场 ⇒ 预测接近 100%)

各族成交记录**形状不同** (本工具要适配, 这本身是本册记过的"同名不同物"):
  * `chase_up` / `uptrend_pullback`: `run_backtest(...)["trades"]` → **DataFrame**
  * `short_reversal`: `run_backtest_v3(...)["trades"]` → **list[dict]**
  * `cycle_price_action`: `run_backtest(...).trades` → **list[TradeRecord]**, **且没有 exit_reason**
    ⇒ 该族只能按"exit_price 与设计止损位的关系"反推 (见下)

方向
----
**多头** (chase/uptrend/cycle): 止损位 = `entry×(1−sl_pct)`; 跳空穿价 = `exit_price < 止损位`
**空头** (short_reversal):   止损位 = `entry×(1+sl_pct)`; 跳空穿价 = `exit_price > 止损位`

用法:
    python3 tools/gap_stop_attribution_4engine.py --family chase_up
    python3 tools/gap_stop_attribution_4engine.py --family short_reversal --preset v35_agg_pctchg_04_09
    python3 tools/gap_stop_attribution_4engine.py --family all      # cycle 很慢 (~10 分钟)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

# §13.90/§13.13: 本工具**确实把四族并列在一张表里** ⇒ **必须**静态导入各族自披露的
# `METRICS_BASIS` 并把差异报出来 (不能走豁免 —— 豁免留给"顺带提到族名但并未并列"的工具)。
from chase_up.backtest import METRICS_BASIS as _BASIS_CHASE  # noqa: E402
from cycle_price_action.allocator import METRICS_BASIS as _BASIS_CYCLE  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS_SHORT  # noqa: E402
from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402

_BASIS = {
    "chase_up": lambda: dict(_BASIS_CHASE),
    "uptrend_pullback": lambda: dict(_BASIS_UPTREND),
    "short_reversal": lambda: dict(_BASIS_SHORT),
    "cycle_price_action": lambda: dict(_BASIS_CYCLE),
}

W0_DEFAULT, W1_DEFAULT = "2024-10-08", "2026-09-18"
INITIAL = 1_000_000.0


def _trades_chase(preset: str, w0: str, w1: str):
    from chase_up.backtest import run_backtest
    from chase_up.data import load_panel
    from chase_up.presets import get_preset
    from chase_up.signals import compute_indicators
    from chase_up.universe import load_universe

    p = get_preset(preset)
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
    pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    t = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)["trades"]
    return p, t, +1


def _trades_uptrend(preset: str, w0: str, w1: str):
    from uptrend_pullback.backtest import run_backtest
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.signals import compute_indicators
    from uptrend_pullback.universe import load_universe

    p = get_preset(preset)
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
    pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    t = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)["trades"]
    return p, t, +1


def _trades_short(preset: str, w0: str, w1: str):
    from short_reversal.engine import run_backtest_v3
    from short_reversal.presets import PRESETS

    name = preset if preset in PRESETS else sorted(PRESETS)[0]
    r = run_backtest_v3(name, w0, w1, DB_PATH)
    return PRESETS[name], pd.DataFrame(r["trades"]), -1   # -1 = 空头


def _trades_cycle(preset: str, w0: str, w1: str):
    import datetime as dt

    from cycle_price_action.backtest import run_backtest
    from cycle_price_action.presets import PRESET_V1

    p = dict(PRESET_V1)
    r = run_backtest(str(DB_PATH), dt.date.fromisoformat(w0), dt.date.fromisoformat(w1), preset=p)
    rows = [{"entry_date": t.entry_date, "thscode": t.thscode,
             "entry_price": t.entry_price, "exit_price": t.exit_price,
             "size": t.shares, "net_pnl": t.pnl,
             "exit_reason": ""} for t in r.trades]
    return p, pd.DataFrame(rows), +1


ADAPTERS = {"chase_up": _trades_chase, "uptrend_pullback": _trades_uptrend,
            "short_reversal": _trades_short, "cycle_price_action": _trades_cycle}
DEFAULTS = {"chase_up": "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082",
            "uptrend_pullback": "v33_long_reverse_v22",
            "short_reversal": "v35_agg_pctchg_04_09",
            "cycle_price_action": "PRESET_V1"}


def _report(fam: str, preset: str, w0: str, w1: str) -> None:
    p, t, direction = ADAPTERS[fam](preset, w0, w1)
    if t is None or len(t) == 0:
        print(f"{fam:<20} {preset:<28} 无成交"); return
    # ⚠️⚠️ 必须用**引擎真正用的**那个止损宽度 —— 而不是 preset 里的 `sl_pct`。
    # 本工具第一版就栽在这里: `chase_v19_...atr_tp6_sl175...` 声明 `sl_pct=0.05`
    # 但同时有 `atr_tp_mult=6.0 / atr_sl_mult=1.75` ⇒ 引擎走 **ATR 分支**
    # (`use_atr = atr_tp_mult is not None and atr_sl_mult is not None`),
    # 于是那个 `sl_pct=0.05` **根本没被读**; 按 5% 算的"设计止损位"是错的,
    # 打出了 100% 跳空占比这个**假的**读数。
    # (§13.128 记过的同一形状: 一个声明着的键并不一定被读。)
    use_atr = p.get("atr_tp_mult") is not None and p.get("atr_sl_mult") is not None
    if use_atr and "atr_pct" in t.columns:
        sl_eff = t["atr_pct"].astype(float) * float(p["atr_sl_mult"])
        sl_pct = float(sl_eff.median())
        sl_des = t["entry_price"] * (1 - direction * sl_eff)
    else:
        sl_pct = float(p.get("sl_pct", 0.0))
        sl_des = t["entry_price"] * (1 - direction * sl_pct)
    tp_pct = float(p.get("tp_pct", 0.0))
    # 「SL 类」成交: 有 exit_reason 就按它; 没有 (cycle) 就按"成交价不优于设计止损位"
    if (t["exit_reason"].astype(str) != "").any():
        sl = t[t["exit_reason"] == "SL"].copy()
    else:
        sl = t[t["exit_price"] <= sl_des + 1e-9].copy()
    if len(sl) == 0:
        print(f"{fam:<20} {preset:<28} 无 SL 成交"); return
    sl["gap"] = (sl["exit_price"] < sl_des.loc[sl.index] - 1e-9) if direction > 0 \
        else (sl["exit_price"] > sl_des.loc[sl.index] + 1e-9)
    sl["extra"] = ((sl_des.loc[sl.index] - sl["exit_price"]) * sl["size"]).abs()
    depth = (sl["extra"] / (sl["entry_price"] * sl["size"])).abs()
    net = float(t["net_pnl"].sum())
    print(f"{fam:<20} {preset[:28]:<28} n={len(t):>4} sl={len(sl):>4} "
          f"止损宽 {sl_pct:>6.2%}  跳空 **{sl['gap'].mean():>5.0%}** "
          f"({int(sl['gap'].sum())}/{len(sl)})  深度中位 {depth[sl['gap']].median() if sl['gap'].any() else float('nan'):>6.2%}  "
          f"多亏 Σ={sl.loc[sl['gap'],'extra'].sum():>+11,.0f}  净利={net:>+11,.0f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--family", default="all",
                    choices=["all", *ADAPTERS.keys()])
    ap.add_argument("--preset", default="")
    ap.add_argument("--w0", default=W0_DEFAULT)
    ap.add_argument("--w1", default=W1_DEFAULT)
    args = ap.parse_args()

    fams = list(ADAPTERS) if args.family == "all" else [args.family]
    print(f"窗口 {args.w0}..{args.w1}   (方向已按各族多/空自动取号)")
    print("\n=== 口径披露 (§13.13/§13.90: **四族同名指标定义不同, 不得跨族比较**) ===")
    for fam in fams:
        print(f"  {fam:<22} {_BASIS[fam]()}")
    print("  ⚠️ 本表并列的是**跳空占比/深度** (由成交价与 ATR 直接算, 不经各族的指标口径),")
    print("     故它们**可**横向比; 而各族 `净利` 列来自不同口径的 metrics ⇒ **不可比**。\n")
    print(f"{'族':<20} {'preset':<28} {'n':>4} {'SL':>4} {'止损宽':>8}  "
          f"{'跳空占比':>9} {'深度中位':>8}  {'多亏Σ':>12} {'净利':>12}")
    for fam in fams:
        preset = args.preset or DEFAULTS[fam]
        try:
            _report(fam, preset, args.w0, args.w1)
        except Exception as e:  # noqa: BLE001
            print(f"{fam:<20} **{type(e).__name__}: {str(e)[:60]}**")
    print("""
读法: 若「跳空占比」随「止损宽」单调反向 (窄 ⇒ 高), 则 §13.134 的机制是**跨族**的:
      **日线级止损策略的下行由跳空分布决定, 而不由止损位决定。**
⚠️ cycle 没有 exit_reason, 其"SL 类"是按 exit_price ≤ 设计止损位**反推**的, 可信度低于另三族。
⚠️ §5: 这是描述, 不选参、不排名。""")


if __name__ == "__main__":
    main()
