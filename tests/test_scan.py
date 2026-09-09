"""scan.run_scan 输出 JSON 字段完整。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from short_reversal.scan import run_scan


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    """最小 DuckDB：1 只票、60+ 日 K 线，价格单调下降 + 末尾小幅反弹。"""
    db = tmp_path / "scan.duckdb"
    csv_path = tmp_path / "_tmp.csv"

    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    rows = []
    for i, d in enumerate(dates):
        price = 10.0 - 0.01 * i if i < 65 else 10.0 - 0.01 * 65 + 0.03 * (i - 64)
        rows.append({
            "thscode": "600000.SH", "date": d,
            "open": price, "high": price + 0.05,
            "low": price - 0.05, "close": price, "turnover": 5e7,
        })
    csv = pd.DataFrame(rows).to_csv(index=False)
    # 必须先写文件再 execute(read_csv_auto)
    csv_path.write_text(csv, encoding="utf-8")

    con = duckdb.connect(str(db))
    try:
        con.execute(
            f"CREATE TABLE v_daily AS SELECT * FROM read_csv_auto('{csv_path}')"
        )
    finally:
        con.close()
    return db


def test_run_scan_returns_signal_dict(fake_db: Path):
    result = run_scan("v33_mainboard", "2025-04-15", fake_db)
    assert "signal_date" in result
    assert "next_trade_date_open" in result
    assert "signals" in result
    assert "count" in result
    assert isinstance(result["count"], int)
    assert result["count"] >= 0
    assert result["signal_date"] == "2025-04-15"