"""跳空穿价 (gap-through-stop) 的**精确归因** (§13.134)。

为什么需要
----------
§13.133 量出止损"设计 2.1% / 实际平均亏 4.04%", 但**没拆开**。
引擎的止损分支有两种成交, 可以**精确切开**:
    if open_p <= sl_p:  price = open_p     ← **跳空穿价** (§4 要求填开盘价, 悲观)
    elif low   <= sl_p: price = sl_p       ← 盘中触及止损位
所以对每一笔 SL, `(sl_des − exit_price) × size` **就是**这笔因跳空多付的钱 —— 无需重跑。

⚠️ 口径 (必须一起读)
------------------
* 这是**同一条已实现路径上的成交价差归因**: 它把 `size` 与后续路径都**固定**,
  只问"这一笔的成交价若在止损位而非开盘价, 会差多少钱"。
  **它不是重跑模拟** (那会因现金变化而改变后续每笔的仓位), 所以它是**下单价格差**的
  精确分解, 不是"改了这个策略就会翻倍"的预测。
* 反过来, TP 分支的跳空 (开盘高于目标位 ⇒ 填在开盘价) 是**有利**的, 一并量出作对照。

用法:
    python3 tools/gap_stop_attribution.py
    python3 tools/gap_stop_attribution.py --w0 2022-10-03 --w1 2024-09-30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd  # noqa: F401  (保持与原脚本一致的导入风格)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

INITIAL = 1_000_000.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--w0", default="2024-10-08")
    ap.add_argument("--w1", default="2026-09-18")
    args = ap.parse_args()

    p = get_preset(args.preset)
    if p.get("atr_tp_mult") or p.get("atr_sl_mult"):
        print("⚠️ 该 preset 用 ATR 派生 TP/SL ⇒ 本工具的『设计位』口径不适用, 请先确认。")
    tp_pct, sl_pct = float(p["tp_pct"]), float(p["sl_pct"])

    uni = set(load_universe(p["universe"], DB_PATH, asof_date=args.w0))
    pan = compute_indicators(load_panel(DB_PATH, args.w0, args.w1, universe=uni))
    t = run_backtest(dict(p), args.w0, args.w1, DB_PATH, panel_ind=pan)["trades"]
    t = t.copy()
    t["sl_des"] = t["entry_price"] * (1 - sl_pct)
    t["tp_des"] = t["entry_price"] * (1 + tp_pct)

    sl = t[t.exit_reason == "SL"].copy()
    tp = t[t.exit_reason == "TP"].copy()
    sl["gap"] = sl["exit_price"] < sl["sl_des"] - 1e-9
    tp["gap"] = tp["exit_price"] > tp["tp_des"] + 1e-9
    sl["extra_loss"] = (sl["sl_des"] - sl["exit_price"]) * sl["size"]
    tp["extra_gain"] = (tp["exit_price"] - tp["tp_des"]) * tp["size"]

    net = float(t["net_pnl"].sum())
    print(f"preset={args.preset}  {args.w0}..{args.w1}   sl_pct={sl_pct:.3%}  tp_pct={tp_pct:.3%}")
    print(f"成交 {len(t)} 笔;  期末净利润 {net:+,.0f} (= {net/INITIAL:+.2%})\n")

    print(f"=== SL 分支 (n={len(sl)}) ===")
    n_gap = int(sl["gap"].sum())
    print(f"  跳空穿价 **{n_gap}/{len(sl)} = {sl['gap'].mean():.0%}**")
    if n_gap:
        g = sl.loc[sl["gap"], "extra_loss"]
        depth = (sl.loc[sl["gap"], "sl_des"] - sl.loc[sl["gap"], "exit_price"]) / \
                sl.loc[sl["gap"], "entry_price"]
        print(f"  多亏 Σ = {g.sum():+,.0f}  (每笔均值 {g.mean():+,.0f})")
        print(f"  跳空深度 (相对入场价): 均值 {depth.mean():.2%}  中位 {depth.median():.2%}  "
              f"最大 {depth.max():.2%}")
    print(f"  实际平均亏 {sl['net_return'].mean():+.2%}")

    print(f"\n=== TP 分支 (n={len(tp)}) ===")
    n_g = int(tp["gap"].sum())
    print(f"  跳空上穿 {n_g}/{len(tp)} = {tp['gap'].mean():.0%}"
          + (f"   多赚 Σ = {tp.loc[tp['gap'],'extra_gain'].sum():+,.0f}" if n_g else ""))

    gap_cost = sl.loc[sl["gap"], "extra_loss"].sum() if n_gap else 0.0
    gap_gain = tp.loc[tp["gap"], "extra_gain"].sum() if n_g else 0.0
    print(f"\n=== 跳空净成本 = {gap_cost - gap_gain:+,.0f} "
          f"(= 初始本金 {(gap_cost-gap_gain)/INITIAL:+.2%}) ===")
    print(f"  对照: 总费用 {t['fees'].sum():,.0f} (= {t['fees'].sum()/INITIAL:.2%}); "
          f"净利 {net:,.0f}")
    if net:
        print(f"  ⇒ **跳空成本 / 净利润 = {(gap_cost-gap_gain)/net:.0%}**")
    print("""
读法: 这是**同一路径上的成交价差分解** (size 与后续路径都固定), **不是重跑模拟**。
     它回答"这一笔的成交价若在止损位而非开盘价会差多少", 不回答"改了策略会怎样"。
⚠️ §4 要求跳空填开盘价 (悲观) —— **这条规则本身是对的**; 本工具量的是"它对结果有多大"。
     一个 2.1% 的止损相对日线跳空分布**太近**, 于是多数止损出场是隔夜跳空。
""")


if __name__ == "__main__":
    main()
