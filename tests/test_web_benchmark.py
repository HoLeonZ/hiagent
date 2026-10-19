"""基准序列与 harness 的标量版必须一致（否则界面与门禁会互相矛盾）。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from web.benchmark import BENCHMARK_LABEL, benchmark_series

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"
START, END = "2024-01-02", "2026-10-16"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


def test_label_does_not_pretend_to_be_an_index():
    """本仓库没有指数数据，标签就不能让人以为是沪深300。"""
    assert "指数" not in BENCHMARK_LABEL or "非指数" in BENCHMARK_LABEL
    assert "等权" in BENCHMARK_LABEL


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_series_starts_at_one_and_is_monotone_in_date():
    s = benchmark_series(_db(), START, END)
    assert s, "基准序列不该为空"
    assert s[0]["value"] == pytest.approx(1.0), "等权买入持有的起点净值应为 1.0"
    dates = [r["date"] for r in s]
    assert dates == sorted(dates), "日期必须单调递增"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_series_cagr_equals_the_harness_scalar_benchmark():
    """**耦合不变量**：序列末值推出的 CAGR 必须等于 harness 的标量版。

    没有这条，平台与门禁会各自演进、给出互相矛盾的"基准收益"。
    """
    from tools.live.compare_ensembles import benchmark_cagr

    s = benchmark_series(_db(), START, END)
    years = (__import__("pandas").Timestamp(END) - __import__("pandas").Timestamp(START)).days / 365.25
    series_cagr = s[-1]["value"] ** (1.0 / years) - 1.0
    scalar_cagr = benchmark_cagr(_db(), START, END)
    assert series_cagr == pytest.approx(scalar_cagr, rel=1e-3), (
        f"序列版 CAGR={series_cagr:.6f} vs 标量版 {scalar_cagr:.6f} —— "
        "两条实现已漂移，界面与门禁会互相矛盾"
    )
