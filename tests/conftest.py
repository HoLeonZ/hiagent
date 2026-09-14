"""共享 fixture：临时 DuckDB（带 v_daily 完整 schema）+ 黑名单 + 合成单股 panel。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest


SAMPLE_CODES = [
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
def sample_thscodes() -> list[str]:
    """覆盖各前缀边界条件。"""
    return list(SAMPLE_CODES)


@pytest.fixture
def temp_duckdb(tmp_path: Path, sample_thscodes: list[str]) -> Path:
    """建 v_daily 表（完整 schema：thscode/date/open/high/low/close/amount/volume）。

    每只代码在 2024-06-01 ~ 2025-12-31 期间每日 1 行 OHLCV 数据。
    """
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "CREATE TABLE v_daily ("
            "  thscode VARCHAR, date DATE,"
            "  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
            "  amount DOUBLE, volume DOUBLE"
            ")"
        )
        dates = pd.date_range("2024-06-01", "2025-12-31", freq="B")
        rows = []
        for code in sample_thscodes:
            for d in dates:
                base = 10.0 + (hash(code) % 100) / 10.0
                rows.append((code, d.date(), base, base + 0.5, base - 0.5,
                             base, 5e7, 1e6))
        con.executemany(
            "INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
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
def synthetic_single_stock_panel() -> pd.DataFrame:
    """200 个交易日 × 1 只股票，价格单调下行 + 满足 V5 cascade 条件。

    用于 Phase3V3Strategy 单股回测：
      - 后 100 日是单调下跌 → MA5<MA10<MA20<MA60 在末尾附近成立
      - 跌速 ~2%/日 → pct_chg 接近 -0.02 (但要 > 0, 所以方向反过来设计)
    """
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    rows = []
    base = 20.0
    for i, d in enumerate(dates):
        # 前 130 日温和上涨（累积让 MA60 形成 + 制造连阳段）
        if i < 130:
            price = base + 0.05 * i  # 累积涨幅 +6.5
        # 后 70 日阶梯式下跌（每日 +0.5% 后再 -3%）
        else:
            price = base + 0.05 * 130 - 0.03 * (i - 130) * 2
        open_p = price
        high_p = price + 0.3
        low_p = price - 0.3
        close_p = price
        rows.append({
            "thscode": "600000.SH",
            "date": d,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)
