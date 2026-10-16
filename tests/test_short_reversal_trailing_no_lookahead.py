"""§1 修正: 浮动止损的止损位只能用**截至上一根 bar** 的信息构造。

缺陷 (2026-10-17 发现并修):
    旧实现
        lowest = min(pos["lowest_price"], low)   # 用**本 bar 的 low** 定出止损位
        ...
        elif high >= sl_p:                       # 又用**本 bar 的 high** 判触发
    两者同处一根 bar, 等价于假设"当日最低价出现在最高价之前" —— 而日线数据不
    提供这个次序。随着 trailing_stop_pct → 0, 成交价趋近当日最低价, 于是指标
    **单调**改善 (实测 W2 Calmar 60→63→81→101→116, 无拐点): 这是在区间内取
    最大有利偏移, 不是优势。

修法: 触发判定用 `prev_lowest` (截至上一根 bar 的最低), 本 bar 的 low 只在出场
判定之后并入跟踪价。悲观方向, 与 §4「同一 bar 内不确定次序时取最坏情形」同精神。

本文件是**结构 + 行为**双层钉桩:
  - 结构断言锁定因果顺序 (防止有人把 min(...) 挪回判定之前);
  - 行为断言用真实回测锁定量级 —— 修好后 v73 在 W2 上的 Calmar 从 60.1 降到 51.0,
    即该缺陷此前虚增了约 18% 的风险调整收益。任何让这个数字回到 60 附近的改动
    都是把缺陷改回来了。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ENGINE = Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py"
SRC = ENGINE.read_text(encoding="utf-8")


def test_trailing_trigger_uses_previous_bar_low() -> None:
    """止损位必须由 prev_lowest (截至上一根 bar) 构造, 不能用本 bar 的 low。"""
    assert "prev_lowest = pos[\"lowest_price\"]" in SRC, (
        "浮动止损必须显式取上一根 bar 的 lowest_price 作为止损位输入"
    )
    assert "trail_p = prev_lowest * (1 + self.p.trailing_stop_pct)" in SRC, (
        "止损位必须由 prev_lowest 构造 —— 用本 bar 的 low 是 §1 within-bar 缺陷"
    )


def test_no_same_bar_low_updates_the_stop() -> None:
    """禁止 `lowest = min(pos['lowest_price'], low)` 出现在出场判定之前。"""
    assert 'lowest = min(pos["lowest_price"], low)' not in SRC, (
        "本 bar 的 low 不得参与本 bar 的止损位构造 (that is the within-bar look-ahead)"
    )


def test_tracking_low_is_updated_only_after_the_exit_decision() -> None:
    """跟踪最低价的更新必须排在 `_close(...)` 之后 (即出场判定之后)。"""
    close_at = SRC.index('self._close(d, price, reason)\n            return')
    update_at = SRC.index('"lowest_price": min(prev_lowest, low)')
    assert update_at > close_at, (
        "跟踪最低价必须在出场判定之后更新, 否则下一根 bar 会用到本 bar 的信息"
    )


def test_trailing_still_off_by_default() -> None:
    """默认必须关闭 —— 该机制是 opt-in, 不得静默改变既有 preset。"""
    m = re.search(r"trailing_stop_pct=([0-9.]+)", SRC)
    assert m and float(m.group(1)) == 0.0


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "short_reversal" / "results").exists(),
    reason="需要本地回测产物",
)
def test_corrected_v73_is_not_the_inflated_number() -> None:
    """行为层: 修正后的 v73 不得回到缺陷时代的量级 (Calmar ~60)。

    这条断言读的是固定窗口的回测结果文件; 缺失时跳过 (§6: 测试不得因
    本地产物缺失而 error)。60.1 是 within-bar 缺陷时代的数字, 修正后为 51.0。
    """
    import json

    f = Path("/tmp/hiagent_mining/sr6/fix_v73.json")
    if not f.exists():
        pytest.skip("本地回测产物缺失")
    d = json.loads(f.read_text())
    calmar = d["cagr"] / d["max_dd"]
    assert calmar < 58.0, (
        f"修正后的 v73 Calmar={calmar:.1f} 已接近缺陷时代的 60.1 —— "
        f"疑似 within-bar look-ahead 被改回来了"
    )
