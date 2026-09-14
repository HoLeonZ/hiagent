"""universe.load_universe_asof() 行为覆盖。"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_reversal.universe import load_universe_asof


EXPECTED_MAINBOARD = {
    "600000.SH", "601318.SH", "603000.SH", "605999.SH",
    "000001.SZ", "002415.SZ", "003000.SZ",
}


def test_mainboard_only_keeps_mainboard(temp_duckdb: Path):
    codes = load_universe_asof("mainboard_only", "2025-12-31", temp_duckdb)
    assert set(codes) == EXPECTED_MAINBOARD


def test_mainboard_only_excludes_chinext_star_bj(temp_duckdb: Path):
    codes = set(load_universe_asof("mainboard_only", "2025-12-31", temp_duckdb))
    assert "300750.SZ" not in codes  # 创业板
    assert "688981.SH" not in codes  # 科创板
    assert "830799.BJ" not in codes  # 北交所
    assert "123456.SH" not in codes  # 非法前缀


def test_mainboard_only_is_sorted(temp_duckdb: Path):
    codes = load_universe_asof("mainboard_only", "2025-12-31", temp_duckdb)
    assert codes == sorted(codes)


def test_exclude_txt_removes_listed(temp_duckdb: Path, exclude_txt: Path):
    codes = set(load_universe_asof(
        "exclude_hs300_zhongtou_finance", "2025-12-31", temp_duckdb, exclude_txt
    ))
    assert "600000.SH" not in codes
    assert "002415.SZ" not in codes


def test_unknown_mode_raises(temp_duckdb: Path):
    with pytest.raises(ValueError, match="Unknown universe mode"):
        load_universe_asof("nonsense", "2025-12-31", temp_duckdb)


def test_asof_filters_future_ipo(temp_duckdb: Path):
    """asof_date 太早 → 应返回空（所有代码都是 2024-06 之后才在 DB 出现）。"""
    codes = load_universe_asof("mainboard_only", "2020-01-01", temp_duckdb)
    assert codes == []


def test_asof_at_first_date_returns_all(temp_duckdb: Path):
    """asof_date = 第一条数据日期 → 全量返回。"""
    codes = load_universe_asof("mainboard_only", "2024-06-03", temp_duckdb)
    assert len(codes) == len(EXPECTED_MAINBOARD)


def test_asof_with_default_exclude_path_works(tmp_path: Path, sample_thscodes):
    """不传 exclude_path → 走默认路径（不存在则忽略），不应抛异常。"""
    # 创建临时 DuckDB 但不带默认 exclude 文件
    import duckdb
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
            "  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
            "  amount DOUBLE, volume DOUBLE)"
        )
        rows = [(c, "2025-01-01", 10.0, 10.5, 9.5, 10.0, 5e7, 1e6)
                for c in sample_thscodes]
        con.executemany(
            "INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    finally:
        con.close()
    # 不传 exclude_path
    codes = load_universe_asof("mainboard_only", "2025-12-31", db)
    assert "600000.SH" in codes  # 黑名单文件不存在 → 不过滤
