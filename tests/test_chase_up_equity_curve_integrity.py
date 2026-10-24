"""chase_up 的 equity 曲线：**双分录** + **成交价域**（§2 / §3 / §5）。

`uptrend_pullback` 在 2026-10-13 修过"建仓名义金额被计入两次"，并留下了
`tests/test_uptrend_pullback_equity_curve_integrity.py`。**chase_up 是同一份代码的
另一份拷贝，却从没修过，也没有对应的测试** —— 于是同一个缺陷在这里又活了 8 个月。

实测（2026-10-24，窗口 2023-06-01..2026-01-01，`chase_v5_pos2_...`）：
628 个交易日里 **128 天**单日净值涨跌超过 ±20%（最大 **+96.9%**），
而 A 股主板涨跌停是 ±10% —— 一条物理上不可能的净值曲线。
它喂给 sharpe / max_dd / calmar / 年化波动率，于是 §5 依赖的 DSR 输入全不可信；
回测平台把这些数字原样显示给用户。

同一次实测还暴露出**第二个**缺陷：预设声明 `price_source_for_execution="raw_close"`
（22/22 个 chase_up 预设都是），建仓用 `raw_open`、股数按 raw 元算，而估值却用
**前复权** 的 `close`。603277.SH 2023-06-02：raw_open=23.40 建仓 42,700 股，
qfq 收盘 12.60 —— 持仓被估成 538,172（raw 域约 928,000）。
两个缺陷叠加，建仓当日净值凭空 +53.8%。
"""
from __future__ import annotations

import pandas as pd

from chase_up.portfolio import ENTRY_COLS, simulate_portfolio


def _panel(prices: list[float], code: str = "EQ.SH",
           raw_prices: list[float] | None = None) -> pd.DataFrame:
    """最小面板。`raw_prices` 给了就带 raw_* 列（模拟 `v_daily_qfq` LEFT JOIN

    `raw_kline_daily` 的形态）。
    """
    days = pd.date_range("2025-09-01", periods=len(prices), freq="B")
    rows = []
    for i, (d, p) in enumerate(zip(days, prices)):
        row = {"date": d, "thscode": code, "open": p, "high": p * 1.01,
               "low": p * 0.99, "close": p, "volume": 1e6, "amount": 1e7}
        if raw_prices is not None:
            r = raw_prices[i]
            row.update({"raw_open": r, "raw_high": r * 1.01, "raw_low": r * 0.99,
                        "raw_close": r,
                        "raw_prev_close": raw_prices[i - 1] if i else r})
        rows.append(row)
    return pd.DataFrame(rows)


def _entries(first_day) -> pd.DataFrame:
    """一行入场信号。列必须凑齐 `ENTRY_COLS`（值除了排序键都不参与本例的算术）。"""
    base = {"date": first_day, "thscode": "EQ.SH", "score": 1.0,
            "sub_signal_type": "A", "atr_pct": 0.05}
    for c in ENTRY_COLS:
        base.setdefault(c, 0.0)
    return pd.DataFrame([base])


def _run(prices, *, raw_prices=None, price_source_for_execution="adj_close"):
    panel = _panel(prices, raw_prices=raw_prices)
    return simulate_portfolio(
        _entries(panel["date"].iloc[0]), panel,
        tp_pct=10.0, sl_pct=10.0, max_hold=99, max_positions=1,
        start_date=str(panel["date"].iloc[0].date()),
        end_date=str(panel["date"].iloc[-1].date()),
        initial_capital=10_000.0, position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution=price_source_for_execution,
    )


def test_equity_row_does_not_double_count_position_notional() -> None:
    """持仓期内 equity = free + settling + 持仓市值；**不得**再叠加一次建仓成本。

    `cash` 列是券商侧 total_cash，它**含着** locked_margin（= 这些持仓已付出的
    成本，`reserve_for_entry` 把 free 挪进 locked）。原实现写的是
    `equity = total_cash + holdings`，于是成本被算两遍。
    """
    trades, equity = _run([10.0, 10.0, 10.1, 10.2, 10.3, 10.3])
    assert len(trades) == 1, f"fixture 应产生 1 笔, 实际 {len(trades)}"
    size = int(trades.iloc[0]["size"])
    notional = size * 10.0

    held = equity.iloc[1:5]                      # 入场后、eod 平仓前
    assert (held["holdings"] > 0).all(), "fixture 应在这些 bar 上持仓"

    # 价格 10.0 那根 bar：未实现盈亏 = 0 ⇒ equity 必须等于 cash
    flat = held.iloc[0]
    assert abs(flat["equity"] - flat["cash"]) < 1e-6, (
        f"建仓当日价格未变，equity 应等于 cash：equity={flat['equity']:,.2f} "
        f"cash={flat['cash']:,.2f} 差={flat['equity'] - flat['cash']:,.2f} "
        f"（持仓名义金额={notional:,.0f}）—— 差额≈名义金额即为双重计数。"
    )

    # 价格 10.1 那根 bar：未实现 = size × 0.1
    up = held.iloc[1]
    expect_unreal = size * (10.1 - 10.0)
    assert abs((up["equity"] - up["cash"]) - expect_unreal) < 1e-6, (
        f"未实现盈亏应为 {expect_unreal:,.2f}，实际 {up['equity'] - up['cash']:,.2f}"
    )


