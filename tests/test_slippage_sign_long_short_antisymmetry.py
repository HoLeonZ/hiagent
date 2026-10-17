"""§4/§0: 执行滑点在**多头与空头上的符号必须相反**。

    多头 (chase_up / uptrend_pullback):  entry = open × (1 + slip)   买得更贵 = 悲观 ✓
    空头 (short_reversal):               entry = open × (1 − slip)   卖得更便宜 = 悲观 ✓

缺陷 (2026-10-17 发现并修): `short_reversal/replay_strategy_v3.py` 原为
`entry_price × (1.0 + atr_slip)` —— 但 short 的 entry 是**卖出**,
**上调卖出价恰恰是收到更多**。原注释自己写着
"slippage 上调 sell price (即收到的 sale proceeds 减少) —— pessimistic 假设'卖得更贵'":
**"上调卖出价" 与 "收到更少" 互相矛盾**, 而代码执行的是前者。
⇒ 该式把**执行成本记成了执行收益**, 方向与 §0「Pessimistic Default」相反。
同一个矛盾也写在 `core/dual_price.atr_slippage` 的 docstring 里 (已一并更正)。

**为什么这是"可直接修"而不是"登记"**: 该分支只在 `atr_slip_scale > 0` 时执行,
而全部 55 个 short_reversal preset 都不声明它 (引擎默认 `0.0`)
⇒ 分支今天**不可达** ⇒ 修正**不产生任何结果漂移** (本文件第 1 条测试钉住这一点)。
但它是**陷阱**: 谁一旦为落实 §4 打开滑点, 就会静默地把空头成交记成更有利。

⚠️ 本文件刻意**不**写"两个字段互相一致"式的断言 —— 那类断言在同源时恒真
(见 tests/test_short_reversal_cagr_period_basis.py 的记载)。这里钉的是
**跨引擎的符号反号关系**: 只改 short_reversal 回到 `+` 会红, 把多头一起改成 `−` 也会红。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

SHORT_SRC = (ROOT / "short_reversal" / "replay_strategy_v3.py").read_text(encoding="utf-8")
CORE_SRC = (ROOT / "core" / "dual_price.py").read_text(encoding="utf-8")


def _long_signs() -> dict[str, str]:
    """多头引擎 entry 滑点后的乘号, 逐文件取。"""
    out = {}
    for rel in ("chase_up/portfolio.py", "uptrend_pullback/portfolio.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        # 只取 "atr_slip" 分支里的 entry_px 赋值
        m = re.search(r"atr_slip = [^\n]*\n\s*if atr_slip > slippage:\s*\n\s*entry_px = float\(o\) \* \(1 (.) atr_slip\)", src)
        out[rel] = m.group(1) if m else "?"
    return out


def test_short_entry_slippage_takes_the_negative_sign() -> None:
    """空头 entry 是卖出 ⇒ 冲击让成交价更低 ⇒ 必须是 `(1.0 - atr_slip)`。"""
    assert "entry_price = entry_price * (1.0 - atr_slip)" in SHORT_SRC, (
        "short_reversal 的 entry 滑点符号不对。空头 entry 是**卖出**, 悲观方向是"
        "成交价更低 ⇒ 必须取减号。取加号 = 把执行成本记成执行收益 (§0 违规)。"
    )


def test_short_entry_slippage_does_not_take_the_positive_sign() -> None:
    """反向钉桩: 旧式 `(1.0 + atr_slip)` 不得回到 short 侧。"""
    assert "entry_price * (1.0 + atr_slip)" not in SHORT_SRC, (
        "`(1.0 + atr_slip)` 又回到 short_reversal 的 entry —— 这是本文件记录的缺陷形态"
    )


def test_long_engines_keep_the_positive_sign() -> None:
    """多头 entry 是买入 ⇒ 买得更贵 = 悲观 ⇒ 必须保持 `(1 + atr_slip)`。

    这条是**防止"顺手统一"**的: 看到 short 用减号就去把多头也改成减号, 会把
    多头从悲观改成乐观。**两侧符号必须相反, 不是一致。**
    """
    signs = _long_signs()
    assert signs == {
        "chase_up/portfolio.py": "+",
        "uptrend_pullback/portfolio.py": "+",
    }, f"多头引擎的 entry 滑点符号被改了: {signs} —— 多头是买入, 应为 '+'"


def test_core_helper_docstring_no_longer_claims_the_wrong_sign() -> None:
    """共享 helper 的 docstring 曾把 `short: ×(1+slip)` 注为"悲观" —— 已更正。"""
    assert "(1 − slip)" in CORE_SRC, "core/dual_price 的 docstring 未更正 short 侧符号说明"
    assert "上调卖出价是收到**更多**" in CORE_SRC, "应写明原注释为何自相矛盾"


def test_branch_is_unreachable_under_shipped_presets() -> None:
    """钉住"修正无结果漂移"的前提: 全部 short_reversal preset 都不开启 ATR 滑点。

    这是本文件声称"零漂移"的**依据**。若哪天某个 preset 显式打开了它, 这条会红 ——
    那不是坏事, 是提醒: 届时该 preset 的数字需要按 §6 重新生成基线并说明漂移。
    """
    import short_reversal.presets as SR

    offenders = [
        k for k, p in SR.PRESETS.items()
        if (p.get("atr_slip_scale") or 0) > 0 or (p.get("slippage") or 0) > 0
    ]
    assert not offenders, (
        f"这些 preset 开启了执行滑点, 于是 short entry 的符号修正**不再零漂移**: {offenders}"
    )
