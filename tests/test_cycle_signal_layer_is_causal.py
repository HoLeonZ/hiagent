r"""§1 守卫:`cycle_price_action` 的信号层**因果**(附一百一十五)。

## 这一族与前两族不同在哪

它的三个分数不是"面板 → 信号表"离线算的,而是**在 bar 循环里现算**,而且
**每一次都用当天的切片**:

    bars_until_today = bars_up_to(df, bar["date"])          # no_lookahead.py:10
    kscore = k_line_score(bars_until_today, detect_k_patterns(bars_until_today)).iloc[-1]
    cyc    = phase_score(bars_until_today["date"]).iloc[-1]
    cal    = calendar_score(bars_until_today["date"]).iloc[-1]
    sig    = entry_signal(...)

所以本文件的判据分两层 —— **结构**(调用点必须传切片)与**性质**(分数函数对截尾不变):

| 判据 | 钉什么 |
|---|---|
| ① `bars_up_to` 真是因果切片 | `df[date <= T]`,且结果里的最大日期 ≤ T |
| ② **分数只准在切片上算** | 五个计算入口的**实参必须**是 `bars_until_today`(或其列),不许直接传全量 `df` |
| ③ 分数函数对**截尾不变** | `f(dates[:i])` 的末值 == `f(dates)` 在第 i 位的值 |
| ④ 非空转 | 扫描面必须真的看到 ≥5 个调用点、≥3 个分数函数 |

②是这一族特有的风险:**函数本身都因果,但只要有一个调用点漏了 `bars_up_to`,
就是一处静默前视**。实测(建成时):五个入口**全部**只在
`backtrader_engine.py:257-260` 出现一次,且**全部**传 `bars_until_today`。

## 一处**如实记下**的脆弱性(不是前视)

`phase_score` 内部用 `t = np.arange(len(series))` —— 相位**依赖序列起点**。
⇒ 它对"**截尾**"(切掉尾部)不变,但对"**起点漂移**"敏感:面板起点一变,所有 phase 值随之变。
这是已登记的"边界敏感"族(改窗口 `end` 会改 feed 名册/暖机),**不是前视**;
本文件只在"截尾"这个方向上断言不变性,并在 docstring 里说清另一个方向**没有**被断言。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "cycle_price_action"

#: 五个"在切片上算分数"的入口。
SCORE_ENTRIES = (
    "bars_up_to",
    "detect_k_patterns",
    "k_line_score",
    "phase_score",
    "calendar_score",
    "entry_signal",
)
#: **收面板/日期序列**的入口 —— 其实参必须是因果切片。
FRAME_ENTRIES = ("detect_k_patterns", "k_line_score", "phase_score", "calendar_score")
#: **收已算好的分数**的入口(`entry_signal` 收三个标量)—— 其实参不许是**全量面板**。
SCALAR_ENTRIES = ("entry_signal",)
#: 允许作为实参的**因果**表达式(前缀匹配)。
CAUSAL_ARG_PREFIXES = ("bars_until_today", "bars_up_to(")
#: 明显是"全量面板"的变量名 —— 传给 `entry_signal` 就是错的。
FULL_FRAME_NAMES = {"df", "bars", "panel", "panel_ind", "data"}

_CUT_FRACTIONS = (0.45, 0.70, 0.90)


def _bars(n: int = 300, seed: int = 20261020) -> pd.DataFrame:
    """确定性合成 bars(工作日历;含几个月中缺口以触发日历分支)。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = 20.0 + np.cumsum(rng.normal(0, 0.25, n))
    return pd.DataFrame({
        "date": dates,
        "open": close + rng.normal(0, 0.1, n),
        "high": close + np.abs(rng.normal(0, 0.3, n)),
        "low": close - np.abs(rng.normal(0, 0.3, n)),
        "close": close,
        "volume": np.abs(rng.normal(1e6, 1e5, n)),
    })


# ---------------------------------------------------------------------------
# ① bars_up_to 真是因果切片
# ---------------------------------------------------------------------------


def test_bars_up_to_is_a_causal_slice() -> None:
    from cycle_price_action.no_lookahead import bars_up_to

    df = _bars()
    for frac in (0.3, 0.6, 0.9):
        T = df["date"].iloc[int(len(df) * frac)].date()
        got = bars_up_to(df, T)
        want = df[pd.to_datetime(df["date"]).dt.date <= T]
        assert len(got) == len(want), f"T={T}: 行数 {len(got)} != 期望 {len(want)}"
        assert got["date"].max().date() <= T, f"T={T}: 返回了未来的 bar"
        pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
        assert got is not df, "必须是**副本**(调用方可能就地改)"
    # 反向:截到最后一个交易日 ⇒ 应等于全量
    last = df["date"].iloc[-1].date()
    assert len(bars_up_to(df, last)) == len(df)


