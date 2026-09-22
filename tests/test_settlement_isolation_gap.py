"""§2 Settlement Isolation RED tests: T+0 vs T+1 资金结算违反.

CLAUDE.md §2: "Differentiate Free_Cash, Locked_Margin, and Settling_Funds.
Do not assume funds from a sell order at T are available for a buy order
at T unless explicitly modeling margin borrowing with interest."

当前状态:
- chase_up/portfolio.py:237 `cash += notional - fees_out` 在同一 bar 内
  把卖出所得立即计入 cash, 后续 entry 可立即使用。
- 同 bar 迭代顺序 (lines 261+): 先 exit 后 entry → 当日卖出所得立即可用于
  当日买入 → 隐式 T+0 结算假设.
- uptrend_pullback / short_reversal / cycle_price_action 需复核 (本 tick 范围外).

后果: A 股市场 T+1 结算, 当前 backtest 把 T 日卖出所得立即用于 T 日买入,
  对 max_positions >= 2 的 preset 存在轻微 over-allocation.

本测试 RED: 当前实现只有单一 `cash` 变量, 无三态分离 (Settling_Funds /
Free_Cash / Locked_Margin).

修复方案: chase_up/portfolio.py 增加 _cash_states = {"settling": float,
"free": float, "locked_margin": float}, _close_position 把所得计入
"settling", entry 前做一次 _settle_cash() (把 settling → free).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_settling_funds_state_exists() -> None:
    """§2 强制要求 Settling_Funds / Free_Cash / Locked_Margin 三态分离。

    当前 RED: chase_up/portfolio.py 只有单一 `cash` 变量, 无三态分离。
    """
    import chase_up.portfolio as p

    src = Path(p.__file__).read_text(encoding="utf-8")

    has_settling_state = "settling" in src.lower()
    has_explicit_free_cash = (
        "Free_Cash" in src or "_free_cash" in src or "free_cash" in src
    )
    has_locked_margin = (
        "Locked_Margin" in src or "locked_margin" in src
    )

    assert has_settling_state, (
        "GAP CAPTURED: chase_up/portfolio.py 没有 Settling_Funds 状态, "
        "§2 Settlement Isolation 未落地"
    )
    assert has_explicit_free_cash, (
        "GAP CAPTURED: 没有显式 Free_Cash 状态变量"
    )
    assert has_locked_margin, (
        "GAP CAPTURED: 没有 Locked_Margin 状态变量 (持仓占用现金)"
    )


def test_close_position_does_not_credit_cash_immediately() -> None:
    """§2: _close_position 应该把卖出所得计入 Settling_Funds, 而非 cash。

    当前 RED: line 237 `cash += notional - fees_out` 立即计入 cash。
    GREEN 后: 应改为 `settling_funds += notional - fees_out`, 并在每 bar
    开始时执行 `_settle_cash()` (T+1 把 settling → free)。
    """
    import chase_up.portfolio as p

    src = Path(p.__file__).read_text(encoding="utf-8")

    # 找 _close_position 函数体
    import re
    match = re.search(
        r"def _close_position\(.*?\n(.*?)(?=\n    def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert match is not None, "_close_position 未找到"
    body = match.group(1)

    # TDD RED: 断言 _close_position 没有立即把所得计入 cash
    # 当前 (RED): body 中有 `cash += notional - fees_out` → 违规
    # GREEN 后: 应改为 `settling_funds += notional - fees_out`, 不再有 cash += notional
    immediate_credit = bool(re.search(r"cash\s*\+=\s*notional", body))

    assert not immediate_credit, (
        "GAP CAPTURED (RED): _close_position 立即把卖出所得计入 cash "
        "(line 237 `cash += notional - fees_out`), "
        "违反 §2 Settlement Isolation (T+0 vs T+1). "
        "GREEN 修复: 应改为 `settling_funds += notional - fees_out`"
    )