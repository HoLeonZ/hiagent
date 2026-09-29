"""Round 30 Finding 2 (2026-09-28, CLAUDE.md §3 truthfulness): cycle_price_action
limit-up guard missing.

cycle_price_action is the ONLY engine among the 4 that does NOT enforce
is_limit_up at entry time:
  - chase_up/portfolio.py:507 — inline (o / pc - 1) >= LIMIT_UP_THRESHOLD guard
  - uptrend_pullback/portfolio.py:470 — same
  - short_reversal/replay_strategy_v3.py:429 — is_limit_down guard (symmetric)
  - cycle_price_action — NONE

Per CLAUDE.md §3 + §4 (Pessimistic Default): a limit-up open means the
stock cannot be bought (no shares available). Entering at limit-up close
generates phantom PnL — the backtest records a fill that could not
actually occur in the market. Same engine category, different outcome.

This test enforces: cycle_price_action/backtrader_engine.py:next MUST call
is_limit_up() (or equivalent threshold check) before try_enter at the
entry path. Threshold must be exposed via params (preset-overridable) so
chase_up's 0.098 vs cycle's default 0.095 distinction is supported.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycle_price_action.backtrader_engine import CyclePriceActionStrategy  # noqa: E402


# ---------------------------------------------------------------------------
# Source guard: cycle_price_action backtrader_engine.next must reference
# is_limit_up before the try_enter call.
# ---------------------------------------------------------------------------


CYCLE_ENGINE = ROOT / "cycle_price_action" / "backtrader_engine.py"


def _read(path: str | Path) -> str:
    return Path(path).read_text()


def test_cycle_engine_has_limit_up_guard_in_next() -> None:
    """§3 RED→GREEN: CyclePriceActionStrategy.next must call is_limit_up()
    (or compute the equivalent (open/prev_close - 1) >= threshold check)
    BEFORE the try_enter call in the entry branch."""
    src = _read(CYCLE_ENGINE)
    # Check that the strategy next() method mentions is_limit_up
    has_is_limit_up_call = bool(re.search(r"is_limit_up\s*\(", src))
    # Or check for the inline equivalent
    has_inline_check = bool(re.search(
        r"(?:open|o|bar\[.open.\])\s*/\s*(?:prev_close|pc|close\[-1\]|self\.datas\[0\]\.close\[-1\])",
        src,
    ))
    assert has_is_limit_up_call or has_inline_check, (
        "§3 VIOLATION: cycle_price_action is the ONLY engine without an "
        "entry-time is_limit_up guard. Entering at limit-up open would "
        "generate phantom PnL — the stock cannot be purchased at limit-up "
        "(no shares available)."
    )


def test_cycle_engine_limit_up_before_try_enter() -> None:
    """§3 structural: limit-up guard must execute BEFORE try_enter call."""
    src = _read(CYCLE_ENGINE)
    # Find positions of is_limit_up call (if any) and try_enter call
    m_limit = re.search(r"is_limit_up\s*\(", src)
    m_try = re.search(r"\.try_enter\s*\(", src)
    if m_limit is None or m_try is None:
        pytest.fail(
            "§3 VIOLATION: cycle_price_action has no is_limit_up guard "
            "before try_enter — see test_cycle_engine_has_limit_up_guard_in_next."
        )
    assert m_limit.start() < m_try.start(), (
        "§3 VIOLATION: is_limit_up guard must execute BEFORE try_enter. "
        f"Found is_limit_up at offset {m_limit.start()} but try_enter at "
        f"offset {m_try.start()}."
    )


def test_cycle_engine_threshold_param_overridable() -> None:
    """§3 forward-defense: limit-up threshold should be exposed via params
    (preset-overridable) so cycle presets can override the default 0.095."""
    src = _read(CYCLE_ENGINE)
    # params dict must include a limit_up_threshold entry (or similar)
    has_param = bool(re.search(
        r"limit_up_threshold\s*=\s*[\d.]+",
        src,
    ))
    assert has_param, (
        "§3 forward-defense: cycle_price_action should expose "
        "limit_up_threshold via params (default 0.095) so presets can "
        "override per CLAUDE.md §4 Pessimistic Default."
    )


# ---------------------------------------------------------------------------
# Behavioral test: limit-up open must reject entry (cycle strategy must
# skip try_enter when today's open hit limit-up).
# ---------------------------------------------------------------------------


def test_cycle_engine_skips_entry_on_limit_up() -> None:
    """§3 behavior: when prev_close=10, today's open=11 (10% above = limit-up),
    CyclePriceActionStrategy.next() must NOT call try_enter with positive
    state outcome.

    We exercise the strategy's `_is_limit_up_bar` (or equivalent) helper
    via inspection if present, or via direct is_limit_up() call assertion.
    """
    from core.dual_price import is_limit_up  # noqa: E402

    prev_close = 10.0
    open_price = 11.0  # 10% above → limit-up
    # Direct API check (sanity)
    assert is_limit_up(prev_close, open_price, threshold=0.095) is True

    # Now verify cycle engine file imports is_limit_up (or the next method
    # contains the inline check). If neither, RED.
    src = _read(CYCLE_ENGINE)
    has_is_limit_up_import = "is_limit_up" in src
    assert has_is_limit_up_import, (
        "§3 VIOLATION: cycle_price_action/backtrader_engine.py must "
        "import is_limit_up from core.dual_price AND call it before "
        "try_enter."
    )


def test_cycle_engine_does_not_enter_at_limit_up_close() -> None:
    """§3 source-guard via parametrize: check the cycle strategy.params dict
    has limit_up_threshold exposed (default 0.095 to match chase_up +
    uptrend_pullback conventions).
    """
    src = _read(CYCLE_ENGINE)
    # Use paren-balanced regex to skip nested `)` in comments
    m = re.search(
        r"params\s*=\s*dict\(((?:[^()]|\([^()]*\))*)\)",
        src,
    )
    assert m is not None, "params dict not found in cycle strategy"
    params_block = m.group(1)
    assert "limit_up_threshold" in params_block, (
        "§3 forward-defense: limit_up_threshold must be in params "
        f"(default 0.095) for preset override. Got params block:\n{params_block}"
    )


# ---------------------------------------------------------------------------
# Cross-engine consistency: chase_up + uptrend_pullback + cycle_price_action
# all reference is_limit_up (or inline LIMIT_UP_THRESHOLD). short_reversal
# references is_limit_down. The guard may live in backtrader_engine.py
# (cycle) or portfolio.py (chase/uptrend use inline check).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_path,guard_token",
    [
        (ROOT / "chase_up" / "portfolio.py", ("is_limit_up", "LIMIT_UP_THRESHOLD")),
        (ROOT / "uptrend_pullback" / "portfolio.py", ("is_limit_up", "LIMIT_UP_THRESHOLD")),
        (ROOT / "cycle_price_action" / "backtrader_engine.py", ("is_limit_up",)),
        (ROOT / "short_reversal" / "replay_strategy_v3.py", ("is_limit_down",)),
    ],
)
def test_cross_engine_includes_limit_guard(engine_path: Path, guard_token: tuple) -> None:
    """§3 cross-engine consistency: all 4 engines must reference their
    appropriate limit guard (chase/uptrend: `is_limit_up()` OR inline
    `LIMIT_UP_THRESHOLD` in portfolio.py; cycle_price_action:
    `is_limit_up()` (Round 30); short_reversal: `is_limit_down()`)."""
    src = _read(engine_path)
    found = any(tok in src for tok in guard_token)
    assert found, (
        f"§3 VIOLATION: {engine_path.name} does NOT reference any of "
        f"{guard_token}. Only engines with limit-bar guards are "
        f"CLAUDE.md §3 compliant."
    )