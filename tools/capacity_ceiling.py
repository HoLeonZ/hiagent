"""当前最优的**容量上限**分布: 上限(元) = `0.1 × 当日成交额` (§13.146)。

问的是什么
----------
§4 的量能上限 (`Max_Fill_Qty = Bar_Volume × 10%`) 是本族**唯一的流动性约束**。
§7 把"容量"列为没做的可行性检验之一; §13.91 写过"容量不是瓶颈"却**没有数**。
本工具给出: ①上限**当下是否咬合** ②**它什么时候会咬** (= 该笔的容量上限)。

⚠️ 判据容易写反 (本工具第一版就写反了)
------------------------------------
* **binding ⇔ `size == cap_sh`** —— 即"应有股数超过上限, 于是被**压到**上限";
* ⚠️ 写成 `size <= cap_sh` 并叫它"被截断"是**反的**: 那只说明"订单装得下"。
  第一版因此打出 **100% 咬合**, 还附了 "size/cap 中位 0.01" —— 而后者在数量级上不可能
  (0.01 × 上限却持有 ~100 万名义金额)。
  > **一个看着极端的读数, 先被数量级检查拦住 —— 不要先解释它。**

用法:
    python3 tools/capacity_ceiling.py
    python3 tools/capacity_ceiling.py --preset v33_long_reverse_v21 --participation 0.10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

CAPITAL = 1_000_000.0
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W2", "2024-10-08", "2026-09-18"),      # 末日按 §13.8 截到干净日
    ("IND", "2022-10-03", "2024-09-30"),
    ("IS1", "2021-10-01", "2022-09-30"),
    ("IS2", "2023-10-01", "2024-09-30"),
    ("EXTRA", "2017-10-02", "2019-09-30"),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--participation", type=float, default=None,
                    help="缺省取 preset 的 max_volume_participation (§4 默认 0.10)")
    args = ap.parse_args()

    p = get_preset(args.preset)
    part = float(args.participation if args.participation is not None
                 else p.get("max_volume_participation", 0.10))
    print(f"preset={args.preset}  上限比例 = {part:.1%}  (§4: Max_Fill_Qty = Bar_Volume × 比例)")
    print(f"假设资金 ¥{CAPITAL:,.0f} (与回测一致)\n")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    print(f"{'窗口':<6} {'n':>4} {'**咬合笔数**':>10} {'咬合率':>8} {'容量上限 中位':>16}")
    caps = []
    for label, w0, w1 in WINDOWS:
        uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        t = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)["trades"].copy()
        del pan
        if len(t) == 0:
            print(f"{label:<6} 无成交"); continue
        t["entry_date"] = pd.to_datetime(t["entry_date"])
        q = con.execute("SELECT thscode, date, volume FROM raw_kline_daily "
                        "WHERE date BETWEEN ? AND ?", [w0, w1]).df()
        q["date"] = pd.to_datetime(q["date"])
        m = t.merge(q, left_on=["entry_date", "thscode"],
                    right_on=["date", "thscode"], how="left").dropna(subset=["volume"])
        m["cap_sh"] = (m["volume"] * part // 100 * 100)
        m["binding"] = (m["size"] == m["cap_sh"])          # ← 正确的 binding 判据
        m["cap_yuan"] = m["cap_sh"] * m["entry_price"]
        caps.append(m["cap_yuan"].to_numpy())
        print(f"{label:<6} {len(m):>4} {int(m['binding'].sum()):>10} "
              f"{m['binding'].mean():>8.1%} {m['cap_yuan'].median():>16,.0f}")

    if caps:
        c = np.concatenate(caps)
        print(f"\n=== 容量上限分布 (n={len(c)}; = {part:.0%} × 当日成交额) ===")
        for q_ in (1, 5, 10, 25, 50, 75, 90, 99):
            print(f"  p{q_:<3} ¥{np.percentile(c, q_):>14,.0f}")
        print(f"  最小 ¥{c.min():>13,.0f}   最大 ¥{c.max():>13,.0f}")
        print(f"\n⇒ **保守容量 ≈ ¥{np.percentile(c,10)/1e6:.1f}M (p10)** · 中位 **¥{np.percentile(c,50)/1e6:.1f}M**")
    print(f"""
读法: 当前资金 ¥{CAPITAL:,.0f} 下咬合率极低 ⇒ **"容量不是瓶颈"这句话只对当前规模成立**。
      资金放大到 ~10 倍就会开始截断**最不流动的那批票** (那不是随机截断)。
⚠️ `比例 × 当日成交额` 是 §4 的**上限公式**, 不是实测成交量; 真实可成交量还受涨跌停/停牌约束 (未做)。""")


if __name__ == "__main__":
    main()
