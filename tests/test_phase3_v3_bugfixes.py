"""回归测试：修复后的事件驱动引擎关键行为。

覆盖 3 个 bug fix：
  - Bug 1 (2026-10-17 更正): SL gap-aware exit price 必须用 **open_p**
    (§4 Gap-Through-Stop)。此前的断言方向是反的 —— 详见下方 Bug 1 节。
  - Bug 2: hold_days = len(self) - pos["entry_bar"]（bar 跨度，不是 bar 数 -1）
  - Bug 3: NAV-based max_dd（cash + 做空持仓 mark-to-market 浮盈）
"""
from __future__ import annotations

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy


def _run_strategy(panel: pd.DataFrame, **kwargs) -> dict:
    """跑 Phase3V3Strategy on 1 stock panel。"""
    initial_capital = kwargs.pop("initial_capital", 1_000_000.0)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_capital)
    cerebro.broker.setcommission(commission=0.0)
    feed = AShareData(dataname=panel, plot=False)
    cerebro.adddata(feed, name=panel["thscode"].iloc[0])
    holder: dict = {"cash": initial_capital, "trades": [], "max_dd": 0.0}
    # 默认 pct_chg_low=0.0 让我们合成的 0.2% UP bars 能触发 C 条件
    kwargs.setdefault("pct_chg_low", 0.0)
    kwargs.setdefault("pct_chg_high", 0.10)
    cerebro.addstrategy(
        Phase3V3Strategy,
        nav_gate_ratio=0.05,  # §2 (audit 2026-10-15): 单元夹具直接构造策略,
                              #   故须显式给出(生产路径由 preset 声明注入)
        initial_capital=initial_capital,
        lot_size=100,
        result_holder=holder,
        **kwargs,
    )
    cerebro.run()
    return holder


