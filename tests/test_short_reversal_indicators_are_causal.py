r"""§1 守卫:`short_reversal` 的指标层**截尾不变**(不许看未来)。

## 为什么是这一族(附一百一十三)

四族里 `short_reversal` 是**唯一**把指标放在 **bar 循环里现算**的
(`indicators_bt.py` 的 `bt.Indicator` 子类: `PctChg` / `Am60` / `UpStreak` /
`BelowMa60Ratio60` / `AtrAdj` / `AmountRatio` / `ReturnN` / `Ma20SlopeN`),
其余三族的指标层是离线预生成 ⇒ 前视只会发生在"离线那一次"。
**离线层的前视是"一次性错",bar 循环里的前视是"每根 bar 都错"** —— 后者风险更高,
却一直没有强判据(§1 的强形式是**截尾不变性**:bar i 的值不得依赖 i 之后的数据)。

## 判据(与"禁用函数扫描"的区别)

§1 已有一条**弱**判据(禁用 `bfill` / `shift(-x)` / `rolling(center=True)` 的字面量扫描)。
弱判据抓不到 `groupby` 泄漏、全局归一化、以及**间接**前视。本文件的判据是**行为**:
把数据在 bar i 处截断重算,**同一个 bar 的值必须逐位相同**。

**本判据测的是 pandas 对偶**(`*_pandas`)。它们与 backtrader 那条路已由
`tests/test_indicator_equivalence_pandas_vs_backtrader.py` 互锁 ⇒ 对偶因果
**且**两者等价 ⇒ bt 路径因果。**两条判据合起来才覆盖生产路径**,这也写在该文件里。

## 实测结果(建成时的读数)

**9 个对偶 × 5 个截断点 = 45 次比较,违反 0 次** ⇒ 这一族当前的指标层是因果的。

## 牙齿(两次才写对,记下来)

第一版牙齿用了 `shift(-1)` 与 `bfill`:
* `shift(-1)` → **2/3 被抓**(最后一个截断点上两边都是 NaN ⇒ 不可区分,属正常);
* **`bfill` → 0/3 —— 不是判据瞎,是我的注入没落地**:合成夹具里**没有 NaN**,
  而 `bfill` 在无 NaN 的数据上是**空操作**。
⇒ 第二版夹具**故意留几个 NaN 洞**(真实面板本来就有:停牌 / 暖机),
再拿 `bfill` / `shift(-1)` / `rolling(center=True)` 当牙齿,**三个都验过会响**。

> 这正是本仓库记过多次的那条:**"不响"的第一嫌疑是"我的注入没生效"**,而不是判据有问题。
"""
from __future__ import annotations

import importlib
import inspect

import numpy as np
import pandas as pd
import pytest

IB = importlib.import_module("short_reversal.indicators_bt")

#: 截断点(bar 下标)。取足够多的位置,且都越过各指标的最短窗口。
CUT_POINTS = (80, 120, 150, 180, 200, 230, 259)
_TOL = 1e-12


def _fixture(n: int = 260, seed: int = 20261020) -> pd.DataFrame:
    """确定性的合成面板 —— **故意留 NaN 洞**(真实面板本来就有;也是 `bfill` 牙齿的落点)。

    无 DB、无网络、0.01s 量级 ⇒ §6「证据不在就跳过」对这条不适用:它不需要任何外部证据。
    """
    rng = np.random.default_rng(seed)
    close = 10.0 + np.cumsum(rng.normal(0, 0.15, n))
    amount = np.abs(rng.normal(5e7, 1e7, n))
    df = pd.DataFrame({
        "close": close,
        "amount": amount,
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": np.abs(rng.normal(1e6, 2e5, n)),
    })
    # NaN 洞(停牌/暖机形状):前视在 NaN 处最容易藏。**必须有一个落在 CUT_POINTS 范围内** ——
    # 实测:`bfill` 类前视**只在洞内可观测**(本夹具 6 个 bar:95-97 与 230-232),
    # 洞里没有截断点 ⇒ 那条牙齿会静默变成空操作(第一版就栽在这)。
    df.loc[95:97, "amount"] = np.nan
    df.loc[140:141, "close"] = np.nan
    df.loc[210, "volume"] = np.nan
    df.loc[230:232, "amount"] = np.nan
    return df


#: 每个对偶怎么被调用 —— 由 `test_every_pandas_dual_is_covered` 强制与模块导出一致。
DUALS: dict[str, object] = {
    "sma_pandas": lambda d: IB.sma_pandas(d.close, 60),
    "pct_chg_pandas": lambda d: IB.pct_chg_pandas(d.close),
    "am60_pandas": lambda d: IB.am60_pandas(d.amount, 60),
    "up_streak_pandas": lambda d: IB.up_streak_pandas(d.close),
    "below_ma60_ratio_pandas": lambda d: IB.below_ma60_ratio_pandas(
        d.close, IB.sma_pandas(d.close, 60), 60
    ),
    "return_n_pandas": lambda d: IB.return_n_pandas(d.close, 20),
    "amount_ratio_pandas": lambda d: IB.amount_ratio_pandas(d.amount, 5, 20),
    "ma20_slope_pandas": lambda d: IB.ma20_slope_pandas(IB.sma_pandas(d.close, 20), 5),
    "rsi_pandas": lambda d: IB.rsi_pandas(d.close, 14),
}


