"""§4: **限价单侧必须成对** —— 守了买入侧, 就必须守卖出侧 (§13.106, 2026-10-19)。

## §4 原文 (两半)
> **Limit-Up / Limit-Down No-Fill:** A buy on a **limit-up**-sealed bar
> **and a sell/cover on a limit-down-sealed bar** MUST be rejected (no fill).

## 修之前的状态
| 族 | 买入侧 (涨停不可买) | 卖出侧 (跌停不可卖) |
|---|---|---|
| `chase_up` | ✅ 内联 | ⛔ **无** |
| `uptrend_pullback` | ✅ 内联 | ⛔ **无** → 本轮补上 (§13.106) |
| `short_reversal` | — (做空, entry 就是卖出) | ✅ `is_limit_down` |
| `cycle_price_action` | ✅ `is_limit_up` | ⛔ 无 (见下) |

⇒ **两个多头族只守了 §4 的前半句。** 而**方向是危险的**: 跌停封板时卖出**物理上不可能**,
旧代码却按 `o` 成交 ⇒ **把一个不能成交的出场记成成交了** ⇒ 结果偏**乐观**。

## 本文件的判据 (跨族对称性 —— 它本来就会抓到上面那个洞)
**一个族若守了买入侧, 就必须守卖出侧。** 这条不依赖任何实现细节:
它只问"两边是否**成对**", 所以在任何一族漏掉任一侧时都会响。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 已补齐卖出侧的族; chase_up 未补 (见 _XFAIL)
_LONG_ENGINES = {
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    # ⚠️ 2026-10-22 (附一百八十八): chase_up **已补上卖出侧**(实测 `is_limit_down` 在第 586 行被调用)
    # ⇒ 按本文件 `strict=True` xfail 的设计(缺口一补上就红,逼人回来删豁免),把它移到这里。
    # 移过来之后,上面两条用例(卖出侧存在 / 守卫排在 SL 之前)**自动对 chase_up 生效** ——
    # 这不只是删一条豁免,是把两个真判据扩到第二族。
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
}
#: **尚未**补上卖出侧的族 —— 现在为空(2026-10-22: chase_up 已补齐, 见 `_LONG_ENGINES`)。
#:
#: 机制**保留**: 将来若有族退回"只守买入侧", 把它写进来, `test_not_yet_...` 会断言缺口**存在**,
#: 缺口一被补上就红(自失效)。registry 为空时该用例自动 skip, 见其内部。
_NOT_YET: dict[str, tuple[Path, str]] = {}


def _calls(path: Path, name: str) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


@pytest.mark.parametrize("fam", sorted(_LONG_ENGINES))
def test_long_engines_guard_the_sell_side_too(fam: str) -> None:
    """★ 跨族对称性: 守了买入侧 ⇒ 必须守卖出侧。"""
    path = _LONG_ENGINES[fam]
    src = path.read_text(encoding="utf-8")
    # 买入侧的存在 (内联或调用都算)
    has_buy = ("is_limit_up" in src) or ("LIMIT_UP_THRESHOLD" in src)
    assert has_buy, f"{fam}: 连买入侧都没有 ⇒ 判据的前提不成立, 请先确认 §4 的前半句。"
    # 卖出侧必须**真的被调用**
    called = _calls(path, "is_limit_down")
    assert called, (
        f"§4: {fam} 守了买入侧却**没有**卖出侧 —— "
        f"`is_limit_down` 未被调用 (仅 import 不算)。\n"
        f"⇒ 跌停封板时卖出会按 `o` 成交 = **记成了一笔不可能发生的成交** ⇒ 结果偏乐观。"
    )


@pytest.mark.parametrize("fam", sorted(_LONG_ENGINES))
def test_the_sell_guard_preempts_the_sl_fill(fam: str) -> None:
    """守卫必须**排在 SL/TP 分支之前** —— 否则跳空破止损会先成交, 守卫形同虚设。

    判据: 在同一个 `For` 节点里, `is_limit_down` 的**行号**必须小于该 For 体内
    第一个 `px, reason = ...` 之类的赋值... 这里用更稳的等价形式:
    **`is_limit_down` 所在行必须早于同函数内 `"SL"` 字符串字面量所在的行**。
    """
    path = _LONG_ENGINES[fam]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ld_lines, sl_lines = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "is_limit_down":
            ld_lines.append(n.lineno)
        if isinstance(n, ast.Constant) and n.value == "SL":
            sl_lines.append(n.lineno)
    assert ld_lines and sl_lines, f"{fam}: 找不到判据的扫描单位 (ld={ld_lines}, sl={sl_lines})"
    assert min(ld_lines) < min(sl_lines), (
        f"{fam}: `is_limit_down` (行 {min(ld_lines)}) 排在 SL 分支 (行 {min(sl_lines)}) **之后** "
        f"⇒ 跳空破止损会先成交, 封板守卫不起作用。"
    )


@pytest.mark.parametrize("fam", sorted(_NOT_YET))
def test_not_yet_families_still_lack_the_sell_side(fam: str) -> None:
    """**已知未补的族必须仍然是"未补"** —— 一旦补上, 本条**红**, 逼人回来更新本文件。

    ⚠️ 这里**不能**用 `@pytest.mark.xfail` —— 本条断言的是"缺口**存在**", 它**现在是通的**;
    加上 `strict=True` 会把"通过"报成 XPASS 失败 (我第一版就是这么写错的)。
    **自失效**由断言本身提供: 缺口一被补上, `assert not ...` 立刻失败。
    """
    if not _NOT_YET:
        pytest.skip("_NOT_YET 已空 —— 四族都补上了卖出侧(2026-10-22);机制保留待将来需要")
    path, why = _NOT_YET[fam]
    assert not _calls(path, "is_limit_down"), (
        f"{fam} 已补上卖出侧 ⇒ 请删掉 _NOT_YET 里那一条豁免, 并把本族加进 _LONG_ENGINES。\n"
        f"原豁免理由: {why}"
    )


def test_the_scanner_actually_finds_the_buy_side_elsewhere() -> None:
    """反空转: 确认"买入侧"这个词组在**别的族**里确实存在 —— 否则上面的前提是空的。"""
    for fam, path in (("chase_up", REPO_ROOT / "chase_up" / "portfolio.py"),):
        src = path.read_text(encoding="utf-8")
        assert "LIMIT_UP_THRESHOLD" in src or "is_limit_up" in src, (
            f"反空转失败: {fam} 里找不到买入侧守卫 ⇒ 本文件的判据可能在空转。"
        )
