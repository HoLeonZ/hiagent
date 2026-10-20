"""§5 Attribution Mandate —— 基准(benchmark)与超额收益。

CLAUDE.md §5 原文:

    **Attribution Mandate:** Headline returns MUST be reported alongside
    benchmark-relative excess return (index or style basket). Pure style-beta
    replication (e.g. size/momentum factor exposure) MUST NOT be presented
    as alpha.

本节是"补空缺":本仓库此前只报裸收益。

**与 `dna_stats/attribution.py` 的关系(2026-10-18 更正,附六十二)**:那份模块
(`attribute()`,含 beta、可注入基准序列)是同一批工作里的**另一支**,已经实现、已有测试
(`tests/test_attribution.py`),但**没有任何生产代码调用它** —— 它在等**指数序列**
(`hithink-finance index history`),而那台数据本机没有。
本模块负责的是**已接线**的那一支:风格篮子基准 + 引擎逐次发布。
两支合起来才是 §5 的完整形态;此前本文件写的是"本仓库完全没有实现这一条",
那句话**在同一提交里就已经不成立**(附六十二 更正)。

## 基准的选择(已声明,可替换)

本机活库中**没有指数数据**(`v_daily` 只有 SZ/SH/BJ 个股,无 000300 一类的指数代码),
故 `index` 这一支暂时不可用。§5 允许 `index **or style basket**`,于是取:

    benchmark = 该窗口 **PIT 宇宙的等权买入持有**(不调仓)总收益

理由:这些策略的候选池就是"全部主板 A 股",等权买入持有正是它们暴露的
**规模/等权 beta**;拿它做基准,恰好回答 §5 关心的那个问题 ——
"这份收益里,有多少只是'拿了那个池子'?"

将来若有指数数据,新增一个 `index` 实现并让调用方声明即可 —— 产物里带
`benchmark_kind`,读者永远知道这个数字**是什么**。

## 价格域(§3)

用**复权**价(`close` 列;面板的 `close` 即复权域)。理由:策略侧的收益是**总收益**
(分红作为现金流入账,见各引擎的公司行为处理),故基准也必须是总收益 ——
用原始价会把分红漏掉,等于给策略送一个虚假的超额。§3 的"raw 用于执行价"
说的是**成交价**,不是收益序列;这里要的是收益序列。
"""
from __future__ import annotations

import pandas as pd

BENCHMARK_KIND_EQUAL_WEIGHT = "equal_weight_pit_universe_buy_and_hold"


def equal_weight_basket_return(panel: pd.DataFrame) -> tuple[float | None, int]:
    """等权买入持有(不调仓)的总收益,返回 `(return | None, 纳入的标的数)`。

    **无成员时返回 `None`,不是 `0.0`**(2026-10-16 自查修正):若返回 0.0,
    `excess_return = 总收益 - 0.0 = 总收益`,产物读起来就是"基准什么都没涨" ——
    与"基准确实是 0%"不可区分。本仓库对"算不出"的口径一贯是 `None`
    (见 `profit_factor` 的处理),这里照办。

    每只标的取窗口内**第一根与最后一根**可用 bar 的复权价之比;bar 数 < 2 的
    标的不纳入(窗口内无法构成一次买入持有),其数量由第二个返回值如实带出 ——
    静默把"没有行情的标的"算成 0 收益也是一种沉默的错。

    不做调仓:等权买入持有 = 各标的收益的**等权平均**(不是几何链式),
    这也是"等权指数"的常见口径,且与本仓库的确定性要求一致(无路径依赖)。
    """
    if panel.empty:
        return None, 0

    per_name: list[float] = []
    for _, sub in panel.groupby("thscode", sort=False):
        series = sub.sort_values("date")["close"].to_numpy(dtype=float)
        series = series[~pd.isna(series)]
        if series.size < 2 or series[0] <= 0:
            continue
        per_name.append(float(series[-1] / series[0] - 1.0))

    if not per_name:
        return None, 0
    return float(sum(per_name) / len(per_name)), len(per_name)


__all__ = ["BENCHMARK_KIND_EQUAL_WEIGHT", "equal_weight_basket_return"]
