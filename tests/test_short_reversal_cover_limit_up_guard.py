"""§4 回补侧涨停 no-fill 守卫（审计 P1-9，2026-10-15）。

CLAUDE.md §4：涨停/跌停封板的 bar 上无法成交。做空的**回补是一次 BUY** ——
涨停封板时买不进（买单队列锁死），故回补必须被拒、持仓顺延到下一根可成交 bar。

审计发现：short_reversal 只守了**入场侧**的 `is_limit_down`，**回补侧完全没有**
`is_limit_up` 守卫 —— 于是在涨停板上照常"买入回补"，把亏损截断在一个物理上
取不到的价位（与长仓引擎的跌停幻影止损互为镜像）。

方向保守：跳过 SL 回补意味着浮亏可能继续扩大，符合 §0 Pessimistic Default。
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy

# SMA(60) 暖机：next() 首次在 len(d)=60（bar 59）触发 → 信号 bar 59，
# 成交 bar 60（entry_bar = len(self) = 61）。_check_exit 的 held<1 保护
# 使判定首次生效于 bar 62 —— 故 _COVER_BAR = 62，不是 61。
_SIGNAL_BAR = 59
_FILL_BAR = 60
_COVER_BAR = 62
_N = 80


def _panel(cover_open: float, thscode: str = "600000.SH") -> pd.DataFrame:
    dates = pd.date_range("2025-09-01", periods=_N, freq="B")
    rows = []
    for i, d in enumerate(dates):
        p = cover_open if i == _COVER_BAR else 10.0
        rows.append({
            "thscode": thscode, "date": d,
            "open": p, "high": p + 0.001, "low": p - 0.001, "close": p,
            "volume": 1e6, "amount": 5e7,
        })
    return pd.DataFrame(rows)


def _run(cover_open: float, monkeypatch, thscode: str = "600000.SH") -> tuple[list, pd.DataFrame]:
    panel = _panel(cover_open, thscode)
    state = {"called": False}

    def first_bar_only(self, d):
        if not state["called"]:
            state["called"] = True
            return True
        return False

    monkeypatch.setattr(Phase3V3Strategy, "_all_conditions", first_bar_only)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.adddata(AShareData(dataname=panel, plot=False), name=thscode)
    holder: dict = {"cash": 100_000.0, "trades": [], "max_dd": 0.0}
    cerebro.addstrategy(
        Phase3V3Strategy,
        result_holder=holder,
        nav_gate_ratio=0.05,
        tp_pct=0.02,          # tp_p = 10.0 × 0.98 = 9.80(不会触及)
        sl_pct=0.05,          # sl_p = 10.0 × 1.05 = 10.50
        max_hold=3,
        signal_price_domain="adj",
    )
    cerebro.run()
    return holder["trades"], panel


def test_cover_on_limit_up_sealed_bar_is_rejected(monkeypatch) -> None:
    """bar 61 开盘 11.0(+10%)→ 涨停封板 → 不得在该 bar 回补,持仓顺延。"""
    # +10% 相对 bar 60 的 close(10.0),超过 9.5% 阈值
    assert abs(11.0 / 10.0 - 1.0) >= 0.095
    trades, panel = _run(cover_open=11.0, monkeypatch=monkeypatch)
    cover_date = panel.iloc[_COVER_BAR]["date"]

    assert trades, "应至少有一笔成交(顺延后由 time 出场)"
    for t in trades:
        assert pd.Timestamp(t["exit_date"]) != cover_date, (
            f"§4 VIOLATION: 在涨停封板 bar({cover_date.date()}) 上完成了回补成交 —— "
            "封板时买不进,必须顺延到下一根可成交 bar"
        )


def test_cover_on_normal_bar_still_triggers_sl(monkeypatch) -> None:
    """反向对照:bar 61 开盘 10.6(+6%,非封板)→ 跳空穿越止损应照常成交。

    这条证明上一条确实是**涨停守卫**在起作用。
    """
    assert abs(10.6 / 10.0 - 1.0) < 0.095
    trades, panel = _run(cover_open=10.6, monkeypatch=monkeypatch)
    cover_date = panel.iloc[_COVER_BAR]["date"]

    assert trades, "非封板时应成交"
    sl_trades = [t for t in trades if pd.Timestamp(t["exit_date"]) == cover_date]
    assert sl_trades, (
        "非封板时应在该 bar 触发止损回补 —— 若为空说明守卫把正常成交也挡掉了"
    )
    assert sl_trades[0]["exit_reason"] == "SL"


# ===========================================================================
# 附五十三 —— 回补侧守卫的**阈值板块感知**必须与入场侧同源
# ===========================================================================
#
# 两处缺陷(同一行代码附近):
#   (1) 回补侧的 `is_limit_up(threshold=self.p.limit_up_threshold)` 用的是**flat
#       0.095**,没走 `_board_limit_threshold` —— 而入场侧早就走了,本文件
#       (replay_strategy_v3.py v67 注释)还明写「20% 板的票用 10% 阈值会误判…
#       broad_only universe 必须走此逻辑」。于是 300/301/302/688/689 上
#       +9.5%…+19.5% 的**合法**开盘被当成封板,回补被无谓推迟。
#   (2) `_board_limit_threshold` 自身的前缀不全:只认 `300.SZ` / `688.SH`,
#       漏了 `301/302.SZ`(创业板后续代码段)与 `689.SH`(科创 CDR)。
#
# 为什么这是**缺陷**而不是"保守":封板是一个关于市场的事实断言。把没封板的
# bar 判成封板,与把封板的 bar 判成可成交一样是错的 —— 且方向上是把**合法**
# 成交挡在门外(与附五十一 的涨停误拒同族)。
#
# 可行域(2026 YTD,活库实测,`v_daily`):
#   300/688 上 open ∈ [+9.5%, +19.5%) 的 bar: 439 根(被 (1) 误判)
#   301/302 上同区间:                            122 根(被 (1)+(2) 误判)
#   301/302 上 open ∈ (−19.5%, −9.5%]:            75 根(被 (2) 误判,入场侧)


def test_board_threshold_covers_every_twenty_pct_board() -> None:
    """`_board_limit_threshold` 必须覆盖**所有** ±20% 的板,且不误伤主板。"""
    from datetime import date as _date

    from short_reversal.replay_strategy_v3 import (
        _LIMIT_THRESHOLD_20PCT,
        _board_limit_threshold,
    )

    d = _date(2026, 6, 1)
    for code in ("300001.SZ", "301234.SZ", "302001.SZ", "688001.SH", "689001.SH"):
        assert _board_limit_threshold(code, d, 0.095) == _LIMIT_THRESHOLD_20PCT, (
            f"{code} 是 ±20% 板,却拿到默认阈值 —— 合法成交会被误判成封板"
        )
    # 反向:主板必须**仍然**是默认阈值 —— 否则守卫整体失效,那是另一种错
    for code in ("600000.SH", "601398.SH", "000001.SZ", "001001.SZ",
                 "002001.SZ", "003001.SZ"):
        assert _board_limit_threshold(code, d, 0.095) == 0.095, (
            f"{code} 是主板,却被套上 20% 阈值 —— 涨停守卫会形同虚设"
        )
    # 历史规则:创业板 2020-08-24 之前是 ±10%
    assert _board_limit_threshold("300001.SZ", _date(2020, 8, 21), 0.095) == 0.095


def test_the_missed_board_prefixes_actually_exist_in_the_data() -> None:
    """**非空转钳制**:上面那些代码段必须在**真实库**里有数据。

    没有这条,「补上前缀」的修复可能只是在为一批不存在的代码写规则 —— 域类契约
    必须同时锁住「规则对」与「规则作用在真实存在的对象上」(附五十一/五十二 的教训)。
    """
    from pathlib import Path

    import duckdb

    from hiagent_config import get_db_path

    db = Path(get_db_path())
    if not db.exists() or db.stat().st_size == 0:
        pytest.skip(f"local DuckDB 不可用 ({db}) — 按 CLAUDE.md §6 skip 而非 error")
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT substr(thscode, 1, 3) AS pre, count(DISTINCT thscode) AS n "
            "FROM v_daily "
            "WHERE thscode LIKE '301%' OR thscode LIKE '302%' OR thscode LIKE '689%' "
            "GROUP BY 1"
        ).fetchall()
    finally:
        con.close()
    found = {r[0]: int(r[1]) for r in rows}
    for pre in ("301", "302", "689"):
        assert found.get(pre, 0) > 0, (
            f"库里没有 {pre} 开头的标的 —— 那么 _board_limit_threshold 的前缀补全"
            f"就不是在修一个真实可达的缺陷(实测:{found})"
        )


def test_cover_guard_is_board_aware_like_the_entry_guard(monkeypatch) -> None:
    """301(±20%)上开盘 +12% **不是**封板 ⇒ 回补必须照常成交。

    对照组在下面一条:同一 +12% 打在主板(±10%)上就必须被拒。
    两条合起来才说明「守卫在按板块判断」,而不是"守卫没生效"。
    """
    trades, panel = _run(cover_open=11.2, monkeypatch=monkeypatch,
                         thscode="301234.SZ")
    cover_date = panel.iloc[_COVER_BAR]["date"]
    hits = [t for t in trades if pd.Timestamp(t["exit_date"]) == cover_date]
    assert hits, (
        "§4 VIOLATION: 创业板(±20%)上 +12% 的开盘被当成涨停封板 —— 合法回补被"
        "无谓推迟。入场侧的同一事实早就走了 board-aware 阈值,只有回补侧漏了。"
    )


def test_cover_guard_still_rejects_a_sealed_bar_on_the_main_board(monkeypatch) -> None:
    """对照:主板 +12% > 10% ⇒ **确实是**封板,回补必须被拒。"""
    trades, panel = _run(cover_open=11.2, monkeypatch=monkeypatch,
                         thscode="600000.SH")
    cover_date = panel.iloc[_COVER_BAR]["date"]
    assert all(pd.Timestamp(t["exit_date"]) != cover_date for t in trades), (
        "主板 +12% 应判为封板并顺延 —— 若照常成交,说明守卫被改成了永久放行"
    )
