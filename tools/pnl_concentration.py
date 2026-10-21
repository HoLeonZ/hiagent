"""当前最优的收益**集中度**: 去掉最好的 k 笔之后还剩什么? (§13.130)

为什么它是**精确**的而不是近似
------------------------------
先验证恒等式 (本工具每次运行都验, 不通过就报警):

    final_equity == initial_capital + Σ net_pnl          (逐元成立)

它对 `max_positions=1` + 全仓成立 —— 权益只会被**已实现盈亏**改变 (§2 复式记账)。
⇒ **每一笔对终值的贡献恰是它的 `net_pnl`** ⇒ "去掉最好的 k 笔"是**减法**, 不是重跑模拟。
(若某个 preset 不是 `max_positions=1`, 恒等式不成立, 本工具会报出来而不是给错数。)

为什么需要它
------------
§13.129 发现: 滑点系数对结果的摆幅**由 1–6 笔 TP 命中**决定。
本节把同一问法上移一层: **结果本身**由几笔撑着?
若去掉 3 笔就把头条的符号翻过来, 那么那个头条是**彩票**, 不是**优势** ——
这句话比"没有 alpha"更硬, 也更不该被引用时省略。

⚠️ 这是**描述**, 不是新检验: 用的还是同一批已被看过的窗口 (§5)。
   它不产生任何新主张, 只给已有的主张补上一个**必须一起引用**的数。

用法:
    python3 tools/pnl_concentration.py
    python3 tools/pnl_concentration.py --preset <name>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

INITIAL = 1_000_000.0
# 末窗末日按 §13.8 截到最后一个干净日
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--drop", type=int, nargs="+", default=[1, 3, 5])
    args = ap.parse_args()

    p = get_preset(args.preset)
    print(f"preset = {args.preset}  max_positions = {p['max_positions']}  "
          f"position_sizing = {p.get('position_sizing')}")
    if p["max_positions"] != 1:
        print("⚠️ max_positions != 1 ⇒ **恒等式未必成立**, 下面的减法分解不可信。")
    print()

    hdr = " ".join(f"{'去最好'+str(k):>11}" for k in args.drop)
    print(f"{'窗口':<6} {'n':>4} {'总收益':>10} {hdr} {'前3占毛利':>10} {'恒等式':>8}")
    bad = 0
    for label, w0, w1 in WINDOWS:
        uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        r = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)
        t = r["trades"]
        fin = r["metrics"]["final_equity"]
        total = float(t["net_pnl"].sum()) if len(t) else 0.0
        ident = abs(fin - INITIAL - total) < 1.0
        bad += (not ident)

        pnl = np.sort(t["net_pnl"].to_numpy())[::-1] if len(t) else np.array([0.0])
        base = r["metrics"]["total_return"]
        drops = " ".join(
            f"{((INITIAL + total - pnl[:k].sum()) / INITIAL - 1):>+11.2%}"
            for k in args.drop
        )
        pos = pnl[pnl > 0].sum()
        share = (pnl[:3].sum() / pos) if pos > 0 else float("nan")
        print(f"{label:<6} {len(t):>4} {base:>+10.2%} {drops} {share:>10.0%} "
              f"{'✅' if ident else '❌':>8}")
        del pan

    if bad:
        print(f"\n⛔ {bad} 个窗口的恒等式**不成立** ⇒ 本表不可引用。")
    print("""
读法: 「去最好 k」= 把该窗已实现盈亏里最大的 k 笔置零后的终值。
      恒等式 `末值 = 初值 + Σnet_pnl` 成立时这一步是**精确减法**, 不是重跑。
⚠️ 若「去最好 3」已把符号翻负, 那么该窗口的头条**由 3 笔撑着** ——
   引用这个头条时**必须一起引用这个数** (§7: 不能由当前代码+一条命令重生成的数字要删;
   而这里是**必须一起给的数**)。""")


if __name__ == "__main__":
    main()
