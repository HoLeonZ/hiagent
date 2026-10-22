"""§2 守卫:`final_capital` 必须取**净值**,而不是总现金。

## 缺陷(审计 §3.2 的 HIGH×3,**本轮复核确认成立**)

`Phase3V3Strategy.stop()` 曾只写 `holder["cash"] = self.total_cash`,而
`_metrics_from_holder` 用 `final_capital = holder["cash"]`。

`total_cash` = **成本基础 + 已实现盈亏**,**不含期末未平仓的浮盈**;而
`equity_curve` 的每行 `equity` 用的是 `nav`(= `self._nav()`,**含浮盈**)。
于是**同一次回测给出两个互相打架的"期末权益"**:

| 产物 | 口径 |
|---|---|
| `equity_curve.csv` 末行 `equity` | `_nav()`(含未平仓浮盈) |
| `metrics.json` 的 `final_capital` | `total_cash`(不含) |

而 `total_yield` / `cagr` 都由 `final_capital` 推出 —— 所以**期末只要还持仓,
收益率就是错的**(方向取决于浮盈正负)。这不是舍入差异,是两个定义。

**注**:审计原文还写了"settle() 只冲刷正值(亏损永不回 Free_Cash)" —— 逐行核对后
**不成立**:`settling_funds` 只有 `+= amount` 一处写入(`credit_settling`),
恒非负,`if > 0` 只是避开加 0。亏损不走这条路径。(又一次:核对已复核过的族时,
最易把"没搜到/看着像"当成"没修/有 bug"。)

## 修法

`stop()` 增写 `"final_nav": self._nav()`;`_metrics_from_holder` 改用它,且**缺即
fail-fast**(合成夹具只给 `cash` 会拿到一个与曲线末行不一致的数,不能静默回退)。
两个数从此都出自**同一个** `_nav()`。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _holder(cash: float, nav: float | None = None) -> dict:
    h = {"cash": cash, "trades": [], "max_dd": 0.0}
    if nav is not None:
        h["final_nav"] = nav
    return h


def test_final_capital_uses_nav_not_total_cash() -> None:
    """行为验证:构造 cash ≠ nav,断言用的是 **nav**。

    两值刻意相差 100 —— 若实现回退到 `cash`,本条必然失败。
    """
    from short_reversal.engine import _metrics_from_holder

    m = _metrics_from_holder(
        _holder(cash=1_000_000.0, nav=1_000_100.0),
        "2025-01-01", "2025-06-30", {"_name": "synthetic"}, n_trading_days=126,
    )
    assert m["final_capital"] == pytest.approx(1_000_100.0), (
        "§2: final_capital 取了 total_cash 而非净值 —— "
        "期末未平仓的浮盈被抹掉,而 equity_curve 末行却含它,两个数会打架。"
    )


def test_missing_final_nav_fails_fast() -> None:
    """§2: 缺 final_nav 必须 fail-fast,不得静默回退到 cash。"""
    from short_reversal.engine import _metrics_from_holder

    with pytest.raises(KeyError, match="final_nav"):
        _metrics_from_holder(
            _holder(cash=1_000_000.0),
            "2025-01-01", "2025-06-30", {"_name": "synthetic"}, n_trading_days=126,
        )



def _stop_node(mod) -> ast.FunctionDef | None:
    """`mod` 里名为 `stop` 的函数节点(按 AST,不按文本切片)。"""
    for n in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(n, ast.FunctionDef) and n.name == "stop":
            return n
    return None

def test_stop_writes_nav_so_metrics_can_use_it() -> None:
    """生产路径:`stop()` 必须写入 `final_nav`,且取自 `_nav()`。"""
    from short_reversal import replay_strategy_v3 as mod

    # ⚠️ 2026-10-22 (附一百八十九 收口后): 原判据是**文本切片** ——
    #     start = src.index("def stop(self):"); body = src[start:start + 900]
    # 两处都脆:① `stop` 改名/搬家 ⇒ `str.index` 抛 **ValueError**(用例在断言之前就炸);
    # ② **900 字魔数窗口** —— 实测今天 `stop()` 是 **738** 字符,窗口刚好盖满;
    #    而只要有人往那段注释里再加一百多字,后半段就**够不着**,那时**不报错**,
    #    只是静默地少判一段(本册反复记的"静默缩小覆盖面"正是这个形状)。
    # ⇒ 按 AST 取 `stop` 节点,并改断**那条真正的不变式**:`"final_nav"` 这个键的值
    #    必须**是** `self._nav()` 的调用。
    fn = _stop_node(mod)
    assert fn is not None, "引擎里找不到 `stop()` —— 它被改名或删除了"
    finals = [
        v for n in ast.walk(fn) if isinstance(n, ast.Dict)
        for k, v in zip(n.keys, n.values)
        if isinstance(k, ast.Constant) and k.value == "final_nav"
    ]
    assert finals, "§2: stop() 未写入 final_nav"
    assert any(
        isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "_nav"
        for v in finals
    ), "§2: stop() 的 final_nav 必须取自 _nav()"


def test_equity_curve_and_final_capital_share_one_definition() -> None:
    """两个"期末权益"必须出自**同一个** `_nav()`(单一定义)。

    这条钉的是缺陷的**形态**:曲线用 `nav`,指标用 `total_cash` —— 两者同名不同源。
    """
    from short_reversal import replay_strategy_v3 as mod

    src = inspect.getsource(mod)
    code = "\n".join(
        l for l in src.splitlines() if not l.strip().startswith("#")
    )
    assert "nav = self._nav()" in code, "equity 行的 nav 不再来自 _nav()"
    # 指标侧不得再用 total_cash 作为 final_capital
    engine_src = (REPO_ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")
    assert 'final_capital = float(holder["cash"])' not in engine_src, (
        "§2 回归:final_capital 又用回 holder['cash']"
    )
