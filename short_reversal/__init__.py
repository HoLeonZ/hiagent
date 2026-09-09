"""short_reversal — A 股下降趋势反弹做空策略（v33 重写版）。

沿用 dna_strat 同款分层架构：
  universe → signals → trades (Phase 1) → backtrader (Phase 2) → 指标
"""
from __future__ import annotations

__all__ = ["ShortReversalError"]


class ShortReversalError(Exception):
    """short_reversal 包级异常基类。"""