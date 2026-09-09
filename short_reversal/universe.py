"""选股范围：沪深主板 + 黑名单剔除。

mode:
  mainboard_only                → 仅沪深主板（SH 60/601/603/605 + SZ 000/001/002/003）
  exclude_hs300_zhongtou_finance → 沪深主板 + 剔除 HS300/CSI500/金融板块（保留接口位）
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import duckdb

from short_reversal import ShortReversalError

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")


def _is_main_board(code: str) -> bool:
    if code.endswith(".BJ"):
        return False
    if code.endswith(".SH"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SH_MAIN)
    if code.endswith(".SZ"):
        body = code.split(".", 1)[0]
        return any(body.startswith(p) for p in _SZ_MAIN)
    return False


def _all_thscodes_from_duckdb(db_path: Path) -> list[str]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT thscode FROM v_daily ORDER BY thscode"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _load_exclude(exclude_path: Path | None) -> set[str]:
    if exclude_path is None or not Path(exclude_path).exists():
        return set()
    return {
        line.strip()
        for line in Path(exclude_path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_universe(
    mode: str,
    db_path: Path,
    exclude_path: Path | None = None,
) -> list[str]:
    """返回 thscode 列表（已按 mode 过滤 + 剔除黑名单）。"""
    if mode not in ("mainboard_only", "exclude_hs300_zhongtou_finance"):
        raise ValueError(
            f"Unknown universe mode: {mode!r}. "
            f"Available: mainboard_only, exclude_hs300_zhongtou_finance"
        )

    try:
        all_codes = _all_thscodes_from_duckdb(db_path)
    except duckdb.Error as e:
        raise ShortReversalError(f"DuckDB read failed: {e}") from e

    excluded = _load_exclude(exclude_path)

    filtered = [c for c in all_codes if _is_main_board(c) and c not in excluded]
    return sorted(filtered)