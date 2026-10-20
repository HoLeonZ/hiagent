r"""§0/§6 守卫:preset 的 `signal` **只能经一个分派器**交给选择函数。

## 缺陷(附一百零九,逐处实测)

`uptrend_pullback` 有**两个**选择函数,选哪个由 `signal["entry_mode"]` 决定:
`"v33_long_mirror"` → `select_entries_v33_long_mirror`,否则 → `select_entries`。

这条分派规则此前有 **11 份副本**:

| 处 | 份数 | 对不对 |
|---|---|---|
| `backtest.py` / `backtrader_engine.py` | 2 | ✅ 写对了 |
| `grid.py` / `render_trades_html.py`(两处) | 3 | ⛔ **漏了分派** |
| `sweep_v33_long*.py` | 6 | ✅ 但**硬编码**了镜像分支 + 自己过滤 `entry_mode` |

**漏分派的三处不是"少一个 branch",而是当场崩**:三个活 preset 的 `entry_mode` 都是
`"v33_long_mirror"`,它们的 `signal` 里带 `pct_chg_low` / `pct_chg_high`,而
`select_entries()` **没有这两个形参** ⇒

    TypeError: select_entries() got an unexpected keyword argument 'pct_chg_low'

实测:`uptrend_pullback/grid.py` 在**第一个 combo** 上就崩(加了 `--grid slots` 也跑不动),
`render_trades_html.py` 的两处调用点同形。**两个 CLI 工具都没有产出** ——
所以它们对 §5/§6 的"执行"是**零**,而这一点没有任何守卫看得见。

## 判据三条

1. **包内除 `signals.py` 外,任何模块不得直接调那两个选择函数** —— 只能走
   `select_entries_for_preset`。把"绕过分派"变成**做不到**,而不是"不推荐"。
2. **分派器必须真的分派**(有 `entry_mode` 分支 + 滤掉它),否则它退化成第二个 `select_entries`。
3. **签名符合性(最强的一条)**:对**每个活 preset**,`signal` 里(除 `entry_mode` 外)的
   每个键都必须被"分派器会选中的那个函数"接受 —— 用 `inspect.signature` 判定,**不落库**。
   这一条直接编码了本批的缺陷,而且**与实现无关**:换任何写法都不会漏。

## 两向验证(都当场做过)

* 把任一调用点退回 `select_entries(...)` 直调 ⇒ **#1 红**;
* 从分派器里删掉 `entry_mode` 分支 ⇒ **#2/#3 红**;
* 从 `select_entries_v33_long_mirror` 的签名里拿掉 `pct_chg_low` ⇒ **#3 红**(且它正是原始缺陷)。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "uptrend_pullback"
SIGNALS = PKG / "signals.py"

DIRECT_SELECTORS = ("select_entries", "select_entries_v33_long_mirror")
DISPATCHER = "select_entries_for_preset"
MIRROR_MODE = "v33_long_mirror"

#: 允许调用分派器的模块(**精确集合**,不是下限)。
#: 少一个 ⇒ 有人绕过了分派;多一个 ⇒ 新脚本出现 —— 两种情况都要人看一眼再改这张表。
DISPATCHER_CALLERS = {
    "uptrend_pullback/backtest.py",
    "uptrend_pullback/backtrader_engine.py",
    "uptrend_pullback/grid.py",
    "uptrend_pullback/render_trades_html.py",
    "uptrend_pullback/sweep_v33_long.py",
    "uptrend_pullback/sweep_v33_long_v2.py",
    "uptrend_pullback/sweep_v33_long_v3.py",
    "uptrend_pullback/sweep_v33_long_v4.py",
    "uptrend_pullback/sweep_v33_long_v5.py",
    "uptrend_pullback/sweep_v33_long_v6.py",
}


def _called_names(path: Path) -> set[str]:
    """文件里**被调用**的函数名(只取 `Name(...)` 形态;属性调用不算)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_only_signals_module_calls_a_selector_directly() -> None:
    """判据 1:除 `signals.py` 外,包内**任何模块**不得直接调那两个选择函数。"""
    offenders = []
    for p in sorted(PKG.rglob("*.py")):
        if p == SIGNALS:
            continue
        hit = _called_names(p) & set(DIRECT_SELECTORS)
        if hit:
            offenders.append(f"{p.relative_to(REPO_ROOT)}: 直接调了 {sorted(hit)}")
    assert not offenders, (
        "§6 单源:以下调用点**绕过了** `signal.entry_mode` 的分派 ——\n  "
        + "\n  ".join(offenders)
        + f"\n请改走 `{DISPATCHER}(panel_ind, signal=…, start_date=…, end_date=…, regime_df=…)`。"
        "\n(附一百零九:三处这样的调用点让 `grid.py` 与 `render_trades_html.py` 对全部活 preset 当场崩)"
    )


