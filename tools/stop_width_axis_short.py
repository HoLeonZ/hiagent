"""`short_reversal` 的**止损受控轴** (§13.170) —— 四族里最后一个没做过赔付几何的。

符号 (§ 引擎 `replay_strategy_v3.py`)
------------------------------------
本族是**空头**:
    tp_p = ep × (1 − tp_pct)      # 在**下方** (跌到止盈)
    sl_p = ep × (1 + sl_pct)      # 在**上方** (涨到止损)
⇒ **跳空穿价 = 开盘已 ≥ sl_p ⇒ 成交在 open_p (更高) = 回补更贵 = 悲观** (§4 明文;
   本族此前填 sl_p = 系统性乐观, 已于 2026-10-17 修正 —— 那正是本族优势消失的原因)。
⇒ 判据: SL 出场且 `exit_price > sl_p` ⇒ **跳空**; 而 `exit_price == sl_p` ⇒ 盘中触及。

⚠️ 成本削减: **名册截到 N_CODES 只** (真引擎/真价格/真信号, 只是票少)。
   ⇒ **绝对量级不可与 §4 的族记分卡相比**; 本节只看**沿轴的方向**。

用法:
    python3 tools/stop_width_axis_short.py
    python3 tools/stop_width_axis_short.py --sl-pcts 0.0005 0.005 0.01 0.02
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from short_reversal import presets as P  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS  # noqa: E402
from short_reversal.engine import run_backtest_v3  # noqa: E402

CAPITAL = 1_000_000.0
N_CODES = 400
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v35_agg_pctchg_04_09")
    ap.add_argument("--sl-pcts", type=float, nargs="+",
                    default=[0.0005, 0.005, 0.01, 0.02])
    ap.add_argument("--tp-pcts", type=float, nargs="+", default=None,
                    help="给了就改跑**目标位**轴 (只动 tp_pct, sl_pct 固定)")
    ap.add_argument("--n-codes", type=int, default=N_CODES)
    args = ap.parse_args()

    import short_reversal.engine as eng
    base = dict(P.PRESETS[args.preset])
    full = eng.load_universe_asof("mainboard_only", WINDOWS[0][1], DB_PATH)
    sub = sorted(full)[: args.n_codes]
    eng.load_universe_asof = lambda *a, **k: sub      # 固定切片 ⇒ 沿轴保持不变

    print(f"口径披露 (§13.13): short_reversal -> {dict(_BASIS)}")
    print(f"preset = {args.preset}  (tp_pct={base.get('tp_pct')} **固定**, max_hold={base.get('max_hold')} **固定**)")
    print(f"⚠️ 名册截到 **{len(sub)}** 只 (全名册 {len(full)}) ⇒ 绝对量级不可与 §4 记分卡相比\n")

    hdr = (f"{'sl_pct':>9}{'窗口':<6}{'笔数':>6}{'SL':>5}{'TP':>5}{'time':>6}{'跳空':>5}"
           f"{'跳空占比':>9}{'跳空成本':>10}{'收益':>11}{'每笔均':>9}{'maxDD':>9}")
    print(hdr); print("-" * len(hdr))
    rows = []
    axis = "tp_pct" if args.tp_pcts else "sl_pct"
    levels = args.tp_pcts if args.tp_pcts else args.sl_pcts
    print(f"**轴 = `{axis}`**  (另一项固定: "
          f"{'sl_pct=' + str(base.get('sl_pct')) if axis == 'tp_pct' else 'tp_pct=' + str(base.get('tp_pct'))})\n")
    for slp in levels:
        name = f"__tmp_{axis}_{slp}"
        P.PRESETS[name] = {**base, axis: float(slp)}
        for wl, w0, w1 in WINDOWS:
            r = run_backtest_v3(name, w0, w1, DB_PATH)
            tr = r["trades"]; t = pd.DataFrame(tr) if tr else pd.DataFrame(
                columns=["entry_price", "exit_price", "size", "exit_reason"])
            # 跳空判据 (空头: 止损在上方 ⇒ 成交价高于止损价即跳空)
            _sl_eff = float(base.get("sl_pct")) if axis == "tp_pct" else float(slp)
            sl_px = t["entry_price"].astype(float) * (1.0 + _sl_eff) if len(t) else pd.Series(dtype=float)
            is_sl = (t["exit_reason"] == "SL") if len(t) else pd.Series(dtype=bool)
            gap = is_sl & (t["exit_price"].astype(float) > sl_px * (1.0 + 1e-9)) if len(t) else pd.Series(dtype=bool)
            n_sl = int(is_sl.sum()); n_gap = int(gap.sum())
            cost = float(((t["exit_price"].astype(float)[gap] - sl_px[gap])
                          * t["size"].astype(float)[gap]).sum()) / CAPITAL if n_gap else 0.0
            n_tp = int((t["exit_reason"] == "TP").sum()) if len(t) else 0
            n_tm = int((t["exit_reason"] == "time").sum()) if len(t) else 0
            ret = float(r["final_capital"]) / CAPITAL - 1.0
            per = float(r.get("avg_pnl", float("nan")))
            print(f"{slp:>9.4f}{wl:<6}{len(t):>6}{n_sl:>5}{n_tp:>5}{n_tm:>6}{n_gap:>5}"
                  f"{(n_gap/n_sl if n_sl else float('nan')):>9.1%}{cost:>10.2%}"
                  f"{ret:>11.2%}{per:>9.2%}{float(r['max_dd']):>9.2%}")
            rows.append(dict(level=float(slp), win=wl, n=len(t), n_sl=n_sl, n_tp=n_tp, n_gap=n_gap,
                             share=(n_gap/n_sl if n_sl else float("nan")),
                             cost=cost, ret=ret, per=per, dd=float(r["max_dd"])))
        P.PRESETS.pop(name, None)
        print()

    # ⚠️ 机理自验**必须跟着轴走**: 动的是止损 ⇒ 看 SL 笔数; 动的是目标 ⇒ 看 TP 笔数。
    # (第一版只看 SL 笔数 ⇒ 跑 `--tp-pcts` 时它会报"SL 非单调" —— 而那**本来就是应该的**
    #  (sl_pct 没动), 于是它会给出一个**看起来像故障**的警告。判据要与被变动的量对齐。)
    key, label, expect = (("n_tp", "TP 笔数", "随 tp 收窄而上升") if axis == "tp_pct"
                          else ("n_sl", "SL 笔数", "随止损变窄而上升"))
    print(f"=== Y1 机理自验: {label} 是否 {expect} ===")
    bad = []
    for wl, _, _ in WINDOWS:
        c = [x[key] for x in rows if x["win"] == wl]
        if any(c[i] < c[i + 1] for i in range(len(c) - 1)):
            bad.append((wl, c))
    print("  ✅ 两窗都单调" if not bad else f"  ⚠️ 非单调: {bad}")

    print("\n=== Y2 跨族复现检验: 跳空成本随止损变宽 ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['cost']:>8.2%}" for x in rows if x["win"] == wl))
    print("\n=== Y3: 逐窗符号 (§5: 不报「哪档最好」) ===")
    for wl, _, _ in WINDOWS:
        print(f"  {wl:<6} " + "  ".join(f"{x['ret']:>+9.2%}" for x in rows if x["win"] == wl))
    print(f"""
⚠️ 名册被截到 {args.n_codes} 只 ⇒ 只读**方向**, 不读量级 (§13.168 的同一条边界)。
⚠️ 每次运行的档数计入 `n_trials` (§5)。""")


if __name__ == "__main__":
    main()
