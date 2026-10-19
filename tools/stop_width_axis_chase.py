"""`chase_up` 的**受控止损宽度轴** —— 而它的"止损"键有两层 (§13.159)。

本族的两件结构事实 (本轮机械普查)
----------------------------------
1. **22/22 个 chase preset 同时声明"固定档"与"ATR 档"**: `sl_pct` / `tp_pct` **与**
   `atr_sl_mult` / `atr_tp_mult`。而引擎里 (§ 关键三行):
       tp_eff, sl_eff = tp_pct, sl_pct          # ← 先读固定档
       if use_atr:                              # use_atr ⇔ 两个 atr_*_mult 都非 None
           tp_eff = a * atr_tp_mult             # ← 再**无条件覆盖**
           sl_eff = a * atr_sl_mult
   ⇒ **`sl_pct` / `tp_pct` 是"影子键"**: 它们只在 **ATR 查表落空 (None/NaN)** 时才生效。
   ⚠️ 这与 §13.145 的两种都不同 (①发动机不读 ②读了但恒等于默认) —— 是**第三种**:
   **读了、然后在同一行代码块里被另一个键覆盖** (a *fallback*, 不是 dead)。
   ⇒ 只读 `sl_pct=0.05` 会把止损认成 5%, 而实际是 `clip(ATR,1%,8%) × 1.75` ∈ **[1.75%, 14%]**。
2. `atr_pct_floor` / `atr_pct_cap` (默认 **0.01 / 0.08**) **四个引擎都没有 plumb**,
   也没有任何 preset 声明 ⇒ 今天无害, 但**谁哪天写了这个键就会被静默忽略**。
   本工具把它当作**已登记的潜伏项**报出来, **不擅自改** (它不是明文契约条款, 是陷阱)。

本工具的**自我证伪** (两道, 都跑在真实引擎上)
--------------------------------------------
* **A. 影子键**: 固定 `atr_sl_mult`, 只把 `sl_pct` 从 0.05 改到 0.20 ⇒
  成交清单必须**逐位相同**。若不同 ⇒ 本工具上面的「影子」结论**错**。
* **B. 活键**: 只动 `atr_sl_mult` ⇒ 成交清单必须**不同**。若相同 ⇒ 轴没接上。

用法:
    python3 tools/stop_width_axis_chase.py
    python3 tools/stop_width_axis_chase.py --mults 0.75 1.75 3.0 5.0 8.0
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
DEFAULT = ("chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082")
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)
FLOOR, CAP = 0.01, 0.08          # § 引擎默认 (未 plumb)


def _sig(tr: pd.DataFrame) -> str:
    """成交清单指纹 —— 用来判定两次运行是否**逐位相同**。"""
    if tr.empty:
        return "EMPTY"
    cols = [c for c in ("entry_date", "exit_date", "thscode", "size",
                        "entry_price", "exit_price", "exit_reason", "net_pnl")
            if c in tr.columns]
    return hashlib.sha256(
        pd.util.hash_pandas_object(tr[cols].astype(str), index=False).values.tobytes()
    ).hexdigest()[:16]


def gap_stats(tr: pd.DataFrame, mult: float) -> dict:
    """跳空识别: 止损价 = entry_price × (1 − clip(ATR) × mult) (§4: 跳空成交**低于**止损价)。"""
    if tr.empty or "atr_pct" not in tr.columns:
        return dict(n=0, n_sl=0, n_gap=0, share=float("nan"), cost_pct=0.0)
    t = tr.copy()
    a = t["atr_pct"].clip(lower=FLOOR, upper=CAP).fillna(FLOOR)
    stop_px = t["entry_price"] * (1.0 - a * mult)
    sl = t["exit_reason"] == "SL"
    n_sl = int(sl.sum())
    gap = sl & (t["exit_price"] < stop_px * (1.0 - 1e-9))
    n_gap = int(gap.sum())
    cost = float(((stop_px[gap] - t["exit_price"][gap]) * t["size"][gap]).sum())
    return dict(n=len(t), n_sl=n_sl, n_gap=n_gap,
                share=(n_gap / n_sl) if n_sl else float("nan"), cost_pct=cost / CAPITAL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default=DEFAULT)
    ap.add_argument("--mults", type=float, nargs="+", default=[0.75, 1.75, 3.0, 5.0, 8.0])
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"口径披露 (§13.13): chase_up -> {dict(_BASIS)}")
    print(f"preset = {args.preset}")
    print(f"声明的固定档: sl_pct={base.get('sl_pct')} tp_pct={base.get('tp_pct')}   "
          f"声明的 ATR 档: atr_sl_mult={base.get('atr_sl_mult')} atr_tp_mult={base.get('atr_tp_mult')}")
    print(f"⇒ 走 ATR 分支 ⇒ 实际止损宽 = clip(ATR, {FLOOR:.0%}, {CAP:.0%}) × atr_sl_mult "
          f"∈ [{FLOOR*base['atr_sl_mult']:.2%}, {CAP*base['atr_sl_mult']:.2%}]  (基线档)\n")

    # ---------- 自证伪 A: 影子键 ----------
    print("=== A. 自证伪: `sl_pct` 是不是**影子键**? (固定 atr_sl_mult, 只改 sl_pct) ===")
    sigs = {}
    for slp in (0.05, 0.20):
        p = dict(base); p["sl_pct"] = slp
        sigs[slp] = _sig(run_backtest(p, "2024-10-08", "2026-09-18", DB_PATH)["trades"])
    shadow = sigs[0.05] == sigs[0.20]
    print(f"  sl_pct=0.05 ⇒ {sigs[0.05]}   sl_pct=0.20 ⇒ {sigs[0.20]}")
    print("  ✅ 逐位相同 ⇒ `sl_pct` 确是**影子键** (只在 ATR 落空时生效)"
          if shadow else
          "  ⛔ **不同** ⇒ 本工具上面的「影子」结论**错**, 下面的读法作废")

    # ---------- 自证伪 B: 活键 ----------
    print("\n=== B. 自证伪: `atr_sl_mult` 是不是**活键**? ===")
    s_lo = _sig(run_backtest({**base, "atr_sl_mult": 0.75}, "2024-10-08", "2026-09-18", DB_PATH)["trades"])
    print(f"  atr_sl_mult=0.75 ⇒ {s_lo}   基线 ⇒ {sigs[0.05]}")
    print("  ✅ 不同 ⇒ 轴接在活键上" if s_lo != sigs[0.05] else "  ⛔ 相同 ⇒ 轴没接上")

    # ---------- 主表 ----------
    hdr = (f"{'mult':>6}{'窗口':<7}{'笔数':>6}{'SL':>5}{'TP':>5}{'time':>6}{'跳空':>5}"
           f"{'跳空占比':>9}{'跳空成本':>10}{'止损中位':>9}{'收益':>11}{'每笔均':>9}{'maxDD':>9}")
    print("\n" + hdr); print("-" * len(hdr))
    rows = []
    for mult in args.mults:
        p = dict(base); p["atr_sl_mult"] = float(mult)
        for wlabel, w0, w1 in WINDOWS:
            r = run_backtest(p, w0, w1, DB_PATH)
            tr, m = r["trades"], r["metrics"]
            g = gap_stats(tr, float(mult))
            n_tp = int((tr["exit_reason"] == "TP").sum()) if len(tr) else 0
            n_tm = int((tr["exit_reason"] == "time").sum()) if len(tr) else 0
            med_w = float(tr["atr_pct"].clip(FLOOR, CAP).median() * mult) if len(tr) else float("nan")
            ret = float(m["final_equity"]) / CAPITAL - 1.0
            print(f"{mult:>6.2f}{wlabel:<7}{g['n']:>6}{g['n_sl']:>5}{n_tp:>5}{n_tm:>6}"
                  f"{g['n_gap']:>5}{g['share']:>9.1%}{g['cost_pct']:>10.2%}{med_w:>9.2%}"
                  f"{ret:>11.2%}{float(m.get('avg_net_return', float('nan'))):>9.2%}"
                  f"{float(m['max_dd']):>9.2%}")
            rows.append(dict(mult=float(mult), win=wlabel, **g, med_w=med_w, ret=ret))
        print()

    print("=== 机理自验: SL 笔数是否随有效止损变宽单调下降 ===")
    bad = []
    for wlabel, _, _ in WINDOWS:
        c = [x["n_sl"] for x in rows if x["win"] == wlabel]
        if any(c[i] < c[i + 1] for i in range(len(c) - 1)):
            bad.append((wlabel, c))
    print("  ✅ 五窗全部单调下降" if not bad else f"  ⚠️ 非单调: {bad}")

    print("\n=== §13.158 那条性质能否跨族复现: 跳空**成本**随止损变宽 ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(
            f"{x['cost_pct']:>7.2%}" for x in rows if x["win"] == wlabel))

    print("\n=== 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wlabel, _, _ in WINDOWS:
        print(f"  {wlabel:<6} " + "  ".join(
            f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wlabel))
    print(f"""
⚠️ **已登记的潜伏项**: `atr_pct_floor`/`atr_pct_cap` (默认 {FLOOR}/{CAP}) **四个引擎都没 plumb**、
   也无 preset 声明 ⇒ 谁写了就被静默忽略。修法是显式 plumb (零漂移), **本轮只登记不擅改**。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
