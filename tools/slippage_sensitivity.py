"""当前最优在 §4 执行滑点下的敏感度 —— 以及那个旋钮**实际动了什么** (§13.129)。

为什么需要
----------
§6.2 一直登记着「**所有已报告数字都不含执行滑点**」, 而 §13.96 已把 §4 的滑点接进
`uptrend_pullback` ⇒ 现在第一次能量出**当前最优的头条里有多少是"零执行成本"的产物**。

⚠️ 三点边界必须与数字一起读
--------------------------
1. **系数取值未定** (§6.2) ⇒ `atr_slip_scale=1` 只是**一个**取值, **不是"正确值"**;
2. §13.95 已实测该旋钮**同时改变仓位大小** (入场价被抬高 ⇒ 份额变少) ⇒ 它**不是**干净的成本实验;
3. 这是**度量**, **不改**任何 preset 的默认值 (§0 悲观默认: 先知道量级, 再决定)。

★ 本工具存在的真正理由 (§13.129(c)(d))
--------------------------------------
引擎里 TP/SL 是**锚在滑点后的成交价**上的:
    "tp": entry_px * (1 + tp_eff)      # entry_px = raw_open × (1 + slip)
    "sl": entry_px * (1 - sl_eff)
⇒ 调"成本"会**移动出场阈值** ⇒ 成交清单随之改变。所以本工具第二张表打的不是收益率,
而是**出场原因分布** —— 它把"这不是一次成本实验"从推断变成读数。

用法:
    python3 tools/slippage_sensitivity.py
    python3 tools/slippage_sensitivity.py --scales 0 0.5 1
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

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
    ap.add_argument("--scales", type=float, nargs="+", default=[0.0, 1.0])
    args = ap.parse_args()

    base = get_preset(args.preset)
    print(f"preset = {args.preset}   atr_slip_scale ∈ {args.scales}")
    print("⚠️ 系数取值未定 (§6.2); 该旋钮同时改变仓位大小 (§13.95)\n")

    print("=== (1) 收益对滑点系数的敏感度 ===")
    print(f"{'窗口':<6} " + " ".join(f"{'s='+str(s):>11}" for s in args.scales)
          + f" {'Δ(末-首)':>10}")
    deltas = {}
    for label, w0, w1 in WINDOWS:
        uni = set(load_universe("mainboard_only", DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        row = []
        for s in args.scales:
            cfg = copy.deepcopy(base)
            cfg["atr_slip_scale"] = s
            m = run_backtest(cfg, w0, w1, DB_PATH, panel_ind=pan)["metrics"]
            row.append(m["total_return"])
        deltas[label] = row[-1] - row[0]
        print(f"{label:<6} " + " ".join(f"{v:>+11.2%}" for v in row)
              + f" {deltas[label]:>+10.2%}")
        del pan
    n_up = sum(1 for v in deltas.values() if v > 0)
    print(f"⇒ 加滑点后 **变好** 的窗口 {n_up}/{len(deltas)} ⇒ "
          f"{'它在这族里不是成本 (见 (2) 的机制)' if n_up else '方向与成本一致'}")

    print("\n=== (2) 它实际动了什么: 出场原因分布 (首/末两个 scale) ===")
    print(f"{'窗口':<6} {'scale':>6} {'笔数':>5} {'SL':>4} {'TP':>4} {'time':>5} "
          f"{'平均单笔':>9} {'均持仓':>7}")
    for label, w0, w1 in WINDOWS:
        uni = set(load_universe("mainboard_only", DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        for s in (args.scales[0], args.scales[-1]):
            cfg = copy.deepcopy(base)
            cfg["atr_slip_scale"] = s
            t = run_backtest(cfg, w0, w1, DB_PATH, panel_ind=pan)["trades"]
            vc = t["exit_reason"].value_counts().to_dict() if len(t) else {}
            ret = (t["exit_price"] / t["entry_price"] - 1).mean() if len(t) else float("nan")
            hold = t["hold_days"].mean() if len(t) else float("nan")
            print(f"{label:<6} {s:>6.1f} {len(t):>5} {vc.get('SL',0):>4} {vc.get('TP',0):>4} "
                  f"{vc.get('time',0):>5} {ret:>+9.2%} {hold:>7.1f}")
        del pan

    print("""
读法: TP/SL 锚在滑点后的成交价上 (portfolio.py `"tp": entry_px * (1+tp_eff)`) ⇒
这个旋钮**移动出场阈值**, 于是成交清单随之改变 —— 所以 (1) 的变化不是成本。
§4 明写 TP/SL 是 **policy**、滑点是 **cost**; 字面 (相对百分比) 满足, 但**可分离性**不满足。
⚠️ §5: 表里任何"加滑点更好"的格子**都不是建议** —— 系数未定 + 单窗择优 + (2) 会显示
   它往往只由**个位数笔交易**决定。""")


if __name__ == "__main__":
    main()