def _violations(fn, df: pd.DataFrame, cuts=CUT_POINTS) -> list[str]:
    """**判据核心**:截断重算后,同一个 bar 的值必须相同。"""
    full = fn(df)
    out = []
    for i in cuts:
        trunc = fn(df.iloc[: i + 1])
        a, b = full.iloc[i], trunc.iloc[i]
        if pd.isna(a) and pd.isna(b):
            continue
        if pd.isna(a) != pd.isna(b) or abs(float(a) - float(b)) > _TOL:
            out.append(f"bar {i}: 全量={a!r} 截尾={b!r}")
    return out


def test_every_pandas_dual_is_covered() -> None:
    """**面**:`indicators_bt` 导出的每个 `*_pandas` 都必须在本文件的参数化里。

    (新增一个指标而不加进来 ⇒ 红。这是本会话反复栽的那条:**判据的面必须等于实际集合**。)
    """
    exported = {
        n for n, v in vars(IB).items()
        if n.endswith("_pandas") and callable(v) and not n.startswith("_")
    }
    covered = set(DUALS)
    assert exported == covered, (
        "`short_reversal.indicators_bt` 的 pandas 对偶与本地参数化不一致:\n"
        f"  未覆盖: {sorted(exported - covered)}\n"
        f"  多出来: {sorted(covered - exported)}\n"
        "新增/删除指标时请同步 `DUALS`(本判据的全部价值就在这个集合相等上)。"
    )
    assert len(covered) >= 9, f"对偶只有 {len(covered)} 个 —— 扫描面异常小"


@pytest.mark.parametrize("name", sorted(DUALS))
def test_indicator_is_truncation_invariant(name: str) -> None:
    """§1:bar i 的值不得依赖 i 之后的数据(截断重算后逐位相同)。"""
    df = _fixture()
    bad = _violations(DUALS[name], df)
    assert not bad, (
        f"§1 前视: `{name}` 在数据被截到该 bar 之后**值变了** —— "
        f"说明它读了未来的 bar:\n  " + "\n  ".join(bad)
    )


def test_the_criterion_actually_catches_lookahead() -> None:
    """**牙齿**:同一套比较逻辑,对**明确的前视变体**必须报红。

    ⚠️ 第一版这里只用了 `shift(-1)` 与 `bfill`,而 `bfill` **0/3 被抓** ——
    原因不是判据瞎,是夹具里**没有 NaN**、`bfill` 是空操作(注入没落地)。
    夹具现在带 NaN 洞,三个变体**逐个验过**:
    """
    df = _fixture()
    # ⚠️ 截断点**必须落在 NaN 洞里**才看得见 `bfill` 类前视 —— 实测只有 6 个 bar 可观测。
    TEETH_CUTS = (96, 150, 200, 231)
    lookahead_variants = {
        "shift(-1)": lambda d: IB.pct_chg_pandas(d.close.shift(-1)),
        "bfill(只在洞内可观测)": lambda d: IB.am60_pandas(d.amount.bfill(), 60),
        "rolling(center=True)": lambda d: d.close.rolling(60, min_periods=60, center=True).mean(),
    }
    not_caught = []
    for label, fn in lookahead_variants.items():
        if not _violations(fn, df, cuts=TEETH_CUTS):
            not_caught.append(label)
    assert not not_caught, (
        "以下前视变体**没有被判据抓到** —— 判据或牙齿有一个是空的:\n  "
        + "\n  ".join(not_caught)
        + "\n(先确认注入是否落地:该变体在这个夹具上真的改变了数值吗?)"
    )


def test_the_fixture_is_not_vacuous() -> None:
    """非空转:夹具要够长、且**真的有 NaN**(否则 `bfill` 那条牙齿是空操作)。"""
    df = _fixture()
    assert len(df) > max(CUT_POINTS), "夹具比截断点还短"
    assert df.isna().any().any(), (
        "夹具里一个 NaN 都没有 —— `bfill` 类前视会变成空操作,牙齿就此失效"
        "(这正是第一版踩的坑)"
    )
    # 更强的一条:洞必须**落在牙齿的截断点范围内**,否则那条牙齿仍会静默空转
    holes = {i for i in range(len(df)) if df.iloc[i].isna().any()}
    assert holes & set((96, 150, 200, 231)), (
        f"牙齿的截断点没有一个落在 NaN 洞里(洞在 {sorted(holes)[:8]}…)—— "
        "`bfill` 那条会变成空操作:实测该类前视**只在洞内可观测**"
    )
    # 且每个对偶的**全量**结果不是全 NaN(否则比较恒真)
    for name, fn in DUALS.items():
        out = fn(df)
        assert not out.isna().all(), f"{name} 在夹具上全是 NaN ⇒ 该条比较恒真"
