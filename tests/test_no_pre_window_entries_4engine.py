r"""§1 窗口边界守卫:**成交不得发生在窗口 start 之前**(四族)。

## 为什么值得一条(附一百二十七)

四族的 `load_panel` 都会把起点**往前推一个暖机缓冲**(`WARMUP_DAYS = 400`,
`core/walkforward.py:81` 记着"chase / uptrend / short_reversal 同构")——
也就是说**引擎手里有一段 start 之前的数据**。于是有一个必须钉住的问题:

> **那段暖机数据,会不会被用于"成交"?**

它不该被用于成交:窗口 `[start, end]` 是**评估期**,暖机只是给指标热身。
但这条**此前只有一族有判据**:实测(逐文件 grep)

| 族 | "窗口前无成交"的断言 |
|---|---|
| `chase_up` | ⛔ 无 |
| `uptrend_pullback` | ⛔ 无 |
| **`short_reversal`** | ✅ 有(`test_short_reversal_no_lookahead.py` 的 LAHEAD-001) |
| `cycle_price_action` | ⛔ 无 |

本文件把这条补成**四族统一**的一条(与 LAHEAD-001 重叠 —— 重叠不删,保留它原有那份更细的 trace)。

## 实测读数(建成时)

| 族 | 窗口 | 成交 | 早于 start 的 |
|---|---|---|---|
| `chase_up` | 2026-02-02..2026-04-30 | 9 | **0** |
| `uptrend_pullback` | 同上 | 14 | **0** |
| `short_reversal` | 同上 | 12 | **0** |
| `cycle_price_action` | 2026-04-01..2026-05-01 | **490** | **0** |

(cycle 那组的**最晚 exit = 2026-05-06 > end** —— 正好演示了右边界:持仓不因窗口结束而消失,
故本文件**只断言左边界**。)

⇒ 四族当前**都干净**。**这条是"网",不是"已发生的缺陷"** —— 两者不能混(本册反复记过这一条)。

## 边界的另一半(顺带钉住)

同一条断言还应当覆盖**右边界之外的出场**:窗口结束后才该结束的持仓,其 `exit_date` **可以**
晚于 `end`(`short_reversal` 的 LAHEAD-002 明确把"窗口后出场"**否证为前视** —— 持仓不因窗口结束而消失)。
故本文件**只断言左边界**,并在此写明为什么不一起断言右边界。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import require_market_db

#: 各族的标准小窗**统一放在 `conftest.STD_WINDOWS`**(附一百二十九)—— 让本文件与
#: `test_accounting_closure_4engine.py` **共用同一批回测**;否则同一份计算会被重复收费
#: (`short_reversal` 3 个月窗 ≈ 9 分钟、`cycle` 1 个月窗 ≈ 6 分钟,套件时长翻倍)。
WINDOW_FAST = ("2026-02-02", "2026-04-30")
WINDOW_CYCLE = ("2026-04-01", "2026-05-01")

CASES = [
    ("chase_up", "chase_v1_atr_tp4_sl1", WINDOW_FAST),
    ("uptrend_pullback", "v33_long_reverse_v19", WINDOW_FAST),
    ("short_reversal", "v50_slope", WINDOW_FAST),
    ("cycle_price_action", "v1", WINDOW_CYCLE),
]


def _trades(fam: str, preset: str, window: tuple[str, str]) -> pd.DataFrame:
    from tests.conftest import run_engine_once

    return run_engine_once(fam, preset, window)[0]


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset,window", CASES, ids=[c[0] for c in CASES])
def test_no_trade_is_entered_before_the_window_start(fam: str, preset: str, window) -> None:
    """§1:窗口 = **评估期**。暖机数据只许给指标热身,不许被用于成交。"""
    require_market_db()
    start, _end = window
    tr = _trades(fam, preset, window)
    # 非空转:必须真的有成交,否则"没有早于 start 的成交"什么都没验到
    assert len(tr) > 0, f"{fam}/{preset} 在 {window} 上没有成交 ⇒ 本条空转(请换窗口/preset)"

    early = tr[pd.to_datetime(tr["entry_date"]) < pd.Timestamp(start)]
    assert early.empty, (
        f"§1 窗口边界: {fam}/{preset} 在 {window} 上有 **{len(early)} 笔**成交的 entry_date 早于 start ——\n"
        f"  最早的几笔: {early[['thscode', 'entry_date']].head(5).to_dict('records')}\n"
        f"  暖机数据(`[start-400d, end]`)被用在了成交上,而窗口是**评估期**。"
    )
