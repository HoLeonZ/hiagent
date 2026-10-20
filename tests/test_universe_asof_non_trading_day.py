"""§0/§3 守卫:PIT universe 的 as-of 必须按「**asof 当日或之前的最后一个交易日**」判定。

## 缺陷(审计 §3.2「§1 窗口边界/宇宙 as-of」的未复核项,2026-10-16 复核**成立**)

`chase_up/universe.py` 的 PIT 查询曾把 as-of 字面值同时用在两侧:

```sql
WHERE date <= ?  GROUP BY thscode  HAVING MAX(date) >= ?     -- [asof, asof]
```

于是当 asof 落在**非交易日**(周末 / 节假日)时,对**每一只票**都有
`MAX(date) <= asof` 的最后交易日 **< asof** ⇒ `HAVING` 全不成立 ⇒ **空集**。
而 `load_universe` 静默返回 `[]`,回测照跑 —— 产出 **0 笔交易 / CAGR 0.0000**,
一个"看起来很干净"的零结果,会被下游 sweep 当成有效样本参与统计。

### 实测(live DB,`mainboard_only`)

| asof | chase_up | uptrend_pullback(早已修) |
|---|---|---|
| 2026-01-09 周五 | 3167 | 3167 |
| 2026-01-10 周六 | **0** | 3167 |
| 2026-01-11 周日 | **0** | 3167 |
| 2026-10-01 国庆 | **0** | 3187 |

端到端(同一 preset `chase_v10_...`,只把窗口起点从周五挪到周六):
11 笔 / 期末 1,425,981.91 → **0 笔 / 1,000,000.00 / CAGR 0.0000**。

### 本条的方法论教训

**同一个缺陷族在两个姊妹引擎里不同步**:`uptrend_pullback/universe.py` 早已是
正确形式,而且**带着解释这条缺陷的注释**;`chase_up/universe.py` 一字不差地
保留着旧形式。修一处不等于修一族 —— 跨引擎的"同形代码"必须逐个点名核对。

## 本文件覆盖

- 行为层(需 DB):非交易日 asof 的 universe 必须等于上一个交易日的 universe,
  且不得为空;两个引擎在**同一 asof** 上必须给出同样大小(引擎间不变量)。
- fail-fast(需 DB):空 universe 必须抛异常,而不是返回 []。
- 结构层:两个引擎都必须是"最后一个交易日"形式,不得退回字面值形式。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_FRI, _SAT, _SUN = "2026-01-09", "2026-01-10", "2026-01-11"
_HOLIDAY, _DAY_BEFORE_HOLIDAY = "2026-10-01", "2026-09-30"

_ENGINES = {
    "chase_up": REPO_ROOT / "chase_up" / "universe.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "universe.py",
}


def _db():
    from hiagent_config import get_db_path

    return Path(get_db_path())


_NEEDS_DB = pytest.mark.skipif(
    not _db().exists() or _db().stat().st_size == 0,
    reason=f"local DuckDB 不可用 ({_db()}) — 按 CLAUDE.md §6 skip 而非 error",
)


def _chase(asof: str) -> list[str]:
    from chase_up.universe import load_universe

    return load_universe("mainboard_only", _db(), asof_date=asof)


def _uptrend(asof: str) -> list[str]:
    from uptrend_pullback.universe import load_universe

    return load_universe("mainboard_only", _db(), asof_date=asof)


# ---------------------------------------------------------------------------
# 行为层
# ---------------------------------------------------------------------------


@_NEEDS_DB
@pytest.mark.parametrize("asof", [_SAT, _SUN])
def test_non_trading_asof_yields_the_previous_trading_day_universe(asof: str) -> None:
    """周末 asof 必须与上一个交易日 asof 等价(而不是空集)。"""
    weekend = _chase(asof)
    friday = _chase(_FRI)
    assert weekend, (
        f"§0/§3 VIOLATION: asof={asof}(非交易日)的 universe 为空 —— "
        "PIT 查询把 asof 字面值当成了最后一个交易日"
    )
    assert weekend == friday, (
        f"asof={asof} 与 asof={_FRI} 的 universe 不等价: "
        f"{len(weekend)} vs {len(friday)} 只"
    )


@_NEEDS_DB
def test_holiday_asof_yields_the_previous_trading_day_universe() -> None:
    """节假日 asof(国庆)同理 —— 这是比周末更容易被真正踩到的一种起点。"""
    assert _chase(_HOLIDAY) == _chase(_DAY_BEFORE_HOLIDAY)
    assert _chase(_HOLIDAY), "节假日 asof 不得产出空宇宙"


@_NEEDS_DB
@pytest.mark.parametrize("asof", [_FRI, _SAT, _SUN, _HOLIDAY])
def test_sibling_engines_agree_on_the_universe_at_the_same_asof(asof: str) -> None:
    """同一 asof 下两个引擎必须给出同样的 universe —— 引擎间不变量。

    这条正是本缺陷的形态:同一个查询在两处写成两种形式,于是**一边有一边没有**。
    """
    c, u = _chase(asof), _uptrend(asof)
    assert len(c) == len(u), (
        f"asof={asof}: chase_up={len(c)} 只 / uptrend_pullback={len(u)} 只 —— "
        "同一 PIT 语义在两个引擎里给了不同的宇宙"
    )


@_NEEDS_DB
def test_empty_universe_fails_fast_instead_of_reporting_zero_trades() -> None:
    """§0: 数据覆盖之前的 asof ⇒ universe 为空 ⇒ 必须抛异常,而不是静默 []。"""
    from chase_up import ChaseUpError
    from uptrend_pullback import UptrendPullbackError

    with pytest.raises(ChaseUpError, match="Empty universe"):
        _chase("1990-01-01")
    with pytest.raises(UptrendPullbackError, match="Empty universe"):
        _uptrend("1990-01-01")


# ---------------------------------------------------------------------------
# 结构层(无 DB 依赖)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine,path", sorted(_ENGINES.items()))
def test_no_engine_uses_the_literal_asof_having_form(
    engine: str, path: Path
) -> None:
    """§3 反向守卫:**禁止**字面值 as-of 的 HAVING 形式(附二十五 的缺陷形态)。

    这条是**负向**断言(禁止已知的错误写法),而不是按"正确写法"做拼写匹配 ——
    后者在附三十三 把 SQL 换成 CTE 形式之后会**静默 skip**(本文件实测曾 skip 2 条,
    覆盖悄悄消失,而套件依然是绿的)。语义正确性由
    `test_halted_name_stays_and_delisted_name_leaves`(合成库 × 三引擎 ×
    「正常/停牌/已退市」三种情形)在行为层钉住。
    """
    src = path.read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "v_daily" in code, f"{engine}: 预期文件里有 v_daily 查询"
    for bad in ("HAVING MAX(date) >= ?", "HAVING MAX(date) >= asof_date"):
        assert bad not in code, (
            f"§3 VIOLATION {engine}: 又出现字面值 as-of 的 HAVING(`{bad}`)—— "
            "非交易日 asof 会让每只票都被误判为已退市(空宇宙),且把当日停牌错杀成退市"
        )
    assert '"Empty universe' in code, (
        f"§0 VIOLATION {engine}: 空 universe 必须 fail-fast,不能静默返回 []"
    )


# ---------------------------------------------------------------------------
# 附三十三(2026-10-16):"已退市" 的判据不得退化成「当日恰好有 bar」
# ---------------------------------------------------------------------------


def _synthetic_db(tmp_path: Path) -> Path:
    """造一个只含三只票的小库,把「正常 / 停牌 / 已退市」三种情形分离开。

    真实库里**没有**退市票(实测:整表最后一根 bar 落在 2020~2024 的标的一只也没有
    —— 数据集里的票都还活着),所以退市那一支只能靠合成库来钉。
    """
    import duckdb

    db = tmp_path / "synthetic.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE v_daily (thscode VARCHAR, date DATE)")
    rows = []
    # 正常票:一直有 bar(截至 asof 与之后)
    for d in ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"):
        rows.append(("600001.SH", d))
    # 停牌票:asof(2025-01-06)当日**没有** bar,但之后复牌
    rows += [("600002.SH", "2025-01-02"), ("600002.SH", "2025-01-03"),
             ("600002.SH", "2025-01-20"), ("600002.SH", "2025-01-21")]
    # 已退市票:整表最后一根 bar 远早于 asof
    rows += [("600003.SH", "2024-06-03"), ("600003.SH", "2024-06-04")]
    con.executemany("INSERT INTO v_daily VALUES (?, ?)", rows)
    con.close()
    return db


def test_halted_name_stays_and_delisted_name_leaves(tmp_path: Path) -> None:
    """§3 PIT: asof 当日**停牌**的票必须留在宇宙里;asof 之前**已退市**的票必须剔除。

    缺陷形态(修复前):判据是 `HAVING MAX(date) >= last_td`,而 MAX 建在
    `date <= last_td` 过滤后的分组上 —— 恒 <= asof,于是退化成「在最后一个交易日
    **恰好有** bar」:停牌票被当成退市票踢掉(实测少 2~9 只),而**真退市票**反倒
    因为"当天没数据"和"停牌"同形而无法区分。
    三种情形在同一张合成表上分开钉住,故这条断言对两边都有牙。
    """
    db = _synthetic_db(tmp_path)
    from chase_up.universe import load_universe as chase
    from short_reversal.universe import load_universe_asof as short_rev
    from uptrend_pullback.universe import load_universe as uptrend

    asof = "2025-01-06"  # 600002.SH 当日停牌;600003.SH 早已退市
    universes = {
        "chase_up": set(chase("mainboard_only", db, asof_date=asof)),
        "uptrend_pullback": set(uptrend("mainboard_only", db, asof_date=asof)),
        "short_reversal": set(short_rev("mainboard_only", asof, db)),
    }
    for engine, uni in universes.items():
        assert "600001.SH" in uni, f"{engine}: 正常票被漏掉"
        assert "600002.SH" in uni, (
            f"{engine}: §3 VIOLATION —— asof 当日**停牌**的票被当成已退市踢出了宇宙;"
            "停牌票仍在市,窗口内会复牌"
        )
        assert "600003.SH" not in uni, (
            f"{engine}: §3 VIOLATION —— asof 之前**已退市**的票仍在宇宙里"
        )


# ---------------------------------------------------------------------------
# 三引擎必须给出同一个宇宙(缺陷的形态:同一语义两处实现)
# ---------------------------------------------------------------------------


def _short_rev(asof: str) -> list[str]:
    from short_reversal.universe import load_universe_asof

    return load_universe_asof("mainboard_only", asof, _db())


@_NEEDS_DB
@pytest.mark.parametrize(
    "asof", [_FRI, _SAT, _SUN, _HOLIDAY, "2025-09-19", "2026-09-30"]
)
def test_all_three_engines_agree_on_the_universe(asof: str) -> None:
    """同一 asof 下**三个**引擎的 mainboard 宇宙必须逐只相同。

    此前只有 chase/uptrend 参与这条不变量,而 short_reversal 的查询**根本没有退市
    判定**(`WHERE date <= ?`)—— 于是它把 2018 年退市的票也留在 2026 年的宇宙里。
    """
    c, u, s = set(_chase(asof)), set(_uptrend(asof)), set(_short_rev(asof))
    assert c == u == s, (
        f"asof={asof}: chase={len(c)} / uptrend={len(u)} / short_reversal={len(s)} —— "
        f"仅 chase 有 {sorted(c - s)[:3]},仅 sr 有 {sorted(s - c)[:3]}"
    )


@_NEEDS_DB
def test_short_reversal_also_fails_fast_on_an_empty_universe() -> None:
    """§0: short_reversal 的空宇宙同样必须失败,不得静默返回 []。"""
    from short_reversal import ShortReversalError

    with pytest.raises(ShortReversalError, match="Empty universe"):
        _short_rev("1990-01-01")
