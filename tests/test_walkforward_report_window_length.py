"""§5/§13.102: `format_walkforward_stats` 估 DSR 的 `n_returns` 必须用**真实的窗口长度**。

## 修的是什么
它此前写死 `n_returns = max(n_windows * 63, 100)`, 注释写「rough estimate: ~63 trading
days/**month**」。**实测一个 2 个月窗口只有约 40 个交易日** (63 已接近 **3** 个月,
且任何月份都没有 63 个交易日) ⇒ `n_returns` **被高估约 43%** ⇒ SE 偏小 ⇒
**z 偏大 ⇒ DSR 偏高**。方向是**乐观**的 (危险的那一侧)。

**实测影响** (当前最优 v22, 22 窗口, k=162): DSR **0.107 → 0.062** (相对 −42%);
祖先搜索 rank-1 (23 窗口, k=39): DSR 0.6665 → 0.5005、Bonferroni 0.1751 → 0.5659。
⇒ **不翻转任何已登记判定** (两处都远未达门槛), 但**每一份 §5 报告里的 DSR 都偏高**。

## 修法: 让它**不可能**再猜
`n_returns` 依赖窗口长度, 而它**无法从入参 `df` 推出** (df 只有每窗指标, 没有窗口长度)
⇒ 改成**必填关键字参数**, 由**知道 windows 的那个调用方**给实测值。
**"忘了给窗口长度"于是变成语法错误, 而不是一个静默偏高的数。**
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pandas as pd
import pytest

from dna_stats.walkforward_report import format_walkforward_stats

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTER = REPO_ROOT / "dna_stats" / "walkforward_report.py"


def _df(n_windows: int = 6) -> pd.DataFrame:
    return pd.DataFrame({
        "total_return": [0.02, -0.01, 0.03, 0.01, -0.02, 0.04][:n_windows],
        "sharpe": [1.2, -0.4, 1.5, 0.3, -0.9, 1.1][:n_windows],
        "max_dd": [-0.05, -0.08, -0.04, -0.06, -0.09, -0.03][:n_windows],
        "trades": [10] * n_windows,
    })


def test_window_length_is_a_required_keyword() -> None:
    """它必须**必填** —— 有默认值就等于又埋了一个"猜"。

    (判据用 `inspect`: 直接看**函数的实际签名**, 不是看源码文本。)
    """
    sig = inspect.signature(format_walkforward_stats)
    assert "trading_days_per_window" in sig.parameters, (
        "§13.102: 缺少 `trading_days_per_window` 参数 ⇒ 报告器又要靠猜。"
    )
    p = sig.parameters["trading_days_per_window"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"§13.102: 它应当是 keyword-only, 实为 {p.kind}"
    )
    assert p.default is inspect.Parameter.empty, (
        f"§13.102: 它**必须必填** (当前默认值 {p.default!r})。\n"
        f"给默认值 = 又埋一个'猜', 而这次猜错的方向是**乐观** (DSR 偏高)。"
    )


def test_window_length_actually_moves_the_reported_dsr() -> None:
    """★ **行为档**: 换窗口长度必须**真的改变**报出的 DSR。

    否则参数是装饰性的 —— 那正是本册记了 15+ 轮的那种"提到 ≠ 做到"。
    """
    a = format_walkforward_stats(_df(), n_comparisons=50, trading_days_per_window=63)
    b = format_walkforward_stats(_df(), n_comparisons=50, trading_days_per_window=40)
    assert a != b, (
        "§13.102: 换 `trading_days_per_window` 后报告**一字未变** ⇒ 参数没被用上。"
    )
    # 窗口越长 ⇒ T 越大 ⇒ SE 越小 ⇒ DSR 越大; 这里 63 > 40 ⇒ a 的 DSR 应不低于 b
    import re
    da = float(re.search(r"DSR\(obs=[-\d.]+, k=\d+\) = ([\d.]+)", a).group(1))
    db = float(re.search(r"DSR\(obs=[-\d.]+, k=\d+\) = ([\d.]+)", b).group(1))
    assert da >= db, (
        f"§13.102: 窗口更长应给出**不低于**的 DSR (T 更大 ⇒ SE 更小), 实测 {da} vs {db}"
    )


def test_no_hardcoded_per_window_constant_left_in_the_reporter() -> None:
    """报告器里不得再出现写死的'每窗交易日数'常数。

    处理方式: 找**乘法字面量** `n_windows * <int>` —— 那正是旧代码的形态。
    """
    tree = ast.parse(REPORTER.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "format_walkforward_stats"), None)
    assert fn is not None, "找不到 format_walkforward_stats"
    bad = []
    for n in ast.walk(fn):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult):
            left = ast.unparse(n.left)
            right = ast.unparse(n.right)
            if "n_windows" in left + right and re.search(r"\b\d{2,}\b", left + right):
                bad.append((n.lineno, ast.unparse(n)))
    assert not bad, (
        f"§13.102: 报告器里又有写死的每窗常数: {bad}\n"
        f"⇒ 窗口长度必须来自调用方, 不得在报告器里猜。"
    )


def test_the_caller_derives_it_from_the_actual_windows() -> None:
    """调用方必须**从真实窗口**导出它, 而不是自己再写一个常数。"""
    src = (REPO_ROOT / "uptrend_pullback" / "wfv_eval.py").read_text(encoding="utf-8")
    assert "_trading_days_per_window" in src, (
        "§13.102: wfv_eval 里没有从 windows 实测交易日数的助手。"
    )
    assert "COUNT(DISTINCT date)" in src, (
        "§13.102: 实测口径应当真的去数交易日 (COUNT(DISTINCT date)), 而不是乘一个日历常数。"
    )
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "_trading_days_per_window"), None)
    assert fn is not None, "找不到 _trading_days_per_window 的定义"
    assert "raise" in ast.unparse(fn), (
        "§13.102: 数不到交易日时必须**抛错**(§0), 不得静默退回一个常数。"
    )
