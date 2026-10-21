"""§2 满仓成交顺序 (single-bullet): 并发信号按统计信心排序, 默认保守不变。

⚠️ **2026-10-20 合并 main 后改名** —— 本文件原为 `test_short_reversal_fill_order.py`,
锁的是本分支的 `fill_order` 旋钮 (`'code'` / `'slope'` / `'vwap'`)。
合并把**同一个** §2 排序统一到了 main 的 `entry_selection`
(`'first'` / `'steepest_slope'`), 本分支的 `fill_order` 已删除
(对应关系写在 `short_reversal/replay_strategy_v3.py:362` 的注释里)。
⇒ 判据按新旋钮重写, **覆盖面不变**:

* 默认必须是保守的 `'first'` —— 新旋钮不得静默改变既有 preset 的结果;
* `'steepest_slope'` 必须按 `_conviction_key`(MA20 斜率, 越陡越先)排序;
* 该旋钮必须由 `engine.py` 从 preset 接上, 否则是死参数。

⚠️ **诚实的边界**: 排序那一步是**内联**在 `_fill_pending_entries` 里的
(不是独立函数), 所以对它的判据是**源码级**(钉住 `key=self._conviction_key`
与 `entry_selection == "steepest_slope"` 这个分支同时存在), 而**不是**跑一遍
完整回放。度量本身 `_conviction_key` 则是**真单元测试**(数值断言)。

本分支原来的 `'vwap'` 度量(按 收盘/VWAP 排序)未随合并保留 —— 它是**未接线**的
候选度量, 已在引擎注释中登记为未保留项。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_reversal.replay_strategy_v3 import Phase3V3Strategy as ShortReversalStrategy

_ENGINE = Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py"
_WIRING = Path(__file__).parent.parent / "short_reversal" / "engine.py"


class _FakeIndi:
    """只提供 `_conviction_key` 需要的那一格: `indi[code]['ma20_slope_5d']`。"""

    def __init__(self, indi: dict) -> None:
        self.indi = indi


# ---- 1) 默认值: 必须保守 ----


def test_default_is_the_conservative_one() -> None:
    """默认必须是 'first' —— 新参数不得静默改变既有 preset 的成交顺序。"""
    assert ShortReversalStrategy.params.entry_selection == "first"


# ---- 2) 度量本身 (真数值断言) ----


def test_conviction_key_is_the_ma20_slope() -> None:
    """conviction = MA20 斜率原值; 越负(下降越陡)越先成交。"""
    f = _FakeIndi({"600001.SH": {"ma20_slope_5d": [-0.09]}})
    assert ShortReversalStrategy._conviction_key(f, "600001.SH") == pytest.approx(-0.09)


def test_conviction_key_sorts_steepest_first() -> None:
    """升序排序 ⇒ 最陡下降排最前 (这就是 §2 的 '按统计信心依次填充')。"""
    f = _FakeIndi({
        "600001.SH": {"ma20_slope_5d": [0.01]},
        "600002.SH": {"ma20_slope_5d": [-0.09]},
        "600003.SH": {"ma20_slope_5d": [-0.05]},
    })
    codes = ["600001.SH", "600002.SH", "600003.SH"]
    assert sorted(codes, key=lambda c: ShortReversalStrategy._conviction_key(f, c)) == [
        "600002.SH", "600003.SH", "600001.SH",
    ]


@pytest.mark.parametrize("indi", [
    {},                                        # 该票无指标
    {"600001.SH": {}},                          # 无斜率键
    {"600001.SH": {"ma20_slope_5d": None}},     # 显式 None
    {"600001.SH": {"ma20_slope_5d": []}},       # 空序列
    {"600001.SH": {"ma20_slope_5d": [float("nan")]}},  # NaN
])
def test_conviction_key_degrades_to_zero(indi: dict) -> None:
    """§0: 缺失 / NaN 一律退化为 0.0(排中间), 不抛异常也不伪造顺序。"""
    f = _FakeIndi(indi)
    assert ShortReversalStrategy._conviction_key(f, "600001.SH") == 0.0


# ---- 3) 接线 (源码级: 排序是内联的) ----


def test_engine_sorts_by_conviction_under_steepest_slope() -> None:
    src = _ENGINE.read_text(encoding="utf-8")
    assert 'entry_selection == "steepest_slope"' in src, (
        "引擎必须保留按信心排序的分支, 否则 §2 single-bullet 退化成字典序"
    )
    assert "key=self._conviction_key" in src, (
        "排序必须用 `_conviction_key`, 否则顺序与信心无关"
    )


def test_engine_plumbs_entry_selection_from_preset() -> None:
    text = _WIRING.read_text(encoding="utf-8")
    assert 'entry_selection=cfg.get("entry_selection", "first")' in text, (
        "engine.py 必须把 preset 的 entry_selection 传给 strategy, 否则参数是死的"
    )
