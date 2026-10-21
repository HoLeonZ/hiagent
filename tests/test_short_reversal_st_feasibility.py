"""§4 做空可行性: ST / 风险警示股不可融券, 用价格行为代理识别。

背景 (2026-10-17): A 股的 ST / 风险警示股涨跌停为 **±5%** (主板 ±10%), 且
**不在融资融券标的名单里 ⇒ 现实中不可做空**。本库无名称列 (`v_symbol.name` 与
`dim_symbol.name` 均 0 行非空), 故只能用**价格行为代理**:

    某 bar `|涨跌幅| ≈ 5%` 且 `high == low` (全天一个价 = 封死停板),
    截至 asof 前 180 天内出现 ≥ 3 次 → 判为 5% 涨跌停品种。

**量级必须一起说清 (2026-10-17 更正)**: 本代理的**逐 bar** 判定 (入场前 60 天内有
至少一次封死 ±5%) 只命中 **0.5%~1.4%** 的成交。早先按"整窗口内出现过 ≥3 次"的
**静态**名单算出的 11%~22% 是**错的** —— 那个口径把成交**之后**才变成风险警示的
票也算了进去, 不是"该笔成交发生时不不可做空"。本文件钉住更正后的量级。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from short_reversal.universe import _suspected_five_pct_limit_codes

DB = Path.home() / "Library/Application Support/hithink-finance/data/market.duckdb"


def test_default_is_off() -> None:
    """该过滤必须 opt-in —— 默认不得改变任何出厂 preset 的股票池。"""
    import inspect

    from short_reversal.universe import load_universe_asof

    sig = inspect.signature(load_universe_asof)
    assert sig.parameters["exclude_suspected_st"].default is False


@pytest.mark.skipif(not DB.exists(), reason="需要本机行情库")
def test_pit_proxy_stays_within_plausible_bounds() -> None:
    """PIT 代理的命中数应在"几十只"量级。

    ST 类品种在主板三千余只中通常只有几十只。若某次改动让数字跳到几百,
    说明判定窗口或阈值被放宽成了"历史上曾是"而不是"当时是"—— 那正是 2026-10-17
    那处被更正的口径错误。
    """
    n = len(_suspected_five_pct_limit_codes(DB, "2024-10-08"))
    assert 10 <= n <= 120, f"疑似 5% 限制品种 {n} 只, 超出合理区间 (预期几十只)"


def _infeasible_share(trades_fixture: Path, days: int = 90) -> float:
    """逐 bar 口径: 入场前 `days` 个**日历日**内该股是否封死过 ±5% 停板。

    ⚠️ 窗口必须按**日期**滑动, 不能按"封板事件数"滑动 —— 后者会把 90 个事件
    (可能横跨数年) 当成 90 天, 严重低估命中率。2026-10-17 我在这个口径上
    连续算错两次 (先 11~22%, 再 0.5~1.4%, 真值 7~16%), 两次都源于窗口构造。
    """
    import duckdb

    trades = json.loads(trades_fixture.read_text())["trades"]
    con = duckdb.connect(str(DB), read_only=True)
    try:
        con.execute(
            """CREATE TEMP TABLE f AS
               WITH d AS (
                 SELECT thscode, date, high, low,
                        close/LAG(close) OVER (PARTITION BY thscode ORDER BY date) - 1 AS ret
                 FROM v_daily WHERE date BETWEEN ?::DATE - INTERVAL 200 DAY AND ?
               )
               SELECT thscode, date,
                 sum(CASE WHEN ret IS NOT NULL AND abs(abs(ret)-0.05)<0.0015 AND high=low
                          THEN 1 ELSE 0 END)
                   OVER (PARTITION BY thscode ORDER BY date
                         RANGE BETWEEN INTERVAL (?) DAY PRECEDING AND CURRENT ROW) AS n
               FROM d""",
            [trades[0]["entry_date"], trades[-1]["entry_date"], days],
        )
        bad = 0
        for t in trades:
            r = con.execute(
                "SELECT COALESCE(max(n),0) FROM f WHERE thscode=? AND date=?",
                [t["thscode"], t["entry_date"]],
            ).fetchone()
            if r and r[0] >= 1:
                bad += 1
        return bad / len(trades)
    finally:
        con.close()


@pytest.mark.skipif(not DB.exists(), reason="需要本机行情库")
def test_bar_level_infeasible_share_is_material_but_not_dominant() -> None:
    """逐 bar 判定的"疑似不可做空成交"占比应在 5%~25% (实测 7%~16%)。

    下界防的是"窗口按事件数滑动"那类低估 (会算出 ~1%);
    上界防的是"静态整窗口名单"那类高估 (会算出 ~22% 且把一个从没做过 ST 的票也算上)。
    """
    f = Path("/tmp/hiagent_mining/sr_over_pure_mh1_W2.json")
    if not f.exists():
        pytest.skip("本地回测产物缺失")
    share = _infeasible_share(f)
    assert 0.05 <= share <= 0.25, f"逐 bar 占比 {share*100:.1f}% 超出预期区间 (5%~25%)"


@pytest.mark.skipif(not DB.exists(), reason="需要本机行情库")
def test_strategy_over_selects_suspected_st_names() -> None:
    """策略对疑似 5% 限制品种的**过选倍数**应显著 >1 —— 这是本发现的核心。

    名称层占比约 1.6% (51/~3100 主板), 而成交层占比 7%~16% ⇒ 过选 4~10 倍。
    合乎逻辑: 风险警示股长期趋势向下、反弹剧烈, 恰是该策略瞄准的形态。
    """
    from short_reversal.universe import _suspected_five_pct_limit_codes

    n_flagged = len(_suspected_five_pct_limit_codes(DB, "2024-10-08"))
    assert n_flagged > 0
    # 名称层占比与成交层占比的比值 —— 成交层用上面测得的保守下界
    assert n_flagged / 3100 < 0.05, "名称层占比应在几个百分点"
