"""§4/§2 守卫:涨停阈值只有**一处**定义;以及登记跨引擎的口径分歧。

## 1 · 同值不同源(已修)

`chase_up/replay_strategy.py` 曾自己写一份 `prev_close_limit=0.098`,旁边一句注释
"与 `chase_up/portfolio.LIMIT_UP_THRESHOLD` 一致"。**注释保证不了任何事**:两个值
分处两文件,改一处不会有任何东西报错 —— 而这条阈值决定"涨停封板时能不能买"。
现已改为 import(值不变,行为中性)。

## 2 · 跨引擎口径分歧(**未改**,登记在案)

| 引擎 | 阈值 |
|---|---|
| `chase_up` / `uptrend_pullback` | **0.098** |
| `short_reversal` / `cycle_price_action` | **0.095** |

2 对 2,且 chase_up 那侧自己的注释把它称作"**历史** override" —— 即有来源、无理由。
两个值对同一件事给出不同判定:0.095 会**拒绝**一些其实可成交的接近涨停的 bar
(悲观),0.098 会**放过**它们(乐观)。§0 的 Pessimistic Default 偏向 0.095 那一侧。

**为什么本轮不改**:统一到任一值都会**改变 chase_up / uptrend_pullback 的成交列表**
(进而要重刷它们的 golden 基线),那是**结果变更**,应按 §0/§6 显式说明漂移后再做,
属使用者拍板项 —— 不是"顺手统一"。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 各引擎的涨停阈值来源(文件 → 期望值)。**这是登记**,不是认可某一侧正确。
LIMIT_UP_THRESHOLDS = {
    "chase_up/portfolio.py": 0.098,
    "uptrend_pullback/portfolio.py": 0.098,
    "short_reversal/replay_strategy_v3.py": 0.095,
    "cycle_price_action/portfolio.py": 0.095,
}


def test_replay_strategy_imports_the_constant_instead_of_redeclaring() -> None:
    """§2 单源:不得再出现 `prev_close_limit=0.098` 这样的字面量副本。"""
    src = (REPO_ROOT / "chase_up" / "replay_strategy.py").read_text(encoding="utf-8")
    assert "prev_close_limit=0.098" not in src, (
        "涨停阈值又变回字面量副本了 —— 注释保证不了它与 portfolio 的常量一致"
    )
    assert "prev_close_limit=LIMIT_UP_THRESHOLD" in src
    assert "from chase_up.portfolio import LIMIT_UP_THRESHOLD" in src


def test_replay_strategy_value_matches_the_single_source() -> None:
    """行为验证:参数默认值确实**取自** portfolio 的常量(而不是恰好相等)。"""
    from chase_up.portfolio import LIMIT_UP_THRESHOLD
    from chase_up.replay_strategy import ChaseUpTradeReplay

    assert ChaseUpTradeReplay.params.prev_close_limit == LIMIT_UP_THRESHOLD


@pytest.mark.parametrize("rel,expected", sorted(LIMIT_UP_THRESHOLDS.items()))
def test_limit_up_threshold_values_are_still_registered(rel: str, expected: float) -> None:
    """钉住四个引擎的现值 —— 数值若变动,必须同时更新本登记(防止悄悄单侧改动)。"""
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert f"{expected}" in src, (
        f"{rel} 的涨停阈值不再是 {expected} —— 若是有意统一口径,"
        "请同时更新 tests/test_limit_up_threshold_single_source.py 的登记,"
        "并在 PR 里说明成交列表漂移(§0/§6)。"
    )


def test_the_cross_engine_divergence_is_not_silently_unified() -> None:
    """登记本身:两侧仍是 2 对 2 分歧时必须**被看见**。

    这条不是"要求它们相等" —— 恰恰相反:在**没有**说明漂移之前,不该有一侧被
    悄悄改成另一侧。两个值都是合法的容忍度选择,区别在悲观/乐观方向。
    """
    values = set(LIMIT_UP_THRESHOLDS.values())
    assert len(values) == 2, (
        "四个引擎的涨停阈值已变成同一个值 —— 好事,但请把本用例与上面的登记"
        "一起删掉(它登记的是一个**已不存在**的分歧)。"
    )
    assert 0.095 in values and 0.098 in values
