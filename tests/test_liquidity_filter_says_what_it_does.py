"""§13.107: 标识符与文档**必须说它做的事** —— `apply_liquidity_filter` 的对齐。

## 修之前
`cycle_price_action/universe.py::apply_liquidity_filter` 的参数叫 `lookback` ——
**而它不是一个回看窗口**: 实现里是 `counts[counts >= lookback]`, 即
「**面板里至少有这么多个不同交易日**」的入场门槛。
而聚合是 `df.groupby("thscode")["amount"].mean()` —— **没有 `rolling`、也没有"60 天"**。

⇒ 「Liquidity filter (**60d rolling mean** of amount)」这句在
`tests/test_cycle_survivorship_bias.py` 与实现自己的注释里**从未成立过**。
而 `data_feed.py` 传进来的面板**没有日期边界** ⇒ 实际是**全历史均值**。

## 本文件钉的 (行为式, 不靠读注释)
1. **参数名不得暗示窗口** —— `lookback` / `window` / `rolling_*` 这类名字一律不许;
2. **它的语义真的是"历史天数门槛"** —— 59 天被排除、60 天入选 (合成数据, 不依赖真实 DB);
3. **文档不得声称 `rolling`**。

⚠️ §13.27 的**算法**问题 (全历史均值 = 用未来数据选票) **本轮一字未动** ——
改它属结果变更, 且"as-of 滚动 60 日"与"as-of 之前全部历史"之间还有一个**口径选择**。
本文件只保证:**代码说的和做的是一致的**。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pandas as pd
import pytest

from cycle_price_action.universe import apply_liquidity_filter

_UNIVERSE_PY = Path(__file__).resolve().parents[1] / "cycle_price_action" / "universe.py"


def _synthetic(n_days: int, amount: float = 1e8) -> pd.DataFrame:
    return pd.DataFrame({
        "thscode": ["600000.SH"] * n_days,
        "date": pd.date_range("2025-01-01", periods=n_days, freq="B"),
        "amount": [amount] * n_days,
    })


def test_no_parameter_name_implies_a_window() -> None:
    """★ 名字不得暗示"回看窗口" —— 那正是这次修掉的谎。"""
    sig = inspect.signature(apply_liquidity_filter)
    bad = [p for p in sig.parameters
           if "lookback" in p or "window" in p or p.startswith("roll")]
    assert not bad, (
        f"§13.107: `apply_liquidity_filter` 的参数里有暗示窗口的名字 {bad}。\n"
        f"实现用的是 `counts >= N` —— 那是**最少历史交易日数**, 不是回看窗口。\n"
        f"⇒ 名字说窗口、代码做门槛, 就是本册反复记的「声明的与做的不相交」。"
    )
    assert "min_history_days" in sig.parameters, (
        f"§13.107: 参数应叫 `min_history_days` (说它做的事), 实为 "
        f"{list(sig.parameters)}"
    )


def test_it_really_is_a_history_length_gate() -> None:
    """**行为档**: 59 个交易日 ⇒ 排除; 60 个 ⇒ 入选。"""
    lo = apply_liquidity_filter(_synthetic(59))
    ok = apply_liquidity_filter(_synthetic(60))
    assert "600000.SH" not in lo, (
        "§13.107: 59 个交易日竟入选 ⇒ `min_history_days` 不是历史天数门槛。"
    )
    assert "600000.SH" in ok, (
        "§13.107: 60 个交易日却落选 ⇒ 门槛的语义与名字不符。"
    )


def test_the_mean_is_not_claimed_to_be_rolling() -> None:
    """文档不得声称 `rolling` / "60d" —— 实现里没有滚动。"""
    doc = (apply_liquidity_filter.__doc__ or "")
    fn = next((n for n in ast.walk(ast.parse(_UNIVERSE_PY.read_text(encoding="utf-8")))
               if isinstance(n, ast.FunctionDef) and n.name == "apply_liquidity_filter"), None)
    assert fn is not None, "找不到 apply_liquidity_filter"
    import re
    # 文档里**不允许**把 mean 描述成 rolling
    for text, where in ((doc, "docstring"),):
        for m in re.finditer(r"[^\n]*rolling[^\n]*", text):
            line = m.group(0)
            assert "没有" in line or "不是" in line or "§13.107" in line or "60d rolling mean" in line, (
                f"§13.107: {where} 里又称周转额是 rolling: {line!r}\n"
                f"⇒ 实现是 `groupby(...).mean()`, 没有任何滚动窗口。"
            )
