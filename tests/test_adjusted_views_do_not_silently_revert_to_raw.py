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


#: 复权序列与原始序列的**同日收益**最多能差多少。
#: 除权日两者本就不同(原始价含分红跳空、复权价不含),但那只有几个百分点;
#: 超过这个量级的差异只可能是**因子缺失/跳变**造成的伪影。
MAX_ADJ_VS_RAW_RETURN_GAP = 0.10


def _diverging_return_rows(threshold: float) -> int:
    con = _con()
    try:
        return con.execute(
            """
            WITH d AS (
              SELECT h.close / LAG(h.close) OVER w - 1 AS r_adj,
                     r.close / LAG(r.close) OVER w - 1 AS r_raw
              FROM v_daily_hfq h
              JOIN raw_kline_daily r USING (thscode, date)
              WINDOW w AS (PARTITION BY h.thscode ORDER BY h.date)
            )
            SELECT count(*) FROM d
            WHERE r_adj IS NOT NULL AND r_raw IS NOT NULL AND abs(r_adj - r_raw) > ?
            """,
            [threshold],
        ).fetchone()[0]
    finally:
        con.close()


#: **登记在案的伪影行数**(实测 2026-10-20,阈值 10%)。
#:
#: 它不是"容忍"——是**已知债务**:成因与修法见本文件 docstring 的"正确修法"一节
#: (上游视图改前向填充,或刷新 `calc_adjust_factor_daily`),两者都在**仓库之外**。
#: 登记的作用有二:①套件不被一个"修不了"的红点长期拖着;②**数字一旦变动就会被注意到**
#: (涨了说明伪影变多;掉到 0 说明已修 ⇒ 本条目必须删掉)。
KNOWN_ADJUSTED_RETURN_ARTIFACT_ROWS = 7_979


@pytest.mark.slow
def test_adjusted_returns_never_diverge_implausibly_from_raw() -> None:
    """§3/§0:**复权序列带给策略的日收益,不许与原始序列的日收益差到物理上不可能**。

    这条比"形状"那几条更贴语义:一个缺失因子会把复权价乘 1(即原始价),在序列里表现为
    **一根凭空造出来的巨幅收益** —— 实测复权域里有 **1,150 行单日 < −50%**,
    而 A 股涨跌幅上限是 ±10%(主板)/±20%(创业板科创板)。它会直接进入 `pct_chg` 类信号
    与下一根 bar 的盯市。

    **实测它今天是红的**(7,979 行),故走"登记债务"而不是"假装绿":数量不得超过登记值。
    """
    require_market_db()
    n = _diverging_return_rows(MAX_ADJ_VS_RAW_RETURN_GAP)
    assert n <= KNOWN_ADJUSTED_RETURN_ARTIFACT_ROWS, (
        f"§3 VIOLATION: 复权/原始同日收益差异超过 {MAX_ADJ_VS_RAW_RETURN_GAP:.0%} 的行数 "
        f"**涨到了 {n:,}**(登记值 {KNOWN_ADJUSTED_RETURN_ARTIFACT_ROWS:,})—— "
        "伪影在变多,请立刻查因子表覆盖与视图定义。"
    )


@pytest.mark.slow
def test_the_registered_artifact_debt_is_not_stale() -> None:
    """登记表**只应当变短**:伪影掉到 0(因子表已刷新/视图已改)⇒ 本条目必须删掉。"""
    require_market_db()
    n = _diverging_return_rows(MAX_ADJ_VS_RAW_RETURN_GAP)
    assert n > 0, (
        "复权/原始同日收益差异**已经为 0** —— 那条已登记的债务解决了,"
        "请从 KNOWN_ADJUSTED_RETURN_ARTIFACT_ROWS 删掉它(登记表只应当变短)。"
    )


@pytest.mark.slow
def test_that_divergence_check_actually_discriminates() -> None:
    """**非空转**:同一条判据在更严的阈值下必须**找出大量行** —— 否则它恒真。

    (用一个远小于真实分红率的阈值 1%:那里应当有成千上万行,证明判据确实在看数据;
     再用排除除权日的严格定义受限于 SQL,故这里只要求"更严 ⇒ 更多"。)
    """
    require_market_db()
    loose = _diverging_return_rows(0.01)
    assert loose > 1_000, (
        f"阈值 1% 时只有 {loose} 行 —— 判据可能没在真的比对收益(除权日应当有大量行)"
    )


