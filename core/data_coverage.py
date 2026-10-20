"""复权因子表的**覆盖面**检查 —— §3/§0 判据单源。

## 为什么需要它

`v_daily_hfq` / `v_daily_qfq` 的定义是 `raw × COALESCE(factor, 1)`,而 `factor` 只覆盖到
`calc_adjust_factor_daily` 的最后一天。**超出之后 `COALESCE` 把「没有因子」当成了「因子 = 1」,
即原始价** ⇒ 复权序列在那里**跳变**,产生物理上不可能的日收益。

实测(2026-10-20 的在线库):因子表止于 **2026-09-18**,K 线到 **2026-09-30** ⇒
**38,870 行(0.38%)** 退回原始价;复权域里出现 **1,150 行单日收益 < −50%**
(而 A 股涨跌幅上限是 ±10%/±20%)。这些会**直接进入** `pct_chg` 类信号与下一根 bar 的盯市。

## 判据

**窗口终点越过因子表末端 ⇒ 抛错。** 宁可让调用方看到一条明确的错误(附上"因子表末到哪一天、
把窗口收到哪天、或先去刷新"),也不要给出一份**看起来正常**的报告(§0 Fail-Fast)。

## 为什么在 `core/` 而不是 `dna_data/`

`dna_data` 是数据访问层,但本仓库有一条**已登记缺口**:"四引擎尚未接 `dna_data`"
(附七十九 §5 ①)。让四个 loader 为了这一行的检查就跨上那一层,会**顺手改变那个已登记的事实**。
故判据放 `core/`(共享纯逻辑层),并且**用调用方已经打开的连接**(不新增 I/O 归属)——
本模块自己 `import duckdb` 都不需要。
"""
from __future__ import annotations

from datetime import date
from typing import Any

import duckdb

__all__ = ["factor_coverage_max", "assert_adjusted_coverage"]


def uncovered_trading_days(con: Any, start: date | str, end: date | str) -> list[date]:
    """窗口内**有行情、但完全没有复权因子**的交易日(升序)。

    "完全没有"= 该日期在 `calc_adjust_factor_daily` 里**一行都没有** ⇒ 那天**所有**标的的
    `COALESCE(factor, 1)` 都退化成 1(即原始价)。

    用的是**两个 `DISTINCT date` 的小集合相减**,不是逐行 JOIN —— 实测 9~148 ms,
    而逐行 JOIN 要在千万行上跑。
    """
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    try:
        rows = con.execute(
            """
            SELECT d.date FROM (SELECT DISTINCT date FROM v_daily WHERE date BETWEEN ? AND ?) d
            EXCEPT
            SELECT f.date FROM (SELECT DISTINCT date FROM calc_adjust_factor_daily
                                WHERE date BETWEEN ? AND ?) f
            ORDER BY 1
            """,
            [start, end, start, end],
        ).fetchall()
    except duckdb.CatalogException:
        return []          # 自建的小库没有因子表 ⇒ 那里也不存在"退回原始价"这回事
    return [r[0] for r in rows]


def assert_adjusted_coverage(
    con: Any, start: date | str, end: date | str, *, source: str
) -> None:
    """窗口内存在**未覆盖的交易日** ⇒ **fail-fast**。

    ⚠️ 判据是"窗口里有没有**有行情却没因子**的**交易日**",**不是**"`end` 是否晚于因子表末日":
    实测第一版按后者判,会把 `--end 2026-09-19`(**周六**,窗口内根本没有数据)误报成越界,
    一次红掉 6 个用例。**"日子越界"与"窗口里有未覆盖的交易日"是两回事。**

    交易日一个都没越界 ⇒ 静默返回;越界 ⇒ 抛错并**点名**那几天(便于立刻判断影响面)。
    """
    bad = uncovered_trading_days(con, start, end)
    if not bad:
        return
    shown = ", ".join(str(d) for d in bad[:7]) + ("…" if len(bad) > 7 else "")
    raise ValueError(
        f"§3/§0: {source} 的窗口 {start}..{end} 里有 {len(bad)} 个交易日**没有复权因子**"
        f"({shown})—— 那些天 `v_daily_hfq` / `v_daily_qfq` 会把因子当成 1(**即原始价**),"
        f"在复权序列里造出物理上不可能的日收益(实测复权域有单日 < −50% 的行)。"
        f"请把窗口收到 {bad[0]} 之前,或先刷新 `calc_adjust_factor_daily`。"
    )


__all__ = ["uncovered_trading_days", "assert_adjusted_coverage"]
