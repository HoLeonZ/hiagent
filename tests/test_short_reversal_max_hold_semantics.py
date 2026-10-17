"""`max_hold=N` 必须恰好持有 N 根 bar —— 旧实现多持一根。

缺陷 (2026-10-17): 成交时 `entry_bar = len(self)` 存的是**计数**, 而
    `held = len(self) - 1 - pos["entry_bar"]`
把它当**索引**用 ⇒ 成交当日 `held == -1` (应为 0) ⇒ `held >= max_hold` 首次成立在
入场后第 **max_hold + 1** 根 bar ⇒ `max_hold=N` 实际持有 N+1 根。

实测 (max_hold=5, 纯持有): `603308.SH` 入场 2024-12-27, 旧实现对 2025-01-07 出场
(第 6 根), 修正后对 2025-01-06 (第 5 根); 另两笔样本同向。

族内对照: chase_up / uptrend 用 `bars = t - entry_t` (入场日 = 0) ⇒ 语义正确,
**只有 short_reversal 差一根** (族内不对称的又一例)。
同文件 `hold_days = len(self) - pos["entry_bar"]` 用的是计数口径 —— 两者本应相等,
旧实现自相矛盾, `held` 是错的一方。

影响: 修正后 v50_slope 在 W2 上 CAGR **+30.5% → -8.5%** —— 又一处虚增。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py").read_text(
    encoding="utf-8"
)


def test_held_uses_count_not_index() -> None:
    """held 必须与 hold_days 同口径 (计数), 不得再减 1。"""
    assert 'held = len(self) - pos["entry_bar"]' in SRC
    assert 'held = len(self) - 1 - pos["entry_bar"]' not in SRC


def test_entry_bar_is_stored_once_and_consistently() -> None:
    """entry_bar 只在成交处写一次, 且为 `len(self)` (计数)。"""
    m = re.findall(r'"entry_bar":\s*([^,\n]+)', SRC)
    assert m == ["len(self)"], f"entry_bar 的写法应唯一且为 len(self), 实际 {m}"


def test_hold_days_and_held_share_the_same_basis() -> None:
    """两个数量必须用同一个基准 —— 否则就是本缺陷的形态。"""
    assert 'hold_days = len(self) - pos["entry_bar"]' in SRC
