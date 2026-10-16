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
def test_pit_query_uses_last_trading_day_not_the_literal_asof(
    engine: str, path: Path
) -> None:
    """两侧都必须取「asof 当日或之前的 MAX(date)」,不得用 asof 字面值。"""
    src = path.read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    if "HAVING MAX(date)" not in code:
        pytest.skip(f"{engine} 无同形 PIT 查询")
    assert "HAVING MAX(date) >= (SELECT MAX(date) FROM v_daily WHERE date <= ?)" in code, (
        f"§0/§3 VIOLATION {engine}: PIT 查询的 HAVING 仍用 asof 字面值 —— "
        "非交易日 asof 会让每一只票都被误判为已退市 ⇒ 空宇宙"
    )
    assert code.count("(SELECT MAX(date) FROM v_daily WHERE date <= ?)") == 2, (
        f"{engine}: WHERE 与 HAVING 两侧都必须锚定最后一个交易日"
    )
    assert '"Empty universe' in code, (
        f"§0 VIOLATION {engine}: 空 universe 必须 fail-fast,不能静默返回 []"
    )
