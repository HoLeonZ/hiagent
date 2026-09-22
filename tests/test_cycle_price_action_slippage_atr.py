"""CLAUDE.md §4 ATR-aware slippage audit — cycle_price_action.

CLAUDE.md §4 铁律: Execution slippage MUST be modeled dynamically as a function of
the asset's current ATR (Average True Range) and the order's participation rate.
Do not use flat-rate slippage (e.g., 1 tick).

本测试锁定 cycle_price_action/replay_broker.py 不能使用 flat-rate slippage.

任何回归 (重新引入 fixed-bps slippage) 必须 FAIL 此测试。
"""
from __future__ import annotations

import inspect
import re

import pytest


# ============================================================ RED: 锁死 §4 违规

class TestCyclePriceActionSlippageAtR:
    """CLAUDE.md §4: cycle_price_action slippage 必须 ATR-aware, 不能 flat-rate."""

    def test_no_flat_rate_slippage_in_replay_broker(self):
        """replay_broker.py 不能有 `notional * 0.0005` 风格的固定 bps slippage.

        chase_up + uptrend_pullback + short_reversal 均已引入 atr_slip_scale
        (R5 2026-09-21 / V5' 2026-09-22, CLAUDE.md §4). cycle_price_action 此前
        用 flat-rate 5bps, 必须升级到 ATR-aware.

        锁定: replay_broker.py 不能直接定义 `slippage = notional * <fixed_bps>`.
        """
        from cycle_price_action import replay_broker

        source = inspect.getsource(replay_broker)
        # 禁止 flat-rate bps 写法 (e.g. `notional * 0.0005` / `notional * 0.001`)
        # 允许 ATR-aware 写法 (含 atr_pct / atr_slip / participation 字样)
        flat_rate_pattern = re.compile(
            r"slippage\s*=\s*notional\s*\*\s*\d+\.\d+",
            re.MULTILINE,
        )
        matches = flat_rate_pattern.findall(source)
        assert not matches, (
            f"CLAUDE.md §4 violation: cycle_price_action/replay_broker.py "
            f"使用 flat-rate slippage: {matches}. "
            f"必须改为 ATR-aware: slippage = f(atr_pct, participation)"
        )

    def test_replay_broker_has_atr_slip_scale(self):
        """replay_broker.py 必须有 atr_slip_scale 参数 (与其他 engine 对齐)."""
        from cycle_price_action import replay_broker

        source = inspect.getsource(replay_broker)
        assert "atr_slip" in source or "atr_pct" in source, (
            "CLAUDE.md §4 violation: cycle_price_action/replay_broker.py "
            "缺少 ATR-aware slippage 实现. 需参考 chase_up/portfolio.py:415-420 "
            "的 atr_slip_scale 模式"
        )

    def test_portfolio_passes_atr_to_broker(self):
        """cycle_price_action/portfolio.py 调用 broker._fee 时必须传 ATR 上下文."""
        from cycle_price_action import portfolio

        source = inspect.getsource(portfolio)
        # 应该传 atr_pct 或类似 ATR-aware 参数给 fee 计算路径
        assert "atr_pct" in source or "atr_slip" in source, (
            "CLAUDE.md §4 violation: cycle_price_action/portfolio.py "
            "未将 ATR 上下文传递给 broker fee 计算"
        )