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

from core.preset_contract import resolve_nav_gate_ratio  # §2 (audit 2026-10-15)
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

    # §6 (audit, 2026-10-15): 两个 override 改为**薄包装**，委托生产实现，
    # 只做观测。
    #
    # 原实现是生产入场/出场逻辑的**分叉副本**：自建 size 公式（基于
    # `self.cash` 而非 free_cash）、`self.cash -= entry_fee` 的单池模型、
    # **不调用 `reserve_for_entry`**、建仓字典只写 3 个键。Round 16 把生产
    # 代码迁到 3-pool settlement isolation 后这里没跟着改，后果是：
    #   - `locked_margin` 恒为 0 → 下一根 bar 被融券日费的 fail-fast 打死，
    #     于是三个「无前视」不变量用例常年是 ERROR 而不是断言失败 ——
    #     **等于从未被有效覆盖**；
    #   - `short_reversal/feed_bt.py` 的注释却引用 "LAHEAD-001 实证
    #     pre_window_entry_count == 0" 作为窗口边界安全的依据，而那个测试
    #     在当前代码栈上根本跑不起来。
    # 即：harness 测的不是生产行为，任何由它得出的窗口结论都不成立。
    # 现在改为委托，harness 与生产同源。

    def _fill_pending_entries(self) -> None:
        before = set(self._holds)
        super()._fill_pending_entries()
        self._entry_meta = getattr(self, "_entry_meta", {})
        for code in set(self._holds) - before:
            pos = self._holds[code]
            self._entry_meta[code] = {
                "entry_bar": pos.get("entry_bar"),
                "entry_date": pos.get("entry_date"),
                "entry_price": pos.get("entry_price"),
                "size": pos.get("size"),
            }

    def _close(self, d, price: float, reason: str) -> None:
        code = d._name
        # 生产实现会 pop 掉持仓，故先取快照
        pos = dict(self._holds.get(code, {}))
        super()._close(d, price, reason)
        if not pos:
            return
        ep = float(pos["entry_price"])
        size = float(pos["size"])
        exit_px = float(price)
        pnl = (ep - exit_px) * size
        exit_fee = max(self.p.min_commission, size * exit_px * self.p.commission_rate)
        entry_fee = float(pos.get("entry_fee", 0.0))
        # Round 24 (canonical Round 19 同款): 总费率含 exit commission 与
        # stamp_duty，避免系统性高估每笔 net。
        gross_pct = (ep - exit_px) / ep
        total_fee_ratio = (
            (self.p.commission_rate + self.p.stamp_duty_rate)
            + self.p.commission_rate * (exit_px / ep)
        )
        net = gross_pct - total_fee_ratio
        try:
            exit_date = pd.Timestamp(d.datetime.date(0)).date()
        except (ValueError, TypeError, AttributeError):
            exit_date = None
        meta = getattr(self, "_entry_meta", {}).pop(code, {})
        entry_date = meta.get("entry_date")
        self.traces.append(
            {
                "thscode": code,
                "entry_bar": meta.get("entry_bar", pos.get("entry_bar")),
                "entry_date": (
                    entry_date.isoformat() if entry_date is not None else None
                ),
                "entry_price": ep,
                "exit_bar": len(self),
                "exit_date": exit_date.isoformat() if exit_date is not None else None,
                "exit_price": exit_px,
                "exit_reason": reason,
                "size": size,
                "hold_days": len(self) - int(pos.get("entry_bar", len(self))),
                "net_per_share": float(net),
                # metric 字段（非 cash walk）：round-trip 全成本摊到该笔，
                # 使 trace 报告的窗口内外 P&L 口径真实。
                "notional_pnl": float(pnl - exit_fee - entry_fee),
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
        # §2 (audit 2026-10-15): 经规范契约解析(缺声明 fail-fast),与引擎同口径。
        nav_gate_ratio=resolve_nav_gate_ratio(cfg, cfg.get("_name", "short_reversal")),
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
        except (ValueError, TypeError):
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