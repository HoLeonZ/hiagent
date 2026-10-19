"""附一百零一 —— 复权视图在**因子表覆盖范围之外**会**静默退回原始价**。

## 缺陷(实测,在线库)

`v_daily_hfq` / `v_daily_qfq` 的定义是(从 `duckdb_views()` 读出):

```sql
SELECT d.<ohlc> * COALESCE(f.backward_factor, 1)  ...
FROM raw_kline_daily d
LEFT JOIN calc_adjust_factor_daily f USING (thscode, date)
```

`LEFT JOIN … COALESCE(factor, 1)` 把"**这个日期没有因子行**"变成了"**因子 = 1**",
而 1 就是**原始价**。实测:

| | |
|---|---|
| `calc_adjust_factor_daily` 覆盖 | 2016-09-02 … **2026-09-18** |
| `v_daily` 覆盖 | 2016-09-02 … **2026-09-30** |
| 落在因子覆盖之外 ⇒ **退回原始价**的行 | **38,870 / 10,364,755 = 0.38%** |
| 落在哪些日期 | **2026-09-21(周一)…09-30,共 7 个交易日**(09-19/20 是周末,库里无 K 线行) |

量级:以 `600000.SH` 为例,该处的后复权因子是 **1.876** ⇒ 这 7 个交易日的"复权价"
比正确值**低约 46%**。这一段是 §3 明令禁止的**跨价域混用**:序列在 09-18/09-21 之间
**跳变**,而任何跨过该边界的指标(MA/MACD/波动率)都会把两个价域混在一起算。

## 当前影响面:**已发布窗口一个都没踩到**(实测)

| 脚本 | 窗口终点 | 是否触及 |
|---|---|---|
| `uptrend_pullback/sweep_v33_long*.py` | 2026-09-16 | 否 |
| `short_reversal/walkforward.py` | 2026-09-18(= 因子最后一日) | 否 |
| `short_reversal/grid_runner.py` | 2026-09-12 | 否 |
| `chase_up/sweep.py` | 2026-09-19(**周六**) | 否 |

⇒ 这是**数据档期滞后**(K 线比因子表新),不是窗口内部的空洞。**但任何人跑一个
终点在 2026-09-18 之后的窗口都会中**,而且**不会有任何报错**。

## 为什么本仓库改不了它

调整视图(`v_daily_hfq`/`v_daily_qfq`)定义在**上游**,不在本仓库的 `sql/` 里 ——
仓库里那份 `sql/migrate_v_daily_dual.sql` 只定义**建在它们之上**的 `v_daily_dual`。
故本轮**不改数据**,只做两件事:

1. **钉住形状**:任何缺因子的行都必须**严格晚于**因子表最大日期(尾部滞后)。
   **中间出现空洞 ⇒ 红** —— 那才是灾难性的形态(一段历史没有复权),而尾部滞后只是档期问题。
2. **登记档期滞后的上限**:因子表最后日期不得比 K 线最后日期落后超过
   `MAX_REGISTERED_LAG_DAYS` 天。当前落后 12 天;**超过上限 ⇒ 红**,提醒去刷新因子表。

## 正确的修法(登记,不在本轮做)

上游视图应把 `COALESCE(f, 1)` 改成**取该标的最后一个已知因子**(前向填充),
即 `LAST_VALUE(factor IGNORE NULLS) OVER (PARTITION BY thscode ORDER BY date)`;
或者让消费者在窗口越过因子覆盖时 **fail-fast**(§0),而不是静默拿到原始价。
两条都要动仓库之外的东西(上游视图 / 四个 loader),故登记而非就地改。
"""
from __future__ import annotations

import duckdb
import pytest

from hiagent_config import DB_PATH
from tests.conftest import require_market_db

#: 因子表允许落后 K 线表的天数(自然日)。当前实测落后 12 天。
#: 超过它 ⇒ 红:提醒去刷新因子表,而不是让"退回原始价"的窗口悄悄变大。
MAX_REGISTERED_LAG_DAYS = 21


def _con():
    return duckdb.connect(str(DB_PATH), read_only=True)


