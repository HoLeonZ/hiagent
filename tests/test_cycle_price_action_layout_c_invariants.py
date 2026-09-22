"""cycle_price_action Layout C 结构性 phantom-free 契约 (CLAUDE.md §3).

Layout C 是单价格域, 不存在 raw/adj split → 结构无 phantom。
这些 invariant 是 Layout C phantom 防护的结构性保证:
  - engine 必须接入 core.dual_price (LAYOUT_CYCLE_PRICE)
  - exit path 必须用 bar_exec.* (extract_execution_bar 输出) 而非原始列
  - portfolio 必须保留 SL-first intraday tiebreak (CLAUDE.md §4)
  - preset 必须声明 price_source_for_execution="raw_close"
  - data_feed 必须从 v_daily 加载 (单价格域, 无 raw_*/adj_* 列)
  - replay_broker 必须 fail-fast on 数据缺口 (CLAUDE.md §0)

任何 Layout C 回归 (e.g. 引入 raw_*/adj_* 列) 必须触发 RED。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# 共享的 helper 函数 — 与 audit_phantom.py 同步
def _engine_text() -> str:
    return (ROOT / "cycle_price_action" / "backtrader_engine.py").read_text()


def _portfolio_text() -> str:
    return (ROOT / "cycle_price_action" / "portfolio.py").read_text()


def _presets_text() -> str:
    return (ROOT / "cycle_price_action" / "presets.py").read_text()


def _data_feed_text() -> str:
    return (ROOT / "cycle_price_action" / "data_feed.py").read_text()


def _broker_text() -> str:
    return (ROOT / "cycle_price_action" / "replay_broker.py").read_text()


class TestCyclePriceActionLayoutCInvariants:
    """Layout C 单价格域结构性 phantom-free — 锁定不变契约."""

    def test_engine_imports_extract_execution_bar(self):
        """backtrader_engine 必须接入 core.dual_price (4-engine 共享)."""
        assert "from core.dual_price import" in _engine_text()
        assert "extract_execution_bar" in _engine_text()

    def test_engine_uses_LAYOUT_CYCLE_PRICE(self):
        """backtrader_engine 必须显式引用 LAYOUT_CYCLE_PRICE."""
        assert "LAYOUT_CYCLE_PRICE" in _engine_text()

    def test_engine_no_raw_adj_split(self):
        """Layout C 单价格域 — engine 不应读 raw_*/adj_* 列.

        若未来切到双价格域, 这个 invariant 必须破坏 → RED → 触发
        trade-level phantom audit 重跑。
        """
        text = _engine_text()
        # 容许 layout 注释提及, 但实际代码逻辑不应直接读 raw_*/adj_* 列
        assert "raw_open" not in text, "Layout C 不应读 raw_open"
        assert "adj_open" not in text, "Layout C 不应读 adj_open"

    def test_engine_exit_path_uses_bar_exec(self):
        """exit path 必须用 bar_exec.* (extract_execution_bar 输出).

        防止直接用 self.datas[0].open[0] 等原始列绕过 Layout 抽象。
        """
        text = _engine_text()
        assert "bar_exec.open" in text
        assert "bar_exec.high" in text
        assert "bar_exec.low" in text
        assert "bar_exec.close" in text

    def test_portfolio_has_intraday_sl_first(self):
        """portfolio 必须保留 try_exit_with_intraday_check (CLAUDE.md §4)."""
        assert "try_exit_with_intraday_check" in _portfolio_text()

    def test_sl_first_in_intraday_check(self):
        """SL-first ordering: SL 判断必须在 TP 判断之前 (worst-case).

        CLAUDE.md §4: 同 bar 内 SL+TP 同时触发 → 假设 SL 先到。
        """
        text = _portfolio_text()
        body = text.split("try_exit_with_intraday_check", 1)[1].split("def ", 1)[0]
        sl_pos = body.find("open <= sl_p")  # SL @ open (gap-down)
        tp_pos = body.find("open >= tp_p")  # TP @ open (gap-up)
        assert sl_pos > 0, "缺少 SL gap-down 判断"
        assert tp_pos > 0, "缺少 TP gap-up 判断"
        assert sl_pos < tp_pos, (
            f"CLAUDE.md §4 违反: SL-first 顺序错位 "
            f"(SL pos={sl_pos}, TP pos={tp_pos})"
        )

    def test_preset_declares_price_source_intent(self):
        """presets.py 必须声明 price_source_for_signal/execution."""
        text = _presets_text()
        assert "price_source_for_signal" in text
        assert "price_source_for_execution" in text

    def test_all_presets_execution_raw_close(self):
        """所有 cycle_price_action preset 的 price_source_for_execution 必须 = raw_close."""
        from cycle_price_action import presets as cpa_presets

        preset_dicts = [
            v for n, v in vars(cpa_presets).items()
            if n.startswith("PRESET_") and isinstance(v, dict)
        ]
        assert preset_dicts, "cycle_price_action 无任何 PRESET_* 常量"
        for p in preset_dicts:
            assert p.get("price_source_for_execution") == "raw_close", (
                f"{p.get('name', '?')} price_source_for_execution "
                f"必须 = raw_close (CLAUDE.md §3 铁律)"
            )

    def test_data_feed_uses_v_daily(self):
        """data_feed.py 必须从 v_daily 视图加载 (单价格域)."""
        assert "v_daily" in _data_feed_text()

    def test_replay_broker_fail_fast(self):
        """replay_broker.py 必须 fail-fast on 数据缺口 (CLAUDE.md §0)."""
        assert "RuntimeError" in _broker_text()