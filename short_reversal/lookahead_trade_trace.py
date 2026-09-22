"""Trade-level trace to identify pre-window / post-window contamination.

按 request:
  1. 跑 v3 引擎 (v35_agg_pctchg_04_09, 2025-09-12 → 2026-09-12)
  2. 给 strategy 加 hook，记录 entry / exit 的 bar idx + date
  3. 分类:
       - pre-window entry: entry_date < start (但 exit 在 end 内)
       - in-window entry post-window exit: entry_date >= start 但 exit_date > end
       - 完全在窗外（entry_date < start 且 exit_date > end）：最少归类为 pre-window entry
       - 其他全归 in-window
  4. 算每类的 PnL 贡献（sum net × size × entry_price 的近似 = 仓位现金 = 实际 nav）
  5. 估算去污染后 CAGR

PnL 模型：cerebro broker 不记账,strategy 用 NAV-based 记账:
  cash_final = cash_initial + sum_over_trades( net_per_share × entry_price × size )
  net_per_share = (entry - exit)/entry - commission_rate
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from short_reversal.engine import (
    COMMISSION_RATE,
    INITIAL_CAPITAL,
    MARGIN_RATE,
    PANEL_FORWARD_BUFFER_DAYS,
    STAMP_DUTY_RATE,
    _load_panel,
    _approx_sharpe,
)
from short_reversal.feed_bt import build_per_stock_feeds
from short_reversal.presets import get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

from hiagent_config import DB_PATH


# ---------------------------------------------------------------- trace strategy


class TraceStrategy(Phase3V3Strategy):
    """Phase3V3Strategy 的子类:在 _fill_pending_entries / _close 时记 trade 元数据。

    新增字段(写入 self.traces 而非 self.trades,避免污染原 metrics):
      thscode, entry_bar (global len(self)), entry_date, entry_price,
      exit_bar, exit_date, exit_price, exit_reason, size, hold_days, net_per_share
    """

    def __init__(self):
        super().__init__()
        self.traces: list[dict] = []

    def _fill_pending_entries(self) -> None:
        if not self.pending_entries:
            return
        for d in self.datas:
            code = d._name
            if code not in self.pending_entries:
                continue
            entry_price = float(d.open[0])
            target_value = self.cash * self.p.position_fraction
            size = (
                int(target_value / entry_price / self.p.lot_size) * self.p.lot_size
            )
            if size < self.p.lot_size:
                self.pending_entries.pop(code, None)
                continue
            entry_fee = size * entry_price * (
                self.p.commission_rate + self.p.stamp_duty_rate
            )
            self.cash -= entry_fee
            self._holds[code] = {
                "entry_price": entry_price,
                "size": size,
                "entry_bar": len(self),
            }
            # trace: 记录 entry
            try:
                entry_date = pd.Timestamp(d.datetime.date(0)).date()
            except Exception:
                entry_date = None
            self._entry_meta: dict = getattr(self, "_entry_meta", {})
            self._entry_meta[code] = {
                "entry_bar": len(self),
                "entry_date": entry_date,
                "entry_price": entry_price,
                "size": size,
            }
            self.pending_entries.pop(code, None)

    def _close(self, d, price: float, reason: str) -> None:
        code = d._name
        pos = self._holds.pop(code)
        ep = pos["entry_price"]
        size = pos["size"]
        pnl = (ep - price) * size
        exit_fee = size * price * self.p.commission_rate
        self.cash += pnl - exit_fee
        gross = (ep - price) / ep
        net = gross - self.p.commission_rate
        # trade dict (与原 strategy 一致)
        self.trades.append(
            {
                "thscode": code,
                "entry_price": ep,
                "exit_price": float(price),
                "exit_reason": reason,
                "size": size,
                "net": float(net),
                "hold_days": len(self) - pos["entry_bar"],
            }
        )
        # trace: 拿 entry 元数据,合并 exit 元数据
        try:
            exit_date = pd.Timestamp(d.datetime.date(0)).date()
        except Exception:
            exit_date = None
        meta = getattr(self, "_entry_meta", {}).pop(code, {})
        self.traces.append(
            {
                "thscode": code,
                "entry_bar": meta.get("entry_bar"),
                "entry_date": (
                    meta["entry_date"].isoformat()
                    if meta.get("entry_date") is not None
                    else None
                ),
                "entry_price": ep,
                "exit_bar": len(self),
                "exit_date": exit_date.isoformat() if exit_date is not None else None,
                "exit_price": float(price),
                "exit_reason": reason,
                "size": size,
                "hold_days": len(self) - pos["entry_bar"],
                "net_per_share": float(net),
                "notional_pnl": float(pnl - exit_fee),
            }
        )


# -------------------------------------------------------------------- run


def run() -> dict:
    preset = "v35_agg_pctchg_04_09"
    start = "2025-09-12"
    end = "2026-09-12"
    cfg = dict(get_preset(preset))
    cfg["_name"] = preset

    universe = load_universe_asof(cfg["universe"], start, DB_PATH)
    panel = _load_panel(DB_PATH, start, end, universe)
    feeds = build_per_stock_feeds(panel, universe)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=0.0)

    holder: dict = {"cash": INITIAL_CAPITAL, "trades": [], "max_dd": 0.0}

    for code, feed in feeds:
        cerebro.adddata(feed, name=code)
    cerebro.addstrategy(
        TraceStrategy,
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"],
        position_fraction=1.0,
        pct_chg_low=cfg.get("pct_chg_low", 0.02),
        pct_chg_high=cfg.get("pct_chg_high", 0.06),
        a_condition=cfg.get("a_condition", "default"),
        margin_rate=MARGIN_RATE,
        commission_rate=COMMISSION_RATE,
        stamp_duty_rate=STAMP_DUTY_RATE,
        initial_capital=INITIAL_CAPITAL,
        lot_size=100,
        result_holder=holder,
    )
    cerebro.run()

    # 抓出 strategy 实例上的 traces
    # cerebro.runstrats 是 list[list[Strategy]] (每个 addstrategy 一个 sublist)
    strat = cerebro.runstrats[0][0]  # type: ignore[index]
    traces: list[dict] = strat.traces  # type: ignore[attr-defined]
    final_capital: float = strat.cash  # type: ignore[attr-defined]

    # ----- 分类 -----------------------------------------------------------
    start_dt = date.fromisoformat(start)
    end_dt = date.fromisoformat(end)

    def parse(s: str | None) -> date | None:
        if s is None:
            return None
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    pre_window: list[dict] = []  # entry_date < start
    in_window_pre_exit: list[dict] = []  # entry_date ∈ window, exit_date ≤ end
    in_window_post_exit: list[dict] = []  # entry_date ∈ window, exit_date > end
    fully_outside: list[dict] = []  # entry_date < start 且 exit_date > end

    for t in traces:
        ed = parse(t.get("entry_date"))
        xd = parse(t.get("exit_date"))
        if ed is None or xd is None:
            continue
        if ed < start_dt and xd > end_dt:
            fully_outside.append(t)
            pre_window.append(t)  # double-count for PnL bucket but classify primarily
        elif ed < start_dt:
            pre_window.append(t)
        elif xd > end_dt:
            in_window_post_exit.append(t)
        else:
            in_window_pre_exit.append(t)

    # unique classification: any trade with entry before start goes to "pre_window_entry"
    pre_window_unique = [t for t in traces if (ed := parse(t.get("entry_date"))) is not None and ed < start_dt]
    post_window_exit_unique = [
        t
        for t in traces
        if (xd := parse(t.get("exit_date"))) is not None and xd > end_dt
    ]

    def pnl_bucket(trs: list[dict]) -> float:
        return float(sum(t["notional_pnl"] for t in trs))

    total_pnl = float(sum(t["notional_pnl"] for t in traces))
    pre_pnl = pnl_bucket(pre_window_unique)
    post_pnl = pnl_bucket(post_window_exit_unique)
    in_window_pnl = total_pnl - pre_pnl - post_pnl

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.0,
        1.0 / 365.0,
    )

    final_capital_clean_pre = final_capital - pre_pnl
    final_capital_clean_post = final_capital - post_pnl
    final_capital_clean_both = final_capital - pre_pnl - post_pnl

    cagr_clean_pre = (
        (final_capital_clean_pre / INITIAL_CAPITAL) ** (1 / years) - 1
        if final_capital_clean_pre > 0
        else -1.0
    )
    cagr_clean_post = (
        (final_capital_clean_post / INITIAL_CAPITAL) ** (1 / years) - 1
        if final_capital_clean_post > 0
        else -1.0
    )
    cagr_clean_both = (
        (final_capital_clean_both / INITIAL_CAPITAL) ** (1 / years) - 1
        if final_capital_clean_both > 0
        else -1.0
    )
    cagr_raw = (
        (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1
        if final_capital > 0
        else -1.0
    )

    def summarize(trs: list[dict], k: int = 5) -> list[dict]:
        out_trs = sorted(trs, key=lambda t: -abs(t["notional_pnl"]))[:k]
        return [
            {
                "thscode": t["thscode"],
                "entry_bar": t["entry_bar"],
                "exit_bar": t["exit_bar"],
                "entry_date": t["entry_date"],
                "exit_date": t["exit_date"],
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "exit_reason": t["exit_reason"],
                "size": t["size"],
                "hold_days": t["hold_days"],
                "net_per_share": t["net_per_share"],
                "notional_pnl": t["notional_pnl"],
            }
            for t in out_trs
        ]

    return {
        "preset": preset,
        "start": start,
        "end": end,
        "panel_start_buffered": (
            pd.Timestamp(start) - pd.Timedelta(days=PANEL_FORWARD_BUFFER_DAYS)
        ).strftime("%Y-%m-%d"),
        "panel_end_buffered": (
            pd.Timestamp(end) + pd.Timedelta(days=60)
        ).strftime("%Y-%m-%d"),
        "universe_size": len(universe),
        "feeds_used": len(feeds),
        "initial_capital": INITIAL_CAPITAL,
        "final_capital_raw": final_capital,
        "total_pnl_raw": total_pnl,
        "cagr_raw": cagr_raw,
        "sharpe_raw": _approx_sharpe(holder["trades"]),
        "max_dd_raw": holder["max_dd"],
        "total_traces": len(traces),
        "total_trades_engine": len(holder["trades"]),
        "pre_window_entry_trades_count": len(pre_window_unique),
        "post_window_exit_trades_count": len(post_window_exit_unique),
        "fully_outside_window_count": len(fully_outside),
        "in_window_entry_post_window_exit_trades_count": len(in_window_post_exit),
        "pre_window_pnl": pre_pnl,
        "post_window_pnl": post_pnl,
        "in_window_pnl": in_window_pnl,
        "pre_window_pnl_contribution_pct": (
            pre_pnl / total_pnl * 100 if total_pnl != 0 else 0.0
        ),
        "post_window_pnl_contribution_pct": (
            post_pnl / total_pnl * 100 if total_pnl != 0 else 0.0
        ),
        "in_window_pnl_contribution_pct": (
            in_window_pnl / total_pnl * 100 if total_pnl != 0 else 0.0
        ),
        "estimated_contaminated_cagr": {
            "raw": cagr_raw,
            "clean_pre_window_entry": cagr_clean_pre,
            "clean_post_window_exit": cagr_clean_post,
            "clean_both": cagr_clean_both,
            "delta_cagr_pct_points": (cagr_raw - cagr_clean_both) * 100,
        },
        "pre_window_entry_trades_samples": summarize(pre_window_unique),
        "post_window_exit_trades_samples": summarize(post_window_exit_unique),
        "fully_outside_window_trades_samples": summarize(fully_outside),
        "in_window_entry_post_window_exit_trades_samples": summarize(
            in_window_post_exit
        ),
    }


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    Path("/tmp/lookahead_trade_trace.json").write_text(
        json.dumps(out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print("\n>>> WROTE /tmp/lookahead_trade_trace.json")