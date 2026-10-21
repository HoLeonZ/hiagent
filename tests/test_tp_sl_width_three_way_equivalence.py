"""§4: ATR 自适应 TP/SL 宽度的**三处实现必须数值一致** (2026-10-19, §13.40)。

## 为什么需要这条
"`tp/sl = entry × (1 ± clamp(atr_pct) × mult)`" 这个式子在本仓库里**写了三遍**:

| # | 位置 | 形态 |
|---|---|---|
| 1 | `chase_up/backtrader_engine.py::compute_trade_tp_sl` | 返回**绝对价** |
| 2 | `uptrend_pullback/backtrader_engine.py::compute_trade_tp_sl` | 返回**绝对价**(与 1 逐字相同) |
| 3 | `chase_up/portfolio.py` + `uptrend_pullback/portfolio.py` 的模拟循环内 | 先算 `tp_eff = a × mult`(**百分比**), 再 `entry × (1 + tp_eff)` |

而 #1 的 docstring **自称**"与 `portfolio.py:simulate_portfolio` 完全一致" ——
**那是一句断言, 而不是一个被检查的事实。**

§2 的 "defined exactly once (in `core/`)" 只点名了成本常量; 这个式子不在其中,
所以**没有任何东西拦得住三份互相漂移**。而它一旦漂移, 改变的是**止损止盈的位置** ——
属 §4 的退出阈值, 后果直接落在成交上。

## 实测 (2026-10-19): **今天三者一致**
256 个组合 (4 entry × 8 atr[含 None/NaN/0/低于下限/高于上限] × 4 mult[含 0] × 2 fixed)
**逐一相同**。⇒ 本条守卫今天**不是**在抓一个现存缺陷, 而是**把"它们一致"从断言变成检查**。

## 判据 (§6: 必须能失败, 且**不许空转**)
* 第 1 条是**反空转对照**: 网格里必须存在至少一个组合, 使 ATR 分支与 fixed 分支给出**不同**结果。
  没有它, "三者一致" 可能只是因为**它们都在返回同一个常数** (§13.19 的教训)。
* 第 2 条是真判据: 三者在全网格上一致。
"""
from __future__ import annotations

import itertools
import math

import pytest

from chase_up.backtrader_engine import compute_trade_tp_sl as chase_bt
from uptrend_pullback.backtrader_engine import compute_trade_tp_sl as up_bt

ENTRIES = (1.0, 10.0, 33.65, 1234.5)
ATRS = (None, float("nan"), 0.0, 0.005, 0.01, 0.035, 0.08, 0.5)
MULTS = ((None, None), (4.0, 1.0), (2.5, 2.5), (0.0, 0.0))
FIXED = ((0.06, 0.05), (0.30, 0.10))
GRID = list(itertools.product(ENTRIES, ATRS, MULTS, FIXED))


def _portfolio_inline(
    entry: float, fixed_tp: float, fixed_sl: float,
    atr: float | None, m_tp: float | None, m_sl: float | None,
    floor: float = 0.01, cap: float = 0.08,
) -> tuple[float, float]:
    """复刻 `chase_up/portfolio.py:583-591` + `:559-560` 的算式 (**百分比式**)。

    刻意**照抄**那份内联代码的形状 (先算 pct 再套 entry), 而不是直接写等价的一行 ——
    因为要守的正是"那份内联代码与另两处一致"。
    """
    tp_eff, sl_eff = fixed_tp, fixed_sl
    if m_tp is not None and m_sl is not None:
        if atr is not None and not (isinstance(atr, float) and math.isnan(atr)):
            a = min(max(float(atr), floor), cap)
            tp_eff = a * m_tp
            sl_eff = a * m_sl
    return entry * (1 + tp_eff), entry * (1 - sl_eff)


def test_grid_is_not_vacuous() -> None:
    """反空转对照: 网格里必须存在 ATR 分支与 fixed 分支**结果不同**的组合。

    否则"三者一致"可能只是因为它们都返回同一个常数 (§13.19 的教训)。
    """
    differing = 0
    for entry, atr, (m_tp, m_sl), (ftp, fsl) in GRID:
        if m_tp is None or atr is None or (isinstance(atr, float) and math.isnan(atr)):
            continue
        if _portfolio_inline(entry, ftp, fsl, atr, m_tp, m_sl) != (
            entry * (1 + ftp), entry * (1 - fsl)
        ):
            differing += 1
    assert differing > 0, (
        "整个网格上 ATR 分支都与 fixed 分支相同 ⇒ 这条判据是空转的, 不能证明任何一致性"
    )


def test_three_implementations_agree_on_the_whole_grid() -> None:
    """三处实现 (两处 backtrader helper + 一处在 portfolio.py 内联) 必须数值一致。"""
    bad = []
    for entry, atr, (m_tp, m_sl), (ftp, fsl) in GRID:
        kw = dict(fixed_tp_pct=ftp, fixed_sl_pct=fsl, atr_pct=atr,
                  atr_tp_mult=m_tp, atr_sl_mult=m_sl)
        c = chase_bt(entry, **kw)
        u = up_bt(entry, **kw)
        p = _portfolio_inline(entry, ftp, fsl, atr, m_tp, m_sl)
        if not (c == u == p):
            bad.append((entry, atr, (m_tp, m_sl), (ftp, fsl), c, u, p))
    assert not bad, (
        "ATR 自适应 TP/SL 的三处实现出现分歧 (entry, atr, mults, fixed, chase_bt, up_bt, portfolio):\n"
        + "\n".join(f"  {b}" for b in bad[:8])
    )


def test_backtrader_helpers_have_identical_signatures() -> None:
    """两处 helper 的**签名**也必须一致 —— 否则调用方无法互换 (只查形参名与默认值)。"""
    import inspect

    sc = inspect.signature(chase_bt)
    su = inspect.signature(up_bt)
    assert list(sc.parameters) == list(su.parameters), (
        f"签名形参不同: chase={list(sc.parameters)} vs uptrend={list(su.parameters)}"
    )
    for name, pc in sc.parameters.items():
        assert pc.default == su.parameters[name].default, (
            f"形参 {name} 的默认值不同: {pc.default!r} vs {su.parameters[name].default!r}"
        )
    assert sc.parameters["entry_price"].kind is su.parameters["entry_price"].kind
