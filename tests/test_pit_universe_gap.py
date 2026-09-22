"""§3 PIT Mandate RED tests: chase_up + uptrend_pullback load_universe 缺 asof_date.

CLAUDE.md §3: "Never hardcode universe constituents. Always query universe
components via a PIT API: get_universe('SP500', as_of_time). Delisted assets
must remain in the simulation until their physical delisting date."

当前状态:
- short_reversal.universe.load_universe_asof  → PIT-correct ✓
- cycle_price_action.data_feed.load_universe_data → PIT-correct (用 MAX(date) >= end 过滤) ✓
- chase_up.universe.load_universe → 仅返回全量代码, 无 asof_date 参数 ✗
- uptrend_pullback.universe.load_universe → 仅返回全量代码, 无 asof_date 参数 ✗

后果: 模拟 2025-06-01 ~ 2025-12-31 时, universe 包含 2025-01 已经退市的股票
(在 backtest 逻辑上不会成交, 但 universe 计数虚高, 且 wf_sweep 报告里
"tested N stocks" 数字夸大). 这是 §3 PIT Mandate gap, 应作为 follow-up 工单.

本测试当前 RED: 标记 gap 存在, GREEN 需要为 chase_up/uptrend_pullback 的
load_universe 增加 asof_date 参数 + 调用方 (walkforward / backtrader_engine /
sweep 等) 同步传入。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from chase_up.universe import load_universe as chase_load_universe
from uptrend_pullback.universe import load_universe as up_load_universe


def _build_duckdb_with_delisted(db_path: Path, delisted_code: str = "600000.SH") -> None:
    """建 v_daily: 600000.SH 在 2025-01-15 之后无数据 (模拟退市),
    其他代码延续到 2025-12-31。"""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE v_daily ("
            "  thscode VARCHAR, date DATE,"
            "  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
            "  amount DOUBLE, volume DOUBLE)"
        )
        # 600000.SH: 2024-06-01 ~ 2025-01-15 (退市)
        delisted_dates = pd.date_range("2024-06-01", "2025-01-15", freq="B")
        rows = [
            (delisted_code, d.date(), 10.0, 10.5, 9.5, 10.0, 5e7, 1e6)
            for d in delisted_dates
        ]
        # 其他 mainboard 代码: 2024-06-01 ~ 2025-12-31 (正常)
        other_codes = ["601318.SH", "603000.SH", "000001.SZ", "002415.SZ"]
        active_dates = pd.date_range("2024-06-01", "2025-12-31", freq="B")
        for code in other_codes:
            for d in active_dates:
                rows.append((code, d.date(), 10.0, 10.5, 9.5, 10.0, 5e7, 1e6))
        con.executemany("INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        con.close()


@pytest.fixture
def duckdb_with_delisting(tmp_path: Path) -> Path:
    db = tmp_path / "test_delisting.duckdb"
    _build_duckdb_with_delisted(db)
    return db


def test_chase_up_load_universe_accepts_asof_parameter(duckdb_with_delisting: Path) -> None:
    """§3 PIT Mandate: chase_up.load_universe 必须接受 asof_date 参数。

    当前 RED: chase_up.load_universe 签名是 (mode, db_path, exclude_path=None),
    缺失 asof_date → PIT 不可能。
    """
    # Should not raise TypeError when asof_date is passed
    codes = chase_load_universe(
        "mainboard_only", duckdb_with_delisting, asof_date="2025-06-01"
    )
    assert "600000.SH" not in codes, (
        "退市票 (2025-01-15 之后无数据) 不应出现在 2025-06-01 asof 的 universe 里"
    )


def test_uptrend_pullback_load_universe_accepts_asof_parameter(
    duckdb_with_delisting: Path,
) -> None:
    """§3 PIT Mandate: uptrend_pullback.load_universe 必须接受 asof_date 参数。"""
    codes = up_load_universe(
        "mainboard_only", duckdb_with_delisting, asof_date="2025-06-01"
    )
    assert "600000.SH" not in codes


def test_chase_up_load_universe_currently_returns_delisted(
    duckdb_with_delisting: Path,
) -> None:
    """CAPTURE CURRENT GAP: 当前 chase_up.load_universe 返回包含退市票。

    一旦 chase_up 增加 asof_date 参数, 本测试需要被替换 (而非修复):
    即不带 asof_date 时仍可调用 (返回全集) 或抛 TypeError,
    但带 asof_date 时正确过滤。本测试只断言当前 (RED) 行为以锁定 gap。
    """
    # 当前接口调用: 不传 asof_date, 期望返回全集 (含退市票)
    try:
        codes = chase_load_universe("mainboard_only", duckdb_with_delisting)
        # Gap 证据: 退市票被错误包含
        assert "600000.SH" in codes, (
            "GAP CAPTURED: chase_up load_universe 返回退市票 600000.SH, "
            "§3 PIT Mandate 未落地"
        )
    except TypeError:
        # 已经修过 (GREEN 路径): 接口已变 → skip
        pytest.skip("chase_up load_universe 接口已升级为 PIT, 本测试已 superseded")


def test_uptrend_pullback_load_universe_currently_returns_delisted(
    duckdb_with_delisting: Path,
) -> None:
    """CAPTURE CURRENT GAP (RED → superseded by GREEN)."""
    try:
        codes = up_load_universe("mainboard_only", duckdb_with_delisting)
        assert "600000.SH" in codes, (
            "GAP CAPTURED: uptrend_pullback load_universe 返回退市票, §3 PIT 未落地"
        )
    except TypeError:
        pytest.skip("uptrend_pullback load_universe 接口已升级为 PIT")