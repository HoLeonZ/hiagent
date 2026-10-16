"""生成 short_reversal 的 trades sha256 基线(§0/§6 安全网)。

用法:  python tests/_capture_short_reversal_baseline.py

对每个 preset:
  1. 在锁定窗口上重算成交列表;
  2. **重算第二次**并要求两次哈希一致 —— 不可复现的东西不该被 pin(§0);
  3. 写入 tests/golden/short_reversal_<preset>_baseline.json。

与 `_regen_chase_baselines.py` 同规矩:**不写运行产物**,只锁哈希;
哈希**直接取 DataFrame**(不做 CSV 往返),与守卫同口径。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402

WINDOW = ("2026-03-01", "2026-08-31")
PRESETS = ["v50_slope", "v58_mp_2"]
GOLDEN_DIR = ROOT / "tests" / "golden"


def _hash(df) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def main() -> int:
    for preset in PRESETS:
        import pandas as pd

        t0 = time.time()
        first = pd.DataFrame(
            run_backtest_v3(preset, WINDOW[0], WINDOW[1], DB_PATH)["trades"]
        )
        t1 = time.time()
        second = pd.DataFrame(
            run_backtest_v3(preset, WINDOW[0], WINDOW[1], DB_PATH)["trades"]
        )
        h1, h2 = _hash(first), _hash(second)
        if h1 != h2:
            raise SystemExit(
                f"§0: {preset} 两次重算哈希不一致({h1[:12]} vs {h2[:12]})—— "
                "不可复现的东西不得 pin 成基线"
            )
        out = GOLDEN_DIR / f"short_reversal_{preset}_baseline.json"
        out.write_text(
            json.dumps(
                {
                    "preset": preset,
                    "window": list(WINDOW),
                    "engine": "short_reversal.engine.run_backtest_v3",
                    "trades_csv_sha256": h1,
                    "trades_csv_rows": int(len(first)),
                    "trades_csv_cols": list(first.columns),
                    "note": (
                        "short_reversal 成交列表 sha256 基线。多跑可复现性不变量:"
                        "同一 preset + DB + 窗口 ⇒ 逐字节相同的成交列表。漂移意味着"
                        "信号/出场/sizing/容量逻辑发生了改变(§6:须重算基线并说明漂移)。"
                    ),
                    "pinned": {
                        "date": "2026-10-17",
                        "why": (
                            "补齐 §6「Golden-baseline hashes lock trade-list behavior for "
                            "every engine」——本引擎此前**一条基线都没有**,而它是迭代最频繁的"
                            "一个(v35→v83)。v50_slope 覆盖单腿生产路径;v58_mp_2 覆盖多仓容量"
                            "路径(附二十七 修过其 sizing 与容量闸门,必须锁住)。"
                        ),
                        "window_rationale": (
                            "6 个月:足以产生数十笔成交;面板的暖机缓冲主导运行成本"
                            "(实测 6 个月 ≈3.9 分钟/preset,一年 ≈5.3 分钟),故不再缩短。"
                        ),
                        "reproducibility_check": (
                            "生成时连续重算两次、哈希一致;守卫在测试内**重算**后比对,"
                            "不读 gitignored 的 results/。"
                        ),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"WROTE {out.name}: rows={len(first)} sha={h1[:12]} "
            f"(两次重算一致 ✓, {t1 - t0:.0f}s + {time.time() - t1:.0f}s)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
