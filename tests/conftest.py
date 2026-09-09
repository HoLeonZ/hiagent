"""共享 fixture：synthetic thscode 列表 + 临时 DuckDB。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


@pytest.fixture
def sample_thscodes() -> list[str]:
    """覆盖各前缀边界条件。"""
    return [
        "600000.SH",  # 沪主板
        "601318.SH",  # 沪主板
        "603000.SH",  # 沪主板
        "605999.SH",  # 沪主板
        "000001.SZ",  # 深主板
        "002415.SZ",  # 深主板
        "003000.SZ",  # 深主板
        "300750.SZ",  # 创业板（应排除）
        "301000.SZ",  # 创业板
        "688981.SH",  # 科创板（应排除）
        "689009.SH",  # 科创板
        "830799.BJ",  # 北交所（应排除）
        "832000.BJ",  # 北交所
        "123456.SH",  # 非法前缀（应排除）
    ]


@pytest.fixture
def temp_duckdb(tmp_path: Path, sample_thscodes: list[str]) -> Path:
    """建一张 v_daily 表，写入 sample_thscodes。"""
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    try:
        rows = ", ".join(f"('{c}', DATE '2025-01-01')" for c in sample_thscodes)
        con.execute(
            f"CREATE TABLE v_daily AS SELECT * FROM (VALUES {rows}) AS t(thscode, dt)"
        )
    finally:
        con.close()
    return db


@pytest.fixture
def exclude_txt(tmp_path: Path) -> Path:
    """黑名单文件：排除 600000.SH 和 002415.SZ。"""
    p = tmp_path / "exclude.txt"
    p.write_text("# comment\n600000.SH\n002415.SZ\n", encoding="utf-8")
    return p