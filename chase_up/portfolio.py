"""多头组合模拟 — 最多 N 只并行持仓,逐日事件驱动 (沿用 uptrend_pullback/portfolio.py 口径)。

时序约定(无未来函数):
  T 日收盘产生信号 → T+1 开盘买入 → T+1 起每日判定 TP/SL/时间止盈
  入场当日不判退出 (bars_in_pos=0 跳过,P3)

退出优先级(同一根 K 线内,P5):
  1. open ≥ tp_p  → TP @ open (跳空突破)
  2. open ≤ sl_p  → SL @ sl_p (跳空破止损)
  3. high ≥ tp_p  → TP @ tp_p (盘内触止盈)
  4. low  ≤ sl_p  → SL @ sl_p (盘内触止损)
  5. bars ≥ max_hold → time @ close (到期,**必须 close**)

ATR 自适应 TP/SL:
  tp = entry_price × (1 + atr_pct_signal × atr_tp_mult)
  sl = entry_price × (1 - atr_pct_signal × atr_sl_mult)
  atr_pct 先夹到 [atr_pct_floor, atr_pct_cap]
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from chase_up.signals import ENTRY_COLS

logger = logging.getLogger(__name__)

TRADE_COLS = [
    "entry_date", "exit_date", "thscode", "exit_reason",
    "entry_price", "exit_price", "size", "hold_days",
    "gross_pnl", "fees", "net_pnl", "net_return",
    # 信号日(T 日收盘)的 atr_pct — 已按 [floor, cap] 夹紧
    "atr_pct",
    # 信号日命中的子信号类型 ("A"/"B"/"C" 拼接)
    "sub_signal_type",
]

# A 股主板涨跌停 10%;开盘涨幅超过该阈值视为无法买入
LIMIT_UP_THRESHOLD = 0.098


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLS)


def _build_index(panel: pd.DataFrame) -> dict[str, dict]:
    """按 thscode 建立 numpy 数组索引。"""
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
        }
    return idx


def _row_at(pi: dict, day: np.datetime64) -> int | None:
    """返回该股票在 day 的行号;停牌/无数据返回 None。"""
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
    """逐日模拟组合,返回 (trades_df, equity_df)。"""
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
                f"position_sizing='kelly' 需要 kelly_fraction ∈ (0, 1]"
            )

    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    pidx = _build_index(panel)

    cal = np.sort(
        panel.loc[
            (panel["date"] >= pd.Timestamp(start_date))
            & (panel["date"] <= pd.Timestamp(end_date)),
            "date",
        ].unique()
    )
    if len(cal) == 0:
        return _empty_trades(), pd.DataFrame(columns=["date", "cash", "holdings", "equity"])

    sigs_by_day: dict[np.datetime64, list[tuple[str, str]]] = {}
    atr_lookup: dict[tuple, float] = {}
    use_atr = atr_tp_mult is not None and atr_sl_mult is not None
    if not entries.empty:
        ent = entries.sort_values(["date", "score"], ascending=[True, False])
        # 显式校验 ENTRY_COLS
        missing = [c for c in ENTRY_COLS if c not in ent.columns]
        if missing:
            raise ValueError(f"entries 缺少列: {missing}")
        for d, sub in ent.groupby("date", sort=False):
            sigs_by_day[np.datetime64(pd.Timestamp(d))] = list(
                zip(sub["thscode"].tolist(), sub["sub_signal_type"].tolist())
            )
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
            "sub_signal_type": pos.get("sub_signal_type", ""),
        })

    last_t = len(cal) - 1

    for t, day in enumerate(cal):
        # ---------- 1) 已有持仓退出判定 ----------
        for code in list(positions.keys()):
            pos = positions[code]
            if pos["entry_t"] == t:
                continue  # 入场当日不判退出 (P3)
            pi = pidx[code]
            j = _row_at(pi, day)
            if j is None:
                continue
            pos["bars"] = t - pos["entry_t"]

            o = pi["open"][j]
            h = pi["high"][j]
            lo = pi["low"][j]
            c = pi["close"][j]
            tp_p, sl_p = pos["tp"], pos["sl"]

            if o >= tp_p:
                px, reason = o, "TP"
            elif o <= sl_p:
                px, reason = o, "SL"
            elif h >= tp_p:
                px, reason = tp_p, "TP"
            elif lo <= sl_p:
                px, reason = sl_p, "SL"
            elif pos["bars"] >= max_hold:
                px, reason = c, "time"
            else:
                continue

            _close_position(code, pos, float(px), day, reason)
            del positions[code]

        # ---------- 2) 新开仓:用前一交易日的信号,今日开盘买入 ----------
        if t > 0 and t < last_t:
            candidates = sigs_by_day.get(cal[t - 1], [])
            if candidates:
                holdings_val = 0.0
                for code, pos in positions.items():
                    j = _row_at(pidx[code], day)
                    px = pidx[code]["close"][j] if j is not None else pos["entry_price"]
                    holdings_val += pos["size"] * px
                equity_now = cash + holdings_val
                if position_sizing == "equal":
                    slot_value = equity_now / max_positions
                elif position_sizing == "all_in":
                    slot_value = equity_now
                else:  # kelly
                    slot_value = equity_now * kelly_fraction

                for code, sub_type in candidates:
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
                        "sub_signal_type": sub_type,
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