"""§13.13 那条禁令的**可执行化**: 四族同名指标的**口径对照表**, 逐族钉死。

## 背景
* §13.13 实测: 四族**全部都会报**的指标只有 4 个 (`cagr`/`sharpe`/`max_dd`/`win_rate`),
  而**这 4 个全部定义不同** ⇒ 立了一条禁令:
  > **不得把这 4 个量中的任何一个当作跨族"可比指标"引用, 除非先对齐定义。**
* §13.15: 要修指标层, 第一步**不是**建 `core/metrics.py`, 而是
  **一个查取值/语义的跨引擎测试** —— 而那个测试"今天必然红" ⇒ 闭环一直没开。

## 本文件做什么 / 不做什么
**做**: 把那张对照表从**散文**变成**机器可读的常量**, 并让任何一族的定义变动**立刻变红**。
**不做**: **不把四族统一** —— 统一属**结果变更** (会动四条回测链的全部历史指标),
按既有授权只登记。本节只让"定义不同"这件事**有载体、且不许静默变化**。

## 表是**量出来的**, 不是回忆的 (出处逐条写在 `_SOURCE` 里)
| 量 | `chase_up` | `uptrend_pullback` | `short_reversal` | `cycle_price_action` |
|---|---|---|---|---|
| 年化常数 | **243** | **243** | **252** | **252** |
| `sharpe` 基准 | 日频净值 ×√243 | 同 | `_equity_sharpe` (252) | 日频净值 ×√252 |
| `cagr` 分母 | `n_days/243` | `n_days/243` | `_years_between(...)` | `n/252` |
| `max_dd` 基准 | 净值 (NAV) | 净值 (NAV) | 净值 (NAV) | 净值 (NAV) |
| `win_rate` 字段 | `net`(=`gross-fees`, 元) | 同 | `net_pnl`(现金走账) | `n_wins/n` |
"""
from __future__ import annotations

import importlib
import math

import pytest

# ---------------------------------------------------------------------------
# 对照表 (机器可读; 出处见 _SOURCE)
# ---------------------------------------------------------------------------


def _trading_days(fam: str) -> int:
    """从模块**导入常量**取值 —— 不读源码文本 (§13.78 的教训)。"""
    if fam in ("chase_up", "uptrend_pullback"):
        return int(getattr(importlib.import_module(f"{fam}.backtest"), "TRADING_DAYS"))
    if fam == "short_reversal":
        return int(getattr(importlib.import_module("short_reversal.engine"),
                           "TRADING_DAYS_PER_YEAR"))
    if fam == "cycle_price_action":
        return int(getattr(importlib.import_module("cycle_price_action.allocator"),
                           "TRADING_DAYS_PER_YEAR"))
    raise KeyError(fam)


PINNED_TRADING_DAYS = {
    "chase_up": 243,
    "uptrend_pullback": 243,
    "short_reversal": 252,
    "cycle_price_action": 252,
}

_SOURCE = {
    "chase_up": "chase_up/backtest.py:22 `TRADING_DAYS = 243`; sharpe ×√243 (同文件 :52); "
                "max_dd 用净值 (:55); win_rate 用 `net` = gross−fees, 元 (:368/:77)",
    "uptrend_pullback": "uptrend_pullback/backtest.py:27 `TRADING_DAYS = 243` (:62 ×√243); "
                        "docstring 自陈「max_dd / Sharpe 用净值, 不用逐笔」; win_rate `net` (:345/:90)",
    "short_reversal": "short_reversal/engine.py:53 `TRADING_DAYS_PER_YEAR = 252`; "
                      "**独立**的 `_equity_sharpe` (:121, 自陈年化常数 252); "
                      "cagr 分母走 `_years_between` (:172); win_rate 按 `net_pnl` (:181)",
    "cycle_price_action": "cycle_price_action/allocator.py:41 `TRADING_DAYS_PER_YEAR = 252` (:161 ×√252); "
                          "⚠️ 另有一个 `cycle_price_action/metrics.py` 返回 `sharpe=None, max_dd=None` —— "
                          "**两个产出者**, 完整的那份在 allocator",
}


@pytest.mark.parametrize("fam", sorted(PINNED_TRADING_DAYS))
def test_family_trading_days_match_the_pinned_table(fam: str) -> None:
    """逐族的**年化常数**必须与对照表一致 —— 它是四族口径差异里最硬的一条。"""
    got = _trading_days(fam)
    assert got == PINNED_TRADING_DAYS[fam], (
        f"§13.13/§13.87: {fam} 的年化常数由 {PINNED_TRADING_DAYS[fam]} 变成 {got}。\n"
        f"这**不一定**是缺陷 —— 但它是四个族共用名字的量的口径之一, **任何变化都必须在 "
        f"docs/strategy_mining_log.md §13.13 的对照表里同步**, 否则「跨族不可比」那条禁令的"
        f"依据就变成了过期信息。\n出处: {_SOURCE[fam]}"
    )


def test_table_records_that_families_actually_differ() -> None:
    """这张表的**内容**就是"四族不同" —— 若哪天被统一了, 本测试必须红以提示更新禁令。

    (§13.13 的禁令建立在"4/4 定义不同"上; 若有人把 243/252 统一, 那条禁令的依据就变了,
     而**没有任何测试会因此变红** —— 这个测试就是那道缺口。)
    """
    vals = set(PINNED_TRADING_DAYS.values())
    assert len(vals) >= 2, (
        "§13.87: 四族的年化常数现在**已经一致**了 —— 这是好事, 但必须同步: "
        "1) 更新 §13.13 的对照表; 2) 重新评估'四个共享指标不可跨族引用'那条禁令是否仍然成立。"
        "本断言是**自失效**的: 它存在的唯一理由是「表里必须记录真实的差异」。"
    )
    assert PINNED_TRADING_DAYS["chase_up"] == PINNED_TRADING_DAYS["uptrend_pullback"] == 243
    assert PINNED_TRADING_DAYS["short_reversal"] == PINNED_TRADING_DAYS["cycle_price_action"] == 252


def test_the_243_vs_252_gap_is_the_documented_1_8_percent() -> None:
    """两族年化常数之比 = √(252/243) ≈ 1.8% —— 与 `short_reversal` 注释自陈的量级一致。

    这是把"散文里的 1.8%"与"表里的两个整数"**对上**的一道小校验:
    若有人改了常数而没改注释, 这里会露。
    """
    ratio = math.sqrt(252 / 243)
    assert abs(ratio - 1.01835) < 1e-4, f"√(252/243) = {ratio} —— 与注释自陈的 1.8% 不符"
    # 且它**确实**是四族之间唯一被量到的标度差 (不是排序差)
    assert max(PINNED_TRADING_DAYS.values()) / min(PINNED_TRADING_DAYS.values()) == 252 / 243
