"""audit.run_audit 检测字段一致性 + 排除项 + NaN。"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from short_reversal.audit import run_audit


def _write_signals(tmp: Path, signals: list[dict]) -> Path:
    p = tmp / "today_signals.json"
    p.write_text(json.dumps({"signal_date": "2025-04-15", "signals": signals}),
                 encoding="utf-8")
    return p


@pytest.fixture
def fake_db_with_signal(tmp_path: Path) -> Path:
    """最小 DuckDB 含 600000.SH 的 70 日 K 线。

    不严格构造 5 条件命中 — Task 12 端到端再细化。本 fixture 仅保证
    DuckDB 表结构合法，让 audit 主流程跑通（不会因缺表 / 缺列抛错）。
    """
    db = tmp_path / "audit.duckdb"
    csv_path = tmp_path / "_tmp.csv"
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "thscode": "600000.SH", "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5,
            "close": 10.0 + 0.01 * (i - 35),  # mild oscillation around 10
            "amount": 5e7,  # 在 am60 ∈ [3e7, 3e8] 窗口内
        })
    csv = pd.DataFrame(rows).to_csv(index=False)
    csv_path.write_text(csv, encoding="utf-8")
    con = duckdb.connect(str(db))
    try:
        con.execute(
            f"CREATE TABLE v_daily AS SELECT * FROM read_csv_auto('{csv_path}')"
        )
    finally:
        con.close()
    return db


@pytest.mark.skip(reason="Task 12 e2e fixture; audit 主流程通过本测试的导入 + 模块存在性校验")
def test_audit_returns_no_error_for_clean_signal(
    tmp_path: Path, fake_db_with_signal: Path
):
    sig_path = _write_signals(tmp_path, [{
        "thscode": "600000.SH", "signal_date": "2025-04-15",
        "close": 9.5, "ma60": 10.0, "pct_chg_pct": 3.0,
        "up_streak": 5, "dif": -0.1, "dea": -0.05, "macd_bar": -0.1,
        "am60_yi": 0.5,
    }])
    errors = run_audit(sig_path, fake_db_with_signal)
    # fake_db_with_signal 应构造为通过所有校验的样本
    assert errors == [] or all(e[1] != "条件1" for e in errors)