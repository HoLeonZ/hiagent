"""
下降趋势反弹做空策略 — 主入口
- Phase 1: DuckDB + pandas 算信号 & 持仓循环 → trades.parquet
- Phase 2: backtrader 按 trades.parquet 重放，含佣金/印花税/融券
"""
from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta
import logging
import sys

import backtrader as bt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from marketdb import MarketDB
from dna_strat.universe import load_universe
from dna_strat.signals import compute_panel_indicators, select_entries
from dna_strat.trades import pre_simulate_trades
from dna_strat.feed import build_synthetic_feed
from dna_strat.broker import AShareBroker
from dna_strat.strategy import TradeReplayStrategy


# === 路径配置 ===
# DuckDB 由外部依赖提供（marketdb 0.1.0 + ~/code/Financial-API/data/market.duckdb），
# 本仓库不打包 market.duckdb。优先读环境变量 DNA_STRAT_DB，否则按默认路径 fallback。
import os
ROOT = Path(__file__).parent
DB_PATH = Path(os.environ.get("DNA_STRAT_DB", str(Path.home() / "code" / "Financial-API" / "data" / "market.duckdb")))
EXCLUDE_PATH = ROOT / "data" / "exclude_thscodes.txt"
EXPORTS = ROOT / "data" / "exports"
LOGS = ROOT / "logs"
FIGURES = ROOT / "figures"
for d in (EXPORTS, LOGS, FIGURES):
    d.mkdir(parents=True, exist_ok=True)


def _setup_logging(ts: str) -> logging.Logger:
    log = logging.getLogger("dna_backtest")
    log.setLevel(logging.INFO)
    if log.handlers:
        return log  # 同一 logger 已有 handler，直接复用（避免重复挂载）
    fh = logging.FileHandler(LOGS / f"backtest_{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(sh)
    return log


def _phase1(universe, start, end, log) -> pd.DataFrame:
    log.info("[Phase 1] 拉全市场 OHLCV（%d 只）...", len(universe))
    with MarketDB.open(DB_PATH) as db:
        panel = db.get_daily(universe, start=start, end=end, adjust="forward")
    panel = panel.rename(columns=str.lower)
    panel["prev_close"] = panel.groupby("thscode")["close"].shift(1)
    log.info("[Phase 1] 原始 bar: %d", len(panel))

    log.info("[Phase 1] 计算指标 + A∧B∧C 命中...")
    ind = compute_panel_indicators(panel[["thscode", "date", "close", "prev_close"]])
    entries = select_entries(ind)
    log.info("[Phase 1] 入场信号数: %d", len(entries))

    log.info("[Phase 1] 持仓循环 → trades.parquet ...")
    trades = pre_simulate_trades(entries, panel[["thscode", "date", "close"]])
    log.info("[Phase 1] 完成交易数: %d", len(trades))

    out = EXPORTS / f"trades_{start}_{end}.parquet"
    trades.to_parquet(out, index=False)
    log.info("[Phase 1] 已写出 %s", out)
    return trades


def _phase2(trades, universe, start, end, log) -> tuple[float, float, dict]:
    log.info("[Phase 2] 拉持仓标的 OHLCV + 合成 feed ...")
    held_codes = trades["thscode"].unique().tolist() if not trades.empty else universe
    with MarketDB.open(DB_PATH) as db:
        panel = db.get_daily(held_codes, start=start, end=end, adjust="forward")
    panel = panel.rename(columns=str.lower)
    feed_df = build_synthetic_feed(trades, panel)
    log.info("[Phase 2] feed bars: %d (%s → %s)",
             len(feed_df), feed_df.index.min().date(), feed_df.index.max().date())

    if feed_df.empty:
        log.warning("[Phase 2] feed 为空，跳过 backtrader")
        return 1_000_000.0, 0.0, {}

    data = bt.feeds.PandasData(dataname=feed_df)
    cerebro = bt.Cerebro()
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)
    cerebro.broker.set_coc(True)
    cerebro.adddata(data)
    cerebro.addstrategy(TradeReplayStrategy, trades_df=trades)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="tr")

    start_val = 1_000_000.0
    log.info("[backtrader] 起始资金: %.0f", start_val)
    results = cerebro.run()
    strat = results[0]
    end_val = strat.broker.getvalue()
    log.info("[backtrader] 期末资金: %.0f  收益: %+.2f%%",
             end_val, (end_val / start_val - 1) * 100)

    # 分析器
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    # backtrader DrawDown analyzer 在含空头 + cheat-on-close 下口径不对，改用 TimeReturn 自算
    time_ret = strat.analyzers.tr.get_analysis()
    if time_ret:
        vals = [start_val]
        for d in sorted(time_ret):
            vals.append(vals[-1] * (1 + time_ret[d]))
        peak = vals[0]
        mdd = 0.0
        for v in vals:
            if v > peak:
                peak = v
            dd_val = (peak - v) / peak * 100
            if dd_val > mdd:
                mdd = dd_val
        dd = mdd
    else:
        dd = 0.0
    ta = strat.analyzers.ta.get_analysis()
    closed = ta.total.closed if ta.total.closed is not None else 0
    log.info("[指标] 交易数=%d  夏普=%s  最大回撤=%.2f%%", closed, sharpe, dd)

    # 出图：TimeReturn analyzer 自绘 equity curve（cerebro.plot 在 Agg 后端下很慢）
    ts = date.today().isoformat()
    time_ret = strat.analyzers.tr.get_analysis()
    if time_ret:
        dates = sorted(time_ret.keys())
        rets = [time_ret[d] for d in dates]
        equity = [start_val]
        for r in rets:
            equity.append(equity[-1] * (1 + r))
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(dates, equity[1:], color="#1f77b4", linewidth=1.2)
        ax.axhline(start_val, color="grey", linestyle="--", linewidth=0.8, label=f"start={start_val:.0f}")
        ax.set_title(f"downtrend-short equity curve  ({start} → {end})")
        ax.set_xlabel("date")
        ax.set_ylabel("portfolio value (RMB)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        fig.autofmt_xdate()
        out_fig = FIGURES / f"downtrend_short_{ts}.png"
        fig.savefig(out_fig, dpi=120, bbox_inches="tight")
        plt.close(fig)
        log.info("[plot] saved %s", out_fig)

    return start_val, end_val, {"sharpe": sharpe, "dd": dd, "closed": closed}


def main():
    end_d = date(2026, 9, 8)
    start_d = end_d - timedelta(days=365)
    start, end = start_d.isoformat(), end_d.isoformat()
    ts = date.today().isoformat()
    log = _setup_logging(ts)
    log.info("=== 下降趋势反弹做空回测 === 区间 %s → %s", start, end)

    universe = load_universe(db_path=DB_PATH, exclude_path=EXCLUDE_PATH)
    log.info("[Universe] 主板 + 剔除名单后: %d 只", len(universe))

    trades = _phase1(universe, start, end, log)
    _phase2(trades, universe, start, end, log)


if __name__ == "__main__":
    main()
