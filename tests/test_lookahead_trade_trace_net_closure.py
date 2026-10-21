"""§0/§3 Net Field Closure for short_reversal/lookahead_trade_trace.py (Round 24).

CLAUDE.md §0 (Pessimistic Default) + §3 (Data Integrity):
  - Per-trade `net` must reflect full cash walk: entry_fee (commission + stamp)
    on SELL entry + exit_fee (commission) on BUY exit.
  - `notional_pnl` must reflect gross_pnl − entry_fee − exit_fee (NOT just
    gross_pnl − exit_fee).

Round 19 (2026-09-28) fixed the canonical formula in
`short_reversal.replay_strategy_v3._close`:
    total_fee_ratio = (comm + stamp) + comm × (price / ep)
    net = gross_pct − total_fee_ratio

The trace subclass `TraceStrategy._close` in `lookahead_trade_trace.py`
inherited the same logic but the fix was NOT propagated (Round 24 finding):
    net = gross − commission_rate         ← only one commission, no stamp
    notional_pnl = pnl − exit_fee         ← no entry_fee subtraction

Impact:
  - `traces[].net_per_share` overstated by ~0.07%/trade
    (stamp_duty_rate 0.0005 ≈ 7.5bp per share per round-trip).
  - `traces[].notional_pnl` overstated by entry_fee per trade
    (~5bp × size). For ~425 trades (v46) ≈ 21bp of overstated PnL.
  - `pre_window_pnl_contribution_pct` and `win_rate` (derived via
    `trades[].net > 0`) drift correspondingly.

This test file pins the canonical formula on the trace subclass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.lookahead_trade_trace import TraceStrategy  # noqa: E402


# ---------------------------------------------------------------------------
# Static source RED: must mirror Round 19 canonical formula
# ---------------------------------------------------------------------------


def _src() -> str:
    return Path(TraceStrategy._close.__code__.co_filename).read_text()


def test_trace_close_uses_total_fee_ratio_not_single_commission() -> None:
    """§0/§3: trace 的 net 必须用 canonical 的 `total_fee_ratio` 口径。

    ⚠️ 2026-10-19 (§13.62): 本条此前是**源码文本钉桩** —— 要求
    `lookahead_trade_trace.py` 里出现 `"total_fee_ratio"`。
    §13.52 把 `_close` 改成**包装**(调 `super()` 后只做记录) ⇒ 那段计算搬回了父类
    ⇒ 文本不在本文件里了 ⇒ 本条变红。**与 §13.59 同一类、同一处重构的第二个牺牲者。**
    而性质**更强**了: 覆写不再自己算费用 ⇒ **不可能**与父类分叉
    (§13.51 记的那次分叉正是"子类自己抄了一份"造成的)。
    """
    src = _src()
    # ① 覆写必须**委派**
    assert "super()._close(" in src, (
        "TraceStrategy._close 必须**委派**给父类 —— 一旦它自己算费用/PnL, 就会与父类分叉"
    )
    # ② canonical 的费率口径必须确实存在(**父类那一份**)
    parent = Path(ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    assert "total_fee_ratio" in parent, (
        "§0/§3: 父类 `replay_strategy_v3._close` 未算 `total_fee_ratio` —— "
        "trace 的 net 也随之失去 canonical 口径 (Round 19/24)"
    )
    # ③ 旧的单费率写法在**两处都不得存在**
    legacy = "net = gross - self.p.commission_rate"
    assert legacy not in src and legacy not in parent, (
        "§0/§3: legacy `net = gross - self.p.commission_rate` 仍在 —— "
        "它只扣一次佣金, 丢掉 entry 的印花税 (5bp) 与 exit 佣金 (~2.5bp)"
    )


def test_trace_close_notional_pnl_includes_entry_fee() -> None:
    """§0/§3 RED→GREEN: notional_pnl = (ep-price)×size − entry_fee − exit_fee."""
    src = _src()
    # The trace record uses `notional_pnl`. Round 24 fix must include entry_fee.
    assert "notional_pnl" in src, (
        "§0/§3: TraceStrategy must emit notional_pnl with entry_fee subtracted. "
        "Current code computes `pnl − exit_fee` only, missing entry_fee."
    )
    # ⚠️ 2026-10-19 (§13.62): 同 §13.59 —— 本条此前是**源码文本钉桩**
    # (`notional_pnl = float(pnl − exit_fee − entry_fee)` 必须出现在本文件里)。
    # §13.52 把 `_close` 改成包装后, 那一行搬回了父类 ⇒ 文本不在本文件里 ⇒ 本条变红。
    # ⇒ 改为断言 trace **从 canonical 记录里取 `net_pnl`** ——
    #   那正是"含入场费"的口径 (canonical `net_pnl` 是**双边费用后**的净额),
    #   并确认父类那一份确实扣了双边费用。
    parent = Path(ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
    assert "super()._close(" in src, "TraceStrategy._close 必须委派给父类"
    assert '"net_pnl"' in src, (
        "§0/§3: trace 的 `notional_pnl` 必须取自 canonical 记录的 `net_pnl` —— "
        "若它自算 `pnl − exit_fee`, 就漏掉了 entry_fee (~5bp, entry 的印花税)"
    )
    assert "entry_fee" in parent, (
        "§0/§3: 父类未引用 `entry_fee` —— 那么 canonical `net_pnl` 也不再是双边扣费"
    )
