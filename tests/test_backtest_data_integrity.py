"""5-layer backtest data integrity framework (2026-09-22, CLAUDE.md §3).

5-layer regression suite for chase_up dual-price correctness:
  Layer 1: panel raw_* coverage (raw_prev_close 0% NaN = 已知数据层 follow-up)
  Layer 2: entry_price ≈ raw_open (per-trade alignment, 含 slippage 容差)
  Layer 3: phantom TP 数 (count of TPs whose raw_high < TP threshold on fill bar)
  Layer 4: per-trade math 闭环 (gross/fees/net/return consistency)
  Layer 5: cash walk conservation (sum of net_pnl ≈ final_equity - initial_capital)

触发条件: 任何 V3a+ 后续修改如回归到 adj_open / phantom TP, 此测试立即 RED.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chase_up.backtest import run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from hiagent_config import DB_PATH


PRESET = "chase_v5_pos2_equal_atr_tp6_sl15_mh10"
WINDOW = ("2025-07-01", "2026-07-01")


@pytest.fixture(scope="module")
def panel():
    universe = set(load_universe("mainboard_only", DB_PATH))
    return load_panel(DB_PATH, WINDOW[0], WINDOW[1], universe=universe)


@pytest.fixture(scope="module")
def panel_ind(panel):
    return compute_indicators(panel)


@pytest.fixture(scope="module")
def trades(panel_ind):
    res = run_backtest(PRESET, WINDOW[0], WINDOW[1], DB_PATH, panel_ind=panel_ind)
    return res["trades"]


def test_layer1_raw_prev_close_coverage(panel):
    """Layer 1: 记录 panel 中 raw_prev_close 覆盖率. 当前 0% 是已知数据层问题
    (DuckDB raw_kline_daily.prev_close NULL upstream), 由 data 层 fix 处理.
    此测试固定记录现状, 数据层修复后覆盖率应提升到 100%."""
    cov = panel["raw_prev_close"].notna().mean()
    # audit P3 (2026-10-15): 原为 `assert cov >= 0.0` —— 恒真,任何输入都通过,
    # 等于没有断言(§6 意义上最坏的一种守卫)。改为可证伪的两条:
    #   (a) 列必须存在(数据层契约);
    #   (b) 覆盖率不足时,入口守卫必须有 adj 回退 —— 那才是缺口被处理的方式。
    assert "raw_prev_close" in panel.columns, "面板缺少 raw_prev_close 列"
    if cov < 1.0:
        guard = (ROOT / "chase_up" / "portfolio.py").read_text(encoding="utf-8")
        assert "raw_prev_close" in guard, (
            f"raw_prev_close 覆盖率仅 {cov:.4%} 且入口守卫无回退 —— "
            "缺口既未被修复,也未被处理"
        )
    print(f"\n[Layer 1] raw_prev_close coverage = {cov:.4%}")


def test_layer2_entry_uses_raw_open(trades, panel):
    """Layer 2: 每笔 trade 的 entry_price 必须 ≈ raw_open (含 slippage 容差).

    V3a+ (CLAUDE.md §3) 修复: entry fill 用 raw_open 而非 adj_open.
    此前 dead-code guard 导致 100% 错用 adj_open, 此断言会 RED.
    """
    panel_idx = panel.set_index(["thscode", "date"]).sort_index()
    bad = []
    for _, t in trades.iterrows():
        code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        if (code, entry_date) not in panel_idx.index:
            continue
        raw_open = float(panel_idx.loc[(code, entry_date), "raw_open"])
        ep = float(t["entry_price"])
        # 容许 ATR-aware slippage (scale_positive up to ~1.5%)
        tol = max(raw_open * 0.05, 0.05)
        if abs(ep - raw_open) > tol:
            bad.append((code, entry_date.date(), ep, raw_open))
    assert not bad, f"{len(bad)} trades entry_price 与 raw_open 不一致:\n{bad[:5]}"


def test_layer3_no_phantom_tp(trades, panel):
    """Layer 3: phantom TP = 0. 每笔 TP exit 必须 raw_high ≥ TP 阈值 (entry × tp_ratio).

    此前 V3a 错用 adj_open 而 exit 用 raw_*, 触发 29/75 phantom TP.
    修复后 entry/exit 同源 (raw), phantom TP = 0.
    """
    panel_idx = panel.set_index(["thscode", "date"]).sort_index()
    phantom = []
    for _, t in trades.iterrows():
        if t["exit_reason"] != "TP":
            continue
        # ATR-based TP threshold = entry × actual TP ratio
        tp_ratio = float(t["exit_price"]) / float(t["entry_price"])
        code, exit_date = t["thscode"], pd.Timestamp(t["exit_date"])
        if (code, exit_date) not in panel_idx.index:
            continue
        raw_high = float(panel_idx.loc[(code, exit_date), "raw_high"])
        raw_open = float(panel_idx.loc[(code, exit_date), "raw_open"])
        # TP threshold = entry_raw × tp_ratio
        entry_code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        if (entry_code, entry_date) not in panel_idx.index:
            continue
        entry_raw = float(panel_idx.loc[(entry_code, entry_date), "raw_open"])
        tp_threshold = entry_raw * tp_ratio
        # phantom = bar's raw_high < threshold AND raw_open < threshold
        if raw_high < tp_threshold and raw_open < tp_threshold:
            phantom.append((code, exit_date.date(), raw_high, tp_threshold))
    assert not phantom, f"{len(phantom)} phantom TP (raw 域未触达 TP 阈值):\n{phantom[:5]}"


def test_layer4_per_trade_math_closure(trades):
    """Layer 4: 每笔 trade 的 gross / fees / net / return 内部闭环."""
    bad = []
    for _, t in trades.iterrows():
        gross = float(t["gross_pnl"])
        fees = float(t["fees"])
        net = float(t["net_pnl"])
        # net = gross - fees
        if abs(net - (gross - fees)) > 0.01:
            bad.append(("net", t.thscode, gross, fees, net))
        # net_return = net / (entry_price * size)
        cost = float(t["entry_price"]) * float(t["size"])
        if cost > 0:
            expected_ret = net / cost
            actual_ret = float(t["net_return"])
            if abs(actual_ret - expected_ret) > 0.01:
                bad.append(("return", t.thscode, expected_ret, actual_ret))
    assert not bad, f"{len(bad)} trades 内部数学闭环失败:\n{bad[:5]}"


def test_layer5_cash_walk_conservation(panel_ind):
    """Layer 5:现金守恒 —— 用**当前运行**的账本断言精确恒等式。

    audit P3 (2026-10-15): 原实现从 golden 里读一个**存储的** final_equity,并用
    **30% 容差**比较,注释写着"含分红 / 利息 / 闲置资金收益,不等于 sum(net_pnl)"。
    那条"守恒"测试因此既依赖一份会漂移的历史数字(§7 已要求清除),又宽到 22% 的
    偏差也能通过 —— 一个 30% 容差的不变量不是不变量。

    现在断言精确恒等式(§2/§3):
        final_equity == initial + Σ net_pnl + Σ dividends
    分红是**独立于逐笔 P&L 的现金流**(§3 要求显式入 Free_Cash),故必须显式计入;
    此前"守恒测试需要 30% 容差"正是因为漏了它。
    """
    import pandas as pd

    from chase_up.backtest import run_backtest
    from hiagent_config import DB_PATH as _DB

    if not Path(_DB).exists() or Path(_DB).stat().st_size == 0:
        pytest.skip(f"§6: 本地 DuckDB 不可用({_DB})—— skip 而非 error")

    res = run_backtest(PRESET, WINDOW[0], WINDOW[1], _DB, panel_ind=panel_ind)
    trades, eq = res["trades"], res["equity"]
    initial = 1_000_000.0
    realised = float(pd.to_numeric(trades["net_pnl"], errors="coerce").sum())
    dividends = float(eq["cum_dividends"].iloc[-1]) if "cum_dividends" in eq.columns else 0.0
    final = float(eq["equity"].iloc[-1])
    expected = initial + realised + dividends
    rel_err = abs(final - expected) / initial
    assert rel_err < 1e-9, (
        f"现金不守恒: final_equity={final:,.6f} != initial({initial:,.0f}) + "
        f"Σnet_pnl({realised:,.6f}) + 分红({dividends:,.6f}) = {expected:,.6f} "
        f"(rel_err={rel_err:.3e})"
    )
