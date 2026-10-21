"""§4(T+1):**入场当日不得出场** —— 四族机制都在,而判据此前只有 cycle 一条(附一百三十六)。

## 实测(2026-10-21;窗口与 preset 沿用 `conftest.STD_WINDOWS` 与闭包守卫那张 `CASES`)

| 族 | 笔数 | `exit_date − entry_date` 日历日 min | 同日出场 |
|---|---|---|---|
| `chase_up` | 9 | **1** | 0 |
| `uptrend_pullback` | 14 | **1** | 0 |
| `short_reversal` | 12 | 2 | 0 |
| `cycle_price_action` | 490 | 2 | 0 |

## 机制(逐族从代码读出,不是照数据猜的)

* `chase_up` / `uptrend_pullback`:`replay_strategy.py` ——
  `bars_in_pos = bar_idx − entry_bar_idx; if bars_in_pos < 1: return  # 入场当日不判退出 (P3)`;
* `short_reversal`:`replay_strategy_v3.py` —— `if pos.get("entry_bar") == len(self):` 显式跳过
  (原注释:「…故需显式用 `entry_bar` 判等跳过 —— 否则当天…」);
* `cycle_price_action`:`Portfolio.try_exit()` —— `if exit_date <= self._pos.entry_date:` 直接拒绝。

## 口径(**方向要写进判据** —— 附一百三十 的教训)

§4 的 T+1 禁的是「卖出**当日买入**的股票」⇒ 对**做空族**(入场即卖、出场是买回)**规则上不适用**。
但四族**都**实现了"入场当日不判出场" ⇒ 本判据断言四族都满足 `exit_date > entry_date`,并写明:
**对做空族这是比明文更严** —— 那是四族共有的实现约定,不是 §4 的要求。

全库此前只有一条同类断言:`tests/test_cycle_backtest.py:54` 的 `hold_days >= 1`(**cycle 专属**)。

## 边界

* 只测一个窗口 × 每族一个 preset;与闭包/权益曲线那几条**共用** `conftest.run_engine_once`
  的回测缓存 ⇒ 边际成本 ≈ 0;
* 判据是「**没有同日出场**」,不是「入场价按 T+1 开盘取」—— 后者由各族 Phase-1 / Phase-2 对拍负责;
* `cycle` 的 `hold_days` 用**日历日**(`(on_date − entry_date).days`),另三族用 **bar 数**
  ⇒ 同一口径四个实现。**不改**:日历日 ≥ 交易日,只会让时间出场更**晚**,对 T+1 是保守方向。
  (但它会让"最大持有天数"这条**策略参数**在四族间不等价 —— 已记,属口径决策。)
"""
from __future__ import annotations

import pandas as pd
import pytest

from tests.conftest import STD_WINDOWS, run_engine_once
from tests.test_accounting_closure_4engine import CASES, ENTRY_IS_A_SALE


def _same_day_or_reversed(trades: pd.DataFrame) -> pd.DataFrame:
    """`exit_date <= entry_date` 的那些笔(同日出场,或时间倒流)。空 = 干净。"""
    if trades is None or len(trades) == 0:
        return pd.DataFrame()
    missing = [c for c in ("entry_date", "exit_date") if c not in trades.columns]
    assert not missing, f"成交里缺列 {missing};实际列={list(trades.columns)}"
    frame = trades[["thscode", "entry_date", "exit_date"]].copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"])
    frame["exit_date"] = pd.to_datetime(frame["exit_date"])
    return frame[frame["exit_date"] <= frame["entry_date"]]


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset", CASES, ids=[c[0] for c in CASES])
def test_no_trade_exits_on_its_entry_bar(fam: str, preset: str) -> None:
    """§4 T+1:入场当日不得出场(四族统一)。

    对**做空族**这一条比 §4 明文更严 —— 见模块 docstring 的「口径」一节。
    """
    trades, _final, _equity = run_engine_once(fam, preset, STD_WINDOWS[fam])
    bad = _same_day_or_reversed(trades)
    entry_side = "卖(做空)" if ENTRY_IS_A_SALE[fam] else "买"
    assert bad.empty, (
        f"§4 T+1 VIOLATION: {fam}/{preset} 有 {len(bad)} 笔在**入场当日**出场"
        f"(该族入场是{entry_side}):\n  "
        f"{bad.head(5).to_dict('records')}\n"
        f"机制见各族 `bars_in_pos < 1` / `entry_bar == len(self)` / "
        f"`try_exit` 的 `exit_date <= entry_date` 拒绝 —— 三者缺一即在此露出来。"
    )


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset", CASES, ids=[c[0] for c in CASES])
def test_the_family_actually_produced_trades(fam: str, preset: str) -> None:
    """**非空转**:上面那条在 0 笔时恒真。

    (本册的教训:一次把窗口缩到 1 个月,`short_reversal` 产出 0 笔,判据照样"绿"。)
    """
    trades, _final, _equity = run_engine_once(fam, preset, STD_WINDOWS[fam])
    assert trades is not None and len(trades) > 0, (
        f"{fam}/{preset} 在窗口 {STD_WINDOWS[fam]} 里 **0 笔成交** —— "
        f"上面那条 T+1 判据会变成空转。窗口/preset 动了就把这条一起改。"
    )


def test_the_same_day_check_has_teeth() -> None:
    """**牙齿**:用合成帧测,不用引擎注入 —— 因为**同日出场需要入场 bar 上就击穿 SL/TP**,
    那是个**物理上可能不发生**的事件(本册 taxonomy 的 ⑤「注入结构上不可能触发」)。

    合成帧是确定性的:同日必报、隔一日必不报。
    """
    clean = pd.DataFrame({
        "thscode": ["600000.SH", "000001.SZ"],
        "entry_date": ["2026-06-01", "2026-06-01"],
        "exit_date": ["2026-06-02", "2026-06-08"],
    })
    assert _same_day_or_reversed(clean).empty, "隔一日以上的成交被误报"

    same_day = pd.DataFrame({
        "thscode": ["600000.SH"],
        "entry_date": ["2026-06-01"],
        "exit_date": ["2026-06-01"],
    })
    assert len(_same_day_or_reversed(same_day)) == 1, "同日出场没被抓到"

    time_travel = pd.DataFrame({
        "thscode": ["600000.SH"],
        "entry_date": ["2026-06-05"],
        "exit_date": ["2026-06-01"],
    })
    assert len(_same_day_or_reversed(time_travel)) == 1, "时间倒流的成交没被抓到"

    assert _same_day_or_reversed(pd.DataFrame()).empty, "空帧不该报"