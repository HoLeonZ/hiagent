"""§6 守卫:快速扫描器**不得**对"它无法忠实复现的 preset"给出信号集。

## 缺陷(审计 §8 #7d,2026-10-16 复核确认)

`scan_signals_fast.py` 是引擎入场条件的**第二处实现**,它把 E/A/B/C/D 的**参数写死**
在代码里(3e7/3e8、3/10、0.6、`d_mode='strict'`),且**不实现**引擎会评估的
F/G/H/I/J/K 与市场宽度开关;也不评估多腿集成。而模块 docstring 当时宣称
**"结果与策略 100% 等价"**。

实测(75 个 preset):

| 偏离原因 | preset 数 |
|---|---|
| 启用本器未实现的入场开关 | 37 |
| 基础参数被写死(声明值不同) | 71 |
| 其中 `d_mode` | 70 |
| 其中 `below_ratio_60` / `close_ma60_buffer` | 各 70 |
| 其中 `up_streak_low/high` / `liq_low/high` | 各 2 |
| 其中 `a_condition` | 1 |
| **合计结论不可信** | **71 / 75** |

对**实时交易**工具而言,多报的信号就是要下单的票 —— 方向错误比不出结果更糟。
更关键的是:`sl_cooldown_days`(J)与市场宽度是**路径依赖**的,单行扫描**原理上**
无法复现,故这不是"实现漏了",而是"这条路径对它们永远不可能等价"。

## 修法

`_scan_preset` 在 `get_preset` 之后即调用 `_assert_fast_path_equivalent`:
不等价 ⇒ 抛 `FastScannerDivergence`,消息里逐条列出原因并指向
`python -m short_reversal.scan_signals`(构造真实 Phase3V3Strategy)。docstring 的
"100% 等价"声明同时改为精确范围。

## 为什么还要钉住"可信集合非空"

守卫最容易被写成"永远拒绝" —— 那种绿是**真空的绿**(附二十:"规则存在 ≠ 规则被应用"
的镜像:守卫存在 ≠ 它放行过任何东西)。故本文件既断言偏离者必须被拒,也断言
可信集合**恰好**是已知的那一份快照:它变空会让工具彻底无用,它变大则说明有人
扩大了适用范围而未在此处留痕。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from short_reversal.presets import PRESETS  # noqa: E402
from short_reversal.scan_signals_fast import (  # noqa: E402
    FastScannerDivergence,
    _scan_preset,
    fast_path_divergences,
)

#: 当前**唯一**可信的 preset 快照(审计 2026-10-16 实测)。
#: 它不是"期望值",而是"已知范围" —— 变更它必须是一次有意识的操作。
KNOWN_FAITHFUL = frozenset({"v35_agg_pctchg_04_09"})

_EMPTY = pd.DataFrame(columns=["thscode", "date", "close", "volume"])


def _raises(preset: str) -> str:
    with pytest.raises(FastScannerDivergence) as ei:
        _scan_preset(preset, "2026-01-05", _EMPTY)
    return str(ei.value)


# ---------------------------------------------------------------------------
# 偏离者必须被拒(两向有牙:删掉闸门 ⇒ 会静默返回空 DataFrame 而不是抛)
# ---------------------------------------------------------------------------


def test_preset_enabling_an_unimplemented_switch_is_refused() -> None:
    """`v50_slope` 启用 F(require_ma20_slope_neg)—— 本器不实现它。"""
    msg = _raises("v50_slope")
    assert "require_ma20_slope_neg" in msg
    assert "scan_signals" in msg, "必须指明可用的替代入口"


def test_preset_with_hardcoded_parameter_divergence_is_refused() -> None:
    """参数被写死同样算不等价 —— 不只是"没实现开关"这一类。"""
    msg = _raises("v38_a_relaxed")  # below_ratio_60=0.5 / close_ma60_buffer=0.02
    assert "below_ratio_60" in msg
    assert "close_ma60_buffer" in msg


def test_ensemble_preset_is_refused() -> None:
    """多腿集成:本器不评估 ensemble_substrategies。"""
    assert "ensemble" in _raises("v63_ensemble").lower()


def test_path_dependent_condition_is_named_as_such() -> None:
    """J(SL 冷静期)是路径依赖的 —— 拒绝理由必须点出它是原理性不可能。"""
    assert "sl_cooldown_days" in _raises("v57_cd_03")


def test_market_breadth_gate_is_refused() -> None:
    """市场宽度闸门同样路径依赖(取决于当日全市场宽度)。"""
    assert "require_market_breadth_bear" in _raises("v66_regime")


# ---------------------------------------------------------------------------
# 可信集合:非空、且恰为已知快照
# ---------------------------------------------------------------------------


def test_faithful_set_is_nonempty() -> None:
    """守卫不得退化成"永远拒绝" —— 那样它的绿是真空的绿。"""
    faithful = {n for n, p in PRESETS.items() if not fast_path_divergences(p)}
    assert faithful, "所有 preset 都被拒 ⇒ 快速扫描器已无任何适用范围"


def test_faithful_set_matches_the_recorded_snapshot() -> None:
    """可信集合变化必须是一次有意识的操作(新增/移除 preset 时更新本快照)。"""
    faithful = {n for n, p in PRESETS.items() if not fast_path_divergences(p)}
    assert faithful == set(KNOWN_FAITHFUL), (
        f"快速扫描器的可信 preset 集合发生变化:\n"
        f"  新增: {sorted(faithful - KNOWN_FAITHFUL)}\n"
        f"  移除: {sorted(KNOWN_FAITHFUL - faithful)}\n"
        "若确有变化,请核对新增者是否真的与引擎条件等价,再更新 KNOWN_FAITHFUL。"
    )


def test_faithful_preset_actually_scans() -> None:
    """正路径:可信 preset 必须真的跑得通(空面板 ⇒ 空信号,不抛)。"""
    sig, st_excluded = _scan_preset("v35_agg_pctchg_04_09", "2026-01-05", _EMPTY)
    assert len(sig) == 0 and st_excluded == []


def test_module_docstring_no_longer_claims_100_percent_equivalence() -> None:
    """§7/§0: 声明的口径必须与实际一致 —— 旧的"100% 等价"是错的。"""
    src = (REPO_ROOT / "short_reversal" / "scan_signals_fast.py").read_text(encoding="utf-8")
    head = src[: src.index('"""', src.index('"""') + 3)]
    assert "100% 等价" not in head, (
        "docstring 又宣称与策略 100% 等价 —— 实测 71/75 个 preset 不成立"
    )
    assert "fail-fast" in head, "docstring 必须写明不等价时会 fail-fast"
