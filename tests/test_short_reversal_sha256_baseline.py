"""short_reversal trades sha256 reproducibility baseline。

CLAUDE.md §0 (verbatim):
  "**Reproducibility Mandate:** Identical inputs MUST produce byte-identical
   outputs. ... A backtest that cannot be reproduced is a bug, not a result."
CLAUDE.md §6 (verbatim):
  "**Test / Verification Layer:** ... Golden-baseline hashes lock trade-list
   behavior for every engine; any logic change that alters the trade list MUST
   regenerate the baseline and justify the drift in the PR."

## 为什么补这个文件

`tests/golden/` 里 chase 有 13 条、uptrend 有 3 条、cycle 有 1 条 trades 级基线,
**short_reversal 一条都没有** —— 而它是四个引擎里迭代最频繁的一个(v35 → v83,75 个
preset)。没有基线 ⇒ 任何触碰它信号/出场/sizing/容量的改动,判断标准只剩"套件还是绿的",
而套件里**没有一条**锁住成交列表。

审计 §8 早已把"补 `tests/golden/short_reversal_*_baseline.json`"登记为未结事项,并注明
**"先修守卫,否则加了基线也无人执行"** —— 指的是:基线必须像
`tests/test_uptrend_pullback_sha256_baseline.py` 那样**在测试内重算**再比对,
而不能去读 gitignored 的 `<engine>/results/`(那种写法在 fresh clone 下会静默 PASS,
本仓库已经吃过一次亏)。本文件照该模式补齐。

## 钉什么

| preset | 覆盖 |
|---|---|
| `v50_slope` | 单腿生产路径的规范形态(F 条件 + 单仓) |
| `v58_mp_2` | **多仓容量路径**(`max_positions=2`)——附二十七 修过它的 sizing 与容量闸门,必须锁住 |

窗口取 6 个月(2026-03-01..2026-08-31):足够产生数十笔成交,而面板的暖机缓冲主导了
运行成本(实测 6 个月 ≈ 3.9 分钟/preset,一年 ≈ 5.3 分钟,故缩短窗口收益有限)。
两条共约 8 分钟 —— 这是本仓库为"成交列表可锁"付出的代价,已记在案。

## 漂移了怎么办

文件里的 `pinned` 块记录窗口/行数/列与**为何**在此刻 pin。任何逻辑变更若改变成交列表,
必须重算基线并在 PR 里说明漂移(§6 明文),而不是把哈希改掉。"改哈希让它变绿"正是
这个守卫要防的事。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

#: 与生成脚本 `tests/_capture_short_reversal_baseline.py` 必须一致。
WINDOW = ("2026-03-01", "2026-08-31")
PRESETS = ["v50_slope", "v58_mp_2"]


def _sha256_of_csv(df: pd.DataFrame) -> str:
    """`df.to_csv(index=False)` 的 sha256 —— 与 chase / uptrend 基线同口径。

    刻意**不做** CSV 往返(写盘再读回):dtype/浮点格式化会变,两边各自"对"却永远对不上
    (该教训写在 `tests/_regen_chase_baselines.py` 里)。
    """
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def _regenerate_trades(preset: str, start: str, end: str) -> pd.DataFrame:
    """从 preset + DB 重算成交列表(不读 results/ —— 那是 gitignored 的)。"""
    from hiagent_config import DB_PATH
    from short_reversal.engine import run_backtest_v3

    return pd.DataFrame(run_backtest_v3(preset, start, end, Path(DB_PATH))["trades"])


def _check_one(preset: str) -> None:
    baseline_path = GOLDEN_DIR / f"short_reversal_{preset}_baseline.json"
    if not baseline_path.exists():
        pytest.skip(f"baseline not pinned yet: {baseline_path.name}")

    from tests.conftest import require_market_db  # §6: 存在**且非空**

    require_market_db()

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    start, end = baseline["window"]
    df = _regenerate_trades(preset, start, end)
    actual = _sha256_of_csv(df)

    assert actual == baseline["trades_csv_sha256"], (
        f"short_reversal {preset} 成交列表 sha256 漂移 ({start}..{end}):\n"
        f"  expected: {baseline['trades_csv_sha256']}\n"
        f"  actual:   {actual}\n"
        f"  rows: {len(df)} (expected {baseline['trades_csv_rows']})\n"
        f"  §6: 改变成交列表的逻辑必须**重算基线**并在 PR 说明漂移,"
        f"而不是把哈希改掉({baseline_path.name})。"
    )
    assert len(df) == baseline["trades_csv_rows"]
    assert list(df.columns) == baseline["trades_csv_cols"]


@pytest.mark.parametrize("preset", PRESETS)
def test_short_reversal_trades_sha256(preset: str) -> None:
    """§0/§6 PASS baseline:成交列表逐字节可复现。"""
    _check_one(preset)
