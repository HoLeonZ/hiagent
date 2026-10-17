"""§2 Canonical Cost Model: 成本常量必须**从 `core.dual_price` 绑定**, 不得写成字面量。

## §2 原文
> **Canonical Cost Model:** Commission / stamp-duty / min-fee constants are defined
> **exactly once (in `core/`)**. Every engine MUST import them; **redefining fee
> constants inside an engine or preset is a fail-fast violation.**

## 2026-10-19 修的是什么 (Iteration 120)
三处都在"看起来已经单源化"的情况下**实际写的是字面量**:

| 位置 | 修前的样子 |
|---|---|
| `short_reversal/engine.py` | 注释写 "canonical cost rates **imported from** core.dual_price single-source", 底下两行却是 `COMMISSION_RATE = 0.00025` / `STAMP_DUTY_RATE = 0.0005` —— **注释与代码相反** |
| `short_reversal/replay_strategy_v3.py` | 文件顶部**已经** `from core.dual_price import ...`, 但成本常量仍另写三行字面量 |
| `cycle_price_action/portfolio.py` | 顶部**确实** import 了三个规范常量, 随后 `class Portfolio` 里**又把同名值字面量重写一遍** ⇒ 模块级 import 从未被用 (装饰性), 且 `STAMP_DUTY_RATE` 被改名成 `STAMP_TAX_SELL` |

**三处取值都与规范值逐字节相同** ⇒ 修复**零结果漂移**
(已跑 `v58_mp_2 / 2018-01-01..2020-12-31` 核对: `trades=686`, `cagr` 与 `sharpe` 两位小数到 15 位
与 Iteration 74 基线逐位相同)。

## 既然取值相同, 为什么还要修
与本循环 §13.14 同一条判据: **判据不是"现在对不对", 而是"下一次会不会悄悄不对"。**
而且 §2 把它明列为 **fail-fast violation** —— 之前只登记未修, 是因为当时把它当成
"84 处重复"的重构; 但**有名常量这一层**(3 处) 取值完全相同, 上收是**零成本**的。

## 本文件的断言形态 (§6: 必须能失败)
既查**反面** (不得出现字面量), 又查**正面** (必须确实绑定到 core) ——
只查反面的话, "把定义删掉"也会通过。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# (文件, 必须出现的绑定表达式)
BINDINGS = (
    ("short_reversal/engine.py", r"from core\.dual_price import .*COMMISSION_RATE"),
    ("short_reversal/replay_strategy_v3.py", r"from core\.dual_price import"),
    ("cycle_price_action/portfolio.py", r"_CANON_COMMISSION_RATE"),
)
# 这些名字**不得**在这些文件里以字面量形式出现
LITERAL_GUARD = (
    ("short_reversal/engine.py", "COMMISSION_RATE", "0.00025"),
    ("short_reversal/engine.py", "STAMP_DUTY_RATE", "0.0005"),
    ("short_reversal/replay_strategy_v3.py", "COMMISSION_RATE", "0.00025"),
    ("short_reversal/replay_strategy_v3.py", "STAMP_DUTY_RATE", "0.0005"),
    ("short_reversal/replay_strategy_v3.py", "MIN_COMMISSION", "5.0"),
    ("cycle_price_action/portfolio.py", "COMMISSION_RATE", "0.00025"),
    ("cycle_price_action/portfolio.py", "MIN_COMMISSION", "5.0"),
    ("cycle_price_action/portfolio.py", "STAMP_TAX_SELL", "0.0005"),
)


@pytest.mark.parametrize("rel,pat", BINDINGS)
def test_cost_constants_are_bound_not_redeclared(rel: str, pat: str) -> None:
    """正面: 必须**确实**绑定到 `core.dual_price`。"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert re.search(pat, src), f"{rel} 没有绑定到 core.dual_price 的规范成本常量"


@pytest.mark.parametrize("rel,name,val", LITERAL_GUARD)
def test_cost_constants_have_no_literal_redefinition(rel: str, name: str, val: str) -> None:
    """反面: `NAME = <字面量>` 不得出现 (赋值右侧是数字才算)。"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    bad = re.search(rf"^\s*{name}\s*(?::\s*float)?\s*=\s*{re.escape(val)}\b", src, re.M)
    assert bad is None, (
        f"{rel}: `{name} = {val}` 又被写成了字面量 —— §2 明文这是 **fail-fast violation**。"
        f"请改为从 `core.dual_price` 绑定。"
    )


def test_canonical_values_are_unchanged() -> None:
    """规范值本身必须未被改动 (本改动是"上收", 不是"改值")。"""
    from core.dual_price import COMMISSION_RATE, MIN_COMMISSION, STAMP_DUTY_RATE

    assert COMMISSION_RATE == 0.00025
    assert STAMP_DUTY_RATE == 0.0005
    assert MIN_COMMISSION == 5.0
