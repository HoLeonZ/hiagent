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

# §0 (audit P3, 2026-10-15): 原为硬编码绝对路径 Path("/Users/holeon/code/hiagent")。
# 后果有两层:(a) 脚本不可复现 —— 在任何别的检出里运行都会去改**另一个**仓库的
# golden(实测:在 worktree 里跑,却把哈希写进了共享树,而测试读的是 worktree,
# 两边永远对不上,重刷也修不好);(b) 会静默污染不属于它的工作树。
# 现从本文件位置推导。
ROOT = Path(__file__).resolve().parents[1]
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
# 本脚本**不写**运行产物(只锁哈希),故也不创建 results/:创建它会把
# "目录不存在 → skip" 的产物 gap-tracker 变成 "目录存在但无产物 → fail",
# 等于用一个空目录反过来污染产物检查。
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
        short_name = preset.replace("chase_", "")  # v5_pos2_...

        # 跑 backtest
        res = run_backtest(preset, WINDOW[0], WINDOW[1], DB_PATH, panel_ind=panel_ind)
        trades_df = res["trades"]
        # §6 (audit P3, 2026-10-15): 不再写 trades.csv。
        # 本脚本的职责是锁定**成交列表哈希**,而不是产出运行产物。原来写 CSV 是因为
        # 测试侧会 round-trip 读回;哈希已改为直接取 DataFrame,写盘遂成冗余 ——
        # 而它会把 results/ 变成"有 trades.csv 却无 metrics.json"的半套产物,直接
        # 触发两个 provenance gap-tracker(实测)。产物由真实回测产生,不由重刷脚本。
        # §6 (audit P3, 2026-10-15): 哈希**直接从 DataFrame** 取,不做 CSV round-trip。
        # 测试侧现在一律重跑并哈希 `df.to_csv(index=False)`(与 uptrend_pullback 的
        # sha256 基线同口径)。原实现 round-trip 后哈希,与测试侧约定不一致 —— 两边
        # 各自"对"却永远对不上,重刷也修不好。
        new_hash = _hash_csv(trades_df)
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
        # §7 (audit P3, 2026-10-15): golden 只锁**成交列表**(sha256)与
        # 结构(行数 / 列),不再写回任何绩效指标。
        # 理由:CLAUDE.md §7 明令"fresh clone 必须包含零历史绩效声明";
        # 而这些数字可由当前代码 + 一条命令重新生成,属"失效结果"。
        # 且它们会随每次重刷覆盖而漂移,成为与 sha256 不同步的第二份事实。
        baseline.pop("metrics", None)

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