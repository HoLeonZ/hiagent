"""§4 融券成本: **声明必须与实现一致**。

缺陷 (2026-10-17): `short_reversal/presets.py` 的 `BORROW_ASSUMPTION` 写着
    "borrow_cost_model": "none",  # engine does not deduct borrow cost (known gap)
**与实现相反** —— `_charge_margin_fees` 一直在按 `engine.MARGIN_RATE` (8.6%/年)
逐日计息。实测把该常量置 0, W2 上 v50_slope 的 CAGR 从 -8.54% 变 +8.82%
⇒ 融券费占约 **17pp 年化**, 绝不是"未扣减"。

方向: 这是**少报了一个存在的成本** —— 与前四处虚增**方向相反**。它同样有害:
一个"未扣减成本"的声明会让读者以为回测数字是上界, 而它不是。

同时 `margin_rate` 此前**硬编码**在 engine.py (`margin_rate=MARGIN_RATE`),
preset 的 `margin_rate` 键从未被读取 —— 属"声明了却无人读取"。已接通。

教训: 五处查出的口径问题里, 四处是"让策略看起来更好", 一处是"让成本看起来更少"。
**共同点是"文档/声明都不可信"**, 而不是"错误方向一致"。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_margin_rate_is_plumbed_from_preset() -> None:
    """`margin_rate` 必须可由 preset 覆盖, 不得硬编码。"""
    eng = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")
    assert 'margin_rate=cfg.get("margin_rate", MARGIN_RATE)' in eng
    assert "margin_rate=MARGIN_RATE," not in eng


def test_declaration_states_a_rate_not_none() -> None:
    """声明必须写明真实费率, 不得再写 "none"。"""
    from short_reversal.presets import BORROW_ASSUMPTION

    assert BORROW_ASSUMPTION["borrow_cost_model"] != "none"
    assert "8.6" in BORROW_ASSUMPTION["borrow_cost_model"]


def test_declared_rate_matches_engine_constant() -> None:
    """声明里的百分数必须与 `engine.MARGIN_RATE` 对得上 —— 否则又会漂移。"""
    from short_reversal.engine import MARGIN_RATE
    from short_reversal.presets import BORROW_ASSUMPTION

    m = re.search(r"([0-9.]+)%", BORROW_ASSUMPTION["borrow_cost_model"])
    assert m, "声明里应含百分数"
    assert float(m.group(1)) == pytest.approx(MARGIN_RATE * 100, abs=0.05), (
        f"声明 {m.group(1)}% 与 MARGIN_RATE={MARGIN_RATE} 不一致"
    )


def test_availability_is_still_declared_as_an_assumption() -> None:
    """可得性仍是**假设** (引擎不做券源检查) —— 这条没有被修掉, 只是据实保留。"""
    from short_reversal.presets import BORROW_ASSUMPTION

    assert BORROW_ASSUMPTION["availability"] == "assumed_unlimited"
