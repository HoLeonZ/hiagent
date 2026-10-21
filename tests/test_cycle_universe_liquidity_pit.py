"""§1/§3: cycle_price_action 的**流动性筛选**必须只用 `asof_date` 及之前的数据。

## 2026-10-19 (§13.27) 的发现
`cycle_price_action/data_feed.py::load_universe_data` 的注释写着
"Round 14 (2026-09-28, CLAUDE.md §3): **PIT-compliant** universe at `asof_date`"。
**PIT 只覆盖了"是否仍在市"这一半**:

```python
listed = {r[0] for r in listed_rows if r[1] >= ref_end}   # ← 这一半是 as-of 的
...
liquidity_codes = con.execute(
    "SELECT thscode, date, amount FROM v_daily WHERE thscode IN (...) "
    "ORDER BY thscode, date")                              # ← **没有任何日期边界**
liquid = apply_liquidity_filter(liquidity_codes, min_avg_turnover=5e7, min_history_days=60)
```
而 `apply_liquidity_filter` 是:
```python
avg_turn = df.groupby("thscode")["amount"].mean()          # 全段历史的**全局均值**
```
⇒ **整个回测窗口的股票池,是用包括窗口之后在内的全部历史选出来的。**

两点与文档不符:
1. `tests/test_cycle_survivorship_bias.py` 把它描述为 "Liquidity filter (**60d rolling
   mean** of amount)" —— 实现既不是 rolling, 也不是 60 天, 是**全历史全局均值**;
2. 模块自称 PIT-compliant —— 流动性这一半**不是**。

**量化** (主板基础池 3,196 只, 窗口 2024-10-08..2026-09-29):
| 口径 | 通过流动性筛 |
|---|---|
| 当前实现 (全历史均值) | **2,990** |
| §1 要求的 as-of `start` | 2,717 |
| 窗口内 | 3,079 |
⇒ **差异 281 只 (9.4%)**, 其中 **277 只**是"当前实现纳入、as-of 会排除" —— 即
**这 277 只用窗口之后的数据换来了自己的入选资格**。

## 本文件的作用 (§6: 必须能失败)
用**合成临时库**(不依赖真数据, 毫秒级)把 PIT 语义钉成行为不变量:
一个在 `asof` 之前成交额**不达标**、`asof` 之后才变大的票, **不得**入选。

* 第 1 条是**正向对照** —— 两段都达标的票必须入选。它证明本文件的机制不空转
  (若哪天 `load_universe_data` 干脆返回空集, 它会先红)。
* 第 2 条是**真判据** —— ✅ **2026-10-20 合并 main 后已转为 PASS**: main 的
  `data_feed.py` 把流动性查询按 `asof` 收口(`AND date <= asof`), 本判据的实现
  因此落地, 原先的 `xfail(strict=True)` 已按它自己的要求**删除**。
  ⚠️ 这同时是一次**结果漂移**(§13.27 → §13.214 登记): 该收口让"用窗口之后的数据
  换来入选资格"的票退出 universe(实测 **2,990 → 2,717**), 会改变含该形态标的的
  窗口的交易清单。
"""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action.data_feed import load_universe_data

START, END = date(2025, 1, 2), date(2025, 6, 30)
FLOOR = 5e7


def _low_amount_db(tmp_path):
    """三个票:
    * `600000.SH` 前后都达标 → 必须入选 (**正向对照**)
    * `600003.SH` **asof 前不达标、asof 后才达标** → 真实 PIT 下**必须排除**
      (但它全历史均值达标 ⇒ 当前实现会错误地放它进来)
    * `600004.SH` 全程不达标 → 必须排除 (证明筛选本身还在生效)
    """
    db = tmp_path / "liquidity_pit.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE, open DOUBLE, high DOUBLE,"
        " low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE)"
    )
    pre = pd.date_range("2024-06-03", "2024-12-31", freq="B")   # asof 之前 ~150 BD
    post = pd.date_range("2025-01-02", "2025-06-30", freq="B")  # 窗口内 ~128 BD
    rows = []
    def add(code, dates, amount):
        for d in dates:
            rows.append((code, d.date(), 10.0, 10.5, 9.8, 10.2, 1e6, float(amount)))
    add("600000.SH", pre, 1e9)          # 前: 达标
    add("600000.SH", post, 1e9)         # 后: 达标
    add("600003.SH", pre, 1e6)          # 前: **不达标**
    add("600003.SH", post, 1e9)         # 后: 达标
    add("600004.SH", pre, 1e6)          # 全程不达标
    add("600004.SH", post, 1e6)
    con.executemany("INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    con.close()
    return db


def test_control_always_liquid_stock_is_included(tmp_path):
    """正向对照: 两段都达标的票必须入选 —— 证明本文件的机制不空转。"""
    universe = load_universe_data(
        str(_low_amount_db(tmp_path)), START, END, asof_date=START
    )
    assert "600000.SH" in universe, "全程达标的票被排除了 —— 筛选逻辑坏了, 不是 PIT 问题"


def test_never_liquid_stock_is_excluded(tmp_path):
    """对照: 全程不达标的票必须排除 —— 证明流动性筛选本身还在生效。"""
    universe = load_universe_data(
        str(_low_amount_db(tmp_path)), START, END, asof_date=START
    )
    assert "600004.SH" not in universe


def test_stock_liquid_only_after_asof_is_excluded(tmp_path):
    """真判据: `asof` 前不达标、之后才变大的票, **不得**入选。

    今天会失败 —— 因为 `apply_liquidity_filter` 取的是**全历史全局均值**,
    窗口内那段高成交额足以把它抬过门槛。
    """
    db = _low_amount_db(tmp_path)
    universe = load_universe_data(str(db), START, END, asof_date=START)
    assert "600003.SH" not in universe, (
        "该票在 asof(2025-01-02)之前成交额只有 ~1e6, 远低于门槛 5e7 —— 它之所以入选, "
        "靠的是**窗口之后**的数据。§1: 'The first line of any data access must "
        "physically slice the dataset: causal_data = data[data['timestamp'] <= as_of_time]'。"
    )
