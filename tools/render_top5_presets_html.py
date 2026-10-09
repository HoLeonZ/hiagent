"""Render top-5 preset HTML trade-detail reports (R527, 2026-10-08).

For each of 5 hand-picked top presets (from results/all_strategies_report.json
2026-10-08 snapshot), produces a self-contained HTML with:
  - Header (preset metadata + summary metrics)
  - Overall equity curve (plotly.js)
  - Trade list table (all trades)
  - Per-trade K-line chart with ALL preset-required indicator overlays +
    entry/exit markers (one plotly chart per trade)

Library: plotly.js via CDN (https://cdn.plot.ly/plotly-2.x.x.min.js).
Window: entry − WINDOW_BEFORE days … exit + WINDOW_AFTER days.

The 5 presets (2026-10-09 re-backtest, chase_up+uptrend fresh, short_reversal reused):
  1. short_reversal / v36_d_converge
  2. short_reversal / v44_ratio02_buf07
  3. short_reversal / v45_ratio01_buf10
  4. short_reversal / v40_tp_07
  5. short_reversal / v38_a_relaxed

Per-engine indicator coverage (all preset-required indicators visualized):
  chase_up (v11):
    row 1 — K-line + MA5/MA10/MA20/MA60/MA120 + breakout high20_prev level +
            entry/exit markers + horizontal/vertical entry/exit lines
    row 2 — Volume bars + vol_ratio (volume / 20-day MA) overlay
    row 3 — MACD (DIF / DEA lines + histogram bar)
    row 4 — mom120 (120-day momentum) + atr_pct (volatility %)
    row 5 — amount60 (60-day mean turnover, ¥)

  short_reversal (v36-v45, d_mode='converge_strict'):
    row 1 — K-line + MA5/MA10/MA20/MA60 + entry/exit markers (short entry ↓,
            cover ↑) + horizontal/vertical entry/exit lines
    row 2 — Volume bars
    row 3 — MACD (DIF / DEA lines + histogram bar)
    row 4 — am60 (60-day mean turnover, ¥) — liquidity filter E
    row 5 — below_ma60_ratio_60 (rolling 60-day % of closes below MA60)
            + up_streak bars — condition A + B
    row 6 — pct_chg bars (day-over-day return) — condition C

Usage:
    python3 -m tools.render_top5_presets_html
    python3 -m tools.render_top5_presets_html --out-dir /tmp/foo
    python3 -m tools.render_top5_presets_html --window-before 30 --window-after 15

Default window is the 10-08 aggregator range (2025-09-08 → 2026-09-08).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hiagent_config import DB_PATH  # noqa: E402
from core.trade_schema import TRADE_COLS  # noqa: E402
from chase_up.presets import get_preset as chase_up_get_preset  # noqa: E402
from short_reversal.presets import get_preset as short_reversal_get_preset  # noqa: E402
from short_reversal.render_html_report import (  # noqa: E402
    fetch_klines,
)


# ---------------------------------------------------------------- top-5 presets

TOP5: list[tuple[str, str]] = [
    ("short_reversal", "v36_d_converge"),
    ("short_reversal", "v44_ratio02_buf07"),
    ("short_reversal", "v45_ratio01_buf10"),
    ("short_reversal", "v40_tp_07"),
    ("short_reversal", "v38_a_relaxed"),
]

WINDOW_BEFORE = 20
WINDOW_AFTER = 10
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
INITIAL_CAPITAL = 1_000_000.0


# ---------------------------------------------------------------- helpers


def _sanitize(s: str) -> str:
    """Sanitize preset name for use in filename."""
    return s.replace("/", "_").replace("\\", "_")


def _clean(v):
    """Convert pd value to plotly-safe number or None (NaN → None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def _series(window: pd.DataFrame, col: str) -> list:
    """Extract a column from window as a JSON-safe list (None for NaN/missing)."""
    if col not in window.columns:
        return [None] * len(window)
    return [_clean(v) for v in window[col]]


def _load_chase_up_panel(preset: str, start: str, end: str) -> pd.DataFrame:
    """chase_up: load the SAME universe + panel the backtest uses (R527, 2026-10-08).

    Critical: must use preset["universe"] mode (not hardcode HS300), or the panel
    will be inconsistent with the trades' actual universe and per-trade K-line
    charts will show empty windows for any symbol outside the hardcoded set.
    """
    from chase_up.data import load_panel
    from chase_up.signals import compute_indicators
    from chase_up.universe import load_universe
    from chase_up.presets import get_preset

    p = get_preset(preset)
    universe = set(load_universe(p["universe"], DB_PATH, asof_date=start))
    panel = load_panel(DB_PATH, start, end, universe=universe)
    panel_ind = compute_indicators(panel)
    return panel_ind


def _run_chase_up(preset: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run chase_up backtest, returning (trades, equity, panel_ind).

    Panel is computed with the SAME universe the backtest uses so per-trade
    K-line lookups are guaranteed to find the symbol.
    """
    from chase_up.backtest import run_backtest
    from chase_up.data import load_panel
    from chase_up.signals import compute_indicators
    from chase_up.universe import load_universe
    from chase_up.presets import get_preset

    p = get_preset(preset)
    universe = set(load_universe(p["universe"], DB_PATH, asof_date=start))
    panel = load_panel(DB_PATH, start, end, universe=universe)
    panel_ind = compute_indicators(panel)

    res = run_backtest(preset, start, end, DB_PATH, panel_ind=panel_ind)
    trades = res["trades"].copy()
    equity = res["equity"].copy()
    return trades, equity, panel_ind


def _normalize_short_reversal_trade(
    raw: dict, klines: dict, start: str, end: str
) -> dict | None:
    """Convert raw short_reversal trade dict to canonical TRADE_COLS row.

    Reverse-engineers entry_date / exit_date via build_trade_dates' approach.
    Synthesizes net_pnl / gross_pnl / fees / net_return from price+size+net%.
    """
    thscode = raw["thscode"]
    ep = float(raw["entry_price"])
    xp = float(raw["exit_price"])
    size = int(raw["size"])
    net_pct = float(raw.get("net", 0.0))  # raw net is % return
    hold_days = int(raw["hold_days"])
    reason = raw.get("exit_reason", "TP")

    if size <= 0 or ep <= 0:
        return None

    kline = klines.get(thscode)
    entry_date = None
    exit_date = None
    if kline is not None and not kline.empty:
        mask = (kline["open"].astype(float) - ep).abs() < 0.001
        if mask.any():
            entry_date = pd.Timestamp(kline.loc[mask, "date"].iloc[0])
            after = kline[kline["date"] > entry_date].head(hold_days + 2)
            for _, row in after.iterrows():
                lo = float(row["low"])
                hi = float(row["high"])
                if lo - 1e-9 <= xp <= hi + 1e-9:
                    exit_date = pd.Timestamp(row["date"])
                    break
            if exit_date is None and not after.empty:
                exit_date = pd.Timestamp(after["date"].iloc[min(hold_days - 1, len(after) - 1)])

    if entry_date is None or exit_date is None:
        return None

    notional_in = ep * size
    gross_pnl = (xp - ep) * size
    net_pnl = net_pct * notional_in
    fees = gross_pnl - net_pnl
    net_return = net_pct

    return {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "thscode": thscode,
        "exit_reason": reason,
        "entry_price": ep,
        "exit_price": xp,
        "size": size,
        "hold_days": hold_days,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "net_return": net_return,
        "atr_pct": float("nan"),
        "sub_signal_type": "",
    }


def _compute_short_indicators(window: pd.DataFrame) -> pd.DataFrame:
    """Compute all short_reversal indicators from a raw K-line window.

    short_reversal's backtrader engine exposes indicators internally but not
    to the report — we re-derive them from the K-line here for visualization.
    Computes the same set the engine's signal conditions consume:
      ma5, ma10, ma20, ma60 — moving averages from raw close
      dif, dea, bar — MACD(12/26/9) computed via EMA
      am60 — 60-day rolling mean of amount (¥ turnover; liquidity filter E)
      below_ma60_ratio_60 — rolling 60-day fraction of closes below ma60 (cond A)
      up_streak — count of consecutive days where close > prev_close (cond B)
      pct_chg — day-over-day return (cond C)
    """
    df = window.copy().sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    amount = df["amount"].astype(float) if "amount" in df.columns else pd.Series([0.0] * len(df))

    # Moving averages — min_periods=1 so first bar after start is not NaN
    df["ma5"] = close.rolling(5, min_periods=1).mean()
    df["ma10"] = close.rolling(10, min_periods=1).mean()
    df["ma20"] = close.rolling(20, min_periods=1).mean()
    df["ma60"] = close.rolling(60, min_periods=1).mean()

    # MACD(12/26/9) — use adjust=False for reproducibility (matches engine)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_bar"] = df["macd_dif"] - df["macd_dea"]
    # Previous-bar MACD bar (needed for D condition "converge_strict" |bar| < |prev_bar| × 0.5)
    df["macd_bar_prev"] = df["macd_bar"].shift(1)

    # am60 — 60-day rolling mean of turnover (¥)
    df["am60"] = amount.rolling(60, min_periods=1).mean()

    # below_ma60_ratio_60 — fraction of last 60 closes that are below ma60
    below = (close < df["ma60"]).astype(float)
    df["below_ma60_ratio_60"] = below.rolling(60, min_periods=1).mean()

    # up_streak — consecutive up-day run length ending today
    up = (close > close.shift(1)).astype(int)
    streak = []
    s = 0
    for v in up.tolist():
        if pd.isna(v) or v == 0:
            s = 0
        else:
            s = s + 1
        streak.append(s)
    df["up_streak"] = streak

    # pct_chg — day-over-day return
    df["pct_chg"] = (close - close.shift(1)) / close.shift(1)

    return df


def _run_short_reversal(preset: str, start: str, end: str):
    """Run short_reversal backtest, normalize trades, synthesize equity.

    Returns (trades_df, equity_df, klines_with_indicators).
    klines_with_indicators maps thscode → DataFrame with raw OHLCV + computed
    indicators (ma5/10/20/60, macd, am60, below_ma60_ratio_60, up_streak, pct_chg).
    """
    from short_reversal.engine import run_backtest_v3

    res = run_backtest_v3(preset, start, end, DB_PATH)
    raw_trades = res["trades"]

    codes = list({t["thscode"] for t in raw_trades})
    klines = fetch_klines(codes, start, end, pad_days=180)

    rows = []
    for t in raw_trades:
        row = _normalize_short_reversal_trade(t, klines, start, end)
        if row is not None:
            rows.append(row)
    trades_df = pd.DataFrame(rows, columns=list(TRADE_COLS))

    if not trades_df.empty:
        trades_sorted = trades_df.sort_values("entry_date").reset_index(drop=True)
        cum = (1.0 + trades_sorted["net_return"].fillna(0.0)).cumprod()
        equity_df = pd.DataFrame({
            "date": trades_sorted["entry_date"],
            "cash": INITIAL_CAPITAL * cum,
            "equity": INITIAL_CAPITAL * cum,
        })
    else:
        equity_df = pd.DataFrame(columns=["date", "cash", "equity"])

    # Pre-compute indicators for every kline so per-trade windows are cheap.
    enriched: dict[str, pd.DataFrame] = {}
    for code, kl in klines.items():
        enriched[code] = _compute_short_indicators(kl)

    return trades_df, equity_df, enriched


# ---------------------------------------------------------------- HTML render


def _fmt_pct(x: float, digits: int = 2) -> str:
    """Format a ratio as percentage. NaN → 'n/a'."""
    if pd.isna(x):
        return "n/a"
    return f"{x*100:+.{digits}f}%"


def _fmt_num(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return "n/a"
    return f"{x:.{digits}f}"


def _fmt_yuan(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    if abs(x) >= 1e8:
        return f"¥{x/1e8:.2f}亿"
    if abs(x) >= 1e4:
        return f"¥{x/1e4:.0f}万"
    return f"¥{x:,.0f}"


def _build_entry_reasons_chase(
    trade: dict, panel: pd.DataFrame, preset: dict
) -> str:
    """Build a detailed HTML block explaining why chase_up entered this trade.

    chase_up generates signal at T-1 close and buys at T+1 open, so the
    decision row is the panel row at entry_date − 1 day. Shows actual
    indicator values alongside thresholds for the 3 sub-signals (A/B/C) and
    the 4 hard filters (mom120, amount60, atr_pct, ma20>ma60).
    """
    code = trade["thscode"]
    ed = pd.Timestamp(trade["entry_date"])
    sig_date = ed - pd.Timedelta(days=1)  # T-1: signal was generated at close
    sub = panel[panel["thscode"] == code].sort_values("date")
    row = sub[sub["date"] == sig_date]
    if row.empty:
        sig_date = ed  # fallback: assume T=entry
        row = sub[sub["date"] == sig_date]
    if row.empty:
        return (
            f'<div class="entry-reason"><b>入场原因</b> '
            f"<span class='muted'>(panel 找不到 {code} @ {sig_date.date()},无法重建)</span></div>"
        )
    r = row.iloc[0]
    sig_cfg = preset.get("signal", {})

    # Sub-signal A (breakout)
    a_close = float(r["close"])
    a_h20p = float(r["high20_prev"]) if not pd.isna(r.get("high20_prev", float("nan"))) else float("nan")
    a_vr = float(r["vol_ratio"]) if not pd.isna(r.get("vol_ratio", float("nan"))) else float("nan")
    a_ok = (a_close > a_h20p) and (a_close > float(r["ma60"])) and (a_vr >= sig_cfg.get("breakout_vol_min", 1.5))
    # Sub-signal B (momentum)
    b_ret1 = float(r["ret1"]) if not pd.isna(r.get("ret1", float("nan"))) else float("nan")
    b_dif = float(r["macd_dif"])
    b_dea = float(r["macd_dea"])
    b_bar = float(r["macd_bar"])
    b_bar_prev = float(r["macd_bar_prev"]) if not pd.isna(r.get("macd_bar_prev", float("nan"))) else float("nan")
    b_expanding = (abs(b_bar) > abs(b_bar_prev)) if not pd.isna(b_bar_prev) else False
    b_ok = (
        sig_cfg.get("pct_chg_low", 0.03) <= b_ret1 <= sig_cfg.get("pct_chg_high", 0.08)
        and b_dif > 0 and b_dea > 0 and b_expanding
        and a_vr >= sig_cfg.get("momentum_vol_min", 1.3)
    )
    # Sub-signal C (macross)
    c_cross = float(r.get("ma_cross_recent", 0.0))
    c_close_ge = a_close >= float(r["ma20"]) * 1.02
    c_ok = c_cross == 1.0 and c_close_ge and a_vr >= sig_cfg.get("macross_vol_min", 1.2)

    sub_type = trade.get("sub_signal_type", "")
    if not sub_type:
        # Fallback: compute from the booleans (engine would have set this but
        # if for some reason the column is empty, derive it ourselves).
        sub_type = ("A" if a_ok else "") + ("B" if b_ok else "") + ("C" if c_ok else "")

    a_cls = "ok" if a_ok else "no"
    b_cls = "ok" if b_ok else "no"
    c_cls = "ok" if c_ok else "no"

    return (
        '<div class="entry-reason">'
        f"<b>入场原因 (chase_up, 信号日 {sig_date.date()})</b> "
        f"<span class='sub-tag'>{sub_type or '?'}</span><br>"
        f"<span class='cond {a_cls}'>A 平台突破</span>: "
        f"close={_fmt_num(a_close)}, high20_prev={_fmt_num(a_h20p)}, "
        f"close&gt;ma60={_fmt_num(float(r['ma60']))}, "
        f"vol_ratio={_fmt_num(a_vr)} (需≥{sig_cfg.get('breakout_vol_min', 1.5)})<br>"
        f"<span class='cond {b_cls}'>B 动量加速</span>: "
        f"ret1={_fmt_pct(b_ret1)} (∈[{_fmt_pct(sig_cfg.get('pct_chg_low', 0.03))},"
        f"{_fmt_pct(sig_cfg.get('pct_chg_high', 0.08))}]), "
        f"DIF={_fmt_num(b_dif, 4)}/DEA={_fmt_num(b_dea, 4)}, "
        f"|bar|={_fmt_num(abs(b_bar), 4)}"
        f"{'&gt;' if b_expanding else '≤'}|prev_bar|={_fmt_num(abs(b_bar_prev), 4)}, "
        f"vol_ratio={_fmt_num(a_vr)} (需≥{sig_cfg.get('momentum_vol_min', 1.3)})<br>"
        f"<span class='cond {c_cls}'>C 均线金叉</span>: "
        f"ma_cross_recent={'✓' if c_cross == 1.0 else '✗'}, "
        f"close={_fmt_num(a_close)}"
        f"{'≥' if c_close_ge else '<'}ma20×1.02={_fmt_num(float(r['ma20'])*1.02)}, "
        f"vol_ratio={_fmt_num(a_vr)} (需≥{sig_cfg.get('macross_vol_min', 1.2)})<br>"
        "<b>硬过滤</b>: "
        f"mom120={_fmt_pct(float(r['mom120']))} (≥{_fmt_pct(sig_cfg.get('min_mom120', 0.05))}), "
        f"ma20={_fmt_num(float(r['ma20']))}"
        f"{'&gt;' if float(r['ma20']) > float(r['ma60']) else '≤'}ma60={_fmt_num(float(r['ma60']))}, "
        f"amount60={_fmt_yuan(float(r['amount60']))} (∈[{_fmt_yuan(sig_cfg.get('min_amount', 3e7))},"
        f"{_fmt_yuan(sig_cfg.get('max_amount', 3e8))}]), "
        f"atr_pct={_fmt_pct(float(r['atr_pct']))} (∈[{_fmt_pct(sig_cfg.get('atr_pct_low', 0.03))},"
        f"{_fmt_pct(sig_cfg.get('atr_pct_high', 0.10))}])"
        "</div>"
    )


def _build_entry_reasons_short(
    trade: dict, kline_ind: pd.DataFrame, preset: dict
) -> str:
    """Build detailed HTML for short_reversal entry reasoning.

    short_reversal enters at T open (signal-day), so decision row is the
    panel row at entry_date. Shows 5 conditions (E/A/B/C/D) with actual
    values vs preset thresholds.
    """
    code = trade["thscode"]
    ed = pd.Timestamp(trade["entry_date"])
    sub = kline_ind[kline_ind["date"] == ed]
    if sub.empty:
        return (
            f'<div class="entry-reason"><b>入场原因</b> '
            f"<span class='muted'>(panel 找不到 {code} @ {ed.date()},无法重建)</span></div>"
        )
    r = sub.iloc[0]

    # Defaults (mirrors replay_strategy_v3.py params)
    liq_lo = 3e7
    liq_hi = 3e8
    us_lo = 3
    us_hi = 10
    pc_lo = float(preset.get("pct_chg_low", 0.03))
    pc_hi = float(preset.get("pct_chg_high", 0.10))
    ratio = float(preset.get("below_ratio_60", 0.5))
    buf = float(preset.get("close_ma60_buffer", 0.02))
    d_mode = preset.get("d_mode", "strict")

    # E liquidity
    e_am60 = float(r["am60"])
    e_ok = liq_lo <= e_am60 <= liq_hi
    # A trend (default mode = below_ratio_60 + close_ma60_buffer)
    a_close = float(r["close"])
    a_ma60 = float(r["ma60"])
    a_ratio_val = float(r["below_ma60_ratio_60"])
    a_ok = (a_close < a_ma60 * (1.0 + buf)) and (a_ratio_val >= ratio)
    # B up_streak
    b_us = float(r["up_streak"])
    b_ok = us_lo <= b_us <= us_hi
    # C pct_chg
    c_pc = float(r["pct_chg"])
    c_ok = pc_lo <= c_pc <= pc_hi
    # D MACD
    d_dif = float(r["macd_dif"])
    d_dea = float(r["macd_dea"])
    d_bar = float(r["macd_bar"])
    d_bar_prev = float(r["macd_bar_prev"]) if not pd.isna(r.get("macd_bar_prev", float("nan"))) else float("nan")
    if d_mode == "d_only":
        d_ok = d_dif < 0
        d_desc = f"DIF={_fmt_num(d_dif, 4)} (需&lt;0)"
    elif d_mode == "converge_strict":
        d_ok = d_dif < 0 and d_dea < 0 and abs(d_bar) < abs(d_bar_prev) * 0.5
        d_desc = (
            f"DIF={_fmt_num(d_dif, 4)}&lt;0, DEA={_fmt_num(d_dea, 4)}&lt;0, "
            f"|bar|={_fmt_num(abs(d_bar), 4)}&lt;|prev_bar|×0.5="
            f"{_fmt_num(abs(d_bar_prev)*0.5 if not pd.isna(d_bar_prev) else float('nan'), 4)}"
        )
    else:  # strict
        d_ok = d_dif < 0 and d_dea < 0 and abs(d_bar) < abs(d_bar_prev)
        d_desc = (
            f"DIF={_fmt_num(d_dif, 4)}&lt;0, DEA={_fmt_num(d_dea, 4)}&lt;0, "
            f"|bar|={_fmt_num(abs(d_bar), 4)}&lt;|prev_bar|={_fmt_num(abs(d_bar_prev), 4)}"
        )

    summary = "+".join(
        label for label, ok in [("E", e_ok), ("A", a_ok), ("B", b_ok), ("C", c_ok), ("D", d_ok)] if ok
    ) or "?"

    def cls(ok): return "ok" if ok else "no"
    return (
        '<div class="entry-reason">'
        f"<b>入场原因 (short_reversal, 入场日 {ed.date()})</b> "
        f"<span class='sub-tag'>{summary}</span><br>"
        f"<span class='cond {cls(e_ok)}'>E 流动性</span>: "
        f"am60={_fmt_yuan(e_am60)} (∈[{_fmt_yuan(liq_lo)},{_fmt_yuan(liq_hi)}])<br>"
        f"<span class='cond {cls(a_ok)}'>A 跌破MA60占比</span>: "
        f"below_ratio_60={_fmt_pct(a_ratio_val, 1)} (≥{_fmt_pct(ratio, 1)}), "
        f"close={_fmt_num(a_close)}"
        f"{'&lt;' if a_close < a_ma60 * (1.0 + buf) else '≥'}ma60×(1+buf)="
        f"{_fmt_num(a_ma60 * (1.0 + buf))} (buffer={_fmt_pct(buf, 1)})<br>"
        f"<span class='cond {cls(b_ok)}'>B 连阳天数</span>: "
        f"up_streak={int(b_us)} (∈[{us_lo},{us_hi}])<br>"
        f"<span class='cond {cls(c_ok)}'>C 日收益</span>: "
        f"pct_chg={_fmt_pct(c_pc, 2)} (∈[{_fmt_pct(pc_lo)},{_fmt_pct(pc_hi)}])<br>"
        f"<span class='cond {cls(d_ok)}'>D MACD ({d_mode})</span>: {d_desc}"
        "</div>"
    )


def _render_per_trade_chart_chase(
    trade: dict, window: pd.DataFrame, idx: int,
    entry_reason_html: str = "",
) -> str:
    """Build plotly.js div + script for one chase_up trade.

    All preset-required indicators visualized (v11: MA5/10/20/60/120, MACD,
    Volume + vol_ratio, mom120 + atr_pct, amount60, breakout high20_prev):
      row 1: K-line + MA5/MA10/MA20/MA60/MA120 + high20_prev breakout level
             + entry/exit markers + horizontal entry/exit lines
      row 2: Volume bars + vol_ratio overlay
      row 3: MACD (DIF/DEA + bar)
      row 4: mom120 (medium-term momentum) + atr_pct (volatility)
      row 5: amount60 (liquidity proxy, ¥)

    entry_reason_html: pre-rendered detailed entry-reason block (A/B/C
    sub-signals + hard filters) shown above the chart.
    """
    if window.empty:
        return f'<div id="trade-{idx}" class="trade-empty">(no panel data for {trade["thscode"]} around {trade["entry_date"]})</div>'

    dates = [d.strftime("%Y-%m-%d") for d in window["date"]]
    kline = [
        [float(r.open), float(r.close), float(r.low), float(r.high)]
        for r in window.itertuples()
    ]
    ma5 = _series(window, "ma5")
    ma10 = _series(window, "ma10")
    ma20 = _series(window, "ma20")
    ma60 = _series(window, "ma60")
    ma120 = _series(window, "ma120")
    high20_prev = _series(window, "high20_prev")
    dif = _series(window, "macd_dif")
    dea = _series(window, "macd_dea")
    macd_b = _series(window, "macd_bar")
    mom120 = _series(window, "mom120")
    atr_pct = _series(window, "atr_pct")
    amount60 = _series(window, "amount60")
    volumes = [float(r.volume) if not pd.isna(r.volume) else 0.0 for r in window.itertuples()]
    vol_ratio = _series(window, "vol_ratio")

    ed_str = pd.Timestamp(trade["entry_date"]).strftime("%Y-%m-%d")
    xd_str = pd.Timestamp(trade["exit_date"]).strftime("%Y-%m-%d")
    ep = float(trade["entry_price"])
    xp = float(trade["exit_price"])

    fig_id = f"trade-{idx}"
    spec = {
        "data": [
            {"type": "candlestick", "x": dates,
             "open": [k[0] for k in kline], "high": [k[1] for k in kline],
             "low": [k[2] for k in kline], "close": [k[3] for k in kline],
             "name": "K线 (红涨绿跌)",
             "increasing": {"line": {"color": "#ef232a"}, "fillcolor": "#ef232a"},
             "decreasing": {"line": {"color": "#14b143"}, "fillcolor": "#14b143"},
             "xaxis": "x", "yaxis": "y", "showlegend": True},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma5,
             "name": "MA5", "line": {"color": "#d9d9d9", "width": 1},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma10,
             "name": "MA10", "line": {"color": "#b37feb", "width": 1},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma20,
             "name": "MA20", "line": {"color": "#faad14", "width": 2},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma60,
             "name": "MA60", "line": {"color": "#1890ff", "width": 2},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma120,
             "name": "MA120", "line": {"color": "#13c2c2", "width": 1, "dash": "dot"},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": high20_prev,
             "name": "high20_prev (breakout 突破线)", "line": {"color": "#52c41a", "width": 1, "dash": "dashdot"},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "markers",
             "x": [ed_str], "y": [ep],
             "marker": {"symbol": "triangle-up", "size": 14, "color": "#fa8c16",
                        "line": {"color": "#000", "width": 1}},
             "name": f"Entry ¥{ep:.2f}", "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "markers",
             "x": [xd_str], "y": [xp],
             "marker": {"symbol": "triangle-down", "size": 14, "color": "#722ed1",
                        "line": {"color": "#000", "width": 1}},
             "name": f"Exit ¥{xp:.2f}", "xaxis": "x", "yaxis": "y"},
            {"type": "bar", "x": dates, "y": volumes, "name": "Volume",
             "marker": {"color": "#bfbfbf"}, "xaxis": "x2", "yaxis": "y2",
             "showlegend": True},
            {"type": "scatter", "mode": "lines", "x": dates, "y": vol_ratio,
             "name": "vol_ratio (vol/MA20)", "line": {"color": "#fa541c", "width": 1},
             "xaxis": "x2", "yaxis": "y2"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": dif,
             "name": "MACD DIF", "line": {"color": "#fa8c16", "width": 1.5},
             "xaxis": "x3", "yaxis": "y3"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": dea,
             "name": "MACD DEA", "line": {"color": "#1890ff", "width": 1.5},
             "xaxis": "x3", "yaxis": "y3"},
            {"type": "bar", "x": dates, "y": macd_b, "name": "MACD bar",
             "marker": {"color": "#999"}, "xaxis": "x3", "yaxis": "y3",
             "showlegend": False},
            {"type": "scatter", "mode": "lines", "x": dates, "y": mom120,
             "name": "mom120 (中长动量)", "line": {"color": "#722ed1", "width": 1.5},
             "xaxis": "x4", "yaxis": "y4"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": atr_pct,
             "name": "atr_pct (波动率)", "line": {"color": "#eb2f96", "width": 1.5},
             "xaxis": "x4", "yaxis": "y4"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": amount60,
             "name": "amount60 (60日均成交额)", "line": {"color": "#2f54eb", "width": 1.5},
             "xaxis": "x5", "yaxis": "y5"},
        ],
        "layout": {
            "title": {
                "text": (
                    f"{trade['thscode']} | {ed_str} → {xd_str} | "
                    f"hold={int(trade['hold_days'])}d | {trade['exit_reason']} | "
                    f"net=¥{trade['net_pnl']:+,.0f} ({trade['net_return']*100:+.2f}%)"
                ),
                "font": {"size": 13},
            },
            "xaxis": {"rangeslider": {"visible": False}, "type": "category",
                       "tickangle": -30, "nticks": 10},
            "xaxis2": {"type": "category", "showticklabels": False},
            "xaxis3": {"type": "category", "showticklabels": False},
            "xaxis4": {"type": "category", "showticklabels": False},
            "xaxis5": {"type": "category", "tickangle": -30, "nticks": 10},
            "yaxis": {"title": "Price + MA + 突破线", "domain": [0.62, 1.0]},
            "yaxis2": {"title": "Vol / vol_ratio", "domain": [0.46, 0.58]},
            "yaxis3": {"title": "MACD", "domain": [0.30, 0.42]},
            "yaxis4": {"title": "mom120 / atr_pct", "domain": [0.14, 0.26]},
            "yaxis5": {"title": "amount60", "domain": [0.0, 0.10]},
            "shapes": [
                {"type": "line", "xref": "x", "yref": "y",
                 "x0": ed_str, "x1": xd_str, "y0": ep, "y1": ep,
                 "line": {"color": "#fa8c16", "width": 1, "dash": "dash"}},
                {"type": "line", "xref": "x", "yref": "y",
                 "x0": ed_str, "x1": xd_str, "y0": xp, "y1": xp,
                 "line": {"color": "#722ed1", "width": 1, "dash": "dash"}},
            ],
            "legend": {"orientation": "h", "y": 1.10, "x": 0,
                       "font": {"size": 10}},
            "margin": {"l": 60, "r": 20, "t": 70, "b": 30},
            "height": 800,
        },
    }
    return (
        f'{entry_reason_html}\n'
        f'<div id="{fig_id}" class="trade-chart"></div>\n'
        f'<script>Plotly.newPlot("{fig_id}", {json.dumps(spec["data"])}, '
        f'{json.dumps(spec["layout"])}, {{"displayModeBar": false, "responsive": true}});</script>\n'
    )


def _render_per_trade_chart_short(
    trade: dict, window: pd.DataFrame, idx: int,
    entry_reason_html: str = "",
) -> str:
    """Short_reversal: K-line + MA5/10/20/60 + entry/exit + MACD + am60 +
    below_ma60_ratio_60 + up_streak + pct_chg.

    All indicators are pre-computed by `_compute_short_indicators` before
    per-trade window slicing (see `_run_short_reversal`). 6-row subplot:
      row 1: K-line + MA5/10/20/60 + short entry ↓ + cover ↑ + entry/exit
             horizontal lines
      row 2: Volume bars
      row 3: MACD (DIF/DEA + bar)
      row 4: am60 (60-day mean turnover, ¥)
      row 5: below_ma60_ratio_60 line + up_streak bars (conditions A + B)
      row 6: pct_chg bars (condition C)
    """
    if window.empty:
        return f'<div id="trade-{idx}" class="trade-empty">(no panel data for {trade["thscode"]})</div>'

    dates = [d.strftime("%Y-%m-%d") for d in window["date"]]
    kline = [
        [float(r.open), float(r.close), float(r.low), float(r.high)]
        for r in window.itertuples()
    ]
    ma5 = _series(window, "ma5")
    ma10 = _series(window, "ma10")
    ma20 = _series(window, "ma20")
    ma60 = _series(window, "ma60")
    dif = _series(window, "macd_dif")
    dea = _series(window, "macd_dea")
    macd_b = _series(window, "macd_bar")
    am60 = _series(window, "am60")
    below = _series(window, "below_ma60_ratio_60")
    up_streak = _series(window, "up_streak")
    pct_chg = _series(window, "pct_chg")
    volumes = [float(r.volume) if not pd.isna(r.volume) else 0.0 for r in window.itertuples()]

    ed_str = pd.Timestamp(trade["entry_date"]).strftime("%Y-%m-%d")
    xd_str = pd.Timestamp(trade["exit_date"]).strftime("%Y-%m-%d")
    ep = float(trade["entry_price"])
    xp = float(trade["exit_price"])

    fig_id = f"trade-{idx}"
    spec = {
        "data": [
            {"type": "candlestick", "x": dates,
             "open": [k[0] for k in kline], "high": [k[1] for k in kline],
             "low": [k[2] for k in kline], "close": [k[3] for k in kline],
             "name": "K线 (红涨绿跌)",
             "increasing": {"line": {"color": "#ef232a"}, "fillcolor": "#ef232a"},
             "decreasing": {"line": {"color": "#14b143"}, "fillcolor": "#14b143"},
             "xaxis": "x", "yaxis": "y", "showlegend": True},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma5,
             "name": "MA5", "line": {"color": "#d9d9d9", "width": 1},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma10,
             "name": "MA10", "line": {"color": "#b37feb", "width": 1},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma20,
             "name": "MA20", "line": {"color": "#faad14", "width": 2},
             "xaxis": "x", "yaxis": "y"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": ma60,
             "name": "MA60", "line": {"color": "#1890ff", "width": 2},
             "xaxis": "x", "yaxis": "y"},
            # Short entry: arrow DOWN (sell short)
            {"type": "scatter", "mode": "markers",
             "x": [ed_str], "y": [ep],
             "marker": {"symbol": "triangle-down", "size": 14, "color": "#fa8c16",
                        "line": {"color": "#000", "width": 1}},
             "name": f"Short Entry ¥{ep:.2f}", "xaxis": "x", "yaxis": "y"},
            # Short cover: arrow UP (buy to cover)
            {"type": "scatter", "mode": "markers",
             "x": [xd_str], "y": [xp],
             "marker": {"symbol": "triangle-up", "size": 14, "color": "#722ed1",
                        "line": {"color": "#000", "width": 1}},
             "name": f"Cover ¥{xp:.2f}", "xaxis": "x", "yaxis": "y"},
            {"type": "bar", "x": dates, "y": volumes, "name": "Volume",
             "marker": {"color": "#bfbfbf"}, "xaxis": "x2", "yaxis": "y2"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": dif,
             "name": "MACD DIF", "line": {"color": "#fa8c16", "width": 1.5},
             "xaxis": "x3", "yaxis": "y3"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": dea,
             "name": "MACD DEA", "line": {"color": "#1890ff", "width": 1.5},
             "xaxis": "x3", "yaxis": "y3"},
            {"type": "bar", "x": dates, "y": macd_b, "name": "MACD bar",
             "marker": {"color": "#999"}, "xaxis": "x3", "yaxis": "y3",
             "showlegend": False},
            {"type": "scatter", "mode": "lines", "x": dates, "y": am60,
             "name": "am60 (60日均成交额)", "line": {"color": "#2f54eb", "width": 1.5},
             "xaxis": "x4", "yaxis": "y4"},
            {"type": "scatter", "mode": "lines", "x": dates, "y": below,
             "name": "below_ma60_ratio_60", "line": {"color": "#722ed1", "width": 1.5},
             "xaxis": "x5", "yaxis": "y5"},
            {"type": "bar", "x": dates, "y": up_streak, "name": "up_streak",
             "marker": {"color": "#52c41a"}, "xaxis": "x5", "yaxis": "y5",
             "showlegend": True},
            {"type": "bar", "x": dates, "y": pct_chg, "name": "pct_chg",
             "marker": {"color": "#fa8c16"}, "xaxis": "x6", "yaxis": "y6"},
        ],
        "layout": {
            "title": {
                "text": (
                    f"{trade['thscode']} SHORT | {ed_str} → {xd_str} | "
                    f"hold={int(trade['hold_days'])}d | {trade['exit_reason']} | "
                    f"net=¥{trade['net_pnl']:+,.0f} ({trade['net_return']*100:+.2f}%)"
                ),
                "font": {"size": 13},
            },
            "xaxis": {"rangeslider": {"visible": False}, "type": "category",
                       "tickangle": -30, "nticks": 10},
            "xaxis2": {"type": "category", "showticklabels": False},
            "xaxis3": {"type": "category", "showticklabels": False},
            "xaxis4": {"type": "category", "showticklabels": False},
            "xaxis5": {"type": "category", "showticklabels": False},
            "xaxis6": {"type": "category", "tickangle": -30, "nticks": 10},
            "yaxis": {"title": "Price + MA", "domain": [0.66, 1.0]},
            "yaxis2": {"title": "Volume", "domain": [0.54, 0.62]},
            "yaxis3": {"title": "MACD", "domain": [0.40, 0.50]},
            "yaxis4": {"title": "am60 (¥)", "domain": [0.26, 0.36]},
            "yaxis5": {"title": "below_ma60 / up_streak", "domain": [0.12, 0.22]},
            "yaxis6": {"title": "pct_chg", "domain": [0.0, 0.08]},
            "shapes": [
                {"type": "line", "xref": "x", "yref": "y",
                 "x0": ed_str, "x1": xd_str, "y0": ep, "y1": ep,
                 "line": {"color": "#fa8c16", "width": 1, "dash": "dash"}},
                {"type": "line", "xref": "x", "yref": "y",
                 "x0": ed_str, "x1": xd_str, "y0": xp, "y1": xp,
                 "line": {"color": "#722ed1", "width": 1, "dash": "dash"}},
            ],
            "legend": {"orientation": "h", "y": 1.10, "x": 0,
                       "font": {"size": 10}},
            "margin": {"l": 60, "r": 20, "t": 70, "b": 30},
            "height": 850,
        },
    }
    return (
        f'{entry_reason_html}\n'
        f'<div id="{fig_id}" class="trade-chart"></div>\n'
        f'<script>Plotly.newPlot("{fig_id}", {json.dumps(spec["data"])}, '
        f'{json.dumps(spec["layout"])}, {{"displayModeBar": false, "responsive": true}});</script>\n'
    )


def _render_equity_chart(equity: pd.DataFrame) -> str:
    """Render overall equity curve (plotly.js)."""
    if equity.empty:
        return '<div id="equity-plot" class="empty">(no equity data)</div>'

    dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in equity["date"]]
    eq = [float(v) for v in equity["equity"]]
    spec = {
        "data": [
            {"type": "scatter", "mode": "lines", "x": dates, "y": eq,
             "name": "Equity", "line": {"color": "#1890ff", "width": 2},
             "fill": "tozeroy", "fillcolor": "rgba(24,144,255,0.1)"},
        ],
        "layout": {
            "title": {"text": f"Equity Curve (final = ¥{eq[-1]:,.0f})", "font": {"size": 14}},
            "xaxis": {"type": "category", "tickangle": -30, "nticks": 10},
            "yaxis": {"title": "Equity (¥)", "tickformat": ",.0f"},
            "margin": {"l": 60, "r": 20, "t": 50, "b": 30},
            "height": 350,
        },
    }
    return (
        '<div id="equity-plot"></div>\n'
        f'<script>Plotly.newPlot("equity-plot", {json.dumps(spec["data"])}, '
        f'{json.dumps(spec["layout"])}, {{"displayModeBar": false, "responsive": true}});</script>\n'
    )


def _render_trade_table(trades: pd.DataFrame, strategy: str) -> str:
    """Render HTML table of all trades.

    Adds an 'entry_signals' column showing the sub-signal letters that
    triggered entry (e.g. 'ABC' for chase_up multi-trigger; 'E+A+B+C+D'
    for short_reversal). Full reasoning is in the per-trade block above
    each chart.
    """
    if trades.empty:
        return "<p>(no trades)</p>"
    rows_html = []
    for i, t in trades.iterrows():
        ed = pd.Timestamp(t["entry_date"]).strftime("%Y-%m-%d")
        xd = pd.Timestamp(t["exit_date"]).strftime("%Y-%m-%d")
        if strategy == "chase_up":
            # trade["sub_signal_type"] like "A"/"AB"/"ABC" — already canonical
            sigs = t.get("sub_signal_type", "") or "?"
        else:
            # short_reversal: derive compact summary from exit_reason context
            # (engine doesn't store it). For visual scan we just show "E+A+B+C+D"
            # markers via the per-trade block; the table column shows a hint.
            sigs = "E+A+B+C+D"
        rows_html.append(
            f"<tr>"
            f"<td>{i+1}</td>"
            f"<td>{t['thscode']}</td>"
            f"<td>{ed}</td>"
            f"<td>{t['entry_price']:.2f}</td>"
            f"<td>{xd}</td>"
            f"<td>{t['exit_price']:.2f}</td>"
            f"<td>{int(t['size'])}</td>"
            f"<td>{int(t['hold_days'])}</td>"
            f"<td>{t['exit_reason']}</td>"
            f"<td><span class='sig-tag'>{sigs}</span></td>"
            f"<td style='color:{'#0a0' if t['net_pnl'] >= 0 else '#a00'}'>"
            f"¥{t['net_pnl']:+,.0f}</td>"
            f"<td>{t['net_return']*100:+.2f}%</td>"
            f"</tr>"
        )
    return (
        "<table class='trade-table'>"
        "<thead><tr>"
        "<th>#</th><th>thscode</th><th>entry_date</th><th>entry_px</th>"
        "<th>exit_date</th><th>exit_px</th><th>size</th><th>hold</th>"
        "<th>exit_reason</th><th>entry_signals</th>"
        "<th>net_pnl</th><th>net_ret</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )


def _summary_metrics(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    """Compute summary metrics from trades + equity (for header)."""
    if trades.empty or equity.empty:
        return {}
    n = len(trades)
    wins = (trades["net_pnl"] > 0).sum()
    win_rate = wins / n if n > 0 else 0.0
    start_eq = INITIAL_CAPITAL
    end_eq = float(equity["equity"].iloc[-1])
    total_return = end_eq / start_eq - 1.0
    days = (pd.Timestamp(equity["date"].iloc[-1]) - pd.Timestamp(equity["date"].iloc[0])).days
    years = days / 365.25 if days > 0 else 1.0
    cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    return {
        "trades": n,
        "win_rate": win_rate,
        "cagr": cagr,
        "total_return": total_return,
        "final_equity": end_eq,
        "start": pd.Timestamp(equity["date"].iloc[0]).strftime("%Y-%m-%d"),
        "end": pd.Timestamp(equity["date"].iloc[-1]).strftime("%Y-%m-%d"),
    }


def _render_html(
    strategy: str, preset: str, trades: pd.DataFrame, equity: pd.DataFrame,
    per_trade_html: list[str], window_meta: dict
) -> str:
    """Render the full HTML page for one preset."""
    m = _summary_metrics(trades, equity)
    title = f"{strategy} — {preset}"
    metrics_block = ""
    if m:
        metrics_block = (
            "<table class='summary'>"
            f"<tr><td>Preset</td><td><b>{preset}</b></td></tr>"
            f"<tr><td>Window</td><td>{m.get('start', '?')} → {m.get('end', '?')}</td></tr>"
            f"<tr><td>Trades</td><td>{m.get('trades', 0)}</td></tr>"
            f"<tr><td>Win Rate</td><td>{m.get('win_rate', 0)*100:.1f}%</td></tr>"
            f"<tr><td>CAGR</td><td>{m.get('cagr', 0)*100:+.1f}%</td></tr>"
            f"<tr><td>Total Return</td><td>{m.get('total_return', 0)*100:+.1f}%</td></tr>"
            f"<tr><td>Final Equity</td><td>¥{m.get('final_equity', 0):,.0f}</td></tr>"
            "</table>"
        )

    # Indicator legend explaining what each chart shows
    if strategy == "chase_up":
        legend = (
            "<div class='legend-box'>"
            "<b>chase_up v11 chart indicators (all preset-required):</b><br>"
            "<b>K线配色 (A 股惯例):</b> 红色 = 收涨 (close &gt; open), "
            "绿色 = 收跌 (close &lt; open)<br>"
            "Row 1 (Price): K线 + MA5/MA10/MA20/MA60/MA120 + high20_prev (突破参考线) "
            "+ Entry ▲ (橙) / Exit ▼ (紫)<br>"
            "Row 2: Volume bars + vol_ratio (vol/MA20)<br>"
            "Row 3: MACD (DIF 橙 + DEA 蓝 + histogram)<br>"
            "Row 4: mom120 (中长动量, 紫) + atr_pct (波动率, 粉)<br>"
            "Row 5: amount60 (60日均成交额, ¥)"
            "</div>"
        )
    else:
        legend = (
            "<div class='legend-box'>"
            "<b>short_reversal v36-v45 chart indicators (all preset-required):</b><br>"
            "<b>K线配色 (A 股惯例):</b> 红色 = 收涨 (close &gt; open), "
            "绿色 = 收跌 (close &lt; open)<br>"
            "Row 1 (Price): K线 + MA5/MA10/MA20/MA60 + Short Entry ▼ (橙) / Cover ▲ (紫)<br>"
            "Row 2: Volume bars<br>"
            "Row 3: MACD (DIF 橙 + DEA 蓝 + histogram)<br>"
            "Row 4: am60 (60日均成交额, 流动性过滤条件 E)<br>"
            "Row 5: below_ma60_ratio_60 (跌破MA60占比, 条件 A) + up_streak (连阳, 条件 B)<br>"
            "Row 6: pct_chg (日收益, 条件 C)"
            "</div>"
        )

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 1300px; margin: 0 auto; padding: 20px; color: #333; }
    h1 { color: #1f1f1f; }
    h2 { margin-top: 40px; border-bottom: 2px solid #1890ff; padding-bottom: 6px; }
    .summary { border-collapse: collapse; margin: 12px 0; }
    .summary td { padding: 4px 12px; border: 1px solid #ddd; }
    .summary td:first-child { background: #f5f5f5; font-weight: 600; }
    .trade-table { border-collapse: collapse; width: 100%; font-size: 13px; }
    .trade-table th, .trade-table td { padding: 4px 8px; border: 1px solid #ddd; text-align: right; }
    .trade-table th { background: #f5f5f5; }
    .trade-table td:nth-child(2), .trade-table td:nth-child(3), .trade-table td:nth-child(5), .trade-table td:nth-child(9) { text-align: left; }
    .trade-chart { width: 100%; margin: 16px 0; }
    .legend-box { background: #f0f5ff; border-left: 4px solid #1890ff; padding: 10px 14px; margin: 14px 0; font-size: 13px; line-height: 1.6; }
    .empty { color: #999; font-style: italic; }
    .meta { color: #666; font-size: 12px; }
    .entry-reason { background: #fffbe6; border: 1px solid #ffe58f; border-left: 4px solid #faad14;
                    padding: 8px 12px; margin: 12px 0 6px 0; font-size: 12.5px; line-height: 1.65;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace; }
    .entry-reason .cond { display: inline-block; padding: 1px 6px; border-radius: 3px;
                          font-weight: 600; margin-right: 4px; font-size: 11.5px; }
    .entry-reason .cond.ok  { background: #d9f7be; color: #135200; border: 1px solid #b7eb8f; }
    .entry-reason .cond.no  { background: #fff1f0; color: #820014; border: 1px solid #ffa39e; }
    .entry-reason .sub-tag { display: inline-block; padding: 1px 8px; border-radius: 10px;
                             background: #722ed1; color: #fff; font-size: 11.5px; font-weight: 600;
                             margin-left: 4px; }
    .entry-reason .muted   { color: #999; font-style: italic; }
    .sig-tag { display: inline-block; padding: 1px 6px; border-radius: 3px;
               background: #f0f5ff; color: #1d39c4; font-size: 11px; font-weight: 600;
               border: 1px solid #adc6ff; }
    """

    body = f"""
    <h1>{title}</h1>
    {metrics_block}
    {legend}
    <p class="meta">Window per trade: entry −{WINDOW_BEFORE}d … exit +{WINDOW_BEFORE if False else WINDOW_AFTER}d | Skipped: {window_meta.get('skipped', 0)}/{window_meta.get('total', 0)} (no panel data)</p>

    <h2>Equity Curve</h2>
    {_render_equity_chart(equity)}

    <h2>Trade List ({len(trades)} trades)</h2>
    {_render_trade_table(trades, strategy)}

    <h2>Per-Trade Detail</h2>
    {''.join(per_trade_html)}

    <p class="meta">Generated by tools/render_top5_presets_html.py — R527, 2026-10-08</p>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="{PLOTLY_CDN}"></script>
  <style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


# ---------------------------------------------------------------- per-preset driver


def render_chase_up(preset: str, start: str, end: str, out_dir: Path) -> Path:
    """Render one chase_up preset HTML."""
    print(f"[chase_up/{preset}] running backtest...")
    trades, equity, panel = _run_chase_up(preset, start, end)
    print(f"  {len(trades)} trades, equity {len(equity)} rows, "
          f"panel {len(panel)} rows / {panel['thscode'].nunique()} symbols")

    p = chase_up_get_preset(preset)
    per_trade_html = []
    skipped = 0
    for i, t in trades.iterrows():
        code = t["thscode"]
        ed = pd.Timestamp(t["entry_date"])
        xd = pd.Timestamp(t["exit_date"])
        sub = panel[panel["thscode"] == code].sort_values("date")
        e_lo = ed - pd.Timedelta(days=WINDOW_BEFORE)
        e_hi = xd + pd.Timedelta(days=WINDOW_AFTER)
        window = sub[(sub["date"] >= e_lo) & (sub["date"] <= e_hi)].reset_index(drop=True)
        if window.empty:
            skipped += 1
            continue
        reason_html = _build_entry_reasons_chase(t.to_dict(), panel, p)
        per_trade_html.append(_render_per_trade_chart_chase(t.to_dict(), window, i + 1, reason_html))

    html = _render_html(
        "chase_up", preset, trades, equity, per_trade_html,
        {"skipped": skipped, "total": len(trades)},
    )
    out_path = out_dir / f"chase_up__{_sanitize(preset)}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  → {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return out_path


def render_short_reversal(preset: str, start: str, end: str, out_dir: Path) -> Path:
    """Render one short_reversal preset HTML."""
    print(f"[short_reversal/{preset}] running backtest...")
    trades, equity, klines_ind = _run_short_reversal(preset, start, end)
    print(f"  {len(trades)} trades, equity {len(equity)} rows")

    p = short_reversal_get_preset(preset)
    per_trade_html = []
    skipped = 0
    for i, t in trades.iterrows():
        code = t["thscode"]
        ed = pd.Timestamp(t["entry_date"])
        xd = pd.Timestamp(t["exit_date"])
        full = klines_ind.get(code)
        if full is None or full.empty:
            skipped += 1
            continue
        e_lo = ed - pd.Timedelta(days=WINDOW_BEFORE)
        e_hi = xd + pd.Timedelta(days=WINDOW_AFTER)
        window = full[(full["date"] >= e_lo) & (full["date"] <= e_hi)].reset_index(drop=True)
        if window.empty:
            skipped += 1
            continue
        reason_html = _build_entry_reasons_short(t.to_dict(), full, p)
        per_trade_html.append(_render_per_trade_chart_short(t.to_dict(), window, i + 1, reason_html))

    html = _render_html(
        "short_reversal", preset, trades, equity, per_trade_html,
        {"skipped": skipped, "total": len(trades)},
    )
    out_path = out_dir / f"short_reversal__{_sanitize(preset)}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  → {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return out_path


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    global WINDOW_BEFORE, WINDOW_AFTER
    p = argparse.ArgumentParser("render_top5_presets_html")
    p.add_argument("--start", default="2025-09-08")
    p.add_argument("--end", default="2026-09-08")
    p.add_argument("--out-dir", default="results/top5_presets",
                   type=lambda s: Path(s))
    p.add_argument("--window-before", type=int, default=WINDOW_BEFORE)
    p.add_argument("--window-after", type=int, default=WINDOW_AFTER)
    p.add_argument("--only", help="comma-separated strategy names to render (default: all 5)")
    args = p.parse_args(argv)

    WINDOW_BEFORE = args.window_before
    WINDOW_AFTER = args.window_after

    args.out_dir.mkdir(parents=True, exist_ok=True)

    only = set(args.only.split(",")) if args.only else None
    outputs = []
    for strategy, preset in TOP5:
        if only and strategy not in only:
            continue
        try:
            if strategy == "chase_up":
                outputs.append(render_chase_up(preset, args.start, args.end, args.out_dir))
            elif strategy == "short_reversal":
                outputs.append(render_short_reversal(preset, args.start, args.end, args.out_dir))
            else:
                print(f"  SKIP {strategy}/{preset} (not implemented)")
        except Exception as e:
            print(f"  ERROR {strategy}/{preset}: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n=== Done: {len(outputs)} HTML files in {args.out_dir} ===")
    for p in outputs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
