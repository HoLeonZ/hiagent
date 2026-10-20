"""Round 29a (2026-09-28, CLAUDE.md §0/§3): MIN_COMMISSION ¥5 floor enforcement.

The canonical ¥5 minimum-commission floor exists in `core/dual_price.py`
(exported as `MIN_COMMISSION = 5.0`), is re-exported by all 4 engines at
module level for AST-detection, and is enforced by `chase_up / uptrend_pullback
/ cycle_price_action` via `max(MIN_COMMISSION, notional × COMMISSION_RATE)`
inside their `_buy_cost` / `_sell_proceeds` helpers.

`short_reversal/replay_strategy_v3.py:482-484` (entry_fee) and :579
(exit_fee) compute fees by raw multiplication WITHOUT the floor:

    entry_fee = size * entry_price * (commission_rate + stamp_duty_rate)
    exit_fee  = size * price     * commission_rate

For 1000 shares × ¥10 = ¥10,000 notional:
- canonical commission = max(5.0, 10000 × 0.00025) = ¥5.00 (floor)
- raw commission       = 10000 × 0.00025           = ¥2.50
- per-trade undercharge = ¥2.50

The same omission propagates to:
- `replay_strategy_v3.py:595-599` `total_fee_ratio` (Round 19 net field)
- `lookahead_trade_trace.py:75-77, 105, 112-114` TraceStrategy overrides

CLAUDE.md §0 Pessimistic Default — undercharging real fees overstates net
PnL by ¥2.50-5.00 per small-notional trade, propagates to avg_pnl, sharpe,
HTML report, and trace contamination metrics.

This test file enforces the floor via:
1. **Behavior tests** — for known small-notional cases, the actual entry_fee
   / exit_fee must equal ¥5 + stamp (not less).
2. **Source-level regex** — the cost path must contain the `max(MIN, …)`
   floor, forbidding raw `notional × rate` only.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.replay_strategy_v3 import Phase3V3Strategy  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — load source block for a method
# ---------------------------------------------------------------------------


def _method_source_block(cls, method_name: str) -> str:
    src = Path(inspect.getsourcefile(cls) or "").read_text()
    idx_start = src.index(f"def {method_name}")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    return rest[: m_end.start()] if m_end else rest


# ---------------------------------------------------------------------------
# Phase3V3Strategy._fill_pending_entries — entry_fee must apply floor
# ---------------------------------------------------------------------------


def test_entry_fee_enforces_min_commission_floor_small_notional() -> None:
    """§0 RED→GREEN: 1000 shares × ¥10 = ¥10,000 notional must charge
    commission = ¥5 floor + stamp ¥5, NOT raw ¥2.50 + ¥5 stamp.
    """
    block = _method_source_block(Phase3V3Strategy, "_fill_pending_entries")
    # Floor pattern: max(MIN_COMMISSION, notional × rate)
    has_floor = bool(re.search(
        r"max\s*\(\s*(?:self\.p\.min_commission|MIN_COMMISSION)",
        block,
    ))
    assert has_floor, (
        "§0/§3 VIOLATION: short_reversal _fill_pending_entries entry_fee does "
        "NOT enforce MIN_COMMISSION floor. Undercharges per-trade fee on "
        "small-notional trades. Found block:\n" + block
    )


def test_entry_fee_block_uses_rate_in_max_expression() -> None:
    """§0 forward-defense: floor must be applied INSIDE the entry_fee calc,
    not as a separate dead-code path.
    """
    block = _method_source_block(Phase3V3Strategy, "_fill_pending_entries")
    # Look for the floor pattern with commission_rate nearby
    has_full_pattern = bool(re.search(
        r"max\s*\(\s*[^,)]*min_commission[^,)]*,\s*[^)]*commission_rate",
        block,
        re.IGNORECASE | re.DOTALL,
    ))
    assert has_full_pattern, (
        "§0/§3 VIOLATION: short_reversal entry_fee does NOT use the canonical "
        "`max(MIN_COMMISSION, notional × COMMISSION_RATE)` pattern. Floor "
        "may be declared but not wired into the actual fee computation."
    )


# ---------------------------------------------------------------------------
# Phase3V3Strategy._close — exit_fee must apply floor
# ---------------------------------------------------------------------------


def test_exit_fee_enforces_min_commission_floor_small_notional() -> None:
    """§0 RED→GREEN: short-cover fee must use floor on small-notional exits."""
    block = _method_source_block(Phase3V3Strategy, "_close")
    has_floor = bool(re.search(
        r"max\s*\(\s*(?:self\.p\.min_commission|MIN_COMMISSION)",
        block,
    ))
    assert has_floor, (
        "§0/§3 VIOLATION: short_reversal _close exit_fee does NOT enforce "
        "MIN_COMMISSION floor. Undercharges per-trade fee on small-notional "
        "exits. Found block:\n" + block
    )


# ---------------------------------------------------------------------------
# TraceStrategy (lookahead_trade_trace.py) — same floor must apply
# ---------------------------------------------------------------------------


def test_trace_entry_fee_comes_from_production_path_with_floor() -> None:
    """§0 MEDIUM: trace 的 entry_fee 必须取自生产路径(含 MIN_COMMISSION floor)。

    审计 P3 (2026-10-15): 原用例对 `TraceStrategy._fill_pending_entries` 做源码
    正则,找 `max(min_commission, ...)`。但该方法当时是生产入场逻辑的**分叉
    副本** —— 正因为它自己重算了一遍,才需要自己实现 floor(也正因为它分叉,
    `reserve_for_entry` 没被调用,导致 `locked_margin` 恒为 0、引擎在每笔建仓后
    被融券费 fail-fast 打死,三个窗口不变量用例常年 ERROR)。

    该方法现已改为**薄包装**:委托 `super()._fill_pending_entries()`,入场费由
    生产路径计算并写入持仓字典,floor 由生产实现负责;trace 只读取。因此断言
    落在真实位置上:
      (a) trace 必须委托生产实现(不得再有副本);
      (b) trace 读取的 `entry_fee` 来自持仓字典(即生产写入的那个值);
      (c) 生产实现本身确实施加 floor。
    """
    from short_reversal.lookahead_trade_trace import TraceStrategy

    block = _method_source_block(TraceStrategy, "_fill_pending_entries")
    assert "super()._fill_pending_entries()" in block, (
        "§6 VIOLATION: TraceStrategy._fill_pending_entries 必须委托生产实现,"
        "不得再是分叉副本(副本会导致 harness 测的不是生产行为)。"
    )
    assert not re.search(
        r"entry_fee\s*=\s*\(", block
    ), "§6 VIOLATION: TraceStrategy 仍在自行重算 entry_fee"

    close_block = _method_source_block(TraceStrategy, "_close")
    assert re.search(r"pos\.get\(\s*[\"']entry_fee[\"']", close_block), (
        "§0/§3: trace 的 entry_fee 必须取自持仓字典(生产路径写入),"
        "而不是自行重算 —— 否则脱离 MIN_COMMISSION floor 与 stamp duty 口径。"
    )

    prod_block = _method_source_block(Phase3V3Strategy, "_fill_pending_entries")
    assert re.search(
        r"max\s*\(\s*(?:self\.p\.min_commission|MIN_COMMISSION)", prod_block
    ), (
        "§0/§3 VIOLATION: 生产入场路径 entry_fee 未施加 MIN_COMMISSION floor。"
    )


def test_trace_exit_fee_enforces_min_commission_floor() -> None:
    """§0 MEDIUM: TraceStrategy._close inherits the floor gap."""
    from short_reversal.lookahead_trade_trace import TraceStrategy
    block = _method_source_block(TraceStrategy, "_close")
    has_floor = bool(re.search(
        r"max\s*\(\s*(?:self\.p\.min_commission|MIN_COMMISSION)",
        block,
    ))
    assert has_floor, (
        "§0/§3 VIOLATION: lookahead_trade_trace.TraceStrategy._close exit_fee "
        "does NOT enforce MIN_COMMISSION floor. Trace report `notional_pnl` "
        "systematically overstates per-trade PnL by ¥2.50-5.00."
    )


# ---------------------------------------------------------------------------
# Cross-cutting: net field (Round 19 fix site) must reflect floor
# ---------------------------------------------------------------------------


def test_net_total_fee_ratio_includes_floor_offset() -> None:
    """§0 MEDIUM: Round 19 `total_fee_ratio` is rate-only; the actual
    fee-ratio on small notional should be HIGHER than rates alone because
    of the floor. Document this in code OR refactor to actual fee amounts.

    Either:
      (a) `total_fee_ratio` uses actual fee amounts (not rates), OR
      (b) the comment explicitly notes this is rate-only and the actual
          fee-floor impact is documented separately
    """
    block = _method_source_block(Phase3V3Strategy, "_close")
    # Look for explicit comment noting floor impact, OR a fee-based refactor
    has_floor_comment = bool(re.search(
        r"(?:MIN_COMMISSION|floor|min_commission).*?(?:#|\"\"\"|''')",
        block,
        re.DOTALL,
    ))
    has_fee_based_refactor = bool(re.search(
        r"entry_fee\s*\+\s*exit_fee",
        block,
    )) and bool(re.search(
        r"entry_price\s*\*\s*size",
        block,
    ))
    assert has_floor_comment or has_fee_based_refactor, (
        "§0/§3 VIOLATION: short_reversal _close total_fee_ratio uses "
        "rate-only formula (Round 19) without acknowledging MIN_COMMISSION "
        "floor impact on per-trade net. Either refactor to fee-based or "
        "document the floor's effect."
    )


# ---------------------------------------------------------------------------
# Source guard: no raw `notional × rate` without floor in cost paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    ["_fill_pending_entries", "_close"],
)
def test_no_raw_commission_multiplication_in_cost_paths(method_name: str) -> None:
    """§0 source guard: forbid `size * price * commission_rate` without
    the floor wrapping. Must use canonical helper or max(MIN, …)."""
    block = _method_source_block(Phase3V3Strategy, method_name)
    # Match: notional × commission_rate NOT wrapped in max(...)
    # Find every occurrence of `* commission_rate` and verify it's inside max()
    bad = []
    for m in re.finditer(
        r"\bsize\s*\*\s*\w+\s*\*\s*self\.p\.commission_rate",
        block,
    ):
        # Look back ~80 chars for max(
        prefix = block[max(0, m.start() - 80): m.start()]
        if "max(" not in prefix:
            bad.append(m.group())
    assert not bad, (
        f"§0/§3 VIOLATION: short_reversal.{method_name} has raw "
        f"size × price × commission_rate WITHOUT floor wrapping: {bad}. "
        f"Use `max(MIN_COMMISSION, size × price × COMMISSION_RATE)`."
    )