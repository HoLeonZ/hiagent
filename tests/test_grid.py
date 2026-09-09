"""grid.run_grid 单维 TP 扫描输出 trades 数 / 资金 / 胜率。"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_reversal.grid import run_grid


def test_run_grid_returns_dataframe_with_tp_rows():
    # 使用空 tp_values → 仍返回 0 行 DataFrame
    import pandas as pd
    result = run_grid("v33_mainboard", [], Path("/tmp/no.db"), "2025-09-01", "2026-09-01")
    assert isinstance(result, pd.DataFrame)
    assert "tp_pct" in result.columns
    assert "trades" in result.columns
    assert "final_capital" in result.columns