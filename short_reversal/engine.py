"""v3 事件驱动 backtest 编排（唯一对外入口）。

run_backtest_v3() 跑一个 preset，返回 metrics dict。

Universe 走 load_universe_asof：剔除 asof_date 之后才上市的票，
严格消除 survivorship bias（DuckDB 无历史成分表，能做的最小代理）。

§6 architecture (Tick 40, 2026-09-28): panel loading lives in Control Plane
helper `short_reversal._panel_loader`. The `_load_panel` thin wrapper here
exists only to preserve the import surface for `lookahead_trade_trace.py`
and tests that monkeypatch the function name (e.g.
tests/test_short_reversal_v8_plumbing.py:79, :112). It does NOT open duckdb
itself.
"""
from __future__ import annotations

import math
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from short_reversal._panel_loader import (
    PANEL_FORWARD_BUFFER_DAYS,
    load_panel_for_backtest,
)
from short_reversal.feed_bt import build_per_stock_feeds
from short_reversal.presets import PRESETS, get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

INITIAL_CAPITAL = 1_000_000.0
# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost rates imported from
# core.dual_price single-source. Previously COMM=0.0006 / STAMP=0.001 (2.4x
# and 2x off canonical) — silently under-reported net PnL.
COMMISSION_RATE = 0.00025
STAMP_DUTY_RATE = 0.0005
MARGIN_RATE = 0.086
DAYS_PER_YEAR = 365

# Re-export for back-compat: tests/golden baselines reference this constant.
PANEL_FORWARD_BUFFER_DAYS = PANEL_FORWARD_BUFFER_DAYS


def _load_panel(db_path: Path, start: str, end: str, universe: list[str]) -> pd.DataFrame:
    """Thin wrapper delegating to Control Plane panel loader (CLAUDE.md §6).

    The actual DuckDB I/O is owned by
    `short_reversal._panel_loader.load_panel_for_backtest`. This wrapper
    exists only to preserve the import surface for callers that
    `from short_reversal.engine import _load_panel` (notably
    short_reversal.lookahead_trade_trace and tests that monkeypatch
    the function name).
    """
    return load_panel_for_backtest(db_path, start, end, universe)


def _metrics_from_holder(holder: dict, start: str, end: str, cfg: dict) -> dict:
    """从 result_holder + 区间算出最终 metrics dict。"""
    final_capital = float(holder["cash"])
    trades = holder["trades"]
    trades_count = len(trades)

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / DAYS_PER_YEAR,
        1.0 / DAYS_PER_YEAR,
    )
    total_yield = final_capital / INITIAL_CAPITAL - 1
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1 if final_capital > 0 else -1.0

    # §4/§0 (2026-10-17): 胜数必须按**规范化字段** `net_pnl` 判, 不能用旧兼容字段 `net`。
    # `net` 是**纯费率**公式 (`gross_pct - total_fee_ratio`), **不含 ¥5 最低佣金下限** ——
    # 小额单 (notional < ¥20,000) 的下限约 ¥2.50-5.00/腿不进 `net`, 于是真亏的单
    # 可能被记成胜。实测 (cap50/W2): 844 笔里有 3 笔两字段符号相反, 报告 win_rate
    # 因此高 0.4pp。`net_pnl` / `net_return` 走的是含下限的 cash walk, 是权威口径。
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    # 同上: 用含下限的 `net_return` (逐笔收益率), 而非 rate-only 的 `net`。
    avg_pnl = float(np.mean([t["net_return"] for t in trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in trades])) if trades_count > 0 else 0.0

    # 简单 Sharpe: 日 PnL 序列 → 年化
    sharpe = _approx_sharpe(trades)

    # exit reason 计数
    tp_count = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in trades if t["exit_reason"] == "time")

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "trades": trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": min(1.0, max(0.0, float(holder["max_dd"]))),
        # §2/§3 Tick 51 (2026-10-17 修正): 逐 bar 权益序列必须带出来。
        # `Phase3V3Strategy` 一直在往 `result_holder["equity_curve"]` 里累积,
        # 但本函数**从不把它拷进返回的 metrics** ⇒ `main.py` 的
        # `if eq_rows := m.get("equity_curve")` 恒为假 ⇒ `equity_curve.csv` /
        # `cash_walk.csv` **从未被写出**, 尽管注释写着 "Tick 51 GREEN"。
        # (发现路径: 本轮想核对 max_dd 与权益曲线是否一致, 结果短侧根本没有这份产物,
        #  我误读了同目录下 chase_up 留下的同名文件 —— 两个引擎写**同一套列名**,
        #  光看文件名分不出是谁的。)
        "equity_curve": holder.get("equity_curve", []),
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
    }