def test_daily_equity_change_tracks_price_move_not_notional() -> None:
    """单日 equity 变化 ≈ 「价格变动 × 股数」，而不是整个名义金额。"""
    trades, equity = _run([10.0, 10.0, 10.1, 10.2, 10.3, 10.3])
    size = int(trades.iloc[0]["size"])
    notional = size * 10.0

    worst_abs = float(equity["equity"].diff().iloc[1:5].abs().max())
    assert worst_abs < notional * 0.5, (
        f"持仓期内单日 equity 跳变 {worst_abs:,.2f}，已达名义金额 "
        f"{notional:,.0f} 的 {worst_abs / notional:.0%} —— 物理上不可能"
        f"（价格日变动仅 1%）。equity 曲线把建仓名义金额计入了。"
    )


def test_mark_to_market_uses_the_execution_price_domain() -> None:
    """**预设用 raw 成交，估值就必须用 raw 收盘**（CLAUDE.md §3 双价制）。

    chase_up 的 22 个预设全部声明 `price_source_for_execution="raw_close"`：
    建仓价、股数、止损止盈都在 raw 域。估值若用**前复权** close，等于拿两把尺子
    量同一根木头 —— 而且**不报错**，只是净值曲线错得很像真的。

    判别力：本 fixture 让 adj 恒为 5.0、raw 从 10.0 走到 11.0。
      · 用 raw 估值：equity = 10,000 + (11−10)×size = 11,000
      · 用 adj 估值：equity = 10,000 + (5−10)×size = 5,000（差一个数量级）
    """
    adj = [5.0] * 6
    raw = [10.0, 10.0, 11.0, 11.0, 11.0, 11.0]
    trades, equity = _run(adj, raw_prices=raw, price_source_for_execution="raw_close")

    assert len(trades) == 1, f"fixture 应产生 1 笔, 实际 {len(trades)}"
    assert trades.iloc[0]["entry_price"] == 10.0, "建仓价应当是 raw_open"
    size = int(trades.iloc[0]["size"])

    held_after_rally = equity.iloc[2]            # raw 已到 11.0 的那根 bar
    expect = 10_000.0 + size * (11.0 - 10.0)
    assert abs(held_after_rally["equity"] - expect) < 1e-6, (
        f"持仓按 raw 从 10.0 涨到 11.0，equity 应为 {expect:,.2f}，"
        f"实际 {held_after_rally['equity']:,.2f}。"
        f"若≈{10_000.0 + size * (5.0 - 10.0):,.2f}，说明估值用了前复权价。"
    )
    # 反向：同一根 bar 上，adj 域估值的结果必须**明显不同**
    assert abs(held_after_rally["equity"] - (10_000.0 + size * (5.0 - 10.0))) > 1.0, \
        "fixture 没有判别力：两个价域算出的结果一样"


def test_the_nav_gate_fires_on_the_real_nav(caplog) -> None:
    """**NAV 闸必须看到与净值行同一个 NAV。**

    原先两处各写一遍 `total_cash + 持仓市值`：同一处双重计数，
    于是闸眼里的 NAV 永远比真实净值高**一个持仓市值** —— 它实际上**不可能触发**。
    这是本仓库最高频的那类缺陷：看起来在把关，实际抓不到。

    判别力：让持仓崩到净值只剩 ~1,000（阈值 5,000）。
      · 真实 NAV = 1,000  → 闸应当拒绝新开仓并打日志
      · 双重计数的 NAV = 11,000（total_cash 10,000 + 市值 1,000）→ 闸静默放行
    所以"`[nav-gate]` 是否出现在日志里"就是这条的判据。
    """
    import logging

    adj = [5.0] * 8
    raw = [10.0, 10.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    panel = _panel(adj, raw_prices=raw)
    # 第二个信号落在崩盘之后：它才会在持仓已崩时被闸看到
    entries = pd.concat([_entries(panel["date"].iloc[0]),
                         _entries(panel["date"].iloc[2])], ignore_index=True)

    with caplog.at_level(logging.WARNING):
        trades, equity = simulate_portfolio(
            entries, panel,
            tp_pct=10.0, sl_pct=10.0, max_hold=99, max_positions=2,
            start_date=str(panel["date"].iloc[0].date()),
            end_date=str(panel["date"].iloc[-1].date()),
            initial_capital=10_000.0, position_sizing="all_in",
            commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
            price_source_for_execution="raw_close",
            nav_gate_ratio=0.50,     # 真实净值跌破 50% 就该拒绝新开仓
        )

    assert equity.iloc[2]["equity"] < 5_000.0, (
        f"崩盘后的真实净值应远低于阈值 5,000，实际 {equity.iloc[2]['equity']:,.2f}"
    )
    assert "[nav-gate]" in caplog.text, (
        "NAV 闸没有触发：它看到的净值比净值行高一个持仓市值（双重计数），"
        f"于是永远不可能跌到阈值以下。日志：{caplog.text!r}"
    )
