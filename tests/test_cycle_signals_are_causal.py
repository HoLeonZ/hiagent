"""§1: `cycle_price_action` 的四个信号函数**截尾不变** (§13.149)。

为什么单开一条
--------------
`cycle_price_action/backtest.py::_precompute_scores` 的 docstring 里有**四条**很精确的 §1 断言:

    * `detect_k_patterns` / `k_line_score`: 全为 rolling/shift 的后向窗口,
      在前缀 `df.iloc[:i+1]` 的第 i 行与在全表第 i 行取值相同;
    * `calendar_score`: 纯日期函数 (锚点是自然日历月末/季报日, **不是切片端点**);
    * `phase_score`: 只用到序列**长度**的 `np.arange(n)`, 第 i 位与 n 无关 ——
      **唯一例外**是 `len < max(periods)` 时整体返回 0。

**四条此前一条都没被验过。** §13.105 的原则:
> **一条只写在 docstring 里的 §1 断言, 与一个不响的守卫是同一种东西。**

而本仓那条强因果性守卫只覆盖 `uptrend_pullback` 与 `chase_up` 的指标层(§13.147/§13.148) ——
cycle 的信号函数**一个都不在**。

本守卫做两件事
--------------
1. **截尾不变性**: 把每只票的序列在第 i 根 bar 处从尾部截断后重算,
   前 i 个值必须逐位不变 (数值列用 isnan+isclose, 字符串列用相等);
2. **把 docstring 里那条"例外"也钉住** —— 显式验证 `len < max(periods)` 时
   `phase_score` 整体返回 0 (那是**声明的行为**, 不是可以默认为真的)。

⚠️ **判据可能失败** —— 已注入验证: 把 `signals.py` 里第一个 `rolling(5)` 改成
   `rolling(5, center=True)` ⇒ `k_line_score` 出现 **31 个不一致值**
   (另三个函数正确地不受影响, 因为那条 rolling 属于 `k_line_score`)。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

W0, W1 = "2024-10-08", "2026-09-18"
N_CODES = 12          # 够用且快; 判据本身与票数无关


@pytest.fixture(scope="module")
def universe():
    from cycle_price_action.data_feed import load_universe_data

    from hiagent_config import DB_PATH

    # ⚠️ `asof_date` / `start` 必须是 `datetime.date` —— 传 str 会在
    # `min(ref_pit, db_last)` 处 TypeError (fail-fast; 我第一版就踩了)。
    return load_universe_data(DB_PATH, dt.date.fromisoformat(W0), dt.date.fromisoformat(W1),
                              asof_date=dt.date.fromisoformat(W0))


def _diff(a: pd.Series, b: pd.Series) -> int:
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    assert len(a) == len(b), f"长度不一致 {len(a)} vs {len(b)}"
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
        va, vb = np.asarray(a, float), np.asarray(b, float)
        same = (np.isnan(va) & np.isnan(vb)) | np.isclose(va, vb, rtol=0, atol=1e-12)
        return int((~same).sum())
    sa = a.astype(object).where(a.notna(), None).values
    sb = b.astype(object).where(b.notna(), None).values
    return int((sa != sb).sum())


def test_cycle_signal_functions_are_truncation_invariant(universe) -> None:
    from cycle_price_action.cycle import DEFAULT_PERIODS, phase_score
    from cycle_price_action.signals import detect_k_patterns, k_line_score
    from cycle_price_action.time_windows import calendar_score

    mb = max(DEFAULT_PERIODS)
    checked = 0
    bad: dict[str, int] = {"k_patterns": 0, "k_line_score": 0,
                           "phase_score": 0, "calendar_score": 0}
    for c in sorted(universe)[:N_CODES]:
        df = universe[c].df.reset_index(drop=True)
        if len(df) <= mb + 30:
            continue
        pat = detect_k_patterns(df)
        for frac in (0.6, 0.8, 0.95):
            i = int(len(df) * frac)
            if i < mb:
                continue
            cut = df.iloc[:i].reset_index(drop=True)
            pat2 = detect_k_patterns(cut)
            checked += 1
            bad["k_patterns"] += _diff(pat.iloc[:i], pat2)
            bad["k_line_score"] += _diff(k_line_score(df, pat).iloc[:i],
                                         k_line_score(cut, pat2))
            bad["phase_score"] += _diff(phase_score(df["date"], periods=DEFAULT_PERIODS).iloc[:i],
                                        phase_score(cut["date"], periods=DEFAULT_PERIODS))
            bad["calendar_score"] += _diff(calendar_score(df["date"]).iloc[:i],
                                           calendar_score(cut["date"]))
    assert checked >= 10, f"只检验了 {checked} 次 —— 判据的扫描单位太窄, 这个绿是虚的"
    assert not any(bad.values()), (
        f"§1: `_precompute_scores` docstring 的四条断言**至少一条不成立** —— "
        f"截尾后被改动的值: { {k: v for k, v in bad.items() if v} }\n"
        f"⇒ 那些函数用到了 T 之后的信息 (或 docstring 的断言写宽了)。"
    )


def test_phase_score_zero_branch_is_pinned(universe) -> None:
    """docstring 那条**例外**必须仍然成立: `len < max(periods)` ⇒ 整体返回 0。

    这不是"顺带一提": 它是 `_precompute_scores` 里**显式复刻**的一个分支
    (`min_bars` 比较) —— 若它哪天不再是 0, 复刻分支就对不上了。
    """
    from cycle_price_action.cycle import DEFAULT_PERIODS, phase_score

    mb = max(DEFAULT_PERIODS)
    df = universe[sorted(universe)[0]].df.reset_index(drop=True)
    short = df.iloc[: mb - 1].reset_index(drop=True)
    out = phase_score(short["date"], periods=DEFAULT_PERIODS)
    assert (np.asarray(out, float) == 0.0).all(), (
        f"§1/docstring: `phase_score` 在 len={len(short)} < max(periods)={mb} 时应整体返回 0, "
        f"实测非全零 ⇒ `_precompute_scores` 里复刻的那个分支已经对不上。"
    )
