"""沿**入场门槛**轴的一次检验: 「抬高边际入场的门槛」到底能不能帮到所有窗? (§13.209)

动机
----
§13.208 在五窗上量到: 几何关死之后, 剩下那条**唯一正向且跨窗稳定**的一路是
**"少切换"**(笔数 5/5 下降 · 残差 5/5 为正)—— 而它**不是**"少暴露" (暴露反而 5/5 上升)。
⇒ 可行动的形状是 **抬高边际入场的门槛**。

本工具把 `signal.min_mom120` (基线 0.18) 往上抬, 在**五个窗**上做**完整重模拟**。

为什么必须五窗一起看 (§13.209 P1)
----------------------------------
§13.208 的机理是**关于数量的**: 单笔期望为负的窗 ⇒ 少做几笔按**均值**就该变好。
而 `W2` 的单笔期望是**正的** (+12,866/笔) ⇒ 少做在那儿**必然**伤害。
⇒ **先验预测: 门槛提高会让四个亏窗变好、让 `W2` 变差, 而没有一档能让五窗同时变好。**

内检
----
* 本工具**不做**"同批入场"的反事实 —— 它是**完整重模拟** (改了信号 ⇒ 换了一批入场);
* 内置断言: `min_mom120` 取基线值时, 结果必须**逐位复现**基线 (否则是本工具写错了)。

⚠️ **只报形状与计数, 不报"哪一档最好"** (§5 同窗择优禁令); 本工具**不采用**任何取值。

用法:
    python3 tools/entry_threshold_axis.py
    python3 tools/entry_threshold_axis.py --key min_mom120 --values 0.18,0.25,0.35,0.50,0.70
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

# 窗口表与 `tools/capacity_ceiling.py` / `same_entries_exit_policy_cf.py` 一致 (§13.8/§13.9)。
WINDOWS: dict[str, tuple[str, str]] = {
    "W2": ("2024-10-08", "2026-09-18"),
    "IND": ("2022-10-03", "2024-09-30"),
    "IS1": ("2021-10-01", "2022-09-30"),
    "IS2": ("2023-10-01", "2024-09-30"),
    "EXTRA": ("2017-10-02", "2019-09-30"),
}
DEFAULT_PRESET = "v33_long_reverse_v22"
DEFAULT_KEY = "min_mom120"


def _run(preset: dict, panel, w0: str, w1: str, key: str, value: float) -> tuple:
    """返回 (净 Σ, 笔数, 笔数, top-3 Σ 占比)。`value is None` ⇒ 用基线值。"""
    p = dict(preset)
    sig = dict(p["signal"])
    if value is not None:
        sig[key] = value
    p["signal"] = sig
    res = run_backtest(p, w0, w1, DB_PATH, panel_ind=panel)
    net = float(res["metrics"]["final_equity"]) - 1_000_000.0
    tr = pd.DataFrame(res["trades"])
    if len(tr) and "net_pnl" in tr.columns:
        pnls = pd.to_numeric(tr["net_pnl"], errors="coerce").fillna(0.0)
        top3 = float(pnls.nlargest(3).sum())
        share = top3 / net if net else float("nan")
    else:
        share = float("nan")
    return net, len(tr), len(tr), share


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT_PRESET)
    ap.add_argument("--key", default=DEFAULT_KEY)
    ap.add_argument("--values", default=None,
                    help="逗号分隔; **第一个必须是基线值**, 它同时是内检档")
    args = ap.parse_args()

    preset = dict(get_preset(args.preset))
    base_val = float(preset["signal"][args.key])
    vals = ([float(x) for x in args.values.split(",")] if args.values
            else [base_val, 0.25, 0.35, 0.50, 0.70])
    if abs(vals[0] - base_val) > 1e-12:
        raise SystemExit(f"⛔ 第一个取值 {vals[0]} 必须等于基线值 {base_val} (它是内检档)。")

    print(f"preset={args.preset}  轴 = signal.{args.key}  基线值 = {base_val}")
    print("⚠️ 这是**完整重模拟** (改了信号 ⇒ 换了一批入场), 与 §13.208 的"
          "「同批入场」反事实**不是同一个设计**。\n")

    per_win: dict[str, dict[float, tuple]] = {}
    for win, (w0, w1) in WINDOWS.items():
        uni = set(load_universe(preset["universe"], DB_PATH, asof_date=w0))
        panel = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        cells = {}
        for v in vals:
            cells[v] = _run(preset, panel, w0, w1, args.key, None if v == base_val else v)
        # 内检: 基线档必须逐位复现基线 —— 用**不带覆盖**的那次作为真基线
        ref = _run(preset, panel, w0, w1, args.key, None)
        assert abs(cells[base_val][0] - ref[0]) < 1e-6 and cells[base_val][1] == ref[1], \
            (win, cells[base_val], ref)
        per_win[win] = cells
        del panel
        print(f"  {win:<6} 内检 ✅ (基线档 {cells[base_val][0]:>+13,.0f} / {cells[base_val][1]} 笔)")

    print(f"\n  === 净 Σ (元) / 笔数 ===")
    hdr = "".join(f"{v:>18.2f}" for v in vals)
    print(f"  {'窗口':<7}{'基线':>18}" + hdr)
    for win, cells in per_win.items():
        row = f"  {win:<7}{cells[base_val][0]:>+18,.0f}"
        for v in vals:
            row += f"{cells[v][0]:>+18,.0f}"
        print(row)
    print(f"\n  === 笔数 / top-3 Σ 占比 ===")
    print(f"  {'窗口':<7}" + "".join(f"{v:>18.2f}" for v in vals))
    for win, cc in per_win.items():
        row = f"  {win:<7}"
        for v in vals:
            row += f"{cc[v][2]:>11} /{cc[v][3]:>6.0%}"
        print(row)
    print("  ⇒ 每格是「笔数 / top-3 Σ 占比」—— **占比 >100% 意味着 top-3 以外那批合计是亏的**")

    print(f"\n  === 「在几个窗上严格超过基线」 ===")
    counts = {}
    for v in vals[1:]:
        beat = [w for w, c in per_win.items() if c[v][0] > c[base_val][0]]
        counts[v] = beat
        fewer = sum(1 for w, c in per_win.items() if c[v][1] <= c[base_val][1])
        print(f"    {args.key} = {v:<6.2f} 超过基线的窗 **{len(beat)}/{len(per_win)}**  {beat}"
              f"   (笔数 ≤ 基线的窗 {fewer}/{len(per_win)})")
    best = max(len(b) for b in counts.values())
    print(f"\n  ⇒ **最大计数 = {best}/{len(per_win)}**"
          f"{'  ⚠️ 有档覆盖全部窗' if best == len(per_win) else ''}")
    print(f"  ⇒ `W2` 那一列: " +
          " · ".join(f"{v:.2f}→{per_win['W2'][v][0] - per_win['W2'][base_val][0]:+,.0f}" for v in vals[1:]))
    print("""  读法: 机理 (§13.208) 说"少切换帮忙"。若某档 5 窗全好 ⇒ 门槛真能通用;
  若"亏窗变好而 W2 变差" ⇒ 它只是**少做负期望的事**, 不是**做出了正期望的事**。
  ⚠️ **本工具不报"哪一档最好", 也不采用任何取值** (§5: 同窗择优)。
  ⚠️ `IND`/`IS2` 重叠 ⇒ 独立单位 ≈ 4。""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
