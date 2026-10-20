"""附七十六 —— `v_daily_dual` 的**真实语义**,以及它与引擎手算口径的兼容性。

## 为什么值得单独钉

`dna_data/dual_price_loader.py`(与它的 `sql/migrate_v_daily_dual.sql`)此前都把
`v_daily_hfq` 称作 "**forward-adjusted**"。实测:

    v_daily_dual.adj_close == v_daily_hfq.close   100.00%（10,364,755 行全中）
    v_daily_dual.adj_close == v_daily_qfq.close     5.06%

即它是**后复权**(backward-adjusted),与前复权几乎不重合 —— 一处错标,传播进了
加载器 docstring 与 `audit_phantom` 的 qfq 校准(附五十八 §4 登记过同一处的后果)。

同时:`v_daily_dual.raw_prev_close` 实测 **100% 等于 `lag(raw_close)`**(0 行例外,
5,565 个 NULL 恰好是各票首根 bar)—— 与我在附五十一 于 `_build_index` 里**手算**的
`shift(raw_close)` 完全同口径(含停牌:取上一根**实际存在**的 bar)。

这决定了已登记的那件事("四引擎接 `dna_data.dual_price_loader`")的**风险大小**:
`raw_prev_close` 这一列接线后**不会改变**附五十一 的守卫行为 —— 这条由下面的用例钉住。

## §6

需真库;无库时 skip(不是 error)。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = REPO_ROOT / "sql" / "migrate_v_daily_dual.sql"
LOADER_PATH = REPO_ROOT / "dna_data" / "dual_price_loader.py"

from tests.conftest import require_market_db  # noqa: E402


@pytest.fixture(scope="module")
def con():
    require_market_db()
    from hiagent_config import get_db_path

    c = duckdb.connect(str(get_db_path()), read_only=True)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 真实语义
# ---------------------------------------------------------------------------


def test_dual_view_adj_is_backward_adjusted_not_forward(con) -> None:
    """`adj_close` 必须等于 `v_daily_hfq.close`(**后复权**),且**不是** qfq。

    这条同时挡住两种退化:(a) 有人把视图悄悄切到 qfq —— 那会让每一个指标的**价位**
    变掉(尺度不变的那些不变,但绝对阈值/跨名比较全变);(b) 有人按"forward-adjusted"
    的字面去改它 —— 前复权的历史价位会随之后每次分红而变,直接违反 §0 可复现性。
    """
    row = con.execute("""
        SELECT count(*) tot,
               sum(CASE WHEN abs(d.adj_close - h.close) < 1e-6 THEN 1 ELSE 0 END) as_hfq,
               sum(CASE WHEN abs(d.adj_close - q.close) < 1e-6 THEN 1 ELSE 0 END) as_qfq
        FROM v_daily_dual d
        JOIN v_daily_hfq h ON h.thscode = d.thscode AND h.date = d.date
        JOIN v_daily_qfq q ON q.thscode = d.thscode AND q.date = d.date
    """).fetchone()
    tot, as_hfq, as_qfq = int(row[0]), int(row[1]), int(row[2])
    assert tot > 0, "夹具为空(库里没有可比的行)"
    assert as_hfq / tot > 0.9999, f"adj_close 不是 hfq:{as_hfq}/{tot}"
    assert as_qfq / tot < 0.10, (
        f"adj_close 看起来变成了前复权(qfq 命中 {as_qfq}/{tot})—— 那会违反 §0 可复现性"
    )


def test_dual_view_raw_is_the_execution_domain(con) -> None:
    """`raw_close` 必须等于 `v_daily.close`(执行域)。"""
    row = con.execute("""
        SELECT count(*) tot,
               sum(CASE WHEN abs(d.raw_close - v.close) < 1e-6 THEN 1 ELSE 0 END) same
        FROM v_daily_dual d JOIN v_daily v ON v.thscode = d.thscode AND v.date = d.date
    """).fetchone()
    assert int(row[0]) > 0 and int(row[1]) == int(row[0]), (
        f"raw_close 与 v_daily.close 不一致:{row[1]}/{row[0]}"
    )


def test_dual_view_raw_prev_close_is_lag_of_raw_close(con) -> None:
    """`raw_prev_close` == `lag(raw_close)`,且 NULL 只出现在各票首根 bar。

    (即"上一根**实际存在**的 bar 的收盘"—— 停牌缺口取的是上一根真实 bar,不是日历前一日。)
    """
    row = con.execute("""
        WITH b AS (
          SELECT thscode, raw_close, raw_prev_close,
                 lag(raw_close) OVER (PARTITION BY thscode ORDER BY date) AS lag_raw,
                 row_number() OVER (PARTITION BY thscode ORDER BY date) AS rn
          FROM v_daily_dual
        )
        SELECT count(*) tot,
               sum(CASE WHEN raw_prev_close IS NOT NULL AND lag_raw IS NOT NULL
                         AND abs(raw_prev_close - lag_raw) < 1e-9 THEN 1 ELSE 0 END) same,
               sum(CASE WHEN (raw_prev_close IS NULL) <> (lag_raw IS NULL) THEN 1 ELSE 0 END) mismatch_null,
               sum(CASE WHEN raw_prev_close IS NULL AND rn > 1 THEN 1 ELSE 0 END) null_not_first
        FROM b
    """).fetchone()
    tot, same, mismatch_null, null_not_first = (int(x) for x in row)
    assert tot > 0
    assert mismatch_null == 0, f"NULL 形态与 lag(raw_close) 不同:{mismatch_null} 行"
    assert null_not_first == 0, f"有 {null_not_first} 行非首根 bar 却是 NULL"
    assert same > 0


def test_dual_view_prev_close_matches_the_engines_hand_rolled_shift(con) -> None:
    """**接线兼容性**:引擎在 `_build_index` 里手算的 `shift(raw_close)`(附五十一)
    与视图的 `raw_prev_close` 必须同值。

    这条把"接线 `dna_data.dual_price_loader` 不会改变附五十一 的守卫行为"从**推断**
    变成**被钉住的事实** —— 那正是 §5/§6 里"结果敏感的重构"最需要的东西。
    """
    # 关键:左侧必须从**引擎真正读的那张表**(`v_daily`)算,而不是也从这个视图算 ——
    # 否则两边同源,"一致"就成了同义反复。(第一版我就是从 v_daily_dual 算 lag,
    # 那样即使视图换了一套行集合也测不出来。)
    row = con.execute("""
        WITH eng AS (
          SELECT thscode, date, close AS raw_close,
                 lag(close) OVER (PARTITION BY thscode ORDER BY date) AS hand_shift
          FROM v_daily
        )
        SELECT count(*) tot,
               sum(CASE WHEN (eng.hand_shift IS NULL) = (d.raw_prev_close IS NULL)
                         AND (eng.hand_shift IS NULL
                              OR abs(eng.hand_shift - d.raw_prev_close) < 1e-9)
                        THEN 1 ELSE 0 END) same,
               count(*) - count(d.raw_prev_close) AS view_nulls
        FROM eng JOIN v_daily_dual d ON d.thscode = eng.thscode AND d.date = eng.date
    """).fetchone()
    assert int(row[0]) > 0 and int(row[1]) == int(row[0]), (
        f"两套口径不一致:{row[1]}/{row[0]} —— 接线时附五十一 的行为会变"
    )


# ---------------------------------------------------------------------------
# 错标不许回来
# ---------------------------------------------------------------------------


def test_sources_call_hfq_backward_adjusted() -> None:
    """视图定义与加载器 docstring 必须用**后复权**描述 `v_daily_hfq`。

    (附七十六:此前 `sql/migrate_v_daily_dual.sql` 的注释把它叫 "forward-adjusted",
    而那处错标传播进了加载器 docstring 与 phantom 工具的 qfq 校准。)
    """
    # 注(附七十七): 本条断言的是**docstring 措辞** —— 主题就是文档。
    # `tests/_census_comment_guards.py` 会把它列为候选,那是**已知误报**(不是空转)。
    sql = SQL_PATH.read_text(encoding="utf-8")
    loader = LOADER_PATH.read_text(encoding="utf-8")

    # ⚠️ 判据必须落在**描述那一行**上,不能只在整个文件里找词:
    # 我第一版是 `assert "backward-adjusted" in sql` —— 而文件里**更正的说明**本身
    # 就含这个词 ⇒ 把描述行改回 "forward-adjusted" 之后守卫**仍然绿**(实测)。
    # 又一次"判词不判事"。(本轮第 6 次"检查方法太弱"。)
    desc_lines = [ln for ln in sql.splitlines() if "view joining" in ln]
    assert desc_lines, "找不到描述视图组成的那行注释"
    for ln in desc_lines:
        assert "backward-adjusted" in ln, f"描述行没有说明 hfq 是后复权:{ln!r}"
        assert "forward-adjusted" not in ln, f"描述行仍把它叫前复权:{ln!r}"

    # 加载器 docstring:同样落在**列清单那一行**
    col_lines = [ln for ln in loader.splitlines() if "adj_close," in ln and "—" in ln]
    assert col_lines, "找不到加载器里说明 adj_* 的那行"
    for ln in col_lines:
        assert "backward-adjusted" in ln, f"加载器未说明 hfq 是后复权:{ln!r}"