def _build_cascade_entry_panel(n: int = 220) -> pd.DataFrame:
    """构造 cascade 触发场景（同 test_phase3_v3_strategy._build_monotonic_down_panel）。

    - bar 195: DROP（22.0）→ 凑 ma5 << ma10
    - bar 196-199: 4 根小幅 UP → 凑 up_streak=4 + pct_chg>0
    - bar 200: close=22.20（与入场所需 close < ma20 一致）
    - bar 200+ 默认保持 22.20（避免 TP/SL 触发）
    """
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        elif i < 200:
            p = 22.0 + 0.05 * (i - 195)
        else:
            p = 22.20  # 默认保持稳定
        rows.append({
            "thscode": "600000.SH",
            "date": d,
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)


# ====================================================================
# Bug 1 (2026-10-17 更正): SL gap-aware exit price — 必须用 **open_p**
# ====================================================================
#
# 本节此前题为「必须用 sl_p 而不是 open_p」,断言 `exit_price == sl_p`,并把
# 「用 open_p」称为 bug。**那是把 §4 的违反锁死**:CLAUDE.md §4 Gap-Through-Stop
# 无条件要求「开盘越过止损 ⇒ 按开盘价成交(悲观),绝不用止损价」,三姊妹引擎
# (chase_up / uptrend_pullback / cycle_price_action)在同样的位置一律按开盘价
# 成交,只有本引擎相反 ⇒ 族内不对称,不是口径选择。
#
# 而且不是边缘场景:生产 preset 的 `sl_pct` 多为 **0.0005**,几乎每一笔 SL 都落进
# 这条 gap 分支,损失被一律钉在 0.05%,与当天真实跳空幅度无关 —— 结果被系统性
# 抬高(逆 §0 Pessimistic Default)。

_GAP_OPEN = 23.0  #: bar 201/202+ 的开盘价;相对 entry(≈22.25)跳空 +3.4%


def test_sl_exit_uses_open_when_gap_up():
    """§4: 开盘跳空穿过止损 → exit_price 必须 = **open_p**(悲观),不是 sl_p。

    `sl_p` 是**开盘就已越过**的价位,物理上取不到 —— 按它成交等于假设"跳空时能
    拿回止损价"。
    跳空幅度刻意保持在 A 股 ±10% 涨停**之内**(+3.4%),场景因此物理可成交、
    不含封板顺延,本用例只测 gap 分支本身。
    """
    n = 220
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    # 前 200 根用 cascade shape（确保 bar=200 触发信号，bar=201 fill）
    for i in range(201):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        else:
            p = 22.0 + 0.05 * (i - 195)
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    # bar 201 起开盘跳空穿过 SL(entry ≈ 22.25 ⇒ sl_p = entry × 1.02 ≈ 22.70)。
    # 跳空 +3.4%:既越过止损,又远在 ±10% 涨停之内(故不触发封板顺延)。
    rows.append({
        "thscode": "600000.SH", "date": dates[201],
        "open": _GAP_OPEN, "high": _GAP_OPEN, "low": _GAP_OPEN - 0.1,
        "close": _GAP_OPEN,
        "amount": 5e7, "volume": 1e6,
    })
    for i in range(202, n):
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": _GAP_OPEN, "high": _GAP_OPEN, "low": _GAP_OPEN - 0.1,
            "close": _GAP_OPEN,
            "amount": 5e7, "volume": 1e6,
        })
    panel = pd.DataFrame(rows)

    h = _run_strategy(
        panel,
        tp_pct=0.06,
        sl_pct=0.02,        # 2% 止损 —— 跳空 +3.4% 必然越过它
        max_hold=20,
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    sl_trade = next((t for t in h["trades"] if t["exit_reason"] == "SL"), None)
    assert sl_trade is not None, f"未触发 SL 出场, trades={h['trades']}"

    ep = float(sl_trade["entry_price"])
    sl_p = ep * 1.02
    # 夹具前提:确实**跳空越过**了止损 —— 否则本用例测不到 gap 分支(d 型契约
    # 必须带非空转前提:不然"通过"无法区分"实现正确"与"分支没走到")。
    assert _GAP_OPEN > sl_p, f"夹具失效: open={_GAP_OPEN} 未越过 sl_p={sl_p:.4f}"
    # §4:按开盘价成交
    assert sl_trade["exit_price"] == pytest.approx(_GAP_OPEN, rel=1e-6), (
        f"§4 VIOLATION: 跳空穿过止损时应 fill @ open_p={_GAP_OPEN:.4f},"
        f"实际={sl_trade['exit_price']:.4f}(sl_p={sl_p:.4f} 是取不到的价位)"
    )
    # 记录的损失 = 跳空幅度 + 往返成本,**不被 stop price 截断**。
    # 成本**从规范单源推导**,不写字面量:做空往返 = 开仓卖出(佣金+印花税)+ 回补买入(佣金)。
    # 此前这里写死 0.0006 —— 那是费率集中到 core/ 之前的旧值,费率规范化后它就成了
    # 一条钉住陈旧数字的断言(§2 Canonical Cost Model:费率只能有一处定义)。
    from core.dual_price import COMMISSION_RATE, STAMP_DUTY_RATE

    round_trip_fee = 2 * COMMISSION_RATE + STAMP_DUTY_RATE
    # abs 容差:成交额较小时触发 ¥5 最低佣金下限,与纯比例口径有微小差异。
    assert sl_trade["net"] == pytest.approx(-(_GAP_OPEN / ep - 1) - round_trip_fee, abs=1e-3)
    # 关键:单笔损失**超过**名义 sl_pct。这条正是旧断言的反面 —— 把实现改回
    # "gap 用 sl_p" 必然打挂它(双向验证的另一半)。
    assert abs(sl_trade["net"]) > 0.02 + round_trip_fee - 1e-4, (
        "损失被 stop price 截断回 -sl_pct —— §4 要求跳空按开盘价成交(悲观)"
    )


# ====================================================================
# Bug 2: hold_days 正确性 = len(self) - entry_bar（bar 跨度）
# ====================================================================

def test_hold_days_is_bar_span_not_bar_count_minus_one():
    """time exit 时 hold_days 应等于 entry bar 到 exit bar 的 bar 跨度。

    Bug 修复前：hold_days = len(self) - 1 - entry_bar = bar_count - 1（off-by-1）
    Bug 修复后：hold_days = len(self) - entry_bar = bar_span

    ⚠️ 2026-10-22 (附一百八十四): 本用例原先钉 `hold_days == 4`(max_hold=3)。那个数**编码了
    另一处的 off-by-one**: `_check_exit` 里 `held` 当时写成 `len(self) - 1 - entry_bar`
    (把**计数**当索引用),于是 time exit 晚一根,跨度才成了 max_hold+1 = 4。
    该处已被修正为 `held = len(self) - entry_bar` ⇒ 跨度**恰等于 max_hold** ⇒ 原先的 4 变成 3。
    ⇒ 本用例改为断言**不变量** `hold_days == max_hold`,不再钉那个由两处 off-by-one 抵消出来的数。
    (族内对照: chase_up / uptrend 的 `max_hold` 同样以「恰 N 根」为语义。)
    """
    n = 220
    max_hold = 3
    panel = _build_cascade_entry_panel(n=n)

    h = _run_strategy(
        panel,
        tp_pct=0.0001,      # 极小 → 永不触发 TP
        sl_pct=10.0,        # 极大 → 永不触发 SL
        max_hold=max_hold,
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    t = h["trades"][0]
    assert t["exit_reason"] == "time"
    # 不变量: time exit 的跨度就是封顶持有期本身(entry bar + max_hold)。
    assert t["hold_days"] == max_hold, (
        f"hold_days 应恰等于 max_hold={max_hold}(time exit 的跨度 = 封顶持有期), "
        f"实际={t['hold_days']}"
    )


# ====================================================================
# Bug 3: NAV-based max_dd — 必须包含做空持仓 mark-to-market 浮盈
# ====================================================================

def test_max_dd_includes_short_position_unrealized_pnl():
    """持仓浮盈/浮亏必须计入 max_dd（NAV-based），不能用纯 cash。

    Bug 修复前：max_dd 用 cash，浮亏不被记录 → max_dd 虚低。
    Bug 修复后：max_dd 用 NAV（含 mark-to-market），浮亏正确计入。

    场景：entry 后 close 持续上涨（做空亏）→ NAV 大幅下降 → max_dd > 0
    """
    n = 230
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    # 前 201 根用 cascade shape（确保 bar=200 触发信号，bar=201 fill @ open_p）
    for i in range(201):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        else:
            p = 22.0 + 0.05 * (i - 195)
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    # bar 201 起：close 持续大幅上涨 → 做空浮亏快速扩大
    # entry_price ≈ 22.20, bar=221 close ≈ 22.20 + 0.5*20 = 32.20
    # 浮亏 = (32.20 - 22.20) * size = 10.0 * 45000 = 450k
    for i in range(201, n):
        p = 22.20 + 0.5 * (i - 201)  # 22.20 → ~32.70
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.1, "low": p - 0.1, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    panel = pd.DataFrame(rows)

    h = _run_strategy(
        panel,
        tp_pct=0.50,        # 极大 → 不会触发
        sl_pct=10.0,        # 极大 → 不会触发
        max_hold=20,        # 较短 → bar 201+20 = 221 触发 time exit
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    # NAV-based max_dd 应显著 > 0（持仓浮亏被计入）
    # cash 路径：entry 扣 entry_fee + margin_fees
    # NAV 路径：cash + (entry_price - current_close) * size
    # peak ≈ entry 后立即 = initial_capital（不含 fee）/ 浮盈触发前
    # bottom NAV ≈ 1M - 9.0 * 44000 = 1M - 396k = 604k
    # max_dd ≈ (1M - 604k) / 1M = 39.6%
    assert h["max_dd"] > 0.05, (
        f"max_dd 应 > 5%（做空浮亏必须计入 NAV），实际={h['max_dd']:.4f} "
        f"(Bug 3 修复验证：cash-only 会让 max_dd 接近 0)"
    )
    assert h["cash"] > 0