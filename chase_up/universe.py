"""选股范围：沪深主板 + 黑名单剔除 (沿用 uptrend_pullback/universe.py 口径)。"""
from __future__ import annotations

from pathlib import Path

import duckdb

from chase_up import ChaseUpError

_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")

VALID_MODES = ("mainboard_only", "all_ex_bj")


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


def _is_a_share_ex_bj(code: str) -> bool:
    return code.endswith(".SH") or code.endswith(".SZ")


def _all_thscodes(db_path: Path) -> list[str]:
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
    """返回符合 mode 的 thscode 列表 (已剔除黑名单)。"""
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown universe mode: {mode!r}. Available: {', '.join(VALID_MODES)}"
        )

    try:
        all_codes = _all_thscodes(db_path)
    except duckdb.Error as e:
        raise ChaseUpError(f"DuckDB read failed: {e}") from e

    excluded = _load_exclude(exclude_path)
    pred = _is_main_board if mode == "mainboard_only" else _is_a_share_ex_bj

    return sorted(c for c in all_codes if pred(c) and c not in excluded)