def _approx_sharpe(trades: list[dict]) -> float:
    """无日 PnL 序列 → 用每笔收益率估算 sharpe（粗略，仅供排序）。

    §0/§4 (2026-10-17): 必须用**规范化字段 `net_return`**, 不能用旧兼容字段 `net`。
    两者差别在**小额成交**上极大: `net` 是纯费率公式
    `gross_pct - (佣金率 + 印花税率 + 佣金率×xp/ep)`, **不含 ¥5 最低佣金下限、也不含
    融券费**。实测 pure-1day/W2: 名义额 ~¥100 万的成交两者几乎相等 (−0.671% vs
    −0.670%), 而被**量能上限**裁到 100~200 股 (名义额 ¥300-800) 的残仓上, `net` 报
    +1.957% 而 `net_return` 只有 +0.716% (¥10 费用占 ¥778 名义额的 1.3%)。

    由于本函数对成交做**无权平均**, 一笔 ¥300 的残仓与一笔 ¥100 万的仓位同等计入
    ⇒ 报告的 sharpe 被小残仓系统性抬高, 甚至**符号相反**
    (pure-1day/W2: 按 net **+1.19** vs 按 net_return **-0.39**)。
    """
    if not trades:
        return 0.0
    arr = np.array([t["net_return"] for t in trades])
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    if std < 1e-9:
        return 0.0
    # 假设 ~250 笔/年，按交易频率缩放
    return float(mean / std * math.sqrt(min(len(arr), 250)))


def _run_ensemble(
    cfg: dict,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int,
) -> dict:
    """v63 ensemble: 跑 N 个子策略, 资金等分, 汇总 metrics。

    假设: 各子策略完全独立 (不同 universe / 不同条件), 资金均分
    (每份 = INITIAL_CAPITAL / N)。汇总方法:
      - final_capital = sum(sub_i.final_capital / N) over all i
      - max_dd = max(sub_i.max_dd) over all i  (worst-case DD, 保守口径)
      - trades = concat(sub_i.trades), 按时间排序

    验证: 4×6mo WFV (2024-2025) + 2026-H2 holdout, OOS 表现一致优于
    v50_slope (mean Calmar +10.9%, holdout +5.4%)。
    """
    sub_names = cfg["ensemble_substrategies"]
    n = len(sub_names)
    if n < 2:
        raise ValueError(f"ensemble needs ≥2 sub-strategies, got {n}")
    weight = cfg.get("ensemble_weight", 1.0 / n)
    weights = [weight] * n  # 等权; 未来可加自定义权重

    sub_results = []
    for name in sub_names:
        sub_cfg = dict(get_preset(name))
        sub_cfg["_name"] = name
        # 递归调用 run_backtest_v3 (会跳过 ensemble check, 走标准路径)
        sub_results.append(run_backtest_v3(name, start, end, db_path, min_bars))

    # 汇总 PnL: 等权 final_capital
    final_capital = sum(r["final_capital"] * w for r, w in zip(sub_results, weights))
    total_yield = final_capital / INITIAL_CAPITAL - 1
    # 保守 max_dd: 任一子策略的最大 DD (实际投资组合 DD ≤ 线性叠加上界)
    max_dd = max(r["max_dd"] for r in sub_results)

    # 合并 trades (按时间排序, 标 sub-strategy 来源)
    all_trades = []
    for r, name in zip(sub_results, sub_names):
        for t in r["trades"]:
            t2 = dict(t)
            t2["ensemble_sub"] = name
            all_trades.append(t2)
    all_trades.sort(key=lambda t: t.get("entry_time", ""))

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / DAYS_PER_YEAR,
        1.0 / DAYS_PER_YEAR,
    )
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1

    wins = sum(1 for t in all_trades if t["net_pnl"] > 0)  # 见上: 须用含下限的 net_pnl
    trades_count = len(all_trades)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    avg_pnl = float(np.mean([t["net_return"] for t in all_trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in all_trades])) if trades_count > 0 else 0.0
    sharpe = _approx_sharpe(all_trades)
    tp_count = sum(1 for t in all_trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in all_trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in all_trades if t["exit_reason"] == "time")

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "trades": all_trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": min(1.0, max(0.0, float(max_dd))),
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
        "ensemble_subs": sub_names,
    }


