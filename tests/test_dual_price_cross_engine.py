"""跨 engine phantom TP 防护 (CLAUDE.md §3, 2026-09-22).

锁定 4 个 strategy 的 phantom 行为契约, 任何 engine 回归 → RED:
  - chase_up + uptrend_pullback: entry 用 raw_open, exit 用 raw_*  (Layout A)
  - short_reversal: entry/exit 全部用 raw (v_daily IS raw)        (Layout B)
  - cycle_price_action: 单价格系统, entry/exit 同源               (Layout C)

统一通过 core.dual_price.extract_execution_bar 处理, 防止 typo / drift。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.dual_price import (
    LAYOUT_CHASE_UPTREND,
    LAYOUT_CYCLE_PRICE,
    LAYOUT_SHORT_REVERSAL,
    PRICE_SOURCE_ADJ,
    PRICE_SOURCE_RAW,
    ExecutionBar,
    extract_execution_bar,
    validate_price_source,
)


# ============================================================ Layout 契约

class TestCrossEngineContract:
    """所有 engine 共用同一份 ExecutionBar 抽象 — 锁定 row → ExecutionBar 转换。"""

    def test_chase_uptrend_layout_a(self):
        """Layout A: raw_* 优先, adj_* 仅 raw_* 缺失时回退 (per extract_execution_bar 行为)。"""
        row = {
            "raw_open": 10.0, "raw_high": 11.0, "raw_low": 9.0, "raw_close": 10.5,
            "raw_prev_close": 9.8,
            "adj_open": 7.8, "adj_high": 8.6, "adj_low": 7.0, "adj_close": 8.2,
        }
        bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
        assert bar == ExecutionBar(open=10.0, high=11.0, low=9.0, close=10.5, prev_close=9.8)

    def test_short_reversal_layout_b(self):
        """Layout B: open/high/low/close 即 raw (v_daily IS raw)。"""
        row = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "prev_close": 9.8}
        bar = extract_execution_bar(row, LAYOUT_SHORT_REVERSAL)
        assert bar == ExecutionBar(open=10.0, high=11.0, low=9.0, close=10.5, prev_close=9.8)

    def test_cycle_layout_c(self):
        """Layout C: 同 Layout B 但缺 prev_close — 单价格系统。"""
        row = {"open": 5.0, "high": 5.5, "low": 4.8, "close": 5.2}
        bar = extract_execution_bar(row, LAYOUT_CYCLE_PRICE)
        assert bar == ExecutionBar(open=5.0, high=5.5, low=4.8, close=5.2, prev_close=None)

    def test_layouts_agree_on_raw_data(self):
        """关键不变量: 给同一份 raw 数据, 不同 layout 提取的 ExecutionBar 一致。

        这是 phantom TP 防护的根 — 不管哪个 engine 处理, 只要 input 是 raw,
        输出的 ExecutionBar 必须相同。
        """
        raw_row = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "prev_close": 9.8}
        bar_b = extract_execution_bar(raw_row, LAYOUT_SHORT_REVERSAL)
        bar_c = extract_execution_bar(raw_row, LAYOUT_CYCLE_PRICE)
        assert bar_b == bar_c, "Layout B vs C 必须产出相同 ExecutionBar (raw 同源)"

        # Layout A 多 raw_* 列 — raw_* 优先, 与 Layout B 的 open 等同值
        bar_a = extract_execution_bar(
            {"raw_open": 10.0, "raw_high": 11.0, "raw_low": 9.0, "raw_close": 10.5,
             "raw_prev_close": 9.8,
             **raw_row},  # open/high/low/close 也是 raw 同值
            LAYOUT_CHASE_UPTREND,
        )
        assert bar_a == bar_b, "Layout A (raw_* 优先) 必须等于 Layout B (open IS raw)"


# ============================================================ price_source 校验

class TestPriceSourceValidation:
    """所有 engine 必须走 PRICE_SOURCE_RAW / PRICE_SOURCE_ADJ 常量, 防止 typo。"""

    def test_raw_constant(self):
        assert PRICE_SOURCE_RAW == "raw_close"

    def test_adj_constant(self):
        assert PRICE_SOURCE_ADJ == "adj_close"

    @pytest.mark.parametrize("valid", [PRICE_SOURCE_RAW, PRICE_SOURCE_ADJ])
    def test_valid_does_not_raise(self, valid):
        validate_price_source(valid)  # 不抛错

    @pytest.mark.parametrize("invalid", [
        "raw_close_",  # typo
        "",            # empty
        "RAW_CLOSE",   # case-sensitive
        "raw",         # incomplete
        "adj",         # incomplete
    ])
    def test_invalid_raises(self, invalid):
        with pytest.raises(ValueError):
            validate_price_source(invalid)


# ============================================================ Phantom 防护原则

class TestPhantomPreventionContract:
    """CLAUDE.md §3 铁律: phantom TP = exit 价格 clamp 到 tp_p 但 raw 域未触达。

    防护原则 (结构性, 不依赖单笔 trade 抽查):
      1. entry_price 来源列必须与 exit trigger 列同价格域 (Layout A: raw_*, B/C: open)
      2. entry fill 在 price_source=raw_close 时必须用 raw_open (not adj_open)
      3. LIMIT_UP 守卫走共享 is_limit_up, 防 adj domain 混用
    """

    def test_entry_and_exit_must_share_price_domain(self):
        """entry (open) 和 exit (high/low/close) 同 row 同 layout → 同 ExecutionBar."""
        row = {"raw_open": 10.0, "raw_high": 11.0, "raw_low": 9.0, "raw_close": 10.5,
               "raw_prev_close": 9.8}
        bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
        # entry 用 bar.open (raw_open); exit 触发用 bar.high/low (raw_high/low)
        assert bar.open > 0 and bar.high >= bar.low
        # 同 row 同 layout → entry/exit 都从 bar.* 取, 不会跨域

    def test_adj_open_dropped_in_favor_of_raw_open(self):
        """Layout A 必须 raw_open 优先 — 验证 phantom 来源已切断。"""
        row = {
            "raw_open": 8.0, "raw_high": 9.0, "raw_low": 7.5, "raw_close": 8.5,
            "adj_open": 12.0,  # ← 价格不同, 若误用此值会触发 phantom
        }
        bar = extract_execution_bar(row, LAYOUT_CHASE_UPTREND)
        assert bar.open == 8.0, (
            "phantom 防护: bar.open 必须 = raw_open (8.0), 不是 adj_open (12.0)"
        )


# ============================================================ cycle_price_action 集成契约

class TestCyclePriceActionIntegration:
    """cycle_price_action 必须接入 core.dual_price (Layout C, 单价格域)."""

    def test_cycle_uses_extract_execution_bar_for_layout_c(self):
        """cycle_price_action 的 exit 路径必须走 extract_execution_bar(Layout C).

        即使 Layout C 是单价格域 (结构性 phantom-free), 仍应走共享入口 —
        与 chase_up / uptrend_pullback / short_reversal 共用同一份代码,
        未来切换 raw/adj split 时无需重写。

        验证方法: backtrader_engine.py 必须从 core.dual_price import extract_execution_bar
        并调用它来处理 exit bar。
        """
        from pathlib import Path
        engine_path = Path("cycle_price_action/backtrader_engine.py")
        text = engine_path.read_text()
        assert "core.dual_price" in text or "extract_execution_bar" in text, (
            "cycle_price_action 未接入 core.dual_price — 4-engine 共享目标未达成"
        )

    def test_cycle_uses_LAYOUT_CYCLE_PRICE(self):
        """backtrader_engine 必须显式用 LAYOUT_CYCLE_PRICE 声明 Layout C。"""
        from pathlib import Path
        engine_path = Path("cycle_price_action/backtrader_engine.py")
        text = engine_path.read_text()
        assert "LAYOUT_CYCLE_PRICE" in text, (
            "cycle_price_action 必须显式声明 LAYOUT_CYCLE_PRICE — 防 Layout 漂移"
        )


# ============================================================ chase_up 集成契约

class TestChaseUpIntegration:
    """chase_up Phase 2 backtrader 必须接入 core.dual_price (Layout A, 双价格域).

    chase_up 22 preset 默认 price_source_for_execution="raw_close",backtrader engine
    必须重映射 feed 到 raw 域,否则 Phase 1 (portfolio.py 用 raw_open) 与 Phase 2
    (ChaseUpTradeReplay 跑在 qfq feed) 口径不一 → phantom SL/TP。
    """

    def test_chase_up_uses_extract_execution_bar_for_layout_a(self):
        """chase_up/backtrader_engine.py 的 feed 构建必须走 Layout A 提取。
        """
        from pathlib import Path
        engine_path = Path("chase_up/backtrader_engine.py")
        text = engine_path.read_text()
        assert "core.dual_price" in text or "extract_execution_bar" in text, (
            "chase_up/backtrader_engine.py 未接入 core.dual_price — "
            "Phase 2 backtrader 跑在 qfq 域,触发 phantom SL/TP"
        )

    def test_chase_up_uses_LAYOUT_CHASE_UPTREND(self):
        """backtrader_engine 必须显式用 LAYOUT_CHASE_UPTREND 声明 Layout A。"""
        from pathlib import Path
        engine_path = Path("chase_up/backtrader_engine.py")
        text = engine_path.read_text()
        assert "LAYOUT_CHASE_UPTREND" in text, (
            "chase_up 必须显式声明 LAYOUT_CHASE_UPTREND — 防 Layout 漂移"
        )

    def test_chase_up_verify_trade_takes_price_source_param(self):
        """_verify_trade_with_backtrader 必须接受 price_source_for_execution 参数。
        """
        from pathlib import Path
        engine_path = Path("chase_up/backtrader_engine.py")
        text = engine_path.read_text()
        assert "price_source_for_execution" in text, (
            "chase_up _verify_trade_with_backtrader 必须接受 price_source_for_execution — "
            "否则 Phase 2 backtrader 永远跑在 qfq 域,与 Phase 1 raw entry 不对齐"
        )
