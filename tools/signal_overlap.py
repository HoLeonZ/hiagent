"""四族**信号频率**与**候选重叠** (§13.142)。

为什么问这个
-----------
"四族全部关闭"这句话隐含"它们是**四条独立证据**"。若各族的信号高度重叠, 那其实是更少的
独立检验 ⇒ 这句话的强度被高估。
另一半动机: §13.138 对 `chase_up` 的结论建在 **n=31 笔**上, 我当时写"n 小"但**没量化事件母体**。
⇒ 本工具量两件事:
  ① **信号频率**: 各族在窗口内产生多少个候选 (日, 票);
  ② **候选重叠**: 两族的候选集之交 / 并 (Jaccard), 分 (日,票) 与 (票) 两种。

⚠️ 只测**两个多头族** (`uptrend_pullback` / `chase_up`): 它们的候选可由 `select_entries*`
    直接取出 (秒级)。**另两族**的候选要走各自的引擎路径 (6–10 分钟/preset)
    ⇒ **本节不测它们, 也不据此推断它们。**

口径: 窗口内、各族**默认 preset** 的完整候选集 (不做容量筛除 —— 这里问的是"信号", 不是"成交")。

用法:
    python3 tools/signal_overlap.py
    python3 tools/signal_overlap.py --w0 2022-10-03 --w1 2024-09-30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

# §13.90/§13.13: 本工具**确实把两族并排在一张表里** ⇒ **必须**静态导入各族自披露的
# `METRICS_BASIS` 并报出来 (不走豁免)。与 §13.138 那个"只提族名不并列"的工具不同。
from chase_up.backtest import METRICS_BASIS as _BASIS_CHASE  # noqa: E402
from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402

_BASIS = {"chase_up": lambda: dict(_BASIS_CHASE),
          "uptrend_pullback": lambda: dict(_BASIS_UPTREND)}


def _uptrend(w0: str, w1: str) -> set[tuple[str, str]]:
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.regime import compute_regime
    from uptrend_pullback.signals import (
        compute_indicators,
        select_entries_v33_long_mirror,
    )
    from uptrend_pullback.universe import load_universe

    p = get_preset("v33_long_reverse_v22")
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
    pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    reg = compute_regime(pan, **p["regime"]) if p.get("regime") else None
    kw = {k: v for k, v in p["signal"].items() if k != "entry_mode"}
    ent = select_entries_v33_long_mirror(pan, start_date=w0, end_date=w1,
                                         regime_df=reg, **kw)
    return {(str(a)[:10], b) for a, b in zip(ent["date"], ent["thscode"])}


def _chase(w0: str, w1: str) -> set[tuple[str, str]]:
    from chase_up.data import load_panel
    from chase_up.presets import get_preset
    from chase_up.signals import compute_indicators, select_entries
    from chase_up.universe import load_universe

    p = get_preset("chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082")
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
    pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    ent = select_entries(pan, start_date=w0, end_date=w1, **p["signal"])
    return {(str(a)[:10], b) for a, b in zip(ent["date"], ent["thscode"])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--w0", default="2024-10-08")
    ap.add_argument("--w1", default="2026-09-18")
    args = ap.parse_args()

    up = _uptrend(args.w0, args.w1)
    ch = _chase(args.w0, args.w1)
    print(f"窗口 {args.w0}..{args.w1}   (候选 = 信号层全部触发, 未做容量筛除)")
    print("\n=== 口径披露 (§13.13/§13.90: 各族同名**指标**定义不同) ===")
    for f in ("uptrend_pullback", "chase_up"):
        print(f"  {f:<22} {_BASIS[f]()}")
    print("  ⚠️ 本表并列的是**候选计数与集合重叠 (Jaccard)** —— 它们由信号层直接得出、\n"
          "     不经任何一族的指标口径 ⇒ **可横比**; 本工具**不报**任何族的 metrics。\n")
    print("=== ① 信号频率 ===")
    print(f"  uptrend_pullback  {len(up):>7,} 个 (日,票)")
    print(f"  chase_up          {len(ch):>7,} 个 (日,票)   "
          f"⇒ **{len(up)/max(len(ch),1):.0f}× 更稀**")
    cu = {c for _, c in up}
    cc = {c for _, c in ch}
    print(f"  涉及票数: uptrend {len(cu):,}   chase {len(cc):,}")

    print("\n=== ② 候选重叠 ===")
    inter = up & ch
    print(f"  (日,票) 交集 {len(inter):>6,}   并集 {len(up | ch):>7,}   "
          f"**Jaccard = {len(inter)/len(up | ch):.4f}**")
    ci = cu & cc
    print(f"  票集(不分日) 交集 {len(ci):>6,}   Jaccard = {len(ci)/len(cu | cc):.4f}")
    print(f"  chase 的票里也在 uptrend 票集里的比例: **{len(ci)/max(len(cc),1):.1%}**")
    print("""
读法:
  * **(日,票) Jaccard ≈ 0** ⇒ 两族的**入场事件在时间上不相交** ⇒
    它们不是"同一次下注被计了两次" ⇒ 对"四族 = 四条独立证据"这句话是**支持**;
  * 而**票集重叠高** ⇒ 不是两个互不相干的宇宙, 而是**两个在时间上不相交的事件流**;
  * **信号频率差 ~70×** ⇒ 稀的那一族, 其任何结论都建在一个**极小的母体**上。
⚠️ 只测两个多头族; **不据此推断另两族** (见模块 docstring)。""")


if __name__ == "__main__":
    main()