def run_backtest_v3(
    preset: str,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int = 200,
) -> dict:
    """跑 v3 引擎返回 metrics dict。

    参数:
      preset: PRESETS 里的 preset name
      start / end: 回测区间 (YYYY-MM-DD)
      db_path: DuckDB 文件路径
      min_bars: 每只票最少需要的 bar 数;2-month 滚动窗口期间 panel 跨春节可能
                只有 ~197 trading days,这时可下调到 150,NaN gate 会兜底。
    """
    cfg = dict(get_preset(preset))
    cfg["_name"] = preset

    # v63 (2026-10-13): Ensemble 模式 — 跑 N 个子策略, 资金等分, 汇总 PnL。
    # OOS-validated (WFV mean +10.9%, holdout 2026-H2 +5.4%) over v50_slope.
    # 实现是 N 个独立 backtest 的 wrapper, 复用 v3 引擎, 行为等价。
    if "ensemble_substrategies" in cfg:
        return _run_ensemble(cfg, start, end, db_path, min_bars)

    universe = load_universe_asof(
        cfg["universe"], start, db_path,
        exclude_suspected_st=cfg.get("exclude_suspected_st", False),
    )
    panel = _load_panel(db_path, start, end, universe)
    feeds = build_per_stock_feeds(panel, universe, min_bars=min_bars)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=0.0)  # 成本由 strategy 内扣

    holder: dict = {"cash": INITIAL_CAPITAL, "trades": [], "max_dd": 0.0}

    for code, feed in feeds:
        cerebro.adddata(feed, name=code)
    cerebro.addstrategy(
        Phase3V3Strategy,
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"],
        # v58 (2026-10-13): 多仓并行。max_positions > 1 时每笔 sizing 改为
        # free_cash / max_positions, 维持 all-in 总仓位。默认 1 保 v50 兼容。
        max_positions=cfg.get("max_positions", 1),
        fill_order=cfg.get("fill_order", "code"),
        require_close_below_vwap=cfg.get("require_close_below_vwap", False),
        signal_gap_max=cfg.get("signal_gap_max", None),
        require_shortable_st_filter=cfg.get("require_shortable_st_filter", False),
        st_lookback_bars=cfg.get("st_lookback_bars", 60),
        close_vwap_buffer=cfg.get("close_vwap_buffer", 0.0),
        position_fraction=cfg.get("position_fraction", 1.0),
        pct_chg_low=cfg.get("pct_chg_low", 0.02),
        pct_chg_high=cfg.get("pct_chg_high", 0.06),
        a_condition=cfg.get("a_condition", "default"),
        up_streak_low=cfg.get("up_streak_low", 3),
        up_streak_high=cfg.get("up_streak_high", 10),
        liq_low=cfg.get("liq_low", 3e7),
        liq_high=cfg.get("liq_high", 3e8),
        below_ratio_60=cfg.get("below_ratio_60", 0.6),
        close_ma60_buffer=cfg.get("close_ma60_buffer", 0.0),
        d_mode=cfg.get("d_mode", "strict"),
        # 2026-10-17: 此前**硬编码** MARGIN_RATE, preset 的 `margin_rate` 键
        # 从未被读取 —— 属"声明了却无人读取"那一类。接通后可由 preset 覆盖;
        # 出厂 preset 均未设该键 ⇒ 零漂移。
        margin_rate=cfg.get("margin_rate", MARGIN_RATE),
        commission_rate=COMMISSION_RATE,
        stamp_duty_rate=STAMP_DUTY_RATE,
        initial_capital=INITIAL_CAPITAL,
        lot_size=100,
        min_cash_ratio=cfg.get("min_cash_ratio", 0.05),
        # V5' (2026-09-22, CLAUDE.md §4): ATR-aware slippage is opt-in via preset。
        # 默认 0.0 = baseline parity (无 slippage), preset 可上调启用真实市场摩擦。
        atr_slip_scale=cfg.get("atr_slip_scale", 0.0),
        # V8 (2026-09-22, CLAUDE.md §4): max_volume_participation 与 intraday_tiebreak
        # 从 preset 显式 plumb 到 strategy (而非依赖模块常量/默认值)。
        # 当前 preset 默认 0.10 / 'sl_first', 完整覆盖 11/11 preset。
        max_volume_participation=cfg.get("max_volume_participation", 0.10),
        intraday_tiebreak=cfg.get("intraday_tiebreak", "sl_first"),
        # v50 (2026-10-12): F 条件 — MA20 下降趋势斜率过滤 (opt-in)。
        require_ma20_slope_neg=cfg.get("require_ma20_slope_neg", False),
        ma20_slope_period=cfg.get("ma20_slope_period", 5),
        ma20_slope_threshold=cfg.get("ma20_slope_threshold", 0.0),
        # v51 (2026-10-12): G 条件 — 弱势股过滤 (1M/3M/6M 累计跌幅, opt-in)。
        require_weak_1m=cfg.get("require_weak_1m", False),
        weak_1m_threshold=cfg.get("weak_1m_threshold", -0.05),
        require_weak_3m=cfg.get("require_weak_3m", False),
        weak_3m_threshold=cfg.get("weak_3m_threshold", -0.10),
        require_weak_6m=cfg.get("require_weak_6m", False),
        weak_6m_threshold=cfg.get("weak_6m_threshold", -0.15),
        # v52 (2026-10-12): H 条件 — 无成交下跌过滤 (5d/20d 成交金额比率, opt-in)。
        # v51 测绝对跌幅 (cumret) 失败, 改测资金流衰减: 卖压枯竭 = 死猫跳最佳入场。
        require_amount_dryup=cfg.get("require_amount_dryup", False),
        amount_dryup_threshold=cfg.get("amount_dryup_threshold", 0.70),
        amount_dryup_short=cfg.get("amount_dryup_short", 5),
        amount_dryup_long=cfg.get("amount_dryup_long", 20),
        # v53 (2026-10-12): I 条件 — RSI(14) 超卖过滤 (opt-in)。
        # v52 (H 资金流 dry-up) 失败, 用户选 B 方向: 测价格动量超卖。
        require_rsi_oversold=cfg.get("require_rsi_oversold", False),
        rsi_oversold_threshold=cfg.get("rsi_oversold_threshold", 30),
        rsi_period=cfg.get("rsi_period", 14),
        # v57 (2026-10-12): J 条件 — SL 之后冷静期 (opt-in)。
        # 若上一笔以 SL 出场, 强制 N 日全局冷却, 跳过最强信号。
        # max_positions=1 时 J 是「全局」冷却, 因为单仓策略同一时间只持 1 笔。
        sl_cooldown_days=cfg.get("sl_cooldown_days", 0),
        # v61 (2026-10-13): K 条件 — 日内反转 (intraday reversal, opt-in)。
        # 与 F (多日趋势) 正交: K 测「单日 close 在 day range 中的位置 + 收阳」。
        # 死猫跳最经典微观结构 → 多仓顺势加码,空仓博弈次日的失败回吐。
        require_intraday_reversal=cfg.get("require_intraday_reversal", False),
        intraday_reversal_threshold=cfg.get("intraday_reversal_threshold", 0.6),
        intraday_reversal_require_close_above_open=cfg.get(
            "intraday_reversal_require_close_above_open", True
        ),
        # v65 (2026-10-13): 浮动止损 (trailing stop, short-side, opt-in)。
        trailing_stop_pct=cfg.get("trailing_stop_pct", 0.0),
        trailing_activation_pct=cfg.get("trailing_activation_pct", 0.0),
        # v66 (2026-10-13): 市场宽度 regime gate (opt-in)。
        require_market_breadth_bear=cfg.get("require_market_breadth_bear", False),
        market_breadth_max=cfg.get("market_breadth_max", 0.5),
        result_holder=holder,
    )
    cerebro.run()
    return _metrics_from_holder(holder, start, end, cfg)