def test_the_dispatcher_is_actually_called() -> None:
    """判据 1 的**第二半**:一次性把所有人都改成"绕过分派"也能满足上一条?不能 —— 这里钉住。"""
    callers = {
        str(p.relative_to(REPO_ROOT))
        for p in sorted(PKG.rglob("*.py"))
        if p != SIGNALS and DISPATCHER in _called_names(p)
    }
    assert callers == DISPATCHER_CALLERS, (
        "调用分派器的模块集合变了 —— 这是**故意的对齐检查**:\n"
        f"  实际多出: {sorted(callers - DISPATCHER_CALLERS)}\n"
        f"  实际缺少: {sorted(DISPATCHER_CALLERS - callers)}\n"
        "确认无误后同步 `DISPATCHER_CALLERS`。"
    )


def test_the_dispatcher_really_dispatches() -> None:
    """判据 2:分派器必须**在可执行代码里**分派 —— 有 `entry_mode` 的比较分支,并滤掉它。

    ⚠️ 第一版判据是 `'"v33_long_mirror"' in body`(body = 函数源码段),
    实测**把分支条件换成 `if False:` 它照样绿** —— 因为那个字面量在**本函数的 docstring** 里
    也出现过 ⇒ **注释满足了判据**。这正是本会话反复记的那条(判据要盯**用法**,不是**文本**),
    而我在写这条"防绕过"的守卫时又犯了一次。故改为走 AST:找 `If`,看它的 **test** 是不是
    在跟那个字面量比较;再看镜像分支里有没有**真的**建了滤掉 `entry_mode` 的 kwargs。
    """
    src = SIGNALS.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        (n for n in tree.body
         if isinstance(n, ast.FunctionDef) and n.name == DISPATCHER),
        None,
    )
    assert fn is not None, f"`{DISPATCHER}` 不见了 —— 判据的落点没了"

    # (i) 可执行分支:存在 `if <… "v33_long_mirror" …>:`
    branches = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.If) and _compares_to_literal(node.test, MIRROR_MODE)
    ]
    assert branches, (
        f"`{DISPATCHER}` 里**在可执行代码里**没有 `{MIRROR_MODE}` 比较分支 —— "
        "它退化成第二个 `select_entries`(提到它 ≠ 用它;docstring 里提到不算)"
    )

    # (ii) 该分支里必须真的滤掉 `entry_mode`(一个对 `"entry_mode"` 做不等比较的推导式)
    filtered = any(
        _filters_out(node, "entry_mode") for b in branches for node in ast.walk(b)
    )
    assert filtered, (
        f"`{DISPATCHER}` 的镜像分支没有真的滤掉 `entry_mode`再转发 ⇒ "
        "镜像选择函数会收到它不认识的键"
    )

    # (iii) 两个选择函数都在**可执行代码**里被调用
    called = _called_names_from_ast(fn)
    assert set(DIRECT_SELECTORS) <= called, (
        f"`{DISPATCHER}` 必须同时**调用**两个选择函数;实际调用的:{sorted(called & set(DIRECT_SELECTORS))}"
    )


def _compares_to_literal(node: ast.AST, literal: str) -> bool:
    """`node` 里有没有把某个东西与字符串字面量 `literal` 比较(可执行代码,不含 docstring)。"""
    return any(
        isinstance(c, ast.Constant) and c.value == literal
        for c in ast.walk(node)
    )


def _filters_out(node: ast.AST, key: str) -> bool:
    """`node` 里有没有对 `key` 做 `!=` 比较(即"把它滤掉")。"""
    for c in ast.walk(node):
        if isinstance(c, ast.Compare) and any(isinstance(op, ast.NotEq) for op in c.ops):
            if any(isinstance(x, ast.Constant) and x.value == key for x in c.comparators):
                return True
    return False


def _called_names_from_ast(node: ast.AST) -> set[str]:
    return {
        c.func.id
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    }


def _live_presets():
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from uptrend_pullback.presets import PRESETS

    return PRESETS


@pytest.mark.parametrize("name,preset", sorted(_live_presets().items()))
def test_every_preset_signal_key_is_accepted_by_the_dispatched_selector(
    name: str, preset: dict
) -> None:
    """判据 3(最强的一条):preset 的每个 `signal` 键都必须被**会被选中的那个函数**接受。

    (`inspect.signature` 判定,不落库、不跑回测 —— 原缺陷的 TypeError 就发生在**调用点**,
     参数不匹配在签名层面已经可判。)
    """
    from uptrend_pullback.signals import (
        select_entries,
        select_entries_v33_long_mirror,
    )

    signal = preset["signal"]
    dispatched = (
        select_entries_v33_long_mirror
        if signal.get("entry_mode") == MIRROR_MODE
        else select_entries
    )
    accepted = set(inspect.signature(dispatched).parameters)
    keys = set(signal) - {"entry_mode"}
    unexpected = sorted(keys - accepted)
    assert not unexpected, (
        f"§0/§6: preset `{name}` 的 signal 带着 {unexpected},而它会被分派到 "
        f"`{dispatched.__name__}()`,后者**不接受**这些键 ⇒ 调用当场 `TypeError`。\n"
        f"(`{dispatched.__name__}` 接受:{sorted(accepted)}\n)"
        "这正是附一百零九 的缺陷形态:工具**没有产出**,却看起来「只是少了点什么」。"
    )
