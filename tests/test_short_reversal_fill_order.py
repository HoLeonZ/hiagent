"""§2 满仓成交顺序: 默认字典序不变, slope 模式按 conviction 降序。

背景: 旧实现 `for d in self.datas` —— 即 thscode 字典序。名额被字母序最小的几只
票占满, 与信号强度无关。§2 要求「sort them by statistical conviction …, and
fill strictly in that order」。本组测试锁定新加的显式排序, 并锁定默认不变。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_reversal.replay_strategy_v3 import Phase3V3Strategy as ShortReversalStrategy


class _Data:
    def __init__(self, name: str) -> None:
        self._name = name


class _Params:
    def __init__(self, fill_order: str) -> None:
        self.fill_order = fill_order


class _Fake:
    """只提供 _fill_order() 用到的三样东西。"""

    def __init__(self, fill_order: str, pending: dict) -> None:
        self.datas = [_Data(c) for c in pending]           # feed 顺序 = 字典序
        self.pending_entries = pending
        self.p = _Params(fill_order)

    def order(self) -> list[str]:
        return [d._name for d in ShortReversalStrategy._fill_order(self)]


# pending_entries 存的是 conviction = -MA20_slope (见 Phase3V3Strategy._conviction):
# 趋势越陡 (slope 越负) conviction 越高。
def test_default_is_feed_order() -> None:
    """默认 'code': 保持历史行为 —— 顺序与 conviction 无关。"""
    f = _Fake("code", {"600001.SH": 0.01, "600002.SH": 0.09, "600003.SH": 0.05})
    assert f.order() == ["600001.SH", "600002.SH", "600003.SH"]


def test_slope_mode_sorts_by_conviction_then_code() -> None:
    """'slope': conviction 越高越先成交; 平分按 thscode。"""
    f = _Fake("slope", {"600001.SH": 0.01, "600002.SH": 0.09, "600003.SH": 0.05})
    assert f.order() == ["600002.SH", "600003.SH", "600001.SH"]


def test_slope_mode_ties_fall_back_to_code() -> None:
    f = _Fake("slope", {"600003.SH": 0.05, "600001.SH": 0.05, "600002.SH": 0.05})
    assert f.order() == ["600001.SH", "600002.SH", "600003.SH"]


def test_only_pending_codes_are_returned() -> None:
    f = _Fake("slope", {"600001.SH": 0.0})
    f.datas = [_Data("600001.SH"), _Data("600099.SH")]
    assert f.order() == ["600001.SH"]


def test_fill_order_param_exists_with_safe_default() -> None:
    """默认必须是 'code' —— 新参数不得静默改变既有 preset 的结果。"""
    assert ShortReversalStrategy.params.fill_order == "code"


def test_engine_plumbs_fill_order_from_preset() -> None:
    text = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert 'fill_order=cfg.get("fill_order", "code")' in text, (
        "engine.py 必须把 preset 的 fill_order 传给 strategy, 否则参数是死的"
    )


class _DataVwap(_Data):
    """带 amount/volume 的 feed 桩。"""

    def __init__(self, name: str, close: float, amount: float, volume: float) -> None:
        super().__init__(name)
        self.close = [close]
        self.amount = [amount]
        self.volume = [volume]


class _FakeVwap:
    def __init__(self, rows: list[_DataVwap], fill_order: str) -> None:
        self.datas = rows
        self.pending_entries = {r._name: 0.0 for r in rows}
        self.p = _Params(fill_order)
        self.pending_entries = {
            r._name: ShortReversalStrategy._conviction(self, r) for r in rows
        }

    def order(self) -> list[str]:
        return [d._name for d in ShortReversalStrategy._fill_order(self)]


def test_vwap_conviction_prefers_close_below_vwap() -> None:
    """'vwap': 收盘越低于当日成交均价, conviction 越高 (越先成交)。"""
    below = _DataVwap("600001.SH", close=10.0, amount=1000 * 10.1, volume=1000)  # vwap 10.1
    above = _DataVwap("600002.SH", close=10.0, amount=1000 * 9.9, volume=1000)   # vwap 9.9
    f = _FakeVwap([above, below], "vwap")
    assert f.order()[0] == "600001.SH", "收盘低于 VWAP 的那只应排在前"


def test_vwap_conviction_falls_back_on_missing_volume() -> None:
    """§0: 量价缺失时退化为 0.0 (同级), 不抛异常也不伪造顺序。"""
    bad = _DataVwap("600001.SH", close=10.0, amount=0.0, volume=0.0)
    f = _FakeVwap([bad], "vwap")
    assert f.pending_entries["600001.SH"] == 0.0
