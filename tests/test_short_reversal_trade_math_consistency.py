"""short_reversal Layout B trade-direction 一致性 (CLAUDE.md §3 trade-level 锚定).

Layout B strategy 是 SHORT: SL 当价格 up, TP 当价格 down。
phantom TP/SL = exit_price 错位 (例如本应 raw_open, 实际 clamp 到 adj_open)。

CSV 不含 entry_date/exit_date, 无法做 raw_open DB JOIN 比对。
但可以验证更弱的不变量:
  - SL exit > entry (short: 价格 up 触发 SL)
  - TP exit < entry (short: 价格 down 触发 TP)

direction-violation = phantom 信号 (策略不该 fire SL/TP 但 exit_price 方向错误)。

跑 3 个 csv preset (v35 + v36 + v38) — 任何 trade direction-violation 必须 FAIL。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.presets import get_preset  # noqa: E402

DBG_TOL = 0.0001  # 1bp tolerance for floating point

PRESETS_WITH_CSV = [
    "v35_agg_pctchg_04_09",
    "v36_d_converge",
    "v38_a_relaxed",
    "v39_pctchg_03_10",
]


@pytest.mark.parametrize("preset_name", PRESETS_WITH_CSV)
def test_short_reversal_exit_direction_matches_short_semantics(preset_name: str):
    """short_reversal exit direction 必须符合 SHORT 语义 — 防 phantom 错位.

    Layout B 是 SHORT strategy:
      - SL: 价格 up 触发 → exit > entry
      - TP: 价格 down 触发 → exit < entry
      - time: 持有到期 → exit ≈ close (无方向要求)

    任何 direction-violation 意味着 exit_price 错位 (例如 fire SL 但 exit < entry
    说明可能 clamp 到 adj_open 或类似 phantom)。
    """
    csv_path = ROOT / "short_reversal" / "results" / f"{preset_name}_trades.csv"
    if not csv_path.exists():
        pytest.skip(f"{preset_name} csv not generated yet — backlog")

    p = get_preset(preset_name)
    sl_pct, tp_pct = p["sl_pct"], p["tp_pct"]
    trades = pd.read_csv(csv_path)
    assert not trades.empty

    violations = []
    for _, t in trades.iterrows():
        ep = float(t["entry_price"])
        xp = float(t["exit_price"])
        reason = t["exit_reason"]
        if reason == "SL":
            # SHORT SL: xp > ep × (1 + sl_pct - tolerance)
            if xp < ep * (1 + sl_pct - DBG_TOL):
                violations.append(
                    f"SL direction-violation thscode={t['thscode']} ep={ep:.4f} xp={xp:.4f}"
                )
        elif reason == "TP":
            # SHORT TP: xp < ep × (1 - tp_pct + tolerance)
            if xp > ep * (1 - tp_pct + DBG_TOL):
                violations.append(
                    f"TP direction-violation thscode={t['thscode']} ep={ep:.4f} xp={xp:.4f}"
                )

    assert not violations, (
        f"{preset_name} phantom signal: {len(violations)}/{len(trades)} trades "
        f"violate SHORT direction semantics. Examples: {violations[:3]}"
    )


def test_short_reversal_trade_math_consistency_summary():
    """汇总所有有 csv 的 preset — 0 direction-violation 证明 Layout B raw-only。

    这个测试是 contract test 的运行时验证锚点 — 任何 preset 添加新 csv 后,
    自动纳入审计。
    """
    results_dir = ROOT / "short_reversal" / "results"
    csvs = sorted(results_dir.glob("*_trades.csv"))
    if not csvs:
        pytest.skip("No short_reversal trades.csv generated yet")

    total_trades = 0
    total_violations = 0
    for csv_path in csvs:
        preset_name = csv_path.stem.replace("_trades", "")
        p = get_preset(preset_name)
        trades = pd.read_csv(csv_path)
        if trades.empty:
            continue
        sl_pct, tp_pct = p["sl_pct"], p["tp_pct"]
        for _, t in trades.iterrows():
            ep = float(t["entry_price"])
            xp = float(t["exit_price"])
            reason = t["exit_reason"]
            if reason == "SL" and xp < ep * (1 + sl_pct - DBG_TOL):
                total_violations += 1
            elif reason == "TP" and xp > ep * (1 - tp_pct + DBG_TOL):
                total_violations += 1
        total_trades += len(trades)

    assert total_violations == 0, (
        f"short_reversal Layout B invariant violated: "
        f"{total_violations}/{total_trades} phantom-direction trades"
    )