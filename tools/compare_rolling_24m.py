"""对比 N 个 preset 在 24 个月滚动窗口上的表现。

支持两种模式:
- 2-CSV (legacy): pairwise head-to-head, 与原脚本完全一致
- N-CSV (N >= 3): N-way 每窗排名 + winner + per-preset 复利串联

Usage:
    python3 tools/compare_rolling_24m.py <csv1> <csv2> [<csv3> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def compute_n_way_ranking(
    df: pd.DataFrame,
    presets: list[str],
) -> pd.DataFrame:
    """把长表 (start, end, preset, total_yield) 转成每窗一行宽表 + rank + winner。

    Args:
        df: 必须含 start/end/preset/total_yield 列
        presets: preset 名列表, 决定宽表列顺序

    Returns:
        列: [start, end, total_yield_<p1>, ..., total_yield_<pN>,
                   rank_<p1>, ..., rank_<pN>, winner]
        winner: 该窗 total_yield 最高的 preset (ties 取 presets 列表中先出现的)
    """
    pivot = df.pivot(index=["start", "end"], columns="preset", values="total_yield")
    pivot = pivot[presets]  # 固定列顺序
    pivot = pivot.reset_index(drop=True)

    # rank (1 = 最高 total_yield, dense 方式; ties 同 rank)
    rank_df = pivot.rank(axis=1, ascending=False, method="min").astype(int)
    rank_df.columns = [f"rank_{p}" for p in pivot.columns]
    rank_df = rank_df.reset_index(drop=True)

    # 拼宽表
    pivot.columns = [f"total_yield_{p}" for p in pivot.columns]
    out = pd.concat([pivot, rank_df], axis=1)
    # start/end 在 pivot 上丢了, 重新从原 df 取
    starts_ends = df[["start", "end"]].drop_duplicates().sort_values("start").reset_index(drop=True)
    out.insert(0, "start", starts_ends["start"].values)
    out.insert(1, "end", starts_ends["end"].values)

    # winner (ties 取 presets 中先出现的)
    pivot_arr = pivot.values
    winners = []
    for row in pivot_arr:
        best = max(row)
        # 找所有等于 best 的列, 取 preset 列表中 index 最小的
        tied = [i for i, v in enumerate(row) if v == best]
        winners.append(presets[min(tied)])
    out["winner"] = winners

    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 tools/compare_rolling_24m.py <csv1> <csv2> [<csv3> ...]")
        sys.exit(1)

    csv_paths = sys.argv[1:]
    dfs = [pd.read_csv(p) for p in csv_paths]
    df = pd.concat(dfs, ignore_index=True)
    presets_in_df = list(df["preset"].unique())

    if len(presets_in_df) == 2:
        # === 老路径: 2-CSV pairwise (保持现有输出格式) ===
        df1, df2 = dfs

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

    else:
        # === 新路径: N-way head-to-head (N >= 3) ===
        n_way = compute_n_way_ranking(df, presets_in_df)
        print("=== N-way 每窗排名 ===")
        print(n_way.to_string(index=False))
        print()

        # per-preset 汇总
        print("=== Per-preset 汇总 (12 窗独立复利) ===")
        for preset in presets_in_df:
            sub = df[df["preset"] == preset].sort_values("start").reset_index(drop=True)
            capital = 1.0
            for _, r in sub.iterrows():
                capital *= (1 + r["total_yield"])
            wins = (n_way["winner"] == preset).sum()
            ty = sub["total_yield"]
            cagr = sub["cagr"]
            print(
                f"[{preset}] 12 窗串联: {capital:.2f}x (累计 {(capital-1)*100:+.2f}%) | "
                f"赢窗 {wins}/12 | 收益中位 {ty.median()*100:+.2f}% 最差 {ty.min()*100:+.2f}% | "
                f"CAGR 中位 {cagr.median()*100:+.2f}% 最差 {cagr.min()*100:+.2f}%"
            )

        # per-preset 退出原因
        print("\n=== 退出原因分布 (per preset) ===")
        for preset in presets_in_df:
            sub = df[df["preset"] == preset]
            total = sub["trades_count"].sum()
            tp = int(sub["tp_count"].sum())
            sl = int(sub["sl_count"].sum())
            tm = int(sub["time_count"].sum())
            print(
                f"[{preset}] TP={tp} ({tp/total*100:.0f}%) "
                f"SL={sl} ({sl/total*100:.0f}%) time={tm} ({tm/total*100:.0f}%) "
                f"n={int(total)}"
            )

        # 输出 CSV
        out_csv = Path(csv_paths[0]).parent / "rolling_24m_n_way.csv"
        n_way.to_csv(out_csv, index=False)
        print(f"\n每窗排名表已保存: {out_csv}")

    # 总是输出合并 raw CSV
    combined_out = Path(csv_paths[0]).parent / "rolling_24m_all.csv"
    df.to_csv(combined_out, index=False)
    print(f"raw combined CSV 已保存: {combined_out}")
