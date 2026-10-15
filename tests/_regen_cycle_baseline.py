"""§0: 生成 cycle_price_action 的 golden 成交列表基线。

用法:  python tests/_regen_cycle_baseline.py

**为什么需要**:`cycle_price_action` 此前**没有任何** pinned 基线 —— 另外三个引擎
都有。于是「这次逻辑改动是否改变了成交列表」这个问题,对 cycle 没有任何守卫能回答。
§6 要求「golden-baseline hashes lock trade-list behavior for every engine」。

**为什么默认 skip 而不是每次跑**:cycle 引擎逐票新建 DuckDB 连接 + 逐票 cerebro,
一次 1 个月窗口的全主板回测约 **4–7 分钟**(实测)。放进每次 `pytest` 会让套件不可用。
故消费端(`tests/test_cycle_price_action_sha256_baseline.py`)默认 skip,需显式
`DNA_RUN_SLOW_GOLDENS=1` 才重跑并比对。

**确定性**:脚本同时输出两个哈希 —— 原序(`trades_csv_sha256`)与按内容排序
(`trades_sorted_sha256`)。若 universe 遍历顺序不稳定,原序哈希会漂移,而排序哈希
仍然可比;取哪个由消费端断言决定(见基线里的 `stable_hash` 字段,由本脚本两次
运行比对后填入 —— 单次运行无法自证稳定性)。
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from cycle_price_action.backtest import run_backtest  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402

#: 固定窗口 —— 参与 §5 迭代计数的基线窗口,改动它必须重生成并重启计数。
WINDOW = (date(2026, 4, 1), date(2026, 5, 1))
CASH = 1_000_000.0
PRESET_KEY = "v1"
GOLDEN_PATH = ROOT / "tests" / "golden" / f"cycle_{PRESET_KEY}_baseline.json"

SORT_COLS = ["entry_date", "thscode", "exit_date", "entry_price", "exit_price", "shares"]


def _digest(df: pd.DataFrame) -> str:
    """与 chase_up / uptrend_pullback 基线同约定:哈希 `to_csv(index=False)`,
    避免 OS 行尾差异(不用二进制文件本身)。"""
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def main() -> int:
    if not Path(DB_PATH).exists() or Path(DB_PATH).stat().st_size == 0:
        print(f"§6: 本地 DuckDB 不可用({DB_PATH})—— 无法生成基线")
        return 1

    result = run_backtest(DB_PATH, WINDOW[0], WINDOW[1], cash=CASH)
    if not result.trades:
        print(f"窗口 {WINDOW} 未产生成交 —— 该窗口不能作基线")
        return 1

    df = pd.DataFrame([asdict(t) for t in result.trades])
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)
    # 原序哈希必须在**排序之前**取 —— 否则它与排序哈希恒等,失去意义。
    ordered_digest = _digest(df)
    canonical = df.sort_values(by=["entry_date", "thscode", "exit_date"]).reset_index(drop=True)

    payload = {
        "engine": "cycle_price_action",
        "preset": PRESET_KEY,
        "window": [WINDOW[0].isoformat(), WINDOW[1].isoformat()],
        "cash": CASH,
        "trades_csv_rows": int(len(canonical)),
        "trades_csv_sha256": ordered_digest,
        # 排序哈希:按 SORT_COLS 排序后取哈希 —— 对 universe 遍历顺序免疫。
        "trades_sorted_sha256": _digest(
            canonical.sort_values(by=SORT_COLS).reset_index(drop=True)
        ),
        "note": (
            "§0 完备性基线。原序哈希对 universe 遍历顺序敏感,故消费端优先断言"
            "排序哈希(见 trades_sorted_sha256)。重生成: python "
            "tests/_regen_cycle_baseline.py。此基线参与 §5 迭代计数:任何为了"
            "「让基线过」而改窗口或改策略的迭代,都必须计入 n_trials。"
        ),
    }
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"已写入 {GOLDEN_PATH}")
    print(f"  rows={payload['trades_csv_rows']}")
    print(f"  ordered={payload['trades_csv_sha256'][:16]}…")
    print(f"  sorted ={payload['trades_sorted_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
