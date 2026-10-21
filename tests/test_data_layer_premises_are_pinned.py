"""把**两条最承重的数据层前提**钉成可执行判据 (§13.109, 2026-10-19)。

> ### ✅ **2026-10-20 状态: 本文件已按数据刷新重钉** (见 `docs/strategy_mining_log.md` §13.214)
> 它按设计**先是红的** —— 那正是本次刷新的**预期反应**。
> * **§13 的缺陷已解除**: 因子与行情**同日**到 `2026-10-20`, 缺口 **0 行**
>   (`lag = 0`)。下面 §13 那段描述的是**历史**, 正文保留原样。
> * **§11 的前提逐字不变**: 退市票仍 **0** 只; 只有票池计数变了 (`5,565` → `5,577`)。

## 为什么值得钉
本册有两条结论**建在数据层的具体事实上**, 而它们的适用范围覆盖前面**全部章节**:
* **§13**: 复权因子表**落后**行情表 ⇒ `v_daily_hfq` 在最后几个交易日给出**假的暴跌**
  (全市场单日 −25%)。这条决定了"哪些窗口的数字不能引用"。**(2026-10-20 已解除)**
* **§11**: 本库是"**当存在者**"快照 —— **0 只**退市票。这条决定了"**全部**前 10 章结论"
  都带着存活偏差。

⚠️ **它们的状态取决于 DB 的当前内容** —— 一旦有人刷新/替换数据库, 这两条会**静默过期**,
而文档不会自己知道。§11 的处置是「文档化, 不加守卫」; 本节补上那条**被跳过**的守卫。

## ⚠️ 与"造一个永远红的测试"的区别 (§11 拒斥的那种)
§11 拒斥的形态是 `assert 存在退市票` —— 而本库恰好是 0 ⇒ **恒红**。
本文件的形态是 `assert 事实 == 记录值`:
* **今天绿** (已实测);
* **数据一变就红**, 且失败信息**指出该去改哪一节**。
⇒ 它不是一个"永远红的测试", 而是一条**自失效的前提钉桩** —— 与 §13.87 的
`PINNED_TRADING_DAYS` 同一形态 (那条也是"钉住事实, 变了就红并要求同步文档")。

## ⚠️ 红不等于缺陷
DB 被刷新是**好事** (因子补齐 ⇒ §13 的污染消失)。本条红的意思是:
**"§13 / §11 的结论所依据的事实变了 —— 去把它们更新, 或把它们撤回。"**
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ---- 记录值 (来源: 2026-10-20 实测, 见 §13.214) ----
# ⚠️ **2026-10-20 数据同步后重钉 (§13.214)**: §13 的"因子表落后"前提**已解除** ——
# 因子与行情**同日**到 `2026-10-20`, 缺口 **0 行**。
# ⇒ 本文件由"钉住一条**缺陷**"变成"钉住刷新后的**现状**";
# 同时历史起点前移 `2016-09-02` → `2016-10-20` (全量 `10y` 重建是**替换**不是追加),
# 票池 `5,565` → `5,577`。**§11 的前提 (`0` 只退市票) 逐字不变。**
PINNED = {
    "price_max": "2026-10-20",
    "factor_max": "2026-10-20",
    "factor_lag_calendar_days": 0,
    "missing_factor_rows": 0,
    "raw_kline_rows": 10_343_320,
    "n_symbols": 5_577,
    "n_delisted": 0,
    "asset_types": {"a-share"},
}
_SRC = "docs/strategy_mining_log.md §13 (因子表落后) 与 §11 (存活偏差)"


def _db():
    try:
        from hiagent_config import DB_PATH
    except Exception:
        return None
    p = Path(str(DB_PATH))
    return p if p.exists() else None


@pytest.fixture(scope="module")
def con():
    p = _db()
    if p is None:
        pytest.skip("本地 DB 缺失")
    import duckdb

    c = duckdb.connect(str(p), read_only=True)
    yield c
    c.close()


def _sync_msg(what: str) -> str:
    return (
        f"⚠️ 这不是缺陷 —— 但它使 {what} **过期**。\n"
        f"本判据钉住的是 {_SRC} 记录的事实。\n"
        f"数据变了 ⇒ 请**先**更新或撤回那两节, **再**更新本文件的 `PINNED`。"
    )


def test_factor_table_vintage_is_the_recorded_one(con) -> None:
    """§13 的前提 (**: 因子/行情两表的末日**)。

    ⚠️ **测试名曾在 2026-10-20 改过**: 原名 `test_factor_table_still_lags_the_price_table`
    —— 那编码的是**当时那条缺陷**; 数据刷新后 `lag == 0`, 名字会与断言矛盾。
    本判据钉的从来是「**事实 == 记录值**」, 所以改的是名字, 不是判据。
    """
    px = con.execute("SELECT MAX(date) FROM raw_kline_daily").fetchone()[0]
    fa = con.execute("SELECT MAX(date) FROM calc_adjust_factor_daily").fetchone()[0]
    lag = (px - fa).days
    assert str(px) == PINNED["price_max"] and str(fa) == PINNED["factor_max"], (
        f"行情末日 {px} / 因子末日 {fa} —— 与记录值 "
        f"({PINNED['price_max']} / {PINNED['factor_max']}) 不符。\n" + _sync_msg("§13")
    )
    assert lag == PINNED["factor_lag_calendar_days"], (
        f"落后 {lag} 天 ≠ 记录值 {PINNED['factor_lag_calendar_days']}。\n" + _sync_msg("§13")
    )


def test_the_factor_gap_is_still_the_recorded_size(con) -> None:
    """**§13 的伤害面**也钉住 —— 它是"哪些数字不能引用"的边界。"""
    n = con.execute(
        "SELECT COUNT(*) FROM raw_kline_daily r LEFT JOIN calc_adjust_factor_daily f"
        " ON r.thscode=f.thscode AND r.date=f.date WHERE f.thscode IS NULL"
    ).fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM raw_kline_daily").fetchone()[0]
    assert tot == PINNED["raw_kline_rows"], (
        f"行情表 {tot} 行 ≠ 记录值 {PINNED['raw_kline_rows']}。\n" + _sync_msg("§13")
    )
    assert n == PINNED["missing_factor_rows"], (
        f"因子缺失 {n} 行 ≠ 记录值 {PINNED['missing_factor_rows']}。\n" + _sync_msg("§13")
    )


def test_survivorship_is_still_the_recorded_shape(con) -> None:
    """**§11 的前提**: "当存在者"面板 —— 0 只退市票, 证券域只有 `a-share`。

    ⚠️ 这里断言的是 **`== 记录值`**, 不是 **`存在退市票`** —— 后者在本库恒红,
    正是 §11 当初**拒斥**加守卫的那个理由。本形态今天绿, 数据一变才红。
    """
    n_sym = con.execute("SELECT COUNT(*) FROM dim_symbol").fetchone()[0]
    assert n_sym == PINNED["n_symbols"], (
        f"`dim_symbol` {n_sym} 只 ≠ 记录值 {PINNED['n_symbols']}。\n" + _sync_msg("§11")
    )
    n_del = con.execute(
        "SELECT COUNT(*) FROM (SELECT thscode, MAX(date) m FROM raw_kline_daily"
        " GROUP BY thscode) WHERE m < DATE '2026-01-01'"
    ).fetchone()[0]
    assert n_del == PINNED["n_delisted"], (
        f"末期早于 2026 的票有 {n_del} 只, 而记录值是 {PINNED['n_delisted']}。\n"
        f"**若它 > 0, 那是好消息** (退市票进来了) —— 但 §11 的结论与文首提示必须同步。\n"
        + _sync_msg("§11")
    )
    at = {r[0] for r in con.execute("SELECT DISTINCT asset_type FROM dim_symbol").fetchall()}
    assert at == PINNED["asset_types"], (
        f"`asset_type` 取值 {at} ≠ 记录值 {PINNED['asset_types']}。\n"
        f"**若多了 ETF / 可转债, 那是好消息** (§9.4 的边界结论要改写)。\n" + _sync_msg("§9.4/§11")
    )


def test_the_pin_actually_bites(con) -> None:
    """反空转: 证明"钉住"这件事**真的会响** —— 故意改一个数, 比对必须失败。"""
    bad = dict(PINNED)
    bad["n_symbols"] = PINNED["n_symbols"] + 1
    n_sym = con.execute("SELECT COUNT(*) FROM dim_symbol").fetchone()[0]
    assert n_sym != bad["n_symbols"], (
        "反空转失败: 加 1 之后仍然相等 ⇒ 比对逻辑写错了, 上面几条断言不可信。"
    )
