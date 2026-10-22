"""§2 Canonical Cost Model: 成本常量必须**从 `core.dual_price` 绑定**, 不得写成字面量。

## §2 原文
> **Canonical Cost Model:** Commission / stamp-duty / min-fee constants are defined
> **exactly once (in `core/`)**. Every engine MUST import them; **redefining fee
> constants inside an engine or preset is a fail-fast violation.**

## 2026-10-19 (Iteration 120): 三处"看起来已单源化、实际是字面量"
`short_reversal/engine.py` / `short_reversal/replay_strategy_v3.py` /
`cycle_price_action/portfolio.py` —— 三处取值都与规范值逐字节相同 ⇒ 修复零结果漂移。

## 2026-10-19 (Iteration 128, §13.22): 这个守卫**自己**犯了同一个错
第 120 轮的写法把 `BINDINGS` / `LITERAL_GUARD` **写死成三个文件** ——
**`chase_up/**` 与 `uptrend_pullback/**` 完全不在列表里**。
于是同一个违反在另两个族里继续存在, 而守卫**结构上不可能看见它们**:
> **守卫的覆盖面 = 作者已经修过的东西 ⇒ 它不是检测器, 只是回归钉桩;
>   但它读起来像一条"全库契约"断言。**

后果 (本轮实测, 全部与规范值逐字节相同 ⇒ 修完仍是零漂移):
| 族 | 站点 |
|---|---|
| `short_reversal` | `replay_strategy_v3.py` **参数默认值**仍是字面量 (第 120 轮只上收了模块级常量, 而注释已宣称 single-source) |
| `cycle_price_action` | `replay_broker.py::_fee` —— `max(5.0, notional * 0.00025)`, 而**同一个函数的下一行**已正确绑定 `STAMP_DUTY_RATE` (**函数内部的不对称**) |
| `chase_up` | `backtest.py` / `backtrader_engine.py` (×2 处) / `portfolio.py` (dataclass 默认值) |
| `uptrend_pullback` | `backtest.py` / `backtrader_engine.py` (×2 处) / `portfolio.py` (dataclass 默认值) |

## 本文件的写法 (§6: 必须能失败)
**不再列文件名** —— 改为**遍历四个策略族目录下的全部 `.py`**。
只做名字锚定与精确的裸值形态, 不做泛化数值扫描: `0.0005` 在 `short_reversal`
里几乎全是 **`sl_pct`**(止损百分比, **巧合同值**), 泛扫会大量误报。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

FAMILIES = ("short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action")

# 成本常量的**全部**名字形态 (含历史别名 STAMP_TAX_SELL)
COST_NAMES = (
    "commission_rate",
    "stamp_duty_rate",
    "stamp_tax_sell",
    "min_commission",
    "COMMISSION_RATE",
    "STAMP_DUTY_RATE",
    "STAMP_TAX_SELL",
    "MIN_COMMISSION",
)

# 定义站点: 这三个文件必须**确实**绑定到 core.dual_price (正面断言)
#: (文件, 必须从 `core.dual_price` 绑定的名字)
BINDINGS = (
    ("short_reversal/engine.py", "COMMISSION_RATE"),
    ("short_reversal/replay_strategy_v3.py", "COMMISSION_RATE"),
    ("cycle_price_action/portfolio.py", "COMMISSION_RATE"),
    # §13.22 新增: 本轮补上的两族
    ("chase_up/backtest.py", "COMMISSION_RATE"),
    ("uptrend_pullback/backtest.py", "COMMISSION_RATE"),
)


def _bound_from_core_dual_price(src: str) -> set[str]:
    """该模块从 `core.dual_price` **导入**的名字集合(AST)。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "core.dual_price":
            names |= {a.asname or a.name for a in node.names}
    return names


def _family_files():
    """四个族目录下的全部 .py —— **发现式**, 不写死文件列表 (§13.22)。"""
    for fam in FAMILIES:
        yield from sorted((ROOT / fam).rglob("*.py"))


def _code_lines(path: Path):
    """跳过整行注释 (行首 `#`), 其余逐行给出 (行号, 文本)。"""
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        yield i, line


