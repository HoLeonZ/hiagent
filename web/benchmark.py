"""等权主板篮子的**日度净值序列**——本平台唯一诚实的基准。

## 为什么不是沪深300
本仓库的 DB **没有指数成分股，也没有指数日线序列**。摆在界面上的基准只能写
「等权主板篮子」，**不能假装是指数**——写错标签比没有基准更坏。

## 与 harness 的一致性
`tools/live/compare_ensembles.py::benchmark_cagr` 是**标量**版（同口径）。本模块是**序列**版。
两者漂移会让界面与门禁互相矛盾，故 `tests/test_web_benchmark.py` 有一条第耦合不变量
（序列末值的 CAGR 必须等于标量版）。

口径（与标量版逐条对齐）：
  - universe 用 **start 时点**的 PIT 成分（避免 post-hoc 选股）
  - 价格用**复权** `v_daily_hfq`
  - 每票以**它在窗口内的首个收盘**为基期
  - **只计窗口内 bar 数 >= 2 的票**——标量版用 `n >= 2` 过滤，这里若计入单 bar 票，
    会凭空引入一个 0 收益样本，两边就对不上了
  - 某票当日无 bar（停牌）时用它自己的上一根收盘**前向填充**（§1：绝不后向填充）
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

#: 基准口径的 universe 模式（与 harness 的 `benchmark_cagr` 一致）
BENCHMARK_MODE = "mainboard_only"

#: **界面必须如实显示这个标签**——它不是指数。
BENCHMARK_LABEL = "等权主板篮子（非指数）"


def benchmark_series(db_path: Path, start: str, end: str) -> list[dict]:
    """等权买入持有的日度净值，起点 1.0。返回 `[{date, value}, …]`。"""
    import duckdb

    from short_reversal.universe import load_universe_asof

    universe = set(load_universe_asof(BENCHMARK_MODE, start, db_path))
    if not universe:
        return []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, close FROM v_daily_hfq "
            "WHERE date BETWEEN ? AND ? ORDER BY thscode, date",
            [start, end],
        ).fetchdf()
    finally:
        con.close()
    df = df[df["thscode"].isin(universe)]
    if df.empty:
        return []
    counts = df.groupby("thscode")["close"].size()
    df = df[df["thscode"].isin(set(counts[counts >= 2].index))]
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="thscode", values="close").sort_index().ffill()
    base = wide.apply(lambda col: col.dropna().iloc[0] if col.notna().any() else None)
    # ⚠️ **必须与标量版一样排除基期为 0（或不可用）的票。**
    # 标量版的过滤条件是 `code in universe and n >= 2 and c0 and c0 > 0`——
    # 那句 `c0 > 0` 不是装饰：基期为 0 时 `wide / base` 会给出 `inf`，
    # 于是一列 inf 混进均值、整条序列变成 inf/NaN（`_finite_or_none` 会把它压成 None，
    # 前端净值图上出现空洞），而且**与标量版对不上，耦合测试会红**。
    # 两边的过滤条件必须逐条相同，否则"钉住漂移"这条测试钉的是两个不同的东西。
    base = base[(base.notna()) & (base > 0)]
    if base.empty:
        return []
    norm = wide.divide(base, axis=1)
    # 基期之前该票为 NaN，故 mean(skipna=True) 只在"当日已有观测"的票上取均值
    series = norm.mean(axis=1, skipna=True)
    return [{"date": d.strftime("%Y-%m-%d"), "value": float(v)}
            for d, v in series.items() if pd.notna(v)]


def benchmark_return(series: list[dict]) -> float | None:
    """窗口内的基准总收益（末值 - 1）。空序列返回 None（**不是 0**）。"""
    if not series:
        return None
    return series[-1]["value"] - 1.0
