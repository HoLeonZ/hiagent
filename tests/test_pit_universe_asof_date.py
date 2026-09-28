"""§3 PIT Mandate: chase_up + uptrend_pullback load_universe 支持 asof_date 参数。

CLAUDE.md §3:
  - NEVER hardcode universe constituents.
  - Always query universe components via PIT API.
  - Delisted assets must remain in simulation until physical delisting date.

本文件目的:
  - 验证 chase_up + uptrend_pullback 的 load_universe 接受 asof_date 参数
    并按 `WHERE date <= asof_date` 过滤 (PIT 兼容)。
  - 验证 BACK COMPAT: 不传 asof_date 时维持当前行为 (post-hoc 全集),
    这样老的 baseline / 调用代码不会因此报错。

对照: short_reversal.universe.load_universe_asof 已经实现此模式 (asof_date
为 2nd positional param, SQL 含 WHERE date <= ?)。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from chase_up.universe import load_universe as chase_load_universe
from uptrend_pullback.universe import load_universe as up_load_universe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_duckdb(db_path: Path) -> None:
    """建 v_daily: 已知 mainboard + 创业板/科创板/北交所代码,
    时间窗 2024-06-01 ~ 2025-12-31, 便于 asof 测试."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE v_daily ("
            "  thscode VARCHAR, date DATE,"
            "  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
            "  amount DOUBLE, volume DOUBLE)"
        )
        # 早期上市 (2024-06-01 起即有数据)
        early_codes = ["600000.SH", "601318.SH", "000001.SZ"]
        # 后期上市 (2025-06-01 才出现 → 模拟新 IPO / 退市后再上市)
        late_codes = ["603000.SH", "002415.SZ"]
        dates = pd.date_range("2024-06-01", "2025-12-31", freq="B")
        rows = []
        for code in early_codes:
            for d in dates:
                rows.append((code, d.date(), 10.0, 10.5, 9.5, 10.0, 5e7, 1e6))
        # late_codes 只在 2025-06-01 之后有数据
        late_dates = pd.date_range("2025-06-01", "2025-12-31", freq="B")
        for code in late_codes:
            for d in late_dates:
                rows.append((code, d.date(), 10.0, 10.5, 9.5, 10.0, 5e7, 1e6))
        con.executemany(
            "INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    finally:
        con.close()


@pytest.fixture
def asof_duckdb(tmp_path: Path) -> Path:
    db = tmp_path / "test_asof.duckdb"
    _build_duckdb(db)
    return db


# ---------------------------------------------------------------------------
# PIT 路径: asof_date 过滤
# ---------------------------------------------------------------------------


def test_chase_up_load_universe_accepts_asof_date(asof_duckdb: Path) -> None:
    """§3 PIT Mandate: chase_up.load_universe 接受 asof_date 参数,
    仅返回 MAX(date) <= asof_date 的 thscode."""
    # 2025-04-01 之前无 late_codes 数据 → 不应返回 603000.SH / 002415.SZ
    codes = set(chase_load_universe(
        "mainboard_only", asof_duckdb, exclude_path=None, asof_date="2025-04-01"
    ))
    assert "603000.SH" not in codes, (
        "PIT 过滤失效: asof=2025-04-01 时不应包含 2025-06 才上市的 603000.SH"
    )
    assert "002415.SZ" not in codes, (
        "PIT 过滤失效: asof=2025-04-01 时不应包含 2025-06 才上市的 002415.SZ"
    )
    # early_codes 在 2024-06 就有数据, 应保留
    assert "600000.SH" in codes
    assert "601318.SH" in codes
    assert "000001.SZ" in codes


def test_uptrend_pullback_load_universe_accepts_asof_date(asof_duckdb: Path) -> None:
    """§3 PIT Mandate: uptrend_pullback.load_universe 接受 asof_date 参数."""
    codes = set(up_load_universe(
        "mainboard_only", asof_duckdb, exclude_path=None, asof_date="2025-04-01"
    ))
    assert "603000.SH" not in codes
    assert "002415.SZ" not in codes
    assert "600000.SH" in codes


def test_chase_up_load_universe_asof_with_explicit_kwarg(asof_duckdb: Path) -> None:
    """asof_date 作为关键字参数传入,验证签名兼容."""
    # 关键字传入
    codes = chase_load_universe(
        "mainboard_only", asof_duckdb, asof_date="2025-04-01"
    )
    assert isinstance(codes, list)


def test_chase_up_load_universe_asof_at_future_date(asof_duckdb: Path) -> None:
    """asof_date = 数据最后日期 → 返回全量 (active at end of period)."""
    codes = set(chase_load_universe(
        "mainboard_only", asof_duckdb, exclude_path=None, asof_date="2025-12-31"
    ))
    # 所有早期+后期代码都应在 2025-12-31 当日仍活跃
    assert {"600000.SH", "601318.SH", "603000.SH", "000001.SZ", "002415.SZ"}.issubset(codes)


# ---------------------------------------------------------------------------
# Backwards compatibility: 不传 asof_date 时维持 post-hoc 全集
# ---------------------------------------------------------------------------


def test_back_compat_chase_up_no_asof_date(asof_duckdb: Path) -> None:
    """BACK COMPAT: 不传 asof_date 时维持当前 (post-hoc 全集) 行为,
    允许现存 18 个 call site 不报错.

    现状: chase_up.load_universe(mode, db_path, exclude_path=None) → 返回全量
    GREEN 修复后: 不传 asof_date 应等价于当前行为 (post-hoc 全集)。
    # 但未来 asof_date=None 时仍可加 Warning → 不强制抛错。
    """
    # Should not raise
    codes = chase_load_universe("mainboard_only", asof_duckdb)
    # 不传 asof_date → post-hoc 全集 (含 late_codes)
    assert "603000.SH" in codes, (
        "BACK COMPAT 失败: 不传 asof_date 时必须维持 post-hoc 全集行为"
    )
    assert "002415.SZ" in codes


def test_back_compat_uptrend_pullback_no_asof_date(asof_duckdb: Path) -> None:
    """BACK COMPAT for uptrend_pullback."""
    codes = up_load_universe("mainboard_only", asof_duckdb)
    assert "603000.SH" in codes
    assert "002415.SZ" in codes


def test_back_compat_explicit_none(asof_duckdb: Path) -> None:
    """BACK COMPAT: asof_date=None 等价于不传."""
    codes_none = chase_load_universe(
        "mainboard_only", asof_duckdb, asof_date=None
    )
    codes_default = chase_load_universe("mainboard_only", asof_duckdb)
    assert set(codes_none) == set(codes_default), (
        "asof_date=None 必须等于不传 asof_date,不允许静默改变后行为"
    )