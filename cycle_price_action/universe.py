"""Main-board universe filter — pure logic, no I/O except where tests need it."""
from __future__ import annotations

import pandas as pd


def is_main_board(thscode: str) -> bool:
    """True for Shanghai (6xxxxx.SH) or Shenzhen (000xxx/001xxx/002xxx/003xxx.SZ).

    Excludes ChiNext (300xxx/301xxx), STAR (688xxx/689xxx), BSE (8xxxxx).
    """
    if not isinstance(thscode, str) or "." not in thscode:
        return False
    code, suffix = thscode.rsplit(".", 1)
    if suffix not in ("SH", "SZ"):
        return False
    if suffix == "SH":
        return (
            code.isdigit()
            and len(code) == 6
            and code.startswith("6")
            and not code.startswith("688")
            and not code.startswith("689")
        )
    return code.isdigit() and len(code) == 6 and (
        code.startswith("000")
        or code.startswith("001")
        or code.startswith("002")
        or code.startswith("003")
    )


def apply_liquidity_filter(
    df: pd.DataFrame,
    min_avg_turnover: float = 5e7,
    min_history_days: int = 60,
) -> set[str]:
    """Return thscodes meeting: history ≥ `min_history_days` AND avg turnover ≥ floor.

    ⚠️⚠️ **2026-10-19 (§13.107) 本函数的描述与实现长期不符 —— 两处。**
    * 参数原名 `lookback` —— 它**不是一个回看窗口**, 实现里用作
      `counts[counts >= lookback]` = 「**面板里至少有这么多个不同交易日**」的**入场门槛**。
      ⇒ 名不副实, 已改名 `min_history_days`。("Recent IPOs (< 60 trading days history)
      must not be selected" 这条**规则**是真的, 只是"lookback"这个词把它说成了窗口。)
    * 周转额用的是 `df.groupby("thscode")["amount"].mean()` ——
      **对 `df` 里**全部行的均值, **没有 `rolling`、也没有"60 天"**。
      而 `data_feed.py` 传进来的那个面板**没有日期边界** (注释自称 "needs full history")
      ⇒ 实际是**全历史均值**。§13.27 记过这一点; 本函数此前**没有任何地方说清**。
    ⇒ **"60d rolling mean of amount" 这个说法从未成立过**
      (`tests/test_cycle_survivorship_bias.py` 的两处描述已一并更正)。

    ⚠️ 口径仍未定 (**§1 要求 as-of**: "as-of 当日往前滚动 60 日" vs "as-of 之前全部历史"),
    ⇒ §13.27 的处置是**登记不修** (改它属结果变更, 且口径未决)。**本函数今天的行为一字未动。**
    """
    counts = df.groupby("thscode")["date"].nunique()
    eligible_history = counts[counts >= min_history_days].index

    avg_turn = (
        df.groupby("thscode")["amount"].mean()
        if "amount" in df.columns
        else pd.Series(dtype=float)
    )
    eligible_liquidity = avg_turn[avg_turn >= min_avg_turnover].index

    return set(eligible_history) & set(eligible_liquidity)


def is_excluded_status(thscode: str, excluded_set: set[str] | None) -> bool:
    """True if thscode is in excluded_set (exact) or matches a wildcard tag prefix.

    A wildcard tag ends with `*` and matches any thscode starting with the
    preceding prefix (e.g. `ST/*` matches `ST华谊`). Empty/None excluded_set
    is a no-op (returns False).
    """
    if not excluded_set:
        return False
    if thscode in excluded_set:
        return True
    for tag in excluded_set:
        if tag.endswith("*") and thscode.startswith(tag[:-1]):
            return True
    return False
