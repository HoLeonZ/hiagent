"""尾部命中率的**基准率**检验: 当前最优的赢家是"选出来的"还是"碰上的"? (§13.133)

背景
----
§13.130/§13.132 已证明: 当前最优报告窗的头条由 **3 笔**撑着, 且去掉最好 3 笔后
15 个滚动窗无一跑赢市场。本节问的是**机制**: 那些"走到 +26.28% TP"的笔,
是信号选出来的, 还是本来就会发生?

三层基准率 (必须分开, 混在一起会得出相反结论)
---------------------------------------------
  L1 **全主板**: 同期所有 (股票, 日期) 的"期内 high 触及 +26.28%"的概率
  L2 **候选集**: v22 的信号集合 (4665 个) 上同一概率  ⇒ L2/L1 回答"**过滤器**有没有富集"
  L3 **实际成交**: 86 笔里真的走到 TP 的笔数        ⇒ 与按 hold_days 匹配的期望比

⚠️ 一个**必须避开的量纲陷阱** (本节第一版就栽在这里)
--------------------------------------------------
引擎的出场条件是「**期内 high 触及** entry × (1+tp_pct)」(running max of intraday high),
**不是**「h 日收盘 ≥ +26.28%」。第一版零假设用了 `LEAD(close,h)/close` ⇒
在 h=3 处把基准率算成 **0.433%** (正确值 **1.352%**) ⇒ 把观测/期望**夸成 31×** (真实 **10.6×**)。
> **同一个 +26% 的阈值, 挂在"收盘"上还是"盘中最高"上, 是两个不同的量。**

用法:
    python3 tools/tail_hit_base_rate.py
    python3 tools/tail_hit_base_rate.py --tp 0.2628 --window W2
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
from uptrend_pullback.regime import compute_regime  # noqa: E402
from uptrend_pullback.signals import (  # noqa: E402
    compute_indicators,
    select_entries_v33_long_mirror,
)
from uptrend_pullback.universe import load_universe  # noqa: E402

MAXH = 24


def _touch_rate(con, h: int, keys: pd.DataFrame | None = None) -> float:
    """P(期内 high 触及 open×(1+tp) | h 日内) —— 与引擎出场条件同口径。"""
    q = con.execute(f"""
      WITH x AS (SELECT thscode, date, open,
                        MAX(high) OVER (PARTITION BY thscode ORDER BY date
                                        ROWS BETWEEN 1 FOLLOWING AND {h} FOLLOWING) mx
                 FROM v_daily WHERE date BETWEEN ? AND ?)
      SELECT thscode, date, mx/open-1 AS r FROM x WHERE mx IS NOT NULL AND open>0
    """, [W0, W1]).df()
    if keys is None:
        return float((q["r"] >= TP).mean())
    q["date"] = pd.to_datetime(q["date"])
    k = keys.copy()
    k["date"] = pd.to_datetime(k["date"])
    m = k.merge(q, on=["date", "thscode"], how="left")
    return float((m["r"] >= TP).mean())


def main() -> None:
    global W0, W1, TP
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", default="v33_long_reverse_v22")
    ap.add_argument("--w0", default="2024-10-08")
    ap.add_argument("--w1", default="2026-09-18")
    ap.add_argument("--tp", type=float, default=0.2628)
    args = ap.parse_args()
    W0, W1, TP = args.w0, args.w1, args.tp

    p = get_preset(args.preset)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=W0))
    pan = compute_indicators(load_panel(DB_PATH, W0, W1, universe=uni))
    trades = run_backtest(dict(p), W0, W1, DB_PATH, panel_ind=pan)["trades"]

    reg = compute_regime(pan, **p["regime"]) if p.get("regime") else None
    kw = {k: v for k, v in p["signal"].items() if k != "entry_mode"}
    ent = select_entries_v33_long_mirror(pan, start_date=W0, end_date=W1,
                                         regime_df=reg, **kw)

    tp_hits = int((trades["exit_reason"] == "TP").sum())
    # 按每笔**自己的** hold_days 匹配的期望笔数
    rates = {h: _touch_rate(con, h) for h in range(1, MAXH + 1)}
    exp = float(sum(rates.get(min(int(h), MAXH), np.nan) for h in trades["hold_days"]))
    tp_rate = float((trades["exit_reason"] == "TP").mean())
    win, los = trades[trades.net_pnl > 0], trades[trades.net_pnl <= 0]

    print(f"preset={args.preset}  窗口 {W0}..{W1}  TP={TP:.4f}")
    print(f"信号 {len(ent)} 个 → 成交 {len(trades)} 笔;  出场=TP 的 {tp_hits} 笔\n")
    print("=== 尾部命中率的三层基准率 (h = 3 为例) ===")
    u3, c3 = _touch_rate(con, 3), _touch_rate(con, 3, ent)
    print(f"  L1 全主板  {u3:.3%}")
    print(f"  L2 候选集  {c3:.3%}    ⇒ 过滤器的富集 = {c3/u3:.1f}×  (≈1 ⇒ 过滤器**不富集尾部**)")
    print(f"  L3 实际成交 走到 TP 的 {tp_hits}/{len(trades)} = {tp_hits/len(trades):.1%}")
    print(f"\n  按各笔自身 hold_days 匹配的**期望** TP 笔数 = **{exp:.2f} 笔**")
    print(f"  观测/期望 = **{tp_hits/exp:.1f}×**  ⇒ 选择(容量+排序)**确实富集尾部**")

    print("\n=== 但那为什么还是亏的: 按出场原因分解 ===")
    print(f"{'原因':<6} {'笔数':>4} {'Σnet_pnl':>14} {'平均净收益':>10}")
    for k, r in trades.groupby("exit_reason").agg(
            n=("net_pnl", "size"), s=("net_pnl", "sum"),
            m=("net_return", "mean")).iterrows():
        print(f"{k:<6} {int(r['n']):>4} {r['s']:>+14,.0f} {r['m']:>+10.2%}")

    avg_w, avg_l = float(win.net_return.mean()), float(los.net_return.mean())
    be = abs(avg_l) / (avg_w + abs(avg_l))
    print(f"\n  平均赢 {avg_w:+.2%}  平均亏 {avg_l:+.2%}")
    print(f"  **盈亏平衡命中率 = {be:.1%}** (拿这个赔率要多少胜率才不亏)")
    print(f"  **实际命中率 = {tp_rate:.1%}**  ⇒ 只高出 "
          f"{(tp_rate-be)*100:.1f} 个百分点")
    print(f"  总费用 = {trades['fees'].sum()/1_000_000:.2%} 于初始本金")
    print("""
读法: **均值口径与尾部口径会给出相反的结论, 两个都对。**
  * §6.3/§13.123 量的是**均值** ⇒ "无可测 alpha" (正确);
  * 本节量的是**尾部** ⇒ 选择把 +26% 触达率抬高约一个数量级 (也正确)。
  ⇒ 二者调和的唯一方式: **排序挑的是"分散度", 而策略的赔付是不对称的
    (止损 2.1% / 目标 26.3%)** ⇒ 命中率被抬高的同时, 止损被触及得更频繁
    (还有 §4 的**跳空穿价**把它从 −2.1% 放大到 −4.04%) ⇒ **均值上两者几乎抵消**
    ⇒ 实现结果由**方差**主导 ⇒ 这正是 §13.130–132 看到的"由 3 笔 + 一个边界决定"。
⚠️ §5: 这是**描述**; 我已在同一批 86 笔上看了多个统计量, 属多重比较。
⚠️ 未做: 逐笔的"可买性"过滤 (基准率用的是全部 (股票,日期), 含开盘涨停等不可买的)。""")


W0 = W1 = ""
TP = 0.2628

if __name__ == "__main__":
    main()
