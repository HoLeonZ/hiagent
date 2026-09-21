"""多头组合模拟 — 最多 N 只并行持仓，逐日事件驱动。

支持组合持仓（最多 max_positions 只并行），并显式建模 A 股交易成本与涨停不可买。

时序约定（无未来函数）：
  T 日收盘产生信号 → T+1 开盘买入 → T+1 起每日判定 TP/SL/时间止盈
  入场当日不判退出（保守，避免用同日 high/low 制造乐观成交）

退出优先级（同一根 K 线内）：
  开盘跳空破止损 → 开盘跳空破止盈 → 盘中触止损 → 盘中触止盈 → 到期平仓
  盘中止损优先于止盈，属保守假设。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADE_COLS = [
    "entry_date", "exit_date", "thscode", "exit_reason",
    "entry_price", "exit_price", "size", "hold_days",
    "gross_pnl", "fees", "net_pnl", "net_return",
    # 信号日（entry_date - 1 个交易日）的 ATR%（已按 [floor, cap] 夹紧）；
    # 由 signals.py 在 T 日收盘时计算，Phase 1 / Phase 2 共用，避免穿越。
    "atr_pct",
]

# A 股主板涨跌停 10%；开盘涨幅超过该阈值视为无法买入
LIMIT_UP_THRESHOLD = 0.098

# 防穿仓 (R8, 2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
# 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
MAX_VOL_PARTICIPATION = 0.10

# 防穿仓 (R1, 2026-09-21): NAV-floor cash gate 阈值。
# 与 short_reversal/replay_strategy_v3.py:64 (min_cash_ratio=0.05) 口径一致。
NAV_GATE_RATIO = 0.05

# 同一天内 NAV gate 触发只打一次 warning
_nav_gate_logged_dates: set = set()


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLS)


def _build_index(panel: pd.DataFrame) -> dict[str, dict]:
    """按 thscode 建立 numpy 数组索引，便于 O(log n) 定位日期。"""
    idx: dict[str, dict] = {}
    for code, sub in panel.groupby("thscode", sort=False):
        closes = sub["close"].to_numpy(dtype=float)
        prev_closes = np.empty_like(closes)
        prev_closes[0] = np.nan
        prev_closes[1:] = closes[:-1]
        idx[code] = {
            "dates": sub["date"].to_numpy(),
            "open": sub["open"].to_numpy(dtype=float),
            "high": sub["high"].to_numpy(dtype=float),
            "low": sub["low"].to_numpy(dtype=float),
            "close": closes,
            "prev_close": prev_closes,
            # R8 (2026-09-21): Volume Participation Limit 需要每根 bar 的成交量
            "volume": sub["volume"].to_numpy(dtype=float) if "volume" in sub.columns else np.full(len(sub), np.nan),
        }
    return idx


def _row_at(pi: dict, day: np.datetime64) -> int | None:
    """返回该股票在 day 的行号；停牌/无数据返回 None。"""
    dates = pi["dates"]
    j = int(np.searchsorted(dates, day, side="left"))
    if j >= len(dates) or dates[j] != day:
        return None
    return j


def simulate_portfolio(
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    tp_pct: float,
    sl_pct: float,
    max_hold: int,
    max_positions: int,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000.0,
    commission_rate: float = 0.00025,
    stamp_duty_rate: float = 0.0005,
    min_commission: float = 5.0,
    slippage: float = 0.0,
    atr_tp_mult: float | None = None,
    atr_sl_mult: float | None = None,
    atr_pct_floor: float = 0.01,
    atr_pct_cap: float = 0.08,
    position_sizing: str = "equal",
    kelly_fraction: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐日模拟组合，返回 (trades_df, equity_df)。

    止盈止损宽度：
      - 默认用��定 tp_pct / sl_pct
      - 若给了 atr_tp_mult / atr_sl_mult，则按信号日 ATR% 自适应：
        tp = atr_pct × atr_tp_mult，sl = atr_pct × atr_sl_mult
        （atr_pct 先夹到 [atr_pct_floor, atr_pct_cap]）

    equity_df: columns=[date, cash, holdings, equity]

    position_sizing:
      "equal"   — 每只分配 equity / max_positions（默认，等额多仓）
      "all_in"  — 单只满仓 equity（应配 max_positions=1）
      "kelly"   — 单只按 kelly_fraction × equity（应配 max_positions=1）
    """
    if tp_pct <= 0:
        raise ValueError(f"tp_pct must be > 0, got {tp_pct}")
    if sl_pct <= 0:
        raise ValueError(f"sl_pct must be > 0, got {sl_pct}")
    if max_hold <= 0:
        raise ValueError(f"max_hold must be > 0, got {max_hold}")
    if max_positions <= 0:
        raise ValueError(f"max_positions must be > 0, got {max_positions}")

    if position_sizing not in ("equal", "all_in", "kelly"):
        raise ValueError(
            f"position_sizing must be 'equal'|'all_in'|'kelly', got {position_sizing!r}"
        )
    if position_sizing == "kelly":
        if kelly_fraction is None or not (0 < kelly_fraction <= 1):
            raise ValueError(
                f"position_sizing='kelly' 需要 kelly_fraction ∈ (0, 1]，got {kelly_fraction}"
            )

    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    pidx = _build_index(panel)

    # 交易日历限制在回测窗口内
    cal = np.sort(
        panel.loc[
            (panel["date"] >= pd.Timestamp(start_date))
            & (panel["date"] <= pd.Timestamp(end_date)),
            "date",
        ].unique()
    )
    if len(cal) == 0:
        return _empty_trades(), pd.DataFrame(columns=["date", "cash", "holdings", "equity"])

    # 按信号日分组的候选（已按 score 降序）
    sigs_by_day: dict[np.datetime64, list[str]] = {}
    atr_lookup: dict[tuple, float] = {}
    use_atr = atr_tp_mult is not None and atr_sl_mult is not None
    if not entries.empty:
        ent = entries.sort_values(["date", "score"], ascending=[True, False])
        for d, sub in ent.groupby("date", sort=False):
            sigs_by_day[np.datetime64(pd.Timestamp(d))] = sub["thscode"].tolist()
        if use_atr:
            if "atr_pct" not in ent.columns:
                raise ValueError("atr_tp_mult/atr_sl_mult 需要 entries 含 atr_pct 列")
            for d, code, a in zip(ent["date"], ent["thscode"], ent["atr_pct"]):
                atr_lookup[(np.datetime64(pd.Timestamp(d)), code)] = float(a)

    cash = float(initial_capital)
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []

    def _sell_fees(notional: float) -> float:
        return max(notional * commission_rate, min_commission) + notional * stamp_duty_rate

    def _buy_fees(notional: float) -> float:
        return max(notional * commission_rate, min_commission)

    def _close_position(code: str, pos: dict, exit_px: float, exit_day, reason: str) -> None:
        nonlocal cash
        notional = pos["size"] * exit_px
        fees_out = _sell_fees(notional)
        cash += notional - fees_out
        gross = (exit_px - pos["entry_price"]) * pos["size"]
        total_fees = pos["entry_fee"] + fees_out
        net = gross - total_fees
        invested = pos["entry_price"] * pos["size"] + pos["entry_fee"]
        trades.append({
            "entry_date": pd.Timestamp(pos["entry_date"]),
            "exit_date": pd.Timestamp(exit_day),
            "thscode": code,
            "exit_reason": reason,
            "entry_price": pos["entry_price"],
            "exit_price": exit_px,
            "size": pos["size"],
            "hold_days": pos["bars"],
            "gross_pnl": gross,
            "fees": total_fees,
            "net_pnl": net,
            "net_return": net / invested if invested > 0 else 0.0,
            "atr_pct": pos.get("atr_pct", np.nan),
        })

    last_t = len(cal) - 1

    for t, day in enumerate(cal):
        # ---------- 1) 已有持仓退出判定 ----------
        for code in list(positions.keys()):
            pos = positions[code]
            if pos["entry_t"] == t:
                continue  # 入场当日不判退出
            pi = pidx[code]
            j = _row_at(pi, day)
            if j is None:
                continue  # 停牌，无法交易
            pos["bars"] = t - pos["entry_t"]

            o = pi["open"][j]
            h = pi["high"][j]
            lo = pi["low"][j]
            c = pi["close"][j]
            tp_p, sl_p = pos["tp"], pos["sl"]

            if o <= sl_p:
                px, reason = o, "SL"
            elif o >= tp_p:
                px, reason = o, "TP"
            elif lo <= sl_p:
                px, reason = sl_p, "SL"
            elif h >= tp_p:
                px, reason = tp_p, "TP"
            elif pos["bars"] >= max_hold:
                px, reason = c, "time"
            else:
                continue

            _close_position(code, pos, float(px), day, reason)
            del positions[code]

        # ---------- 2) 新开仓：用前一交易日的信号，今日开盘买入 ----------
        if t > 0 and t < last_t:
            candidates = sigs_by_day.get(cal[t - 1], [])
            if candidates:
                # 防穿仓 (R1, 2026-09-21): NAV-floor cash gate。
                # 若 NAV (cash + 持仓 mark-to-market 浮盈) 跌到 initial_capital ×
                # NAV_GATE_RATIO 以下, 拒绝新开仓 — 已持仓仍按 SL/TP/time exit 正常执行。
                # 与 short_reversal/replay_strategy_v3.py:160-170 口径一致, 防止多仓
                # 策略在反复 gap-down 击穿 SL 后继续 all-in 累积亏损直到穿仓 0。
                holdings_val_for_gate = 0.0
                for code, pos in positions.items():
                    j = _row_at(pidx[code], day)
                    px = pidx[code]["close"][j] if j is not None else pos["entry_price"]
                    holdings_val_for_gate += pos["size"] * px
                nav_now = cash + holdings_val_for_gate
                if nav_now < initial_capital * NAV_GATE_RATIO:
                    if day not in _nav_gate_logged_dates:
                        logger.warning(
                            "[nav-gate] NAV=%.2f < threshold=%.2f, 拒绝 %d 个 pending entries",
                            nav_now,
                            initial_capital * NAV_GATE_RATIO,
                            len(candidates),
                        )
                        _nav_gate_logged_dates.add(day)
                    continue
                # 防穿仓 (R7, 2026-09-21): 只用 cash (实有资金), 不用 cash + holdings_val
                # 含未实现浮盈做 budget 会让多仓策略在持仓浮盈期隐式加杠杆 — 一旦浮盈回吐
                # 等价于用未变现利润继续 all-in, 单次回撤即可击穿 0。
                # 此修复与 chase_up/portfolio.py:239 (commit 3845380) 口径一致:
                # 仅以 cash_only = max(cash, 0) 为 budget base。
                cash_only = float(cash)
                if cash_only <= 0:
                    continue
                if position_sizing == "equal":
                    slot_value = cash_only / max_positions
                elif position_sizing == "all_in":
                    slot_value = cash_only
                else:  # kelly
                    slot_value = cash_only * kelly_fraction

                for code in candidates:
                    if len(positions) >= max_positions:
                        break
                    if code in positions:
                        continue
                    pi = pidx.get(code)
                    if pi is None:
                        continue
                    j = _row_at(pi, day)
                    if j is None:
                        continue

                    o = pi["open"][j]
                    pc = pi["prev_close"][j]
                    # 涨停开盘视为无法买入
                    if not np.isnan(pc) and pc > 0 and (o / pc - 1) >= LIMIT_UP_THRESHOLD:
                        continue

                    entry_px = float(o) * (1 + slippage)
                    if entry_px <= 0:
                        continue

                    budget = min(slot_value, cash)
                    size = int(budget / entry_px / 100) * 100
                    if size < 100:
                        continue
                    # 防穿仓 (R8, 2026-09-21): Volume Participation Limit
                    # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION, 超出丢弃。
                    # 这是 CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
                    # 防止大单砸穿市场、产生 slippage / market impact。
                    bar_vol = pi["volume"][j]
                    if not np.isnan(bar_vol) and bar_vol > 0:
                        max_fill = int(bar_vol * MAX_VOL_PARTICIPATION // 100) * 100
                        if max_fill > 0 and size > max_fill:
                            size = max_fill
                    if size < 100:
                        continue
                    notional = size * entry_px
                    fee_in = _buy_fees(notional)
                    if notional + fee_in > cash:
                        size -= 100
                        if size < 100:
                            continue
                        notional = size * entry_px
                        fee_in = _buy_fees(notional)
                        if notional + fee_in > cash:
                            continue

                    cash -= notional + fee_in
                    tp_eff, sl_eff = tp_pct, sl_pct
                    atr_used = np.nan
                    if use_atr:
                        a = atr_lookup.get((cal[t - 1], code))
                        if a is not None and not np.isnan(a):
                            a = min(max(a, atr_pct_floor), atr_pct_cap)
                            atr_used = float(a)
                            tp_eff = a * atr_tp_mult
                            sl_eff = a * atr_sl_mult
                    positions[code] = {
                        "entry_t": t,
                        "entry_date": day,
                        "entry_price": entry_px,
                        "size": size,
                        "entry_fee": fee_in,
                        "tp": entry_px * (1 + tp_eff),
                        "sl": entry_px * (1 - sl_eff),
                        "bars": 0,
                        "atr_pct": atr_used,
                    }

        # ---------- 3) 末日强制平仓 ----------
        if t == last_t:
            for code in list(positions.keys()):
                pos = positions[code]
                pi = pidx[code]
                j = _row_at(pi, day)
                px = float(pi["close"][j]) if j is not None else pos["entry_price"]
                pos["bars"] = t - pos["entry_t"]
                _close_position(code, pos, px, day, "eod")
                del positions[code]

        # ---------- 4) 记录净值 ----------
        holdings_val = 0.0
        for code, pos in positions.items():
            j = _row_at(pidx[code], day)
            px = pidx[code]["close"][j] if j is not None else pos["entry_price"]
            holdings_val += pos["size"] * px
        equity_rows.append({
            "date": pd.Timestamp(day),
            "cash": cash,
            "holdings": holdings_val,
            "equity": cash + holdings_val,
        })

    trades_df = (
        pd.DataFrame(trades, columns=TRADE_COLS) if trades else _empty_trades()
    )
    equity_df = pd.DataFrame(equity_rows, columns=["date", "cash", "holdings", "equity"])
    logger.info("simulate_portfolio: %d 笔交易", len(trades_df))
    return trades_df, equity_df
