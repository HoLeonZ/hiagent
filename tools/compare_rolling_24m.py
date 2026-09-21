"""对比两个 preset 在 24 个月滚动窗口上的表现。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if len(sys.argv) != 3:
    print("用法: python3 tools/compare_rolling_24m.py <csv1> <csv2>")
    sys.exit(1)

df1 = pd.read_csv(sys.argv[1])
df2 = pd.read_csv(sys.argv[2])
df = pd.concat([df1, df2], ignore_index=True)

# 按窗口对齐
pivot = df.pivot(index="start", columns="preset", values=[
    "trades_count", "win_rate", "total_yield",
    "cagr", "sharpe", "max_dd",
    "tp_count", "sl_count", "time_count",
])
# 重新索引按 start 排序
pivot = pivot.sort_index()
print("=== 12 个 2 月窗对比 ===\n")
print(df[["preset", "start", "end", "trades_count", "win_rate",
          "total_yield", "cagr", "sharpe", "max_dd",
          "tp_count", "sl_count", "time_count"]].to_string(index=False))
print()

print("=== 汇总 (按 preset) ===")
for preset, sub in df.groupby("preset"):
    ty = sub["total_yield"]
    cagr = sub["cagr"]
    wr = sub["win_rate"]
    n = sub["trades_count"]
    print(f"\n[{preset}]")
    print(f"  窗数 {len(sub)} | 总交易 {int(n.sum())} | 平均每窗交易 {n.mean():.1f}")
    print(f"  收益: 盈利窗 {int((ty > 0).sum())}/{len(sub)} | "
          f"中位 {ty.median()*100:+.2f}% | 均值 {ty.mean()*100:+.2f}% | "
          f"最差 {ty.min()*100:+.2f}% | 最好 {ty.max()*100:+.2f}%")
    print(f"  CAGR(年化,2 月窗放大): 中位 {cagr.median()*100:+.2f}% | "
          f"最差 {cagr.min()*100:+.2f}% | 最好 {cagr.max()*100:+.2f}%")
    print(f"  胜率: 均值 {wr.mean()*100:.1f}% | 最低 {wr.min()*100:.1f}% | 最高 {wr.max()*100:.1f}%")
    print(f"  MaxDD: 均值 {sub['max_dd'].mean()*100:.2f}% | 最深 {sub['max_dd'].max()*100:.2f}%")
    print(f"  退出原因分布: TP={int(sub['tp_count'].sum())} "
          f"SL={int(sub['sl_count'].sum())} time={int(sub['time_count'].sum())} "
          f"({int(sub['tp_count'].sum()/sub['trades_count'].sum()*100)}% TP)")

# 跨 preset 的对比:相同样本窗下谁更好
print("\n=== 同窗 head-to-head (按 total_yield) ===")
common = df1.merge(df2, on=["start", "end"], suffixes=("_a", "_b"))
common["winner"] = common.apply(
    lambda r: "tp6" if r["total_yield_a"] > r["total_yield_b"] else "tp2",
    axis=1,
)
print(f"tp6 win windows: {(common.winner=='tp6').sum()} / {len(common)}")
print(f"tp2 win windows: {(common.winner=='tp2').sum()} / {len(common)}")
print()
print("各窗 winner:")
for _, r in common.iterrows():
    print(f"  {r['start']}..{r['end']}: "
          f"tp6={r['total_yield_a']*100:+.2f}%  tp2={r['total_yield_b']*100:+.2f}%  "
          f"→ winner={r['winner']}")

# 12 窗串联复利 (假设 1M 起,每窗独立复利)
print("\n=== 12 窗独立复利串联(假设每窗 1M 起) ===")
for preset, sub in df.groupby("preset"):
    sub = sub.sort_values("start").reset_index(drop=True)
    capital = 1.0
    for _, r in sub.iterrows():
        capital *= (1 + r["total_yield"])
    total = (capital - 1) * 100
    print(f"  [{preset}] 12 窗串联: {capital:.2f}x (累计 {total:+.2f}%)")

out_csv = Path(sys.argv[1]).parent / "rolling_24m_compare.csv"
df.to_csv(out_csv, index=False)
print(f"\n保存: {out_csv}")
