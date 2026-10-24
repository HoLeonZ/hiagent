"""PIT universe 的**行为**（不只是签名）—— §3。

`tests/test_pit_universe_4engine.py` 守的是"`asof_date` 这个参数存在"，
那是一条**看起来在把关、实际抓不到**的断言：参数在，SQL 照样可以错。

实测缺陷（2026-10-24）：`chase_up/universe.py` 的 PIT 过滤把 `date <= asof`
写进了 WHERE，于是 `HAVING MAX(date) >= asof` 只能在"该票**恰好**在 asof 当天
有 bar"时成立 —— asof 落在周末/节假日时对每只票都不成立 → **空集** →
回测**静默**产出 0 笔交易：

| asof | 修复前 | 修复后 |
|---|---|---|
| 2023-06-01（周四，交易日） | 3086 | 3092 |
| 2024-01-01（元旦） | **0** | 3113 |
| 2025-01-01（元旦） | **0** | 3137 |
| 2025-06-01（周日） | **0** | 3152 |

后果：平台默认窗口（起 2025-01-01）在 chase_up 上**永远 0 笔**，
而界面上只是"这个策略没信号" —— 看不出是 universe 坏了。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


#: as-of 落在**非交易日**（元旦 / 周日）。这几个日子曾经让 universe 变成空集。
NON_TRADING_ASOF = ("2024-01-01", "2025-01-01", "2025-06-01", "2026-10-16")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_an_as_of_on_a_non_trading_day_still_yields_a_universe():
    """**as-of 落在非交易日时，universe 不能是空集。**

    判据不只是"非空"：空集是最坏的一种错（0 笔看起来像"没信号"）。
    """
    from chase_up.universe import load_universe

    db = _db()
    for asof in NON_TRADING_ASOF:
        u = load_universe("mainboard_only", db, None, asof)
        assert len(u) > 1000, (
            f"as-of={asof}（非交易日）的 universe 只有 {len(u)} 只 —— "
            "回测会静默产出 0 笔交易，而界面上只是「没信号」"
        )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_the_universe_of_a_non_trading_day_matches_the_preceding_trading_day():
    """**非交易日的 as-of 应当等于它之前那个交易日的 as-of。**

    一天之内不会有新的上市/退市，所以两个 universe 应当几乎一样。
    这条比"非空"更强：它同时挡住"为了非空而放宽"（例如退回 post-hoc 全集）。
    """
    from chase_up.universe import load_universe

    db = _db()
    for asof in NON_TRADING_ASOF:
        u = load_universe("mainboard_only", db, None, asof)
        # 之前的最后一个交易日：向前找一天
        import datetime as dt

        d = dt.date.fromisoformat(asof) - dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
        prev = load_universe("mainboard_only", db, None, d.isoformat())
        assert abs(len(u) - len(prev)) <= 50, (
            f"as-of={asof} 的 universe（{len(u)}）与前一交易日 {d}（{len(prev)}）"
            f"差 {abs(len(u) - len(prev))} 只 —— 一天之内不该差这么多"
        )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_every_engine_yields_a_universe_for_a_non_trading_day():
    """**四个引擎在同一个非交易日 as-of 上都不能是空集。**

    三个引擎各自的实现（short_reversal 的 `load_universe_asof`、
    chase_up 的 `load_universe`、uptrend_pullback 的 `load_universe`）
    历史上各自修过一次同类缺陷（uptrend 的注释里写着"回测静默产出 0 笔交易"），
    却没有一条**行为**测试守住 —— 于是 chase_up 那份拷贝一直坏着。
    """
    db = _db()
    asof = "2025-01-01"          # 元旦

    from chase_up.universe import load_universe as cu
    from short_reversal.universe import load_universe_asof as sr
    from uptrend_pullback.universe import load_universe as up

    for name, got in (
        ("short_reversal", sr("mainboard_only", asof, db)),
        ("chase_up", cu("mainboard_only", db, None, asof)),
        ("uptrend_pullback", up("mainboard_only", db, None, asof)),
    ):
        assert len(got) > 1000, (
            f"{name} 在 as-of={asof}（非交易日）上的 universe 只有 {len(got)} 只"
        )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_stock_listed_after_the_as_of_is_excluded():
    """**PIT 的另一半：不能选到 as-of 之后才上市的票。**

    上面的判据（"非空"）挡不住"为了非空而放宽成 post-hoc 全集"。
    """
    import duckdb

    from chase_up.universe import load_universe

    db = _db()
    con = duckdb.connect(str(db), read_only=True)
    try:
        row = con.execute(
            "SELECT thscode, MIN(date) FROM v_daily GROUP BY thscode "
            "HAVING MIN(date) > DATE '2025-01-01' ORDER BY MIN(date) LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if row is None:
        pytest.skip("库里没有 as-of 之后才上市的票")

    code, listed = row
    u = load_universe("mainboard_only", db, None, "2025-01-01")
    assert code not in u, (
        f"{code} 于 {listed} 上市，晚于 as-of=2025-01-01，却出现在 universe 里 —— "
        "那是**未来**的票（§3 PIT Mandate）"
    )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_chase_up_backtest_over_a_non_trading_day_start_actually_trades():
    """**端到端：as-of 落在非交易日的 chase_up 回测必须真的跑出成交。**

    上面几条都只看 universe；这条看**用户看得见的结果**：
    修复前，起点 2025-06-01（周日）的 chase_up 回测是 0 笔、0 信号，
    而界面上只是"这个策略没信号" —— 看不出是 universe 坏了。
    """
    from web.runners import run

    got = run("chase_up", "chase_v5_pos2_equal_atr_tp6_sl15_mh10",
              "2025-06-01", "2026-01-01")
    assert got.metrics.get("signals", 0) > 0, (
        "起点是非交易日的 chase_up 回测**一个信号都没有** —— "
        "universe 又被过滤成空集了"
    )
    assert got.trades, "起点是非交易日的 chase_up 回测**一笔成交都没有**"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_stock_suspended_on_the_as_of_date_is_still_in_the_universe():
    """**as-of 当天停牌的票仍是成分** —— 停牌不是退市（§1）。

    `uptrend_pullback` 的 PIT 过滤曾把 `MAX(date)` 的范围也限制在 `date <= last_td`，
    于是 `HAVING MAX(date) >= last_td` 又退化成"必须恰好在 last_td 那天有 bar"，
    当天停牌的票被当成已退市剔掉（实测 2025-09-19 少 6 只）。`chase_up` 用的是
    同一条 SQL —— 两份必须一致，别再各自演化。
    """
    import duckdb

    db = _db()
    asof = "2025-09-19"
    con = duckdb.connect(str(db), read_only=True)
    try:
        row = con.execute(
            "SELECT thscode FROM v_daily WHERE thscode LIKE '6%.SH' "
            "AND date < DATE '2025-09-19' "
            "AND thscode NOT IN (SELECT thscode FROM v_daily WHERE date = DATE '2025-09-19') "
            "AND thscode IN (SELECT thscode FROM v_daily WHERE date > DATE '2025-09-19') "
            "LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if row is None:
        pytest.skip("库里没有 as-of 当天停牌的票")

    code = row[0]
    from chase_up.universe import load_universe as cu
    from uptrend_pullback.universe import load_universe as up

    assert code in cu("mainboard_only", db, None, asof), \
        f"{code} 在 {asof} 停牌、之后仍交易 —— chase_up 不该把它当成已退市"
    assert code in up("mainboard_only", db, None, asof), \
        f"{code} 在 {asof} 停牌、之后仍交易 —— uptrend_pullback 不该把它当成已退市"