@pytest.mark.slow
def test_adjusted_views_are_never_mixed_with_raw_inside_their_range() -> None:
    """§3:**缺因子的行只能是尾部滞后,不许在中间出现空洞**。

    (尾部滞后是档期问题;中间空洞意味着一整段历史没有复权 —— 那才是灾难形态。)
    """
    require_market_db()
    con = _con()
    try:
        factor_max = con.execute("SELECT max(date) FROM calc_adjust_factor_daily").fetchone()[0]
        holes = con.execute(
            """
            WITH gap AS (
              SELECT vv.thscode, vv.date
              FROM v_daily_hfq vv
              LEFT JOIN calc_adjust_factor_daily f
                ON vv.thscode = f.thscode AND vv.date = f.date
              WHERE f.thscode IS NULL
            )
            SELECT count(*) FROM gap WHERE date <= ?
            """,
            [factor_max],
        ).fetchone()[0]
    finally:
        con.close()
    assert holes == 0, (
        f"§3 VIOLATION: 在因子表覆盖范围**之内**(≤ {factor_max})有 {holes} 行拿不到因子 ⇒ "
        "视图把它们当成了原始价 —— 那是**中间空洞**,不是尾部滞后。"
    )


@pytest.mark.slow
def test_the_factor_table_is_not_stale_beyond_the_registered_lag() -> None:
    """档期滞后必须**有上界**:因子表不许比 K 线表落后太多天。

    (目前落后 12 天是数据档期问题;这条把"再落后下去"变成可见的事。)
    """
    require_market_db()
    con = _con()
    try:
        kline_max = con.execute("SELECT max(date) FROM v_daily").fetchone()[0]
        factor_max = con.execute("SELECT max(date) FROM calc_adjust_factor_daily").fetchone()[0]
    finally:
        con.close()
    lag = (kline_max - factor_max).days
    assert lag <= MAX_REGISTERED_LAG_DAYS, (
        f"§3: 因子表最后日期 {factor_max} 比 K 线表最后日期 {kline_max} 落后 {lag} 天,"
        f"超过登记上限 {MAX_REGISTERED_LAG_DAYS} 天 —— 这期间所有日期都会**静默退回原始价**。"
        "请刷新 calc_adjust_factor_daily,或按本文件 docstring 的「正确修法」改成前向填充。"
    )


@pytest.mark.slow
def test_the_gap_is_a_pure_tail() -> None:
    """把缺口**量化**出来并钉住它的形状:只允许出现在因子表最后日期**之后**。"""
    require_market_db()
    con = _con()
    try:
        factor_max = con.execute("SELECT max(date) FROM calc_adjust_factor_daily").fetchone()[0]
        total, after = con.execute(
            """
            WITH gap AS (
              SELECT vv.date FROM v_daily_hfq vv
              LEFT JOIN calc_adjust_factor_daily f
                ON vv.thscode = f.thscode AND vv.date = f.date
              WHERE f.thscode IS NULL
            )
            SELECT count(*), sum(CASE WHEN date > ? THEN 1 ELSE 0 END) FROM gap
            """,
            [factor_max],
        ).fetchone()
    finally:
        con.close()
    assert total == after, f"缺口不全是尾部:{total} 行缺因子,其中只有 {after} 行晚于 {factor_max}"


@pytest.mark.slow
def test_the_views_really_apply_the_factor() -> None:
    """**阳性对照**:视图确实做了乘法 —— 否则上面几条"没有缺口"会退化成"视图是原始价"。"""
    require_market_db()
    con = _con()
    try:
        # 取一只有分红、且日期在因子覆盖内的标的:复权价必须 ≠ 原始价
        row = con.execute(
            """
            SELECT count(*) FROM v_daily_hfq v
            JOIN v_daily d ON v.thscode = d.thscode AND v.date = d.date
            WHERE abs(v.close - d.close) > 1e-6
            """
        ).fetchone()[0]
    finally:
        con.close()
    assert row > 1_000_000, (
        f"只有 {row} 行复权价与原始价不同 —— 视图可能根本没做乘法,"
        "那上面几条「无缺口」就变成了空转"
    )
