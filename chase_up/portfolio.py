"""多头组合模拟 — 最多 N 只并行持仓,逐日事件驱动 (沿用 uptrend_pullback/portfolio.py 口径)。

时序约定(无未来函数):
  T 日收盘产生信号 → T+1 开盘买入 → T+1 起每日判定 TP/SL/时间止盈
  入场当日不判退出 (bars_in_pos=0 跳过,P3)

退出优先级(同一根 K 线内, P5):
  1. open ≤ sl_p → SL @ open (跳空破止损)
  2. open ≥ tp_p → TP @ open (跳空突破止盈)
  3. low  ≤ sl_p → SL @ sl_p (盘内触止损)        — V6 (2026-09-22): SL-first
  4. high ≥ tp_p → TP @ tp_p (盘内触止盈)
  5. bars ≥ max_hold → time @ close (到期,**必须 close**)

V6 (2026-09-22, CLAUDE.md §4): 同 bar high ≥ tp_p 且 low ≤ sl_p 双触发时,
  假设 SL 命中 (Pessimistic Default)。Gap case 互斥 (open 不能同时跨 sl_p 和 tp_p),
  故仅 intraday 顺序生效。

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

# 防穿仓 (R8, 2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
# 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
MAX_VOL_PARTICIPATION = 0.10

# 防穿仓 (R1, 2026-09-21): NAV-floor cash gate 阈值。
# 当 NAV (cash + 持仓 mark-to-market 浮盈) 跌至 initial_capital × NAV_GATE_RATIO
# 以下时, 拒绝新开仓。已持仓仍按 SL/TP/time exit 正常执行 (不主动平仓)。
# 与 short_reversal/replay_strategy_v3.py:64 (min_cash_ratio=0.05) 口径一致。
NAV_GATE_RATIO = 0.05

# 同一天内 NAV gate 触发只打一次 warning,避免静默刷屏
_nav_gate_logged_dates: set = set()


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLS)


def _build_index(panel: pd.DataFrame) -> dict[str, dict]:
    """按 thscode 建立 numpy 数组索引。

    V3a (2026-09-22, CLAUDE.md §3): 当 panel 含 raw_* 列 (v_daily_qfq +
    raw_kline_daily LEFT JOIN), 把 raw_open/raw_high/raw_low/raw_close 也
    注入 index。portfolio 在 price_source_for_execution="raw_close" 时
    切换 SL/TP 触发价格到 raw_* 列。raw_* 缺失 (NaN) 自动回退到 adj 列,
    保持 baseline parity。
    """
    idx: dict[str, dict] = {}
    has_raw = "raw_close" in panel.columns
    for code, sub in panel.groupby("thscode", sort=False):
        closes = sub["close"].to_numpy(dtype=float)
        prev_closes = np.empty_like(closes)
        prev_closes[0] = np.nan
        prev_closes[1:] = closes[:-1]
        entry: dict = {
            "dates": sub["date"].to_numpy(),
            "open": sub["open"].to_numpy(dtype=float),
            "high": sub["high"].to_numpy(dtype=float),
            "low": sub["low"].to_numpy(dtype=float),
            "close": closes,
            "prev_close": prev_closes,
            # R8 (2026-09-21): Volume Participation Limit 需要每根 bar 的成交量
            "volume": sub["volume"].to_numpy(dtype=float) if "volume" in sub.columns else np.full(len(sub), np.nan),
        }
        if has_raw:
            entry["raw_open"] = sub["raw_open"].to_numpy(dtype=float) if "raw_open" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_high"] = sub["raw_high"].to_numpy(dtype=float) if "raw_high" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_low"] = sub["raw_low"].to_numpy(dtype=float) if "raw_low" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_close"] = sub["raw_close"].to_numpy(dtype=float) if "raw_close" in sub.columns else np.full(len(sub), np.nan)
            entry["raw_prev_close"] = sub["raw_prev_close"].to_numpy(dtype=float) if "raw_prev_close" in sub.columns else np.full(len(sub), np.nan)
        idx[code] = entry
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
    # R5 (2026-09-21): ATR-aware slippage (CLAUDE.md §4)。
    # 若 atr_slip_scale > 0, slippage 改为 signal-day atr_pct × participation × scale。
    # 若 atr_slip_scale = 0, 沿用旧的静态 slippage 参数 (默认)。
    atr_slip_scale: float = 0.0,
    atr_tp_mult: float | None = None,
    atr_sl_mult: float | None = None,
    atr_pct_floor: float = 0.01,
    atr_pct_cap: float = 0.08,
    position_sizing: str = "equal",
    kelly_fraction: float | None = None,
    # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
    # "raw_close" → SL/TP 触发用 raw_high/raw_low/raw_close (除权日 raw > adj)。
    # "adj_close" (或 legacy 默认) → 用 adj high/low/close, 保持旧行为。
    price_source_for_execution: str = "adj_close",
    # V8 (2026-09-22, CLAUDE.md §4): preset→strategy explicit plumbing。
    # intraday_tiebreak='sl_first': 同 bar SL+TP 双触发时, 假设 SL 命中 (Pessimistic)。
    # max_volume_participation=0.10: Bar_Volume × 0.10 volume cap, 默认按模块常量。
    intraday_tiebreak: str = "sl_first",
    max_volume_participation: float = 0.10,
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
            # V3a (2026-09-22, CLAUDE.md §3): 当 preset 声明 raw_close 作为
            # execution source 且 panel 含 raw_* 列, 用 raw 价格判 SL/TP。
            # raw_* 缺失 (NaN, LEFT JOIN miss) → 回退到 adj high/low/close,
            # baseline parity 保留。
            if price_source_for_execution == "raw_close" and "raw_close" in pi:
                r_o = pi["raw_open"][j]
                r_h = pi["raw_high"][j]
                r_lo = pi["raw_low"][j]
                r_c = pi["raw_close"][j]
                if not np.isnan(r_o) and not np.isnan(r_h) and not np.isnan(r_lo) and not np.isnan(r_c):
                    o, h, lo, c = r_o, r_h, r_lo, r_c
            tp_p, sl_p = pos["tp"], pos["sl"]

            # V6 (2026-09-22): CLAUDE.md §4 同 bar SL+TP 双触发时, 假设 SL 命中
            # (worst-case Pessimistic Default)。Gap case 用 gap 价优先匹配,
            # intraday case 在 high/low 双触发时取 SL (与 uptrend_pullback / short_reversal
            # 口径一致)。Gap-up-over-TP 不受影响 — 仍先出 TP @ open。
            # V8 (2026-09-22): 验证 intraday_tiebreak 声明 (从 preset 显式传入)。
            if intraday_tiebreak != "sl_first":
                raise ValueError(
                    f"intraday_tiebreak must be 'sl_first' (CLAUDE.md §4), "
                    f"got {intraday_tiebreak!r}"
                )
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

        # ---------- 2) 新开仓:用前一交易日的信号,今日开盘买入 ----------
        if t > 0 and t < last_t:
            candidates = sigs_by_day.get(cal[t - 1], [])
            if candidates:
                # 保守限制:budget base 只用现金,绝不用未实现 PnL 当杠杆。
                # 旧实现 equity_now = cash + holdings_val,当 holdings 上涨时
                # slot_value > cash,但 min(slot_value, cash) 只约束单笔,
                # 循环扣逐笔累加会让 cash < 0(隐式融资)。
                # 现在用 cash_only = max(cash, 0),cash < 0 时不开仓。
                if cash < 0:
                    continue
                # 防穿仓 (R1, 2026-09-21): NAV-floor cash gate。
                # 若 NAV (cash + 持仓 mark-to-market 浮盈) 跌到 initial_capital ×
                # NAV_GATE_RATIO 以下, 拒绝新开仓 — 已持仓仍按 SL/TP/time exit 正常执行。
                # 与 short_reversal/replay_strategy_v3.py:160-170 口径一致, 防止多仓
                # 策略在反复 gap-down 击穿 SL 后继续 all-in 累积亏损直到穿仓 0。
                holdings_val = 0.0
                for code, pos in positions.items():
                    j = _row_at(pidx[code], day)
                    px = pidx[code]["close"][j] if j is not None else pos["entry_price"]
                    holdings_val += pos["size"] * px
                nav_now = cash + holdings_val
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
                cash_only = float(cash)
                if position_sizing == "equal":
                    slot_value = cash_only / max_positions
                elif position_sizing == "all_in":
                    slot_value = cash_only
                else:  # kelly
                    slot_value = cash_only * kelly_fraction

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
                    # V3a (2026-09-22, CLAUDE.md §3): 当 raw_close 是 execution
                    # source 且 raw_open 存在, 用 raw_open 作为 entry fill 价。
                    # raw 缺失 → 回退到 adj open, baseline parity 保留。
                    if price_source_for_execution == "raw_close" and "raw_open" in pi:
                        r_o_entry = pi["raw_open"][j]
                        r_pc_entry = pi["raw_prev_close"][j]
                        if not np.isnan(r_o_entry) and not np.isnan(r_pc_entry) and r_pc_entry > 0:
                            o, pc = r_o_entry, r_pc_entry
                    # 涨停开盘视为无法买入
                    if not np.isnan(pc) and pc > 0 and (o / pc - 1) >= LIMIT_UP_THRESHOLD:
                        continue

                    # 先用静态 slippage 算 entry_px, 然后用预算算 size_pre_cap (R5
                    # slippage 在 vol cap 之前用 pre-cap size 计算更悲观)
                    entry_px = float(o) * (1 + slippage)
                    if entry_px <= 0:
                        continue

                    budget = min(slot_value, cash)
                    size = int(budget / entry_px / 100) * 100
                    if size < 100:
                        continue
                    # 防穿仓 (R8, 2026-09-21): Volume Participation Limit
                    # 单笔最大成交量 = Bar_Volume × max_volume_participation, 超出丢弃。
                    # 这是 CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
                    # 防止大单砸穿市场、产生 slippage / market impact。
                    # V8 (2026-09-22): 改为参数化 (从 preset 显式传入, 默认 0.10)。
                    bar_vol = pi["volume"][j]
                    size_pre_cap = size
                    if not np.isnan(bar_vol) and bar_vol > 0:
                        max_fill = int(bar_vol * max_volume_participation // 100) * 100
                        if max_fill > 0 and size > max_fill:
                            size = max_fill
                    # R5 (2026-09-21): ATR-aware slippage (CLAUDE.md §4)。
                    # 静态 slippage 不区分低/高波动率; 改用 signal-day atr_pct ×
                    # participation × scale 动态建模。
                    # 公式: slip_eff = max(static_slippage, atr_pct × participation × scale)
                    # participation = size_pre_cap / bar_vol (clamp 到 [0, 1])
                    # atr_pct 来源: atr_lookup (use_atr=True) 或 entries.atr_pct 列
                    if atr_slip_scale > 0:
                        atr_slip_lookup = atr_lookup.get((cal[t - 1], code))
                        if (atr_slip_lookup is None or np.isnan(atr_slip_lookup)) and "atr_pct" in ent.columns:
                            ent_match = ent[(ent["date"] == cal[t - 1]) & (ent["thscode"] == code)]
                            if not ent_match.empty:
                                atr_slip_lookup = float(ent_match.iloc[0]["atr_pct"])
                        if atr_slip_lookup is not None and not np.isnan(atr_slip_lookup):
                            if not np.isnan(bar_vol) and bar_vol > 0:
                                participation = min(1.0, size_pre_cap / bar_vol)
                            else:
                                participation = 0.0
                            atr_slip = atr_slip_lookup * participation * atr_slip_scale
                            if atr_slip > slippage:
                                entry_px = float(o) * (1 + atr_slip)
                                if entry_px <= 0:
                                    continue
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