def _literal_binding_hits(path: Path):
    """名字锚定: 成本名被**绑定**成**任何数值字面量**。

    覆盖四种形态 (全部是本轮实测到的真实形态):
      NAME = 0.00025            /  NAME: float = 0.0005
      NAME=0.00025              (kwarg / dataclass 默认值)
      NAME=p.get("x", 0.00025)  (带回落的 plumb)

    ⚠️ 判据是"**有没有写成数字**", 不是"这个数字等不等于规范值" ——
    只查规范值会漏掉**漂移成别的数字**的情形 (`= 0.0003`)。
    那类漂移由 `test_cost_model_single_source_enforcement.py` 的**值比对**抓,
    两条守卫**互补而非重复** (本轮实测过: 注入 `0.0003` 时那条红、这条原先不红)。
    """
    out = []
    num = r"(\d+\.\d+(?:e-?\d+)?|\d+)"
    for i, line in _code_lines(path):
        for name in COST_NAMES:
            # NAME <可选 : type> = <可选 p.get(...,)> <数值字面量>
            pat = re.compile(
                rf"\b{name}\b\s*(?::\s*float)?\s*=\s*"
                rf"(?:[A-Za-z_][\w\.]*\.get\([^)]*?,\s*)?"
                rf"{num}\b"
            )
            m = pat.search(line)
            if m:
                out.append((i, name, m.group(1), line.strip()[:110]))
    return out


def _bare_literal_hits(path: Path):
    """无名字的裸值: 成本表达式的**被乘数**或**下限**。

    只查两种精确形态, 避免误伤 `sl_pct = 0.0005` 这类巧合同值:
      `* 0.00025` / `* 0.0005`   (费率被乘数)
      `max(5.0,` / `min(5.0,`    (最低佣金下限)
    """
    out = []
    for i, line in _code_lines(path):
        if re.search(r"\*\s*0\.00025\b", line):
            out.append((i, "*0.00025 裸费率", "0.00025", line.strip()[:110]))
        if re.search(r"\*\s*0\.0005\b", line):
            out.append((i, "*0.0005 裸费率", "0.0005", line.strip()[:110]))
        if re.search(r"\b(?:max|min)\(\s*5\.0\s*,", line):
            out.append((i, "max(5.0, 裸下限", "5.0", line.strip()[:110]))
    return out


@pytest.mark.parametrize("rel,name", BINDINGS)
def test_cost_constants_are_bound_not_redeclared(rel: str, name: str) -> None:
    r"""正面: 必须**确实**从 `core.dual_price` 绑定该常量。

    ⚠️ 2026-10-22 (附一百八十八): 此处原为 `re.search(pat, src)`, 三条模式是:

        r"from core\.dual_price import .*COMMISSION_RATE"   ← `.*` **不跨行**
        r"_CANON_COMMISSION_RATE"                           ← 这个**名字根本不存在**

    实现后来改成**多行括号导入**(`COMMISSION_RATE,` 落在下一行)⇒ 三条一起假红,
    而**三个引擎都真的绑定了**(实测: 5 个文件全都从 `core.dual_price` 导入 `COMMISSION_RATE`)。
    ⇒ 改为 AST: 直接问「这个名字有没有从 `core.dual_price` 导入」, 与排版无关。
    """
    bound = _bound_from_core_dual_price((ROOT / rel).read_text(encoding="utf-8"))
    assert name in bound, (
        f"{rel} 没有从 core.dual_price 绑定 {name} —— 实测它导入的名字: {sorted(bound)}"
    )


def test_no_cost_name_is_bound_to_a_literal_anywhere() -> None:
    """反面 (发现式): 四个族目录下的**任何** .py 都不得把成本名绑成字面量。

    §13.22: 这里是本轮把守卫从"三个写死的文件"改成"遍历族目录"的地方 ——
    旧写法对 `chase_up` / `uptrend_pullback` **结构性失明**。
    """
    hits = []
    for p in _family_files():
        for i, name, val, text in _literal_binding_hits(p):
            hits.append(f"  {p.relative_to(ROOT)}:{i}  `{name} = {val}`  → {text}")
    assert not hits, (
        "§2 fail-fast violation: 成本常量被写成字面量 (必须从 core.dual_price 绑定):\n"
        + "\n".join(hits)
    )


def test_no_bare_cost_literal_in_expressions() -> None:
    """反面 (发现式): 不得出现**无名字的**裸费率/裸下限 (§13.22 新增形态)。"""
    hits = []
    for p in _family_files():
        for i, what, val, text in _bare_literal_hits(p):
            hits.append(f"  {p.relative_to(ROOT)}:{i}  [{what}]  → {text}")
    assert not hits, (
        "§2 fail-fast violation: 成本表达式里出现裸字面量 (必须绑定 core.dual_price):\n"
        + "\n".join(hits)
    )


def test_canonical_values_are_unchanged() -> None:
    """规范值本身必须未被改动 (本改动是"上收", 不是"改值")。"""
    from core.dual_price import COMMISSION_RATE, MIN_COMMISSION, STAMP_DUTY_RATE

    assert COMMISSION_RATE == 0.00025
    assert STAMP_DUTY_RATE == 0.0005
    assert MIN_COMMISSION == 5.0
