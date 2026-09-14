"""选股范围：沪深主板 + 黑名单剔除 + as-of 过滤。

DuckDB 无历史成分表 → as-of 代理：剔除 asof_date 之后才上市的票。
严格的 HS300 / 中证 500 历史成分 as-of 标 P2（需新拉数据）。
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from short_reversal import ShortReversalError

# 沪深主板前缀
_SH_MAIN = ("60", "601", "603", "605")
_SZ_MAIN = ("000", "001", "002", "003")

# 默认 exclude 路径（与历史约定一致）
DEFAULT_EXCLUDE_PATH = Path(__file__).parent / "data" / "exclude_thscodes.txt"


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


def _load_exclude(exclude_path: Path | None) -> set[str]:
    path = Path(exclude_path) if exclude_path else DEFAULT_EXCLUDE_PATH
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_universe_asof(
    mode: str,
    asof_date: str,
    db_path: Path,
    exclude_path: Path | None = None,
) -> list[str]:
    """返回 asof_date 之前已上市 + 黑名单过滤 + mode 分类的代码列表。

    Args:
      mode: 'mainboard_only' | 'exclude_hs300_zhongtou_finance'
            （后者目前等同 mainboard_only；HS300/CSI500 历史成分表未建立）
      asof_date: 'YYYY-MM-DD' —— 剔除该日之后才上市/才有交易的票
      db_path: DuckDB 路径
      exclude_path: 黑名单文件路径（默认 data/exclude_thscodes.txt）

    Raises:
      ValueError: mode 未知
      ShortReversalError: DuckDB 读取失败
    """
    if mode not in ("mainboard_only", "exclude_hs300_zhongtou_finance"):
        raise ValueError(
            f"Unknown universe mode: {mode!r}. "
            f"Available: mainboard_only, exclude_hs300_zhongtou_finance"
        )

    excluded = _load_exclude(exclude_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT thscode FROM v_daily "
            "WHERE date <= ? ORDER BY thscode",
            [asof_date],
        ).fetchall()
    except duckdb.Error as e:
        raise ShortReversalError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()

    all_codes = [r[0] for r in rows]
    filtered = [
        c for c in all_codes
        if _is_main_board(c) and c not in excluded
    ]
    return sorted(filtered)
