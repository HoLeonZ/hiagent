"""选股范围：沪深主板 + 黑名单剔除。"""
from __future__ import annotations

from pathlib import Path
import duckdb


_MAIN_BOARD_SH = ("60", "601", "603", "605")  # SH 主板前缀
_MAIN_BOARD_SZ = ("000", "001", "002")         # SZ 主板前缀（含中小）


def _is_main_board(thscode: str) -> bool:
    if thscode.endswith(".BJ"):
        return False
    if thscode.endswith(".SH"):
        body = thscode.split(".", 1)[0]
        return any(body.startswith(p) for p in _MAIN_BOARD_SH)
    if thscode.endswith(".SZ"):
        body = thscode.split(".", 1)[0]
        return any(body.startswith(p) for p in _MAIN_BOARD_SZ)
    return False


def _all_thscodes_from_duckdb(db_path: Path) -> list[str]:
    """直接从 v_daily_qfq 抓 DISTINCT thscode（绕过空的 dim_symbol/v_symbol）。"""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT thscode FROM v_daily_qfq ORDER BY thscode"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _load_exclude(exclude_path: Path) -> set[str]:
    if not exclude_path.exists():
        return set()
    return {
        line.strip()
        for line in exclude_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_universe(*, db_path: str | Path, exclude_path: str | Path) -> list[str]:
    """返回沪深主板 thscode 列表（已剔除黑名单）。"""
    db = Path(db_path)
    exc = Path(exclude_path)
    all_codes = _all_thscodes_from_duckdb(db)
    excluded = _load_exclude(exc)
    return sorted(c for c in all_codes if _is_main_board(c) and c not in excluded)
