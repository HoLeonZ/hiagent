"""附七十五 —— WFV 窗口的**跨窗口**语义:重叠 / 首尾相接 / 空档,必须被算出来并说出来

## 缺陷(实测)

`core/walkforward.py::walkforward_windows` 只保证**窗口内**的 OOS
(`train_end < test_start`),对**跨窗口**的关系既不校验也不提示:

| `roll_months` vs `test_months` | 后果(实测) |
|---|---|
| `roll < test`(**默认 6 < 12**) | 相邻 **test 窗重叠 6 个月(50%)** —— 10 个窗里有 9 对重叠 |
| `roll == test` | 首尾相接,不重不漏(5 窗,无重叠无空档) |
| `roll > test` | 中间**留空档 6 个月** —— 那段行情没人评估(4 窗,3 处空档) |

而 `tests/test_core_walkforward.py::test_walkforward_windows_enforces_oos_test_window`
的 docstring 写的是「**(无 sample overlap)**」—— 那句话**只在窗口内**成立。
聚合层(跨窗均值/中位数、DSR 的 T)会把"N 个窗"当成 N 份独立证据,而默认参数下并不独立。

## 处置

* 新增纯函数 `window_coverage(windows) -> (overlaps, gaps)`(以**日历月**计);
* `walkforward_windows` 在重叠/空档时**告警**并给出月数(不报错 —— 那是选择,不是 bug);
* docstring 写清三种关系的后果;
* 更正那条测试 docstring 的过度声称。

**"要不要把默认 `roll` 改成等于 `test`(即不重叠)"登记为口径决定** —— 它会改变每一次
sweep 的窗口集合 ⇒ 结果变更,不擅自改。
"""
from __future__ import annotations

import logging
from datetime import date

import pytest

from core.walkforward import walkforward_windows, window_coverage

_START = date(2020, 1, 1)
_END = date(2026, 9, 1)


def _windows(train=12, test=12, roll=6):
    return walkforward_windows(_START, _END, train, test, roll)


# ---------------------------------------------------------------------------
# 纯函数:三种关系
# ---------------------------------------------------------------------------


def test_roll_less_than_test_overlaps() -> None:
    ws = _windows(roll=6)
    overlaps, gaps = window_coverage(ws)
    assert gaps == []
    assert overlaps and all(o == 6 for o in overlaps), (
        f"roll=6 / test=12 ⇒ 相邻窗应各重叠 6 个日历月,实际 {overlaps}"
    )


def test_roll_equal_to_test_is_contiguous() -> None:
    """`roll == test` 是"不重不漏"的那一档 —— 它必须既无重叠也无空档。"""
    ws = _windows(roll=12)
    assert window_coverage(ws) == ([], [])


def test_roll_greater_than_test_leaves_gaps() -> None:
    ws = _windows(roll=18)
    overlaps, gaps = window_coverage(ws)
    assert overlaps == []
    assert gaps and all(g == 6 for g in gaps), (
        f"roll=18 / test=12 ⇒ 相邻窗之间应各空档 6 个月,实际 {gaps}"
    )


def test_coverage_is_empty_for_a_single_window() -> None:
    # 视野要 ≥ train+test(否则函数本身会 ValueError),但短到只装得下一窗:
    # 2024-01 起 24.9 个月,窗 0 的 test 到 2025-12-31 收得下,窗 1 的 test_end
    # (2026-06-30)越界 ⇒ 只有一窗。
    ws = walkforward_windows(date(2024, 1, 1), date(2026, 1, 31), 12, 12, 6)
    assert len(ws) == 1 and window_coverage(ws) == ([], [])


# ---------------------------------------------------------------------------
# 告警:必须被说出来
# ---------------------------------------------------------------------------


def test_overlap_is_warned(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="core.walkforward"):
        _windows(roll=6)
    assert any("重叠" in r.getMessage() for r in caplog.records), \
        "roll<test 时没有告警"


def test_gap_is_warned(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="core.walkforward"):
        _windows(roll=18)
    assert any("空档" in (r.getMessage()) for r in caplog.records), \
        "roll>test 时没有告警"


def test_no_warning_when_contiguous(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="core.walkforward"):
        _windows(roll=12)
    assert not [r for r in caplog.records if "§5 WFV" in r.getMessage()], (
        "roll==test 是干净的一档,不该告警"
    )


# ---------------------------------------------------------------------------
# 把仓库**默认参数**的事实钉住
# ---------------------------------------------------------------------------


def test_repo_default_arguments_overlap_by_half() -> None:
    """仓库默认(train 12 / test 12 / roll 6)⇒ test 窗重叠 50%。

    这条把"默认口径是什么"钉成**可测的事实**:若有人改了默认,它会红,提示同步更新
    聚合层与附录里关于 T 口径的说明(附六十/六十四 的"一个窗口的观测数"正是因为
    窗口重叠才那么取)。
    """
    ws = _windows(roll=6, train=12, test=12)
    overlaps, _ = window_coverage(ws)
    assert overlaps and overlaps[0] * 2 == 12, (
        f"默认参数的相邻窗重叠应为 6 个月(=test 的一半),实际 {overlaps}"
    )


def test_within_window_oos_holds_for_every_relation() -> None:
    """无论 roll 取多少,**窗口内**的 OOS(train_end < test_start)都必须成立。"""
    for roll in (3, 6, 12, 18, 24):
        for w in _windows(roll=roll):
            assert w.train_start <= w.train_end < w.test_start <= w.test_end, (
                f"roll={roll}: 窗口内不变量被破坏:{w}"
            )
