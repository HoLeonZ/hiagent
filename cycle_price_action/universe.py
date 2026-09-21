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
    lookback: int = 60,
) -> set[str]:
    """Return thscodes meeting: history ≥ lookback AND avg turnover ≥ floor.

    Default lookback=60 matches the project's "Recent IPOs (< 60 trading days
    history) must not be selected" rule — codes with fewer than 60 unique
    trading dates in the panel cannot build a stable turnover baseline and
    are excluded by default.
    """
    counts = df.groupby("thscode")["date"].nunique()
    eligible_history = counts[counts >= lookback].index

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
