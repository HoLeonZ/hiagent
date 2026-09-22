"""Regenerate chase_up golden baselines after V3a+ dual-price entry fix.

V3a+ (2026-09-22, CLAUDE.md §3): chase_up/portfolio.py entry override guard
拆解 (decoupling). 此前守卫要求 raw_prev_close 非 NaN 且 > 0, 但实测 panel
该字段 100% NaN (DuckDB raw_kline_daily.prev_close NULL upstream). 导致
entry 静默回退到 adj_open → phantom TP/SL 触发. 修复后 entry 用 raw_open
(per §3 raw_close execution source). trades.csv 必然变化, 必须重生成.

For each chase_v5 / v8-v19 preset:
  1. Run run_backtest in the locked window
  2. Hash the trades.csv
  3. Update tests/golden/chase_v{N}_baseline.json with new hash + metrics
  4. Append v3a_change_note (preserve existing v6/v7 notes)

Usage:  python tests/_regen_chase_baselines.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/Users/holeon/code/hiagent")
sys.path.insert(0, str(ROOT))

from chase_up.backtest import run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from hiagent_config import DB_PATH

PRESETS = [
    "chase_v5_pos2_equal_atr_tp6_sl15_mh10",
    "chase_v8_pos2_equal_atr_tp6_sl15_mh18",
    "chase_v9_pos2_equal_atr_tp6_sl15_mh18_score12",
    "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16",
    "chase_v11_pos2_equal_atr_tp6_sl15_mh18_score17",
    "chase_v12_pos2_equal_atr_tp6_sl15_mh18_score17_atr035",
    "chase_v13_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom10",
    "chase_v14_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11",
    "chase_v15_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11_ma60buf08",
    "chase_v16_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08",
    "chase_v17_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08_atr082",
    "chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082",
    "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082",
]

GOLDEN_DIR = ROOT / "tests" / "golden"
RESULTS_DIR = ROOT / "chase_up" / "results"
WINDOW = ("2025-09-19", "2026-09-19")


def _hash_csv(df) -> str:
    """Hash must match test: pd.read_csv → df.to_csv round-trip form."""
    import io
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    raw = buf.getvalue()
    return hashlib.sha256(raw.encode()).hexdigest()


def main() -> None:
    universe = set(load_universe("mainboard_only", DB_PATH))
    panel = load_panel(DB_PATH, WINDOW[0], WINDOW[1], universe=universe)
    panel_ind = compute_indicators(panel)

    print(f"[regen] V3a+ dual-price entry fix baselines — {len(PRESETS)} presets")
    print(f"[regen] window={WINDOW[0]}..{WINDOW[1]} universe={len(universe)}\n")

    for preset in PRESETS:
        # 删除旧 trades.csv 强制重新生成
        short_name = preset.replace("chase_", "")  # v5_pos2_...
        trades_csv = RESULTS_DIR / f"{short_name.split('_pos')[0]}_trades.csv"
        if trades_csv.exists():
            trades_csv.unlink()

        # 跑 backtest
        res = run_backtest(preset, WINDOW[0], WINDOW[1], DB_PATH, panel_ind=panel_ind)
        trades_df = res["trades"]
        trades_df.to_csv(trades_csv, index=False)
        # 测试侧用 pd.read_csv + to_csv, 必须 round-trip 同一份 trades.csv 才能 hash 一致
        import pandas as pd
        reread = pd.read_csv(trades_csv)
        new_hash = _hash_csv(reread)
        m = res["metrics"]

        # 更新 golden baseline
        golden_path = GOLDEN_DIR / f"chase_{short_name.split('_pos')[0]}_baseline.json"
        if not golden_path.exists():
            # 找短名 (v5 / v8 / v9 / v10-v19)
            for v in ("v5", "v8", "v9", "v10", "v11", "v12", "v13", "v14",
                       "v15", "v16", "v17", "v18", "v19"):
                if preset.startswith(f"chase_{v}_"):
                    golden_path = GOLDEN_DIR / f"chase_{v}_baseline.json"
                    break
        if not golden_path.exists():
            print(f"  [SKIP] {preset}: no golden at {golden_path}")
            continue

        baseline = json.loads(golden_path.read_text(encoding="utf-8"))
        old_hash = baseline.get("trades_csv_sha256", "?")
        baseline["trades_csv_sha256"] = new_hash
        baseline["trades_csv_rows"] = len(trades_df)
        # 同步 metrics
        baseline["metrics"]["trades"] = len(trades_df)
        baseline["metrics"]["win_rate"] = round(m["win_rate"], 4)
        baseline["metrics"]["total_return"] = round(m["total_return"], 4)
        baseline["metrics"]["cagr"] = round(m["cagr"], 4)
        baseline["metrics"]["sharpe"] = round(m["sharpe"], 2)
        baseline["metrics"]["max_dd"] = round(m["max_dd"], 4)
        baseline["metrics"]["tp_count"] = m["tp_count"]
        baseline["metrics"]["sl_count"] = m["sl_count"]
        baseline["metrics"]["time_count"] = m["time_count"]
        baseline["metrics"]["eod_count"] = m.get("eod_count", 0)
        baseline["metrics"]["profit_factor"] = round(m["profit_factor"], 2)
        baseline["metrics"]["avg_net_return"] = round(m["avg_net_return"], 4)
        baseline["metrics"]["exposure"] = round(m["exposure"], 3)
        baseline["metrics"]["final_equity"] = m["final_equity"]
        baseline["metrics"]["avg_hold_days"] = round(m["avg_hold_days"], 1)
        baseline["metrics"]["max_hold_days"] = m["max_hold_days"]
        baseline["v6_change_note"] = (
            "V6 (2026-09-22): chase_up/portfolio.py intraday tiebreak flipped "
            "TP-first → SL-first per CLAUDE.md §4 worst-case. Some TP exits "
            "where intraday low also crossed SL became SL exits. Compare "
            "tp_count/sl_count against pre-V6 baseline."
        )
        baseline["v3a_change_note"] = (
            "V3a+ (2026-09-22, CLAUDE.md §3): chase_up/portfolio.py entry "
            "override 守卫拆解 (decoupling). 此前守卫要求 raw_prev_close 非 NaN "
            "且 > 0 才走 raw entry, 但实测 panel 该字段 100% NaN (DuckDB "
            "raw_kline_daily.prev_close NULL upstream). 导致 V3a entry 静默 "
            "回退到 adj_open, exit 用 raw_*, 混用触发 phantom TP/SL. 修复后 "
            "entry fill 用 raw_open (per §3 raw_close execution source). "
            "trades.csv 已重生成, entry_price 列与 panel raw_open 对齐."
        )

        golden_path.write_text(
            json.dumps(baseline, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        delta = "+" if new_hash != old_hash else "="
        print(
            f"  {preset[:50]:<50} n={len(trades_df):>4}  "
            f"TP/SL/T={m['tp_count']}/{m['sl_count']}/{m['time_count']:<3}  "
            f"hash {delta}{old_hash[:6]}→{new_hash[:6]}"
        )


if __name__ == "__main__":
    main()