"""V3a runtime integration helper (2026-09-22, CLAUDE.md §3).

Resolves the preset-declared `price_source_for_signal` / `price_source_for_execution`
into actual column lookups against the dual-price panel.

This is the runtime complement to `dual_price.py` (loader). Strategies still
load their primary panel via v_daily / v_daily_qfq / v_daily_hfq (single close),
so the resolver accepts BOTH shapes:
  - dual panel: rows have adj_open/adj_high/adj_low/adj_close AND
    raw_open/raw_high/raw_low/raw_close
  - legacy panel: rows have open/high/low/close (single adjusted close)

For legacy panels, both signal and execution resolve to the single close column
(degraded mode). This preserves backwards compatibility while allowing the
declarations to take effect when the loader is switched to dual_price_panel.

Why a runtime helper instead of a flag in the loader?
  - Allows incremental migration: one strategy at a time can opt into the dual
    loader without breaking the others.
  - Tests can verify signal-vs-execution separation by passing a synthesized
    dual-price panel directly.
"""
from __future__ import annotations

import pandas as pd


# Column mapping per price_source_for_signal (CLAUDE.md §3).
# adj_* = forward-adjusted, for mathematical indicators.
# raw_* = raw, for SL/TP triggers and mark-to-market.
_SIGNAL_COL_MAP: dict[str, str] = {
    "adj_close": "adj_close",
    "raw_close": "raw_close",
    "close": "close",  # legacy: single close column
}

# Column mapping per price_source_for_execution (CLAUDE.md §3).
# Same convention: adj_* for indicators, raw_* for execution triggers.
_EXECUTION_COL_MAP: dict[str, str] = {
    "adj_close": "adj_close",
    "raw_close": "raw_close",
    "close": "close",  # legacy
}


def signal_close(panel_row: pd.Series, price_source_for_signal: str) -> float:
    """Resolve the closing price for SIGNAL computation (indicators).

    Fallback chain when declared source not in panel:
      adj_close requested → adj_close (skip) → close (skip raw_close, because
        raw_close 在 partial dual 场景下 ≠ adj semantics)
      raw_close requested → raw_close (skip) → close
      close requested → close
    """
    col = _SIGNAL_COL_MAP.get(price_source_for_signal, "close")
    if col in panel_row.index and not pd.isna(panel_row[col]):
        return float(panel_row[col])
    # Signal fallback: skip the OTHER family (avoid raw_close when signal
    # is supposed to use adj semantics — they're not interchangeable).
    if col == "adj_close":
        fallbacks = ("close",)
    elif col == "raw_close":
        fallbacks = ("close",)
    else:
        fallbacks = ("close",)
    for fallback in fallbacks:
        if fallback in panel_row.index and not pd.isna(panel_row[fallback]):
            return float(panel_row[fallback])
    raise KeyError(
        f"No close column found in panel_row for signal source={price_source_for_signal!r}; "
        f"available: {[c for c in panel_row.index if 'close' in c]}"
    )


def execution_close(panel_row: pd.Series, price_source_for_execution: str) -> float:
    """Resolve the closing price for EXECUTION triggers (SL/TP/mark-to-market).

    Same fallback rule as signal_close.
    """
    col = _EXECUTION_COL_MAP.get(price_source_for_execution, "close")
    if col in panel_row.index and not pd.isna(panel_row[col]):
        return float(panel_row[col])
    if col == "raw_close":
        fallbacks = ("close",)
    elif col == "adj_close":
        fallbacks = ("close",)
    else:
        fallbacks = ("close",)
    for fallback in fallbacks:
        if fallback in panel_row.index and not pd.isna(panel_row[fallback]):
            return float(panel_row[fallback])
    raise KeyError(
        f"No close column found in panel_row for execution source={price_source_for_execution!r}; "
        f"available: {[c for c in panel_row.index if 'close' in c]}"
    )


def execution_open(panel_row: pd.Series, price_source_for_execution: str) -> float:
    """Resolve the OPENING price for EXECUTION (T+1 entry fill, gap detection).

    Mirrors execution_close but for the open column.
    """
    base = price_source_for_execution
    # raw_* / adj_* prefix mapping
    if base == "raw_close":
        col = "raw_open"
    elif base == "adj_close":
        col = "adj_open"
    else:
        col = "open"
    if col in panel_row.index and not pd.isna(panel_row[col]):
        return float(panel_row[col])
    # §3 (audit 2026-10-15): **不得跨域回退** —— 与同文件的两个兄弟函数同规则。
    #
    # 此前这里是 `("raw_open", "adj_open", "open")`:当 raw_open 缺失时,会先落到
    # **adj_open**,也就是让**执行价**静默变成**复权价**。这直接违反 §3
    # ("ALWAYS use Raw Prices for evaluating limit order triggers, stop-losses, and
    # portfolio physical cash mark-to-market"),而且与 `execution_close` /
    # `signal_close` 明确写在注释里的规则**互相矛盾**:
    #   "skip the OTHER family ... they're not interchangeable"
    # 后果正是本仓库此前抓到的幻影成交:入场价被换成另一个价域而不留任何痕迹。
    # 现在缺 raw_open 就 fail-fast(与 `execution_close` 缺 close 时同样),不猜。
    for fallback in ("open",):
        if fallback in panel_row.index and not pd.isna(panel_row[fallback]):
            return float(panel_row[fallback])
    raise KeyError(
        f"No open column found in panel_row for execution source={base!r}; "
        f"available: {[c for c in panel_row.index if 'open' in c]}"
    )