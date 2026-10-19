"""棘轮: **不得新增"导入了 `core.*` 却从未引用"的符号** (§13.120, 2026-10-19)。

## 为什么钉这一族
本册反复出现「**声明/导入 vs 实际做**」, 而一直是**一次发现一个**:
§13.83 ("自动套 DSR + Bonferroni" ×23) / §13.95 (`atr_slippage` "用于 chase_up") /
§13.106(e) (`is_limit_up` 导入却未调用, 且被假称"共用单一来源") / §13.107 ("60d rolling mean")。

**扫描器 `tools/scan_unused_core_imports.py` 已在两个已知实例上验证命中**
(`uptrend_pullback/portfolio.py` 的 `is_limit_up`、`short_reversal` 的 `dual_atr_slippage`)。

## 判据是**双向**的 (棘轮的两面都是自失效)
* **新增** 一条 ⇒ `found ⊆ FROZEN` 失败 ⇒ 红 (要求要么修掉, 要么显式加进清单并写明理由);
* **修掉** 一条而没更新清单 ⇒ `FROZEN ⊆ found` 失败 ⇒ 红 (要求把清单收窄)。

⚠️ **本判据判不了语义** —— 它只知道"这个名字在可执行代码里没被引用",
不知道它是否被**别的方式**用到。⇒ 清单里每一条都应带一句人写的理由。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.scan_unused_core_imports import PKGS, scan  # noqa: E402


def _found() -> set[str]:
    """当前"导入了 core.* 却从未引用"的集合 (形如 `路径::名字`)。"""
    out: set[str] = set()
    for pkg in PKGS:
        root = REPO_ROOT / pkg
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                hits = scan(p)
            except SyntaxError:
                continue
            for _ln, orig, _local, is_reexport in hits:
                if not is_reexport:
                    out.add(f"{p.relative_to(REPO_ROOT).as_posix()}::{orig}")
    return out


# ---- 冻结清单 (2026-10-19 实测 13 处; 每条都附人写的判断) ----
FROZEN = {
    # ⚠️ 这两个是**已登记的假声明的载体** (§13.106(e) / §13.95); 注释已更正, 导入**按规矩不删**
    #    ("看到未使用的代码, 指出它, 不删它")。
    "uptrend_pullback/portfolio.py::is_limit_up":
        "§13.106(e): 守卫是**内联**式 (本地 `LIMIT_UP_THRESHOLD = 0.098`), 此导入未被调用。",
    "short_reversal/replay_strategy_v3.py::atr_slippage":
        "§13.95: 别名 `dual_atr_slippage`, **导入后零读取**; 真正用的是 `effective_slippage`。",
    # 其余为**纯死导入** (各处只出现 1 次 = import 行本身), 不影响任何行为。
    "uptrend_pullback/main.py::CASH_WALK_COLS": "纯死导入 (产物列名常量)。",
    "uptrend_pullback/main.py::EQUITY_CURVE_COLS": "纯死导入 (产物列名常量)。",
    "uptrend_pullback/portfolio.py::LAYOUT_CHASE_UPTREND": "纯死导入 (布局常量)。",
    "uptrend_pullback/portfolio.py::PRICE_SOURCE_RAW": "纯死导入 (价源常量; 判定用的是字面量)。",
    "uptrend_pullback/portfolio.py::extract_execution_bar": "纯死导入。",
    "uptrend_pullback/portfolio.py::validate_price_source": "纯死导入。",
    "short_reversal/replay_strategy_v3.py::LAYOUT_SHORT_REVERSAL": "纯死导入 (布局常量)。",
    "short_reversal/replay_strategy_v3.py::extract_execution_bar": "纯死导入。",
    "short_reversal/walkforward.py::walkforward_windows": "纯死导入 (别名 `core_walkforward_windows`)。",
    "cycle_price_action/walkforward.py::WalkForwardWindow":
        "§13.77: 该文件是 **19 行 re-export 存根**, 导入本身即导出; 但它没用 `__all__` ⇒ 未被标 reexport。",
    "cycle_price_action/walkforward.py::walkforward_windows":
        "§13.77: 同上 (re-export 存根)。",
}


def test_the_scanner_actually_finds_something() -> None:
    """反空转: 扫描器必须真的抓到东西 —— 否则下面的 ⊆ 是空集比空集。"""
    got = _found()
    assert got, (
        "§13.120: 扫描器一处都没找到 —— 要么清单真的清空了(好事, 请收窄 FROZEN), "
        "要么**判据的扫描单位坏了**。"
    )


def test_no_new_unused_core_imports() -> None:
    """**新增**一条 ⇒ 红。"""
    got = _found()
    new = got - set(FROZEN)
    assert not new, (
        f"§13.120: 新增了这些「导入了 `core.*` 却从未引用」的名字: {sorted(new)}\n"
        f"⇒ 要么删掉这个导入, 要么**显式**加进 `FROZEN` 并写明它为什么留着。\n"
        f"(本册反复记的那族: **声明/导入 vs 实际做**。)"
    )


def test_the_frozen_list_has_no_stale_entries() -> None:
    """**修掉**一条却没更新清单 ⇒ 红 (棘轮的另一面)。"""
    got = _found()
    stale = set(FROZEN) - got
    assert not stale, (
        f"§13.120: 清单里这些条目**已经不存在**了: {sorted(stale)}\n"
        f"⇒ 请把它们从 `FROZEN` 里删掉 —— 否则清单会慢慢变成一份没人读的旧账。"
    )