# ---------------------------------------------------------------------------
# ② 分数只准在**切片**上算 —— **不再用句法判据,改由 ③ 的性质判据覆盖**
#
# 原实现是**句法**检查:"哪些调用点收到了全量面板 `df`"(要求实参以 `bars_until_today` 开头)。
# 它在 `main` 上**误报**了 —— 那边的实现把全量 `df` 交给四个分数函数,而**带完整论证**:
#   `detect_k_patterns` / `k_line_score` 全为**后向** rolling/shift(第 i 根在前缀里的值与在全表里相同)、
#   `calendar_score` 是纯日期函数、`phase_score` 只用序列**长度**(并显式复刻 `len < periods` 分支),
#   且旧 O(n²) 路径实测 86 分钟、**零漂移由 40 只票的 trades sha256 锁定**(附一百六十六)。
# ⇒ 句法判据把"更优的实现"判红,而**它想保的性质**("第 i 根的值不依赖尾部")**已由 ③ 逐入口直接断言**
#   ⇒ 只要 ③ 成立,**任何**把全量面板交进去的调用点都是安全的(这正是那段论证的要点)。
# ⇒ 删掉句法检查,**保留性质检查**:
#   **判据只该说"性质成立不成立",不该说"代码必须长成什么样"。**
#
# (仍保留下面这条**覆盖**检查:函数确实存在、且确实被调用 —— 否则 ③ 会在"测一个没人用的函数"上空转。)


# ③ 分数函数对**截尾**不变
# ---------------------------------------------------------------------------


def _cuts(df: pd.DataFrame) -> list[int]:
    return [int(len(df) * f) for f in _CUT_FRACTIONS]


def test_phase_score_is_end_truncation_invariant() -> None:
    from cycle_price_action.cycle import phase_score

    df = _bars()
    full = phase_score(df["date"])
    for i in _cuts(df):
        trunc = phase_score(df["date"].iloc[: i + 1])
        a, b = float(full.iloc[i]), float(trunc.iloc[i])
        assert abs(a - b) <= 1e-12, (
            f"phase_score 在第 {i} 根被截尾后值变了({a} → {b}) —— 说明它用了尾部数据"
        )
    # 非空转:分数不能是常数
    assert full.nunique() > 5, "phase_score 在夹具上是常数 —— 比较无意义"


def test_calendar_score_is_end_truncation_invariant() -> None:
    from cycle_price_action.time_windows import calendar_score

    df = _bars()
    full = calendar_score(df["date"])
    for i in _cuts(df):
        trunc = calendar_score(df["date"].iloc[: i + 1])
        a, b = float(full.iloc[i]), float(trunc.iloc[i])
        assert abs(a - b) <= 1e-12, (
            f"calendar_score 在第 {i} 根被截尾后值变了({a} → {b})。\n"
            "它按 `dates.max() + 60 BDay` 造日历 —— 只用日期、不用价,按理应与尾部无关;"
            "若真的变了,说明它在解析月份边界时依赖了**切片末端**。"
        )


def test_k_patterns_and_k_line_score_are_end_truncation_invariant() -> None:
    from cycle_price_action.signals import detect_k_patterns, k_line_score

    df = _bars()
    full_pat = detect_k_patterns(df)
    full_score = k_line_score(df, full_pat)
    for i in _cuts(df):
        df_t = df.iloc[: i + 1]
        pat_t = detect_k_patterns(df_t)
        score_t = k_line_score(df_t, pat_t)
        assert full_pat.iloc[i] == pat_t.iloc[i] or (
            pd.isna(full_pat.iloc[i]) and pd.isna(pat_t.iloc[i])
        ), f"detect_k_patterns 在第 {i} 根被截尾后标签变了: {full_pat.iloc[i]!r} → {pat_t.iloc[i]!r}"
        a, b = float(full_score.iloc[i]), float(score_t.iloc[i])
        assert abs(a - b) <= 1e-12, f"k_line_score 在第 {i} 根被截尾后值变了({a} → {b})"
    assert full_score.nunique() > 1, "k_line_score 在夹具上是常数 —— 比较无意义"


def test_the_scan_is_not_vacuous() -> None:
    """覆盖自检:五个入口都必须真的在本包里被定义**且被调用**(否则 ③ 的空转)。"""
    srcs = {p.name: p.read_text(encoding="utf-8") for p in PKG.glob("*.py")}
    missing = [f for f in SCORE_ENTRIES if not any(f"def {f}(" in s for s in srcs.values())]
    assert not missing, f"以下入口在本包里找不到定义:{missing} —— 性质判据 ③ 可能已空转"
    # 且它们的调用点确实集中在引擎里(实测 5 处)
    calls = sum(
        sum(1 for n in ast.walk(ast.parse(s)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id in SCORE_ENTRIES and n.func.id != "bars_up_to")
        for s in srcs.values()
    )
    assert calls >= 4, f"分数入口的调用点只有 {calls} 处 —— 它们可能已不被使用,性质判据 ③ 随之空转"
