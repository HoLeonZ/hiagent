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

from chase_up.backtest import INITIAL_CAPITAL, run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from hiagent_config import DB_PATH
from tests.conftest import require_market_db  # §6 共享跳过助手


PRESET = "chase_v5_pos2_equal_atr_tp6_sl15_mh10"
WINDOW = ("2025-07-01", "2026-07-01")


@pytest.fixture(scope="module")
def panel():
    # §6 (audit 2026-10-15): 无库时 **skip 而非 error**。此前的 skip 检查写在文件
    # 中部的一个测试里,而这三个 module 级 fixture 在它之前就先连库了 —— 于是
    # fresh clone 下 5 个用例是 ERROR,不是 skip。
    require_market_db()
    universe = set(load_universe("mainboard_only", DB_PATH))
    return load_panel(DB_PATH, WINDOW[0], WINDOW[1], universe=universe)


@pytest.fixture(scope="module")
def panel_ind(panel):
    return compute_indicators(panel)


@pytest.fixture(scope="module")
def result(panel_ind):
    return run_backtest(PRESET, WINDOW[0], WINDOW[1], DB_PATH, panel_ind=panel_ind)


@pytest.fixture(scope="module")
def trades(result):
    return result["trades"]


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

    audit P3 (2026-10-15) 曾把这条改成"列存在 + 覆盖率不足时断言源码里出现过
    `raw_prev_close` 字符串" —— 那是**在文本上设卡, 不在性质上设卡**: 它会在
    LAG 的 PARTITION BY 坏掉时照旧放行(字符串还在), 而 §6/审计点名的正是这种
    "断言读了非断言对象的形状"的守卫。故此处改为两条**可证伪的行为断言**:

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


def test_layer5_cash_walk_conservation(result):
    """Layer 5: §2 复式记账 —— **同一次运行**的权益变化必须等于逐笔净额 + 分红。

    ⚠️ 本测试此前有两个**独立**的缺陷, 且它们的失效方向相反, 所以这条断言在
    亏损窗口恒红、在盈利窗口形同虚设:

    **(a) 两个不同的运行相比** —— 断言左右两侧根本不是同一次回测:
            左边: 本次 backtrader 运行        WINDOW   = 2025-07-01 .. 2026-07-01
            右边: baseline 里的 simulate 运行  window   = 2025-09-19 .. 2026-09-19
        窗口不同 + 引擎不同 ⇒ 实测 rel_err 184% 且**符号相反**
        (左 −606,218 / 右 +720,140)。

    **(b) 容差分母写错** —— `rel_err = |net − delta| / max(delta, 1)`:
            delta > 0 (盈利): 容差 = 30% × delta。实测 W1 的 delta = +720,140
                              ⇒ **容差上限 ¥216,042**, 连 ¥200,000 的记账回归都放过去;
            delta < 0 (亏损): `max(delta, 1)` 塌成 1 ⇒ 分子再小也超 30%
                              ⇒ **无论记账对不对都恒红**。
        即 **盈利时形同虚设, 亏损时恒红** —— 两个方向都不提供信息。

    **(c) 漏掉分红项。(audit P3, 2026-10-15)** 旧注释用"含分红 / 利息 / 闲置资金
    收益, 不等于 sum(net_pnl)"给 30% 容差做辩护 —— 但分红**不是**噪声, 它是一条
    **可对账的独立现金流**: §3 要求现金分红显式入 `Free_Cash`, 于是它必然出现在
    `final_equity` 里而不在 `net_pnl` 里。正因如此, 恒等式必须写成(见
    `core/trade_schema.EQUITY_COLS` 的 §2/§3 注释):

        final_equity == initial + Σ net_pnl + Σ cum_dividends

    "守恒测试需要 30% 容差"从来不是这条不变量的性质, 而是漏项的证据。实测本窗口
    分红约 ¥4,340。

    现金走账守恒是**单次运行**的不变量 (`chase_up/portfolio.py` 把每笔 `net_pnl`
    记进 cash ⇒ 逐笔净额之和 + 分红 == 权益变化, §2 双分录), 所以必须拿本次运行的
    `final_equity` 去比(共用 module 级 `result` fixture, 而不是再跑一遍回测 ——
    那正是 (a) 的形态); 容差收到 ¥1.00 —— 实测**残差 0.00**, 该不变量是
    **构造性成立**的。

    §6 双向验证 (注入, 逐条实测):
        盈利 regime (delta=+720,140):  ¥5,000 误差  新 FAIL / 旧 PASS
                                        ¥200,000 误差 新 FAIL / 旧 PASS   ← (b) 的洞
        亏损 regime (delta=−606,218):  记账正确     新 PASS / 旧 FAIL   ← (b) 的恒红
        引擎报 `cum_dividends` 时, 漏掉该列的等式会以误差=分红而 FAIL。   ← (c)

    (`chase_v5_baseline.json` 仍然有用 —— 它锁的是 W1 的历史基线; 只是**不该被
    用来验证另一个窗口的守恒**, 那是把"两个运行的差异"当成了"记账误差"。)
    """
    equity = result["equity"]
    net_total = float(result["trades"]["net_pnl"].sum())
    final_equity = float(result["metrics"]["final_equity"])
    # §3: 分红是独立于逐笔 P&L 的现金流入, 必须显式计入, 否则等式凭空多出分红额。
    # 列不存在时取 0.0 —— 未做公司行动记账的引擎退化为"净额守恒"这一特例。
    dividends = (
        float(equity["cum_dividends"].iloc[-1])
        if "cum_dividends" in equity.columns and not equity.empty
        else 0.0
    )
    delta = final_equity - INITIAL_CAPITAL
    residual = abs(net_total + dividends - delta)
    assert residual < 1.0, (
        f"§2 现金走账不守恒: sum(net_pnl)={net_total:,.2f} + 分红={dividends:,.2f} "
        f"vs final_equity-initial={delta:,.2f} (残差 {residual:,.4f}, 容差 ¥1.00)"
    )
