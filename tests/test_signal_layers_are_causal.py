r"""§1 守卫:四族的**指标层与信号层截尾不变**(附一百一十三 / 一百一十四)。

## 为什么需要"强"判据

§1 已有一条**弱**判据:扫描 `bfill` / `shift(-x)` / `rolling(center=True)` 的**字面量**。
弱判据抓不到 `groupby` 泄漏、全局归一化、以及任何**间接**前视。
强形式是**行为**判据:

> 把数据在日期 T 处**截断**重算 —— 凡 `date <= T` 的**指标值**与**信号集合**都必须与全量一致。

## 覆盖

| 族 | 指标层 | 信号层 | 实现位置 |
|---|---|---|---|
| `chase_up` | ✅ 40 列 | ✅ | 本文件 |
| `uptrend_pullback` | ✅ 44 列 | ✅ | 本文件 |
| `short_reversal` | ✅ 9 个 pandas 对偶 | ⚠️ 见下 | `tests/test_short_reversal_indicators_are_causal.py` |
| `cycle_price_action` | ⛔ **未覆盖** | ⛔ **未覆盖** | 见"边界" |

`short_reversal` 的指标在 **bar 循环里现算**(`indicators_bt` 的 `bt.Indicator`),
它的对偶已由本文件同款的截尾判据覆盖,且与 backtrader 路径有等价性守卫互锁。
它的**信号层**在 `next()` 里逐 bar 判定,不适用"面板 → 信号表"这种截尾比较 ——
那一层由既有的 `tests/test_short_reversal_no_lookahead.py`(窗口边界、跳空填充等)覆盖。

## 实测读数(建成时)

| 族 | 指标层 | 信号层 |
|---|---|---|
| `chase_up` | 40 列 × 3 截断点 ⇒ **违反 0** | 625 条信号 ⇒ **违反 0** |
| `uptrend_pullback` | 44 列 × 3 截断点 ⇒ **违反 0** | 716 条信号 ⇒ **违反 0** |

⇒ 这两族的指标与信号层**当前是因果的**。这是**正面读数** —— 它把"离线预生成 ⇒ 前视会藏在
那一次"从**怀疑**变成**已检**。

## 边界(如实声明)

* `cycle_price_action` **未覆盖**:它的信号是四个分数函数(`k_patterns` / `k_line_score` /
  `phase_score` / `calendar_score`),接口与"面板 → 信号表"不同,要另写夹具。**属未做,不是已否**。
* 判据测的是**信号生成**;`next()` 里的**成交/出场决策**由各族 `no_lookahead` 文件与 §4 的
  成交规则守卫覆盖。
* 夹具是**真实库**的一小块(120 只主板 × 2 年,约 1 秒)⇒ 按 §6,无库时 **skip 而非 fail**。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import require_market_db

START, END = "2023-06-01", "2024-12-31"

#: 截断点在**面板自己的交易日**里取(≈45% / 70% / 90% 处)。
#:
#: ⚠️ 第一版把截断日期**手写**成 `2024-03-31 / 2024-08-31 / 2024-12-31`,三个**全都不可比**:
#: 前两个是**周末**(非交易日)⇒ `date == T` 的行集为空;第三个正好是**面板最后一天**
#: ⇒ 任何"取下一根 bar"的前视在两侧都是 NaN、**看不出差别**。
#: 结果:**判据一次都没真比过**而报"0 违反" —— 注入 `close.shift(-1)` 也照样绿。
#: ⇒ 截断点必须**从数据里取**,并由 `test_the_comparison_is_not_vacuous` 断言真的比过。
_CUT_FRACTIONS = (0.45, 0.70, 0.90)


def _cuts(panel) -> list:
    days = sorted(set(panel["date"]))
    return [days[int(len(days) * f)] for f in _CUT_FRACTIONS]
N_CODES = 120
TOL = 1e-12

FAMILIES = ("chase_up", "uptrend_pullback")


def _modules(fam: str):
    data = __import__(f"{fam}.data", fromlist=["x"])
    sig = __import__(f"{fam}.signals", fromlist=["x"])
    univ = __import__(f"{fam}.universe", fromlist=["x"])
    return data, sig, univ


def _panel_and_signals(fam: str):
    """小块真实面板 + 全量信号。两族各约 1 秒。"""
    from hiagent_config import get_db_path

    db = Path(str(get_db_path()))
    data, sig, univ = _modules(fam)
    codes = list(univ.load_universe("mainboard_only", db, asof_date=START))[:N_CODES]
    panel = data.load_panel(db, START, END, universe=set(codes))
    ind_full = sig.compute_indicators(panel)
    full_sig = sig.select_entries(ind_full, start_date=START, end_date=END)
    return panel, sig, ind_full, full_sig


def _n_diff(x: pd.Series, y: pd.Series) -> int:
    """判据的核心比较:NaN 对 NaN 算相同;数值走容差;其余走相等。"""
    eq = (x == y) | (x.isna() & y.isna())
    if pd.api.types.is_numeric_dtype(x) and not pd.api.types.is_bool_dtype(x):
        eq = eq | ((x - y).abs() <= TOL).fillna(False)
    return int((~eq).sum())


def _indicator_violations(panel, sig, ind_full, cols, cuts, *, compared: list | None = None) -> list[str]:
    """返回违反列表;`compared` 用于**留痕**"实际比了多少 (列, 截断点)" —— 防空转。"""
    out = []
    for T in cuts:
        ind_t = sig.compute_indicators(panel[panel["date"] <= T])
        a = ind_full[ind_full["date"] == T].set_index("thscode")
        b = ind_t[ind_t["date"] == T].set_index("thscode")
        common = a.index.intersection(b.index)
        if compared is not None:
            compared.append(int(len(common)))
        for c in cols:
            n = _n_diff(a.loc[common, c], b.loc[common, c])
            if n:
                out.append(f"{c} @{pd.Timestamp(T).date()}: {n} 只票的值不同")
    return out


def _signal_violations(panel, sig, full_sig, cuts, *, compared: list | None = None) -> list[str]:
    out = []
    for T in cuts:
        ind_t = sig.compute_indicators(panel[panel["date"] <= T])
        s_t = sig.select_entries(ind_t, start_date=START, end_date=T)
        keep = full_sig[full_sig["date"] <= T]
        if compared is not None:
            compared.append(int(len(keep)))
        kf = set(zip(keep["thscode"], keep["date"]))
        kt = set(zip(s_t["thscode"], s_t["date"]))
        if kf != kt:
            out.append(f"@{T}: 只在全量 {len(kf - kt)} 条 / 只在截尾 {len(kt - kf)} 条")
    return out


@pytest.mark.slow
@pytest.mark.parametrize("fam", FAMILIES)
def test_indicator_layer_is_truncation_invariant(fam: str) -> None:
    """§1:`date <= T` 的指标值不得随 T 之后的数据变化。"""
    require_market_db()
    panel, sig, ind_full, _ = _panel_and_signals(fam)
    cols = [c for c in ind_full.columns if c not in ("thscode", "date")]
    assert len(cols) >= 30, f"{fam}: 只比了 {len(cols)} 列 —— 指标层扫描面异常小"

    cuts = _cuts(panel)
    compared: list[int] = []
    bad = _indicator_violations(panel, sig, ind_full, cols, cuts, compared=compared)
    assert all(n > 0 for n in compared), (
        f"{fam}: 有截断点上**一行都没比到**(每点比到的票数 = {compared}) —— "
        "截断点可能落在非交易日或面板末行,判据会空转"
    )
    assert not bad, (
        f"§1 前视: `{fam}` 的指标层在 T 处被截断后**值变了** —— 说明它读了未来的 bar:\n  "
        + "\n  ".join(bad)
        + "\n(逐个指标定位:`compute_indicators` 里查它的滚动窗口是否 trailing)"
    )


@pytest.mark.slow
@pytest.mark.parametrize("fam", FAMILIES)
def test_signal_layer_is_truncation_invariant(fam: str) -> None:
    """§1:`date <= T` 的信号**集合**不得随 T 之后的数据变化。

    (信号是"选了哪些票、在哪天",所以比较的是**集合**,不是逐值。)
    """
    require_market_db()
    panel, sig, _, full_sig = _panel_and_signals(fam)
    # 非空转:这个夹具必须真的产出信号,否则"0 违反"什么都没验到
    # (第一版夹具 6 只票 × 9 个月 ⇒ 两族各 **0 条信号** ⇒ 那半条判据是空转的)
    assert len(full_sig) >= 100, (
        f"{fam}: 夹具只产出 {len(full_sig)} 条信号 —— 太少,判据接近空转。"
        "请把窗口或票数调大(实测 120 只 × 2 年 ⇒ 625/716 条)"
    )

    cuts = _cuts(panel)
    compared: list[int] = []
    bad = _signal_violations(panel, sig, full_sig, cuts, compared=compared)
    # 门槛按**最小截断点**定:45% 那一档只有 29(chase)/54(uptrend)条 —— 够比,但不是 100。
    # (第一版写成 `n > 100` ⇒ 把一条**非空转**的判据判成空转;门槛要与夹具的实际规模相称。)
    assert all(n >= 10 for n in compared), (
        f"{fam}: 有截断点上的信号太少({compared})—— 比较接近空转"
    )
    assert not bad, (
        f"§1 前视: `{fam}` 的信号层在 T 处截断后**信号集合变了**:\n  " + "\n  ".join(bad)
    )


def test_the_comparator_catches_lookahead() -> None:
    """**牙齿**:同一套比较逻辑,对明确的前视变体必须报出违反。

    (这里用合成数据,免得依赖库;管线级的牙齿由本批在 `chase_up/signals.compute_indicators`
    上做过的实测注入验证负责 —— 注入 `shift(-1)` 后该族的指标判据变红。)
    """
    import numpy as np

    idx = list(range(12))
    base = pd.Series(np.arange(12, dtype=float), index=idx)
    BAR = 7
    CUT = base.iloc[: BAR + 1]

    def _recomputed_last(fn, series, bar):
        return float(fn(series).iloc[bar])

    # ⚠️ 必须在**截断输入上重算** —— 切片一个"已经算好的全量序列"不会显现前视。
    # (第一版就是切片的:`variant.iloc[7]` 与 `variant.iloc[:8].iloc[7]` 是同一个值。
    #  这与 short_reversal 那批的 `bfill` 牙齿同源:前视只在**重算**里可见。)
    lookahead = lambda s: s.shift(-1)          # noqa: E731
    a = _recomputed_last(lookahead, base, BAR)
    b = _recomputed_last(lookahead, CUT, BAR)
    assert _n_diff(pd.Series([a]), pd.Series([b])) == 1, (
        f"合成牙齿失败:重算后 `shift(-1)` 在截断前后居然相同({a!r} vs {b!r})—— 牙齿落不了地"
    )

    causal = lambda s: s.shift(1)              # noqa: E731
    c = _recomputed_last(causal, base, BAR)
    d = _recomputed_last(causal, CUT, BAR)
    assert _n_diff(pd.Series([c]), pd.Series([d])) == 0, "因果序列被误判为前视"
    assert a != c, "夹具本身没能区分前视与因果(两个变体给出同一个值)"
