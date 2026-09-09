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


@pytest.fixture
def synthetic_panel() -> "pd.DataFrame":
    """100 个交易日 × 2 只股票，价格单调 + 严格按时间排序。"""
    import pandas as pd
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    rows = []
    for code in ("600000.SH", "000001.SZ"):
        # 第一只单调上涨，第二只单调下跌，构造可验证的指标
        base = 10.0 if code == "600000.SH" else 20.0
        slope = 0.05 if code == "600000.SH" else -0.05
        for i, d in enumerate(dates):
            price = base + slope * i
            rows.append({
                "thscode": code, "date": d,
                "open": price, "high": price + 0.1,
                "low": price - 0.1, "close": price,
                "turnover": 1e7,
            })
    return pd.DataFrame(rows)