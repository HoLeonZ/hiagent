"""§2 契约守卫：`try_exit_with_intraday_check` 的 `time` 分支不得提交成交。

审计 B6/V8（2026-10-15）。

`try_exit_with_intraday_check` 是"检查并出场"，但调用方
(`backtrader_engine.next`) 明确只在 `reason in ("SL","TP")` 时重置
`_entry_day`，并注释 "reason == 'time' → fall through to max_hold check
below"。而被调方此前在 `time` 分支也**无条件**写 `closed_trades`、清
`self._pos`：

  - 持仓在第一根未触发 SL/TP 的 bar 就被强平；
  - 调用方的 `max_hold` 分支成为**死代码**（`_pos` 已是 None）；
  - `_entry_day` 与实际持仓状态不一致。

即调用方与被调方的契约矛盾。本文件锁定修后的契约：`time` = 未出场，
时间出场由调用方的 `max_hold` 分支经 `try_exit()` 完成。
"""
from __future__ import annotations

from datetime import date

import pytest

from cycle_price_action.portfolio import Portfolio


def _entered() -> Portfolio:
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    return pf


def test_time_branch_does_not_commit_the_exit() -> None:
    """无触发 → 返回 ('time', close) 但**持仓必须仍在**。"""
    pf = _entered()
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10, high=10.30, low=9.90, close=10.20,
        tp_pct=0.06, sl_pct=0.05,      # tp=10.60, sl=9.50 → 均未触及
    )
    assert reason == "time"
    assert fill == pytest.approx(10.20)
    assert pf.position is not None, (
        "§2 VIOLATION: `time` 分支提交了出场（持仓被清空）—— 调用方的 "
        "max_hold 分支因此成为死代码，且 _entry_day 与实际持仓不一致"
    )
    assert pf.closed_trades == [], "`time` 分支不得写入 closed_trades"


def test_triggered_branches_do_commit() -> None:
    """反向对照：SL 触发时必须照常提交并清空持仓。"""
    pf = _entered()
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10, high=10.30, low=9.40, close=10.05,
        tp_pct=0.06, sl_pct=0.05,      # low 9.40 <= sl 9.50 → SL
    )
    assert reason == "SL"
    assert fill == pytest.approx(9.50)
    assert pf.position is None, "SL 触发必须清空持仓"
    assert len(pf.closed_trades) == 1
    assert pf.closed_trades[0]["exit_reason"] == "SL"


def test_max_hold_exit_still_commits_via_try_exit() -> None:
    """`time` 不提交之后，时间出场必须仍能经 `try_exit()` 完成。

    否则持仓将永远无法了结（把"不提交"修成了"永不退出"）。
    """
    pf = _entered()
    pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10, high=10.30, low=9.90, close=10.20,
        tp_pct=0.06, sl_pct=0.05,
    )
    assert pf.position is not None
    pnl = pf.try_exit(date(2024, 6, 5), fill_price=10.25)
    assert pf.position is None, "try_exit 必须能了结持仓"
    assert len(pf.closed_trades) == 1
    assert isinstance(pnl, float)


def test_caller_contract_is_consistent_with_callee() -> None:
    """调用方只在 SL/TP 时重置状态 —— 与被调方语义对齐（防回归成矛盾契约）。"""
    import inspect

    from cycle_price_action import backtrader_engine as eng

    src = inspect.getsource(eng.CyclePriceActionStrategy.next)
    assert 'if reason in ("SL", "TP"):' in src, (
        "调用方的出场判据已变；必须同时复核 `time` 分支是否提交（本文件锁定的契约）"
    )
    assert "max_hold" in src, "调用方必须保留 max_hold 出场分支（time 不提交后它才是活代码）"
