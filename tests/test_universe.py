"""universe.load_universe() 覆盖各 mode + 黑名单。"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_reversal.universe import load_universe


EXPECTED_MAINBOARD = {
    "600000.SH", "601318.SH", "603000.SH", "605999.SH",
    "000001.SZ", "002415.SZ", "003000.SZ",
}


def test_mainboard_only_keeps_mainboard(temp_duckdb: Path):
    codes = load_universe("mainboard_only", temp_duckdb)
    assert set(codes) == EXPECTED_MAINBOARD


def test_mainboard_only_excludes_chinext_star_bj(temp_duckdb: Path):
    codes = set(load_universe("mainboard_only", temp_duckdb))
    # 创业板/科创板/北交所/非法前缀全部剔除
    assert "300750.SZ" not in codes
    assert "301000.SZ" not in codes
    assert "688981.SH" not in codes
    assert "689009.SH" not in codes
    assert "830799.BJ" not in codes
    assert "123456.SH" not in codes


def test_mainboard_only_is_sorted(temp_duckdb: Path):
    codes = load_universe("mainboard_only", temp_duckdb)
    assert codes == sorted(codes)


def test_exclude_hs300_removes_listed(temp_duckdb: Path, exclude_txt: Path):
    # exclude_txt 排除了 600000.SH 和 002415.SZ
    codes = set(load_universe("exclude_hs300_zhongtou_finance", temp_duckdb, exclude_txt))
    assert "600000.SH" not in codes
    assert "002415.SZ" not in codes


def test_exclude_unknown_mode_raises(temp_duckdb: Path):
    with pytest.raises(ValueError, match="Unknown universe mode"):
        load_universe("nonsense", temp_duckdb)


def test_exclude_path_optional(temp_duckdb: Path):
    """exclude_hs300_zhongtou_finance 模式允许 exclude_path=None（HS300/CSI500/finance 暂未注入）。"""
    codes = load_universe("exclude_hs300_zhongtou_finance", temp_duckdb, None)
    # 此 mode 起步 = mainboard_only，无黑名单则与 mainboard_only 一致
    assert set(codes) == EXPECTED_MAINBOARD