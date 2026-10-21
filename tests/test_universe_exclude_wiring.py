"""§0/§3 黑名单接线守卫（审计 §6 第 4 条的「未覆盖面」）。

**原状况**（三处叠加，任何一处都足以让黑名单彻底失效）：

1. `short_reversal/universe.py` 的 `DEFAULT_EXCLUDE_PATH` 指向
   `short_reversal/data/exclude_thscodes.txt` —— 该路径**不存在**；
2. 被跟踪的共享黑名单其实在仓库根 `data/exclude_thscodes.txt`（提交于 `ffe29be`），
   于是它**从未被加载**；
3. 模块 docstring 把 no-op 的原因写成"`data/exclude_thscodes.txt` 不存在" ——
   而它存在且被跟踪。**一句错误的说明把后来人引向完全错误的结论**；
4. `_load_exclude` 在路径缺失时**静默返回空集**，于是"要排除 29 只"与
   "排除了 0 只"不可区分。chase_up / uptrend_pullback 的副本同型。

本文件钉住修复后的契约：
  - 共享黑名单存在、无重复项；
  - 默认路径解析到**那个被跟踪的**文件；
  - 黑名单由 `exclude_hs300_zhongtou_finance` 模式门控（名单是大盘金融股，
    属研究口径，不得影响 `mainboard_only` / `broad_only`）；
  - 显式传入缺失路径 → 三个引擎都 fail-fast，不再静默空集。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_BLACKLIST = REPO_ROOT / "data" / "exclude_thscodes.txt"


# ---------------------------------------------------------------------------
# 1) 共享黑名单本身
# ---------------------------------------------------------------------------


def test_shared_blacklist_exists_and_is_tracked() -> None:
    assert SHARED_BLACKLIST.exists(), (
        f"共享黑名单不存在: {SHARED_BLACKLIST} —— "
        "它应被 git 跟踪(见 ffe29be),不是本地产物。"
    )


def test_shared_blacklist_has_no_duplicates() -> None:
    codes = [
        ln.strip() for ln in SHARED_BLACKLIST.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    dups = sorted({c for c in codes if codes.count(c) > 1})
    assert not dups, f"§7/§3: 黑名单含重复代码 {dups} —— 名单漂移的常见起点。"


# ---------------------------------------------------------------------------
# 2) 默认路径必须解析到那个**存在**的文件
# ---------------------------------------------------------------------------


def test_default_exclude_path_resolves_to_the_shared_file() -> None:
    from short_reversal.universe import DEFAULT_EXCLUDE_PATH

    assert Path(DEFAULT_EXCLUDE_PATH).resolve() == SHARED_BLACKLIST.resolve(), (
        f"DEFAULT_EXCLUDE_PATH={DEFAULT_EXCLUDE_PATH} 未指向共享黑名单 "
        f"{SHARED_BLACKLIST} —— 指向一个不存在的路径等于永不加载。"
    )
    assert Path(DEFAULT_EXCLUDE_PATH).exists()


# ---------------------------------------------------------------------------
# 3) 模式门控：只有"以排除命名"的模式才排除
# ---------------------------------------------------------------------------


def test_blacklist_is_gated_on_the_exclusion_mode() -> None:
    from short_reversal.universe import DEFAULT_EXCLUDE_PATH, _resolve_exclude_path

    for mode in ("mainboard_only", "broad_only"):
        assert _resolve_exclude_path(mode, None) is None, (
            f"§2/§3: {mode} 不应应用黑名单 —— 名单是大盘金融股,属**研究口径**;"
            "让它在此生效等于用一次「修 bug」偷偷改掉所有 preset 的股票池。"
        )
    assert (
        Path(_resolve_exclude_path("exclude_hs300_zhongtou_finance", None))
        == Path(DEFAULT_EXCLUDE_PATH)
    ), "以「排除」命名的模式必须真的应用黑名单 —— 模式名是契约,不是装饰。"


def test_exclusion_mode_actually_excludes_a_nonempty_set() -> None:
    """以「排除」命名的模式必须真的排除 —— 模式名不是装饰, 名单不是空文件。

    (「解析到一个路径」≠「真的排除了」: 路径解析对了、名单却读回空集, 正是旧
    缺陷躲过守卫的形态 —— 断言必须落在**非空集**这个前提上。)
    """
    from short_reversal.universe import _load_exclude, _resolve_exclude_path

    path = _resolve_exclude_path("exclude_hs300_zhongtou_finance", None)
    assert path is not None, (
        "exclude_hs300_zhongtou_finance 模式必须解析到黑名单路径"
    )
    assert len(_load_exclude(path)) > 0, (
        "exclude_hs300_zhongtou_finance 模式排除了 0 只 —— 名单没被真的加载"
    )


def test_explicit_path_always_wins() -> None:
    """调用方显式传入路径 → 一律生效(它明说了要排除),不受模式门控影响。"""
    from short_reversal.universe import _resolve_exclude_path

    explicit = REPO_ROOT / "data" / "exclude_thscodes.txt"
    assert _resolve_exclude_path("mainboard_only", explicit) == explicit


# ---------------------------------------------------------------------------
# 4) 要排除却找不到文件 → fail-fast(三引擎一致)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", [
    "short_reversal.universe", "chase_up.universe", "uptrend_pullback.universe",
])
def test_missing_explicit_blacklist_fails_fast(module_path: str) -> None:
    """显式要求的黑名单文件不存在 → 抛错,不得静默变成"排除 0 只"。"""
    import importlib

    from short_reversal import ShortReversalError

    mod = importlib.import_module(module_path)
    missing = REPO_ROOT / "data" / "__no_such_blacklist__.txt"
    expected = ShortReversalError if module_path.startswith("short_reversal") else FileNotFoundError
    with pytest.raises(expected, match="不存在"):
        mod._load_exclude(missing)


def test_absent_path_is_none_means_no_exclusion() -> None:
    """None = 未要求排除 → 空集(这不是静默失败,而是明确的"不排除")。"""
    import importlib

    for module_path in (
        "short_reversal.universe", "chase_up.universe", "uptrend_pullback.universe",
    ):
        mod = importlib.import_module(module_path)
        assert mod._load_exclude(None) == set()
