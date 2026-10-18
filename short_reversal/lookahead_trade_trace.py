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
        self._entry_meta: dict[str, dict] = {}

    def _fill_pending_entries(self) -> None:
        """**包装**父类: 先让它做真正的工作 (含结算/保证金状态机), 再记录新开的仓。

        2026-10-19 (§13.52): 此前这里是一份**父类逻辑的分叉** —— 而且用的是**早期的
        sizing 公式** `self.cash * position_fraction`, 没有 §2 的保证金闸门。
        它绕开父类状态机 ⇒ `locked_margin` 恒为 0 ⇒ 父类的 `_charge_margin_fees` 一查就抛。
        **分叉产出的 trace 描述的不是"产出那些 metrics 的那个引擎"。** 改为包装。
        """
        before = set(self._holds)
        super()._fill_pending_entries()
        for code in set(self._holds) - before:
            pos = self._holds[code]
            self._entry_meta[code] = {
                "entry_bar": pos["entry_bar"],
                "entry_date": pos.get("entry_date"),
                "entry_price": pos["entry_price"],
                "size": pos["size"],
            }

    def _close(self, d, price: float, reason: str) -> None:
        """**包装**父类: 先出场, 再从父类刚写下的 canonical 记录里取字段做 trace。

        沿用 §13.51 的诊断: **不从父类复制一份逻辑**, 只**观察**它的结果。

        ⚠️ 两个字段的**口径随本次修复而变**(这是有意的, 因为要让 trace 描述当前引擎):
          * `net_per_share` 现在取 canonical 的 `net_return` (而不是分叉里自算的 `net`);
          * `notional_pnl` 现在取 canonical 的 `net_pnl`。
        """
        n0 = len(self.trades)
        super()._close(d, price, reason)
        if len(self.trades) == n0:
            return                      # 父类没有产出记录 (例如被拒)
        t = self.trades[-1]
        meta = self._entry_meta.pop(d._name, {})

        def _iso(v):
            return v.isoformat() if hasattr(v, "isoformat") else v

        ep_ = t.get("exit_price")
        self.traces.append({
            "thscode": d._name,
            "entry_bar": meta.get("entry_bar"),
            "entry_date": _iso(meta.get("entry_date")),
            "entry_price": t.get("entry_price"),
            "exit_bar": len(self),
            "exit_date": _iso(t.get("exit_date")),
            "exit_price": float(ep_) if ep_ is not None else None,
            "exit_reason": t.get("exit_reason"),
            "size": t.get("size"),
            "hold_days": t.get("hold_days"),
            "net_per_share": float(t.get("net_return") or 0.0),
            "notional_pnl": float(t.get("net_pnl") or 0.0),
        })


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
        # 2026-10-19 (§13.51): `min_cash_ratio` 的默认值是 **None**, 而那是**刻意的 fail-fast
        # 设计**(见 replay_strategy_v3.py:176-178: "默认 None, engine 必须显式从 preset 传入
        # —— 忘传时 cash_gate_threshold 计算报 TypeError 而非 silently 0.05")。
        # ⇒ **坏的是这个调用者, 不是那个默认值。** 本工具是 `Phase3V3Strategy` 的子类,
        #   却从未注入它 ⇒ `run_trace()` 直接抛 TypeError ⇒ 依赖它的 LAHEAD-001 三条测试
        #   只能 ERROR。这里按 engine.py:170 的同一写法补上。
        min_cash_ratio=cfg.get("min_cash_ratio", 0.05),
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