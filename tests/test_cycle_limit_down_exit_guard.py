"""§4 卖方跌停 no-fill 守卫 —— **cycle_price_action 此前全包零处 `is_limit_down`**。

CLAUDE.md §4(逐字):"a sell/cover on a limit-down-sealed bar MUST be rejected
(no fill)"。长仓出场是一次 SELL ⇒ 跌停封板日卖不出去,成交不能凭空发生。

## 为什么这条值得单独钉

`tests/test_limit_down_exit_guard.py`(审计 P1-9)为这个缺陷族写过守卫,但它建在
`chase_up.portfolio.simulate_portfolio` 上 —— 而**同一个** P1-9 修复也改到了
`uptrend_pullback`(两处都有 `is_limit_down`)。`cycle_price_action` 全包
**零处**:它是唯一一个"长仓 + 无跌停出场门"的引擎。而它的入场侧涨停门(Round 30)
早就补上了 —— 于是出现"买不进去有门、卖不出去没门"的单侧缺口。

(与附五十一/五十三 同族:守卫只覆盖了缺陷族的一部分,"锁一处 ≠ 锁一族"。)

## 归属层

`tests/test_cycle_limit_up_guard.py::test_cycle_limit_up_guard_lives_in_the_execution_layer`
裁定:涨跌停不可成交是**执行**约束,归 `Portfolio`(§6 一条规则一处归属)。
故跌停侧的规则实现也放在 `Portfolio`,由两个决策点(SL/TP 出场判定、max_hold 出场)
复用同一个谓词 `exit_blocked_by_limit_down`。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from cycle_price_action.portfolio import Portfolio  # noqa: E402


def _pf_with_position(**kw) -> Portfolio:
    pf = Portfolio(cash=100_000.0, **kw)
    st = pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    assert st is not None, "夹具未建仓"
    return pf


# ---------------------------------------------------------------------------
# 行为
# ---------------------------------------------------------------------------


def test_limit_down_sealed_bar_blocks_the_exit() -> None:
    """-10% 开盘(封板)→ 不得出场,且**持仓必须保留**。"""
    pf = _pf_with_position()
    before = pf.position.shares
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=9.0, high=9.0, low=9.0, close=9.0,     # -10%
        tp_pct=0.06, sl_pct=0.05,
        prev_close=10.0,
    )
    assert reason == "limit_down", (
        f"§4 VIOLATION: 跌停封板 bar 上仍作出场判定(返回 {reason!r})—— "
        f"卖不出去的成交不能凭空发生"
    )
    assert fill == 0.0 and pf.position is not None
    assert pf.position.shares == before


def test_non_limit_down_bar_still_exits(monkeypatch) -> None:
    """反向对照:-6% 开盘**不是**封板 ⇒ 该出的照出(证明上一条是守卫在起作用)。"""
    pf = _pf_with_position()
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=9.4, high=9.5, low=9.3, close=9.4,     # -6%,触 SL(@9.5)
        tp_pct=0.06, sl_pct=0.05,
        prev_close=10.0,
    )
    assert reason == "SL", f"-6% 开盘不该被封板门挡住,实际 {reason!r}"
    assert fill == pytest.approx(9.4)


def test_threshold_is_symmetric_and_overrideable() -> None:
    """默认 0.095;可被构造参数覆盖(与入场侧的 is_limit_up_threshold 镜像)。"""
    pf = Portfolio(cash=100_000.0)
    assert pf.exit_blocked_by_limit_down(10.0, 9.0) is True       # -10%
    assert pf.exit_blocked_by_limit_down(10.0, 9.4) is False      # -6%
    assert pf.exit_blocked_by_limit_down(None, 9.0) is False      # 无前收 → best-effort
    strict = Portfolio(cash=100_000.0, is_limit_down_threshold=0.05)
    assert strict.exit_blocked_by_limit_down(10.0, 9.4) is True   # -6% ≥ 5% 阈值


# ---------------------------------------------------------------------------
# §6 单层归属:规则在执行层,且生产路径确实把 prev_close 递下去
# ---------------------------------------------------------------------------


def test_the_guard_lives_in_the_execution_layer_and_is_reachable() -> None:
    """(a) 执行层实现了它;(b) 生产路径把 prev_close 传下去 —— 否则守卫不可达。"""
    port = (ROOT / "cycle_price_action/portfolio.py").read_text(encoding="utf-8")
    assert "is_limit_down" in port, (
        "§4 VIOLATION: Portfolio 未实现跌停守卫(§6:该规则归执行层)"
    )
    assert re.search(r"def exit_blocked_by_limit_down", port), (
        "§4 VIOLATION: 缺少唯一的谓词实现 —— 规则被抄成两份就会各自演化"
    )
    engine = (ROOT / "cycle_price_action/backtrader_engine.py").read_text(encoding="utf-8")
    assert re.search(r"prev_close=prev_close", engine), (
        "§4 VIOLATION: 引擎未把 prev_close 传给出场判定 —— "
        "执行层的跌停守卫在生产路径上不可达(与涨停侧同一课)"
    )
    assert "exit_blocked_by_limit_down" in engine, (
        "§4 VIOLATION: max_hold 出场路径未过同一道门"
    )
