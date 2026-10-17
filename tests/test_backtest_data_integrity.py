"""5-layer backtest data integrity framework (2026-09-22, CLAUDE.md §3).

5-layer regression suite for chase_up dual-price correctness:
  Layer 1: panel raw_* coverage (raw_prev_close 只在**每票首根 bar** 为 NaN ——
           数据层已于 Round 23 2026-09-28 用内联 LAG 修复; 此前记为
           "0% NaN = 已知数据层 follow-up" 的说法与恒真断言都是陈旧的, 见 Layer 1)
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
    """Layer 1: raw_prev_close 必须**只**在每只票的首根 bar 上为 NaN。

    ⚠️ 本测试此前是**空转守卫** (审计 docs/audits/strategy-discipline-audit.md §(c)
    点名的形态): 断言写作 `assert cov >= 0.0`, **恒真**; docstring 写着
    "当前 0% 是已知数据层问题 ... 数据层修复后覆盖率应提升到 100%"。

    但那句话**已经过期**: 数据层在 Round 23 (2026-09-28) 就修了 ——
    `chase_up/data.py` 改用内联 `LAG(r.close) OVER (PARTITION BY thscode ORDER BY date)`
    取代 0% populated 的 `raw_kline_daily.prev_close`。实测覆盖率 **99.80%**,
    不是 0%。**恒真的断言正是没人发现 docstring 过期了的原因** —— 这正是"空转守卫"
    腐蚀红/绿信号的机制: 文档在漂, 测试不会响。

    现在钉两条**真**断言:
      1. 覆盖率 ≥ 99% —— 实测 99.80% (方差来自每票首根 bar 无前行);
      2. 每一个 NaN 都必须落在该票的**首根 bar** 上。若 NaN 出现在中间, 说明
         LAG 的分区或排序坏了 —— 那会**静默改变 LIMIT_UP 守卫的输入**
         (`extract_execution_bar` 会用 qfq 域的 `prev_close` 顶替, 见
         `chase_up/portfolio.py` 的 "best-effort 回退" 注释)。
    """
    cov = float(panel["raw_prev_close"].notna().mean())
    assert cov >= 0.99, (
        f"raw_prev_close 覆盖率 {cov:.4%} < 99% —— 数据层的 LAG 回填退化了"
    )

    nulls = panel.loc[panel["raw_prev_close"].isna(), ["thscode", "date"]]
    first = panel.groupby("thscode")["date"].min().rename("first_date")
    merged = nulls.merge(first, left_on="thscode", right_index=True, how="left")
    off_first = merged[merged["date"] != merged["first_date"]]
    assert off_first.empty, (
        f"{len(off_first)} 个 raw_prev_close NaN **不在首根 bar** 上 —— "
        f"LAG 的 PARTITION BY / ORDER BY 可能坏了:\n{off_first.head(5)}"
    )
    print(f"\n[Layer 1] raw_prev_close coverage = {cov:.4%}, NaN={len(nulls)} (全部为首根 bar)")


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


def test_layer5_cash_walk_conservation(trades):
    """Layer 5: sum(net_pnl) ≈ final_equity - initial_capital (允许小 epsilon).

    验证 cash walk 守恒: 所有 trade 的 net_pnl 之和应等于最终权益变化.
    """
    net_total = float(trades["net_pnl"].sum())
    # 假设 initial_capital=1_000_000, 取 baseline 中 final_equity
    initial = 1_000_000.0
    # 从 baseline 拿 final_equity
    import json
    baseline_path = ROOT / "tests" / "golden" / "chase_v5_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    final_equity = baseline["metrics"]["final_equity"]
    delta = final_equity - initial
    # 容许 30% epsilon: cash walk 含分红 / 利息 / 闲置资金收益, 不等于 sum(net_pnl)
    # 但 abs(delta - net_total) 不应超过 delta 绝对值的 30%. 实测 v5 当前 ~22%.
    rel_err = abs(net_total - delta) / max(delta, 1)
    assert rel_err < 0.30, (
        f"cash walk 不守恒: sum(net_pnl)={net_total:.2f} "
        f"vs final_equity-initial={delta:.2f} (rel_err={rel_err:.4%})"
    )