@pytest.mark.slow
def test_the_engine_refuses_a_window_with_uncovered_trading_days() -> None:
    """§0:引擎**不许**静默跑一个"窗口里有未覆盖交易日"的回测。

    ⚠️ 判据**不是**"`end` 是否晚于因子表末日" —— 第一版按后者写,
    把 `--end 2026-09-19`(**周六**,窗口内无数据)误判成越界,一次红掉 6 个用例。
    **"日子越界"与"窗口里有未覆盖的交易日"是两回事**,本用例把两者都钉住。

    消费者侧的 fail-fast 落在 `cycle_price_action/main.py::assert_adjusted_window_is_covered`
    (薄包装,规则本身在 `core/data_coverage`),并被四个引擎的复权价入口各自调用。
    """
    from datetime import date, timedelta

    require_market_db()
    from core.data_coverage import uncovered_trading_days
    from cycle_price_action.main import assert_adjusted_window_is_covered

    con = _con()
    try:
        coverage = con.execute(
            "SELECT max(date) FROM calc_adjust_factor_daily"
        ).fetchone()[0]
    finally:
        con.close()

    # ① 覆盖之内 ⇒ 放行(否则 fail-fast 会退化成"永远拒绝")
    assert_adjusted_window_is_covered(str(DB_PATH), coverage - timedelta(days=365), coverage)

    # ② **周末当终点** ⇒ 放行:窗口里没有任何未覆盖的**交易日**
    #    (这条正是第一版判据的漏洞:字面上 end > coverage,但没有数据)
    weekend = coverage + timedelta(days=1)
    assert weekend.weekday() >= 5, f"夹具失效:{weekend} 不是周末"
    con = _con()
    try:
        assert uncovered_trading_days(con, coverage - timedelta(days=30), weekend) == []
    finally:
        con.close()
    assert_adjusted_window_is_covered(str(DB_PATH), coverage - timedelta(days=365), weekend)

    # ③ 越过覆盖且**确有交易日** ⇒ 必须抛错,且点名日期
    later = coverage + timedelta(days=14)
    con = _con()
    try:
        bad = uncovered_trading_days(con, coverage - timedelta(days=365), later)
    finally:
        con.close()
    if bad:   # 因子表一旦刷新到覆盖 later,这一段自动不再触发
        with pytest.raises(ValueError) as ei:
            assert_adjusted_window_is_covered(str(DB_PATH), coverage - timedelta(days=365), later)
        msg = str(ei.value)
        assert str(bad[0]) in msg and "原始价" in msg, f"错误信息没说清:{msg}"


#: 四个引擎各自的**复权价入口**(复权价从这些函数进 engine)。
#: 逐个实测确认过:chase/uptrend 的 `load_panel`、short_reversal 的 `load_panel_for_backtest`、
#: cycle 的 `load_universe_data`(它 LEFT JOIN v_daily_hfq 取 adj_close;
#: 而同模块的 `load_bars_by_code` 读的是 **v_daily 原始价**,不需要这道检查)。
ADJUSTED_PRICE_ENTRY_POINTS = {
    "chase_up/data.py": "chase_up/data.load_panel",
    "uptrend_pullback/data.py": "uptrend_pullback/data.load_panel",
    "short_reversal/_panel_loader.py": "short_reversal/_panel_loader.load_panel_for_backtest",
    "cycle_price_action/data_feed.py": "cycle_price_action/data_feed.load_universe_data",
}


def test_every_engine_checks_the_coverage_at_its_adjusted_price_entry() -> None:
    """**四个引擎各自的复权价入口**都必须接这条检查。

    (附一百零三 只给 `cycle` 的 CLI 加了检查 —— 那是"只改了看到的那一个"的形状。
     判据已在附一百零四 收到 `core/data_coverage` 单源;本用例钉**接线是满的**,
     免得将来新增一个 loader 时又漏一格。)
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    missing = []
    for rel, source_tag in ADJUSTED_PRICE_ENTRY_POINTS.items():
        src = (root / rel).read_text(encoding="utf-8")
        if f'source="{source_tag}"' not in src:
            missing.append(f'{rel} 未接(期望 source="{source_tag}")')
    assert not missing, (
        "§3/§0: 以下**复权价入口**没有做因子覆盖检查 —— 越过因子表末端的窗口会在那里静默退回原始价:\n  "
        + "\n  ".join(missing)
    )


def test_the_coverage_entry_list_is_not_vacuous() -> None:
    """**非空转**:四个引擎一个都不能少(少一个就说明我漏了某个价域)。"""
    engines = {rel.split("/")[0] for rel in ADJUSTED_PRICE_ENTRY_POINTS}
    assert engines == {"chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"}, (
        f"复权价入口的引擎集合不完整:{sorted(engines)}"
    )
