r"""§1 守卫:`short_reversal` 的**信号层**因果 —— 补上四族表里的最后一格。

## 为什么这一格此前是空的

四族里 `short_reversal` 的信号是在 `next()` 里**逐 bar 判定**的,不适用"面板 → 信号表"式的
截尾比较;它的**指标层**已由 `tests/test_short_reversal_indicators_are_causal.py` 覆盖
(9 个 pandas 对偶 × 截断点,实测 0/45 违反),而**信号层**一直登记为"未做"。

本批找到同形式的落点:快扫器 `scan_signals_fast._scan_preset(preset, signal_date, panel)`
正是"面板 → 信号表"的形状,且它与**真引擎路径**由
`tests/test_fast_scanner_matches_engine.py` 互锁(6 preset × 真引擎逐只比较)
⇒ 覆盖快扫器 = 覆盖引擎的信号层。

## 判据

> 同一个信号日 T,**面板里有没有 T 之后的 bar,不得改变 T 日的命中集合**。

## ⚠️ 顺带查到的一处**静默契约违反**(已修,记在这里)

`_filter_signals` 原实现是 `df.groupby("thscode").tail(1)` —— 取的是**面板的最后一行**,
`signal_date` 参数**不决定取哪一行** ⇒ as-of 日其实是"面板末端"。生产路径恰好让两者相等
(它用 `load_panel_for_signal(db, signal_date)`,面板本来就止于 signal_date),所以一直没露;
但**传错不会报错,只会静默算成另一天**。实测:面板止于 `06-30` 而 `signal_date=04-30`
⇒ 返回的是 **06-30 的命中**(7 只),而 T 日正确命中是 **2 只**。

修法是**零生产漂移**的(生产路径的面板本来就止于 T,切片是恒等):
加一行 `df = df[df["date"] <= pd.Timestamp(signal_date)]`。
**零漂移证据**:与真引擎的等价性门禁 `test_fast_scanner_matches_engine.py` **22 passed**。

本文件的 `test_a_mismatched_signal_date_no_longer_silently_scans_another_day`
把这个修复**钉住** —— 它是这条守卫的牙齿。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import require_market_db

PRESET = "v50_slope"
#: 信号日 → 用来对照的"更长的面板"的末端。
CUTS = (("2026-03-31", "2026-06-30"), ("2026-04-30", "2026-06-30"), ("2026-05-29", "2026-06-30"))


def _scan(date: str, panel):
    import short_reversal.scan_signals_fast as fast

    df, _ = fast._scan_preset(PRESET, date, panel, exclude_st=False)
    return sorted(df["thscode"])


def _panels(date: str, longer_end: str):
    from hiagent_config import get_db_path
    from short_reversal._panel_loader import load_panel_for_signal

    db = Path(str(get_db_path()))
    return load_panel_for_signal(db, date), load_panel_for_signal(db, longer_end)


@pytest.mark.parametrize("date,longer_end", CUTS)
def test_signal_layer_is_truncation_invariant(date: str, longer_end: str) -> None:
    """§1:面板里有没有 T 之后的 bar,不得改变 T 日的命中集合。"""
    require_market_db()
    p_short, p_long = _panels(date, longer_end)
    assert p_short["date"].max() <= p_long["date"].max(), "夹具:对照面板必须更长"
    hits_short, hits_long = _scan(date, p_short), _scan(date, p_long)
    assert hits_short == hits_long, (
        f"§1 前视:信号日 {date} 的命中随面板末端变化 ——\n"
        f"  面板止于 {date} : {hits_short}\n"
        f"  面板止于 {longer_end} : {hits_long}\n"
        f"  只在后者: {sorted(set(hits_long) - set(hits_short))}\n"
        f"  只在前者: {sorted(set(hits_short) - set(hits_long))}"
    )


def test_the_criterion_has_teeth() -> None:
    """**牙齿**:`signal_date` 必须真的决定取哪一行 —— 去掉那个切片 ⇒ 本文件必红。

    (这一条就是本批修的那处静默契约违反:原实现取"面板最后一行",于是面板更长时
     同一 T 日会返回**另一天**的命中。实测 `04-30` 那组:2 只 → 7 只。)
    """
    require_market_db()
    p_short, p_long = _panels("2026-04-30", "2026-06-30")
    assert _scan("2026-04-30", p_short) == _scan("2026-04-30", p_long), (
        "判据失效:同一 T 日、两种面板末端应当给出同一命中集合"
    )
    # 非空转:该 T 日必须真的**有**命中,否则"两者相同"什么都没验到
    hits = _scan("2026-04-30", p_short)
    assert hits, f"夹具失效:信号日 2026-04-30 在 {PRESET} 上没有命中 ⇒ 本判据空转"


def test_the_fixture_is_not_vacuous() -> None:
    """夹具自检:两个面板都非空、且**确实长度不同**(否则那条比较恒真)。"""
    require_market_db()
    p_short, p_long = _panels("2026-04-30", "2026-06-30")
    assert len(p_short) > 0 and len(p_long) > len(p_short), (
        f"夹具失效:长短面板长度 {len(p_short)} / {len(p_long)} —— 必须后者更长"
    )
