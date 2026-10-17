"""§0/§3: 黑名单必须真的被加载, 且"要求排除却读不到"必须 fail-fast。

缺陷 (2026-10-17 复核): `data/exclude_thscodes.txt`(仓库根, 29 条)被 README 记为
"排除股票清单", 但

  * `short_reversal/universe.py` 的 `DEFAULT_EXCLUDE_PATH` 指向
    `short_reversal/data/exclude_thscodes.txt` —— **该文件不存在**;
  * chase_up / uptrend_pullback 的调用点根本不传 `exclude_path`;
  * 三个引擎的 `_load_exclude` 都在**路径缺失时静默返回空集**。

叠加结果: 「要排除 29 只」与「排除了 0 只」**完全不可区分** —— 违反 §0
「Do not silently bypass」。同时 short_reversal 的模块 docstring 把 no-op 的原因
写成"该文件不存在", 而它**存在且被 git 跟踪** —— 一句错误的说明会把后来人引向
完全错误的结论。

修法与门控: 黑名单是**单一共享**文件(仓库根), 且只在
`exclude_hs300_zhongtou_finance` 模式下生效 —— 名单内容是大盘金融股, 属**研究
口径**的排除; 让它在 `mainboard_only` 下也生效等于借"修 bug"之手改掉全部出厂
preset 的股票池。故对 `mainboard_only` **行为中性**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from chase_up.universe import _load_exclude as chase_load
from short_reversal.universe import (
    DEFAULT_EXCLUDE_PATH,
    _load_exclude as sr_load,
    _resolve_exclude_path,
)
from uptrend_pullback.universe import _load_exclude as up_load

EXCLUDE_MODES = ("exclude_hs300_zhongtou_finance",)


def test_default_path_points_at_a_file_that_exists() -> None:
    """默认路径必须指向真实存在的共享黑名单 —— 这正是此前的缺陷。"""
    assert DEFAULT_EXCLUDE_PATH.exists(), (
        f"DEFAULT_EXCLUDE_PATH={DEFAULT_EXCLUDE_PATH} 不存在 ⇒ 黑名单恒为 no-op"
    )
    assert DEFAULT_EXCLUDE_PATH.resolve() == (
        Path(__file__).parent.parent / "data" / "exclude_thscodes.txt"
    ).resolve(), "黑名单应是仓库根的单一共享文件"


def test_exclude_mode_actually_excludes() -> None:
    """以"排除"命名的模式必须真的排除 —— 模式名不是装饰。"""
    path = _resolve_exclude_path(EXCLUDE_MODES[0], None)
    assert path is not None
    assert len(sr_load(path)) > 0, "exclude_hs300_zhongtou_finance 模式排除了 0 只"


def test_mainboard_mode_is_behaviour_neutral() -> None:
    """mainboard_only 不受黑名单影响 —— 出厂 preset 的行为不得被这次修复改掉。"""
    assert _resolve_exclude_path("mainboard_only", None) is None


def test_explicit_missing_path_fails_fast_in_all_three_engines() -> None:
    """显式要求排除却读不到文件 → 三个引擎都必须 fail-fast, 不得静默返回空集。"""
    missing = Path("/tmp/__definitely_not_here__.txt")

    with pytest.raises(Exception, match="黑名单文件不存在"):
        sr_load(missing)
    with pytest.raises(Exception, match="黑名单文件不存在"):
        chase_load(missing)
    with pytest.raises(Exception, match="黑名单文件不存在"):
        up_load(missing)


def test_none_path_is_a_legitimate_empty_set() -> None:
    """exclude_path=None 是**明确**的"不排除", 仍应返回空集 (不是 fail-fast)。"""
    assert sr_load(None) == set()
    assert chase_load(None) == set()
    assert up_load(None) == set()


def test_shared_blacklist_has_no_duplicates() -> None:
    path = Path(__file__).parent.parent / "data" / "exclude_thscodes.txt"
    lines = [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) == len(set(lines)), "共享黑名单含重复项"
