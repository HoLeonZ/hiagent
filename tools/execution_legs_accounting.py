"""执行链**两条腿**的统一记账 (§13.139): 都换成**同一路径、同样股数下的「元」**。

为什么需要
----------
§13.137 用"每笔百分比"比两条腿 —— 但两者的**分母不同**:
进场腿是"相对信号日收盘", 出场腿是"相对账户价值" ⇒ **不能直接相减**。
本节把两条腿都算成**元**:

   ① 进场腿 (省下)   = Σ (信号日收盘 − 实际成交价) × 股数      ← 正 = 买得便宜 = 省下
   ② 出场腿 (多付)   = Σ (设计止损位 − 实际成交价) × 股数      ← 正 = 跳空穿价多亏 (只含 SL 跳空笔)
   ③ 费用            = Σ fees

⚠️ **口径 (必须一起读)**
* 三者都在**同一条已实现路径**上、**股数固定** ⇒ 是**价格效应归因**, **不是重跑模拟**;
* 它也**不是**"改了会怎样"的预测: 真换入场价会改**股数** (预算/价格) 与 **TP/SL 锚点** (§13.129)
  ⇒ 那是另一个实验。
* 两侧都用 **raw 价** (§3): 行情取 `raw_kline_daily`, 信号日用 `LAG(close)` 自建
  (不用 `prev_close` 列 —— 那列 100% NULL, §13.106 的坑)。

用法:
    python3 tools/execution_legs_accounting.py
    python3 tools/execution_legs_accounting.py --preset v33_long_reverse_v21
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

from uptrend_pullback.backtest import run_backtest  # noqa: E402
from uptrend_pullback.data import load_panel  # noqa: E402
from uptrend_pullback.presets import get_preset  # noqa: E402
from uptrend_pullback.signals import compute_indicators  # noqa: E402
from uptrend_pullback.universe import load_universe  # noqa: E402

INITIAL = 1_000_000.0
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
    args = ap.parse_args()

    p = get_preset(args.preset)
    tp_pct, sl_pct = float(p["tp_pct"]), float(p["sl_pct"])
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print(f"preset={args.preset}  sl_pct={sl_pct:.3%} tp_pct={tp_pct:.3%}")
    print("口径: 同一路径 + 股数固定 ⇒ **价格效应归因**, 不是重跑模拟\n")
    print(f"{'窗口':<6} {'净利':>13} {'①进场省下':>12} {'②出场多付':>12} "
          f"{'③费用':>10} {'执行净':>12}")
    for label, w0, w1 in WINDOWS:
        uni = set(load_universe(p["universe"], DB_PATH, asof_date=w0))
        pan = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
        t = run_backtest(dict(p), w0, w1, DB_PATH, panel_ind=pan)["trades"].copy()
        del pan
        if len(t) == 0:
            print(f"{label:<6} 无成交"); continue
        t["entry_date"] = pd.to_datetime(t["entry_date"])
        q = con.execute("""
          WITH r AS (SELECT thscode, date, close,
                            LAG(close) OVER (PARTITION BY thscode ORDER BY date) pc
                     FROM raw_kline_daily WHERE date BETWEEN ?::DATE - 90 AND ?)
          SELECT thscode, date, pc FROM r""", [w0, w1]).df()
        q["date"] = pd.to_datetime(q["date"])
        m = t.merge(q, left_on=["entry_date", "thscode"],
                    right_on=["date", "thscode"], how="left").dropna(subset=["pc"])
        entry_save = float(((m["pc"] - m["entry_price"]) * m["size"]).sum())

        sl = t[t.exit_reason == "SL"].copy()
        sl_des = sl["entry_price"] * (1 - sl_pct)
        g = sl[sl["exit_price"] < sl_des - 1e-9]
        exit_cost = float(((sl_des.loc[g.index] - g["exit_price"]) * g["size"]).sum())

        fees = float(t["fees"].sum())
        net = float(t["net_pnl"].sum())
        print(f"{label:<6} {net:>+13,.0f} {entry_save:>+12,.0f} {exit_cost:>12,.0f} "
              f"{fees:>10,.0f} {entry_save - exit_cost - fees:>+12,.0f}")
    print("""
读法: ① 的作用是**省下**, ②③ 是**多付** ⇒ 三者可直接相减 (单位一致)。
⚠️ 它**不是**"改了会怎样": 真换入场价会改股数与 TP/SL 锚点 (§13.129)。
⚠️ 两侧都用 raw 价; 信号日由 LAG(close) 自建 (§13.106 的 prev_close 列 100% NULL)。""")


if __name__ == "__main__":
    main()
