"""§0 cycle_price_action 成交列表可复现性基线（Tick 36 / Round 13；2026-10-15 重写）。

CLAUDE.md §0 (verbatim):
  "**Reproducibility Mandate:** Identical inputs MUST produce byte-identical
   outputs. ... A backtest that cannot be reproduced is a bug, not a result."

CLAUDE.md §6 (verbatim):
  "Golden-baseline hashes lock trade-list behavior for every engine; any logic
   change that alters the trade list MUST regenerate the baseline and justify
   the drift in the PR."

**为什么重写**:原版是「RED-by-design」——它断言 `tests/golden/` 下**不存在**
`cycle_*_baseline.json`,以此登记「cycle 没有基线」这个缺口。缺口本身是真的
(另外三个引擎都有基线,cycle 没有),但用一条**永远失败**的用例来表达它有三个问题:
  1. 红灯成了常态 —— 真实回归会藏身其中(本分支整改中已实际发生过一次)。
  2. 它只断言「文件不在」,从不比对任何东西 —— 即使文件出现了,它也不验证哈希。
  3. 其 `_check_one` 读的是 `cycle_price_action/results/` 下的 trades.csv,
     那是 **gitignore 的本地缓存**(§7)——于是"哈希比对"实际在比对**上一次跑出
     的产物**,与当前代码无关:陈旧产物在场时永远绿,缺失时又什么都不做。

现在它做它该做的事:重跑引擎、比对 pinned 哈希。**成本**:cycle 引擎逐票新建
DuckDB 连接 + 逐票 cerebro,1 个月窗口的全主板回测约 4–7 分钟(实测)。

故默认**不跑**(否则整套件不可用),需显式开启:

    DNA_RUN_SLOW_GOLDENS=1 pytest tests/test_cycle_price_action_sha256_baseline.py

未开启时 skip,且 skip 文本会说明**为什么**跳过 —— 不静默(§6:skip 而非 error,
但 skip 必须是**有信息**的 skip)。

生成/更新基线: `python tests/_regen_cycle_baseline.py`
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
BASELINE_PATH = GOLDEN_DIR / "cycle_v1_baseline.json"

#: 显式开启开关。见模块 docstring —— 一次重跑是分钟级,不能进默认路径。


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_cycle_price_action_has_pinned_baseline_files() -> None:
    """§0/§6: cycle 必须有一条 pinned 成交列表基线(不是断言它不存在)。"""
    assert BASELINE_PATH.exists(), (
        f"§0 GAP: {BASELINE_PATH.relative_to(REPO_ROOT)} 不存在 —— "
        "cycle_price_action 没有任何 pinned 基线,于是「这次改动是否改变了成交列表」"
        "无人能回答。生成:`python tests/_regen_cycle_baseline.py`。"
    )
    payload = _baseline()
    for key in ("window", "cash", "trades_csv_rows", "trades_csv_sha256"):
        assert key in payload, f"基线缺字段 {key!r}"


@pytest.mark.slow  # 重跑 cycle 全主板回测,实测约 7 分钟
def test_cycle_trades_list_matches_the_pinned_baseline() -> None:
    """§0: 重跑引擎,成交列表的 sha256 必须与 pin 一致 —— 否则就是漂移。

    2026-10-17:此前用**环境变量**默认跳过(`DNA_RUN_SLOW_GOLDENS=1` 才跑),
    理由是"放进默认套件会让整体不可用"。那个理由在**没有 marker 机制**时成立,
    但现在有了 `slow` marker ⇒ 改用 marker:
      · **默认执行**(CI 与本地全量都覆盖 cycle 的成交列表);
      · 本地快速迭代用 `-m "not slow"` 显式排除。

    为什么值得默认跑:默认跳过重型守卫,会让"覆盖"在一片绿里消失 ——
    而这一条正是四个引擎里**唯一**锁住 cycle 成交列表的守卫。
    """
    from hiagent_config import DB_PATH

    if not Path(DB_PATH).exists() or Path(DB_PATH).stat().st_size == 0:
        pytest.skip(f"§6: 本地 DuckDB 不可用({DB_PATH})—— skip 而非 error")

    from cycle_price_action.backtest import run_backtest

    payload = _baseline()
    from tests.conftest import skip_if_pinned_under_other_data  # §0/§6 数据指纹(附一百一十七)

    skip_if_pinned_under_other_data(payload, BASELINE_PATH.name)
    start, end = (date.fromisoformat(d) for d in payload["window"])
    result = run_backtest(DB_PATH, start, end, cash=payload["cash"])

    df = pd.DataFrame([asdict(t) for t in result.trades])
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert len(df) == payload["trades_csv_rows"], (
        f"§0 漂移: cycle 成交笔数 {len(df)} ≠ 基线 {payload['trades_csv_rows']}"
    )
    assert actual_hash == payload["trades_csv_sha256"], (
        "§0 漂移: cycle_price_action 成交列表与 pin 的基线不一致。\n"
        f"  窗口: {payload['window']}\n"
        f"  expected: {payload['trades_csv_sha256']}\n"
        f"  actual:   {actual_hash}\n"
        "若这是**有意的**逻辑变更:按 §6 重生成基线(`python "
        "tests/_regen_cycle_baseline.py`)并在 PR 里说明漂移原因与方向。"
    )
