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
    """§0/§3 RED→GREEN: net must use total_fee_ratio (comm+stamp+exit comm)."""
    src = _src()
    assert "total_fee_ratio" in src, (
        "§0/§3: TraceStrategy._close must compute total_fee_ratio "
        "(commission + stamp_duty + exit commission) per Round 19 fix. "
        "Current code uses `gross - commission_rate` which only subtracts "
        "ONE commission and drops stamp_duty + exit_fee entirely."
    )
    # And the legacy single-line bug must be gone.
    assert "net = gross - self.p.commission_rate" not in src, (
        "§0/§3: legacy `net = gross - self.p.commission_rate` formula "
        "still present — drops stamp_duty on entry (5bp) and exit "
        "commission (~2.5bp). Systematically overstates per-trade net."
    )


def test_trace_close_notional_pnl_includes_entry_fee() -> None:
    """§0/§3 RED→GREEN: notional_pnl = (ep-price)×size − entry_fee − exit_fee.

    审计 P3 (2026-10-15): 原实现用正则要求源码里出现字面量
    `notional_pnl = float(...entry_fee...)`。它断言的对象是**源码文本**而非
    语义 —— 把同一个表达式挪进 dict 值(`"notional_pnl": float(...)`)就会
    误报,而语义一字未变(该 refactor 发生在把 TraceStrategy 改为委托生产
    实现时)。改为解析 AST 取出该值表达式再判定,对书写形式免疫。
    """
    import ast

    src = _src()
    tree = ast.parse(src)
    exprs: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "notional_pnl":
                    exprs.append(v)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "notional_pnl":
                    exprs.append(node.value)

    assert exprs, (
        "§0/§3: TraceStrategy 必须产出 notional_pnl,且扣除 entry_fee。"
    )
    # 该文件里 notional_pnl 会出现多次:产出点(float(pnl - exit_fee - entry_fee))
    # 以及汇总处的透传(t["notional_pnl"])。要求落在**产出点**上,故用 any。
    def _names(expr: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}

    assert any({"entry_fee", "exit_fee"} <= _names(e) for e in exprs), (
        "§0/§3: 没有任何 notional_pnl 产出表达式同时减去 entry_fee 与 exit_fee"
        "(Round 19 canonical: `pnl - exit_fee - entry_fee`);"
        f"各产出点引用的名字: {[sorted(_names(e)) for e in exprs]}"
    )