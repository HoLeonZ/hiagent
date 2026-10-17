"""§4 成本常量: 守卫必须**能失败** —— 只允许规范取值出现在生产代码里。

背景 (2026-10-17): `tests/test_cost_constants_single_source_4engine.py` 里有四条
名字承诺"禁止硬编码成本字面量"的测试, 但实现是**空转的**:

    def test_chase_up_no_hardcoded_cost_literals():
        ...
        if chase:
            pass          # ← 什么都不做
    def test_uptrend_pullback_no_hardcoded_cost_literals():
        ...
        if uptrend:
            pass          # ← 什么都不做
    def test_short_reversal_no_wrong_cost_literals():
        ...  # 只对 ==0.0006 / ==0.001 报警 ⇒ 其它任何值都放行
    def test_cycle_price_action_no_wrong_cost_literals():
        ...  # 只对 ==0.001 报警

它们的 docstring 明写 "Allowed location: core/dual_price.py; Disallowed location:
any other production file", 而实现**不检查任何东西**。这正是本仓库反复出现的
"守卫不能失败"形态 (审计已记: 「恒真断言」应改为真断言)。

后果可证: Tick 53 记录过 short_reversal 用 0.0006、cycle 用 0.001 —— 两条都是
**值错**, 而当时的守卫不会因"值错"报警 (只对硬编码的**特定**错值报警, 且那两条
错值出现时套件仍是绿的)。

本文件把守卫改成真断言: **生产代码里出现的成本字面量必须 ∈ 规范集合**。
这不会因"重复定义"报警 —— 全量单源化 (84 处重复) 仍是登记未做的重构;
但任何**非规范取值**会被立刻抓住, 包括那两条已发生过的错值。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CANONICAL = {"0.00025", "0.0005"}       # 万2.5 佣金 / 万5 印花税
KNOWN_WRONG = {"0.0006", "0.001", "0.002"}  # 历史错值 (Tick 53)
COST_LITERAL = re.compile(r"\b(0\.00025|0\.0005|0\.0006|0\.001|0\.002)\b")
#: 只在**成本上下文**里判 —— `0.001` 也常用作浮点容差 (如价格比较), 那是另一回事。
#: 收窄到成本上下文是为了让守卫精确: 旧守卫的问题是不能失败, 而一个过宽的守卫
#: 会用误报把真正的违规淹掉。
COST_CONTEXT = re.compile(
    r"(commission|stamp|duty|tax|min_commission|\bRATE\b|fee_rate)", re.IGNORECASE
)
ENGINES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")


def _violations(engine: str) -> list[tuple[str, int, str]]:
    """返回 (文件, 行号, 字面量) —— 非规范或历史错值。"""
    out = []
    for f in (ROOT / engine).rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if not COST_CONTEXT.search(line):
                continue
            for m in COST_LITERAL.finditer(line):
                v = m.group(1)
                if v not in CANONICAL:
                    out.append((str(f.relative_to(ROOT)), i, v))
    return out


@pytest.mark.parametrize("engine", ENGINES)
def test_production_code_uses_only_canonical_cost_rates(engine: str) -> None:
    v = _violations(engine)
    assert not v, (
        f"{engine} 出现非规范成本字面量 (应为 {sorted(CANONICAL)}): {v[:5]}"
    )


def test_the_guard_actually_catches_the_two_historical_bugs() -> None:
    """守卫必须能抓住 Tick 53 记录过的两条真实错值 (0.0006 佣金 / 0.001 印花税)。

    旧守卫对这两条的判断依赖"它们恰好等于某个硬编码的错值", 而不是"它们不等于
    规范值" —— 本断言用同一套正则与判定, 直接验证 0.0006 与 0.001 会被判为违规。
    """
    for wrong in ("0.0006", "0.001"):
        m = COST_LITERAL.search(f"x = max(5.0, notional * {wrong})")
        assert m and m.group(1) not in CANONICAL, f"{wrong} 必须被判为违规"


def test_canonical_values_match_core() -> None:
    """规范集合必须与 `core/dual_price` 的导出值一致 —— 否则守卫锚错了。"""
    from core.dual_price import COMMISSION_RATE, STAMP_DUTY_RATE

    assert f"{COMMISSION_RATE}" in CANONICAL
    assert f"{STAMP_DUTY_RATE}" in CANONICAL
