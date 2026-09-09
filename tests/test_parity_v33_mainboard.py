"""v33 mainboard parity test — 新管线 trades 列表与 baseline 严格一致。"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "v33_mainboard_trades.json"


@pytest.mark.skipif(
    not os.environ.get("DNA_STRAT_DB"),
    reason="parity test 需要 DuckDB（DNA_STRAT_DB 环境变量）",
)
def test_parity_v33_mainboard_trades_match():
    from short_reversal.main import run_backtest

    db_path = Path(os.environ["DNA_STRAT_DB"])
    result = run_backtest("v33_mainboard", "2025-09-01", "2026-09-01", db_path)
    new_trades = result["trades"]

    with GOLDEN.open() as f:
        golden = json.load(f)
    old_trades = golden["trades"]

    assert len(new_trades) == len(old_trades), (
        f"trades 数不一致: new={len(new_trades)} vs old={len(old_trades)}"
    )

    diffs = []
    for new, old in zip(new_trades, old_trades):
        if new["thscode"] != old["thscode"]:
            diffs.append(("thscode", new["thscode"], old["thscode"]))
        if new["entry_date"][:10] != old["entry_date"][:10]:
            diffs.append(("entry_date", new["entry_date"], old["entry_date"]))
        if new["exit_date"][:10] != old["exit_date"][:10]:
            diffs.append(("exit_date", new["exit_date"], old["exit_date"]))
        if abs(float(new["entry_price"]) - float(old["entry_price"])) > 0.01:
            diffs.append(("entry_price", new["entry_price"], old["entry_price"]))
        if abs(float(new["exit_price"]) - float(old["exit_price"])) > 0.01:
            diffs.append(("exit_price", new["exit_price"], old["exit_price"]))
        if new["exit_reason"] != old["exit_reason"]:
            diffs.append(("exit_reason", new["exit_reason"], old["exit_reason"]))

    assert not diffs, f"parity 失败，差异样本: {diffs[:5]}"
