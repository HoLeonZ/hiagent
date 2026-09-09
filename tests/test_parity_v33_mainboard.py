"""v33 mainboard parity test — 新管线 trades 列表与 baseline 严格一致。

此测试需要 DuckDB 在环境变量 DNA_STRAT_DB 指定的位置可用，
且 main.py 已实现。Task 12 完成后再 enable。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "v33_mainboard_trades.json"


@pytest.mark.skipif(
    not os.environ.get("DNA_STRAT_DB"),
    reason="parity test 需要 DuckDB（DNA_STRAT_DB 环境变量）",
)
def test_parity_v33_mainboard_trades_match():
    from short_reversal.main import run_backtest  # noqa
    # 实际断言在 Task 12 补全；此处先确保 golden 文件可读
    with GOLDEN.open() as f:
        data = json.load(f)
    assert "trades" in data
    assert len(data["trades"]) > 0