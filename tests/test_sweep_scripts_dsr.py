"""CLAUDE.md §5 Penalty Metrics audit — sweep scripts.

CLAUDE.md §5 铁律: "Evaluation scripts must output Deflated Sharpe Ratio (DSR)
or apply Bonferroni corrections when reporting backtest results from
multi-parameter sweeps."

本测试锁定所有 sweep / wf_sweep 脚本必须 import dna_stats.deflated 模块
(DSR / Bonferroni 输出), 任何 sweep 脚本不引用 §5 penalty metrics 必然 RED.

锁定 sweep 脚本:
  - chase_up/sweep.py
  - chase_up/sweep_all.py
  - chase_up/wf_sweep_all.py
  - uptrend_pullback/sweep_v33_long*.py (6 files)
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# ⚠️⚠️ 2026-10-19 (§13.101): 这里此前写着一句
#   「额外 glob `**/grid*.py` 由 test_sweep_dsr_test_coverage_catches_grid_runner 单独 verify」
# —— **而那句话是自指的**: 那条 "单独 verify" 的测试本身就是一个 RED 前向防御, 它断言的是
# "本文件的 glob 漏了 `**/grid*.py`"。**用一条"断言这里有洞"的测试, 给这个洞当覆盖证明。**
# 更糟的是那条测试的判据是**整文件文本正则** ⇒ 上面**这句描述洞的注释本身就满足了它**
# ⇒ 它**恒绿, 从来没红过** (§13.78 的同一形态: 判据的单位是文本, 注释算数)。
# ⇒ 已把 glob **真的**扩到 `**/grid*.py` (这正是那条 RED 测试自己写明的 GREEN fix)。
_EXTRA_GLOBS = ("**/grid*.py",)

# 具名豁免 (**自失效**): 见下方 _XFAIL_SCRIPTS 的 strict xfail。
_XFAIL = {
    "uptrend_pullback/grid.py": (
        "§13.101: 真实的 `itertools.product` 网格搜索, 却**没有任何 §5 惩罚指标**。"
        "补它卡在一个**口径选择**上 —— 共享报告器 `format_walkforward_stats` 里 "
        "`n_returns = max(n_windows * 63, 100)` **把「2 个月窗口」硬编码进了共享函数**; "
        "而本脚本用**1 年**窗口 ⇒ 直接复用会把 DSR 算错约 4 倍。"
        "⇒ 待窗口长度成为**显式参数**后再补 (已登记)。"
        "⚠️ **本豁免自失效**: 一旦 grid.py 出现 §5 指标, 下面的 strict xfail 会 XPASS ⇒ 红。"
    ),
}


def _collect_sweep_scripts() -> list[Path]:
    """收集所有 sweep / wf_sweep / **grid** 脚本 (含数字后缀变体)."""
    candidates = []
    for pattern in ("**/sweep*.py", "**/wf_sweep*.py", *_EXTRA_GLOBS):
        for p in REPO_ROOT.glob(pattern):
            # 排除 tests, .git, venv
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if any(part.startswith(".") or part == "tests" for part in parts):
                continue
            candidates.append(p)
    return sorted(set(candidates))


_ALL = _collect_sweep_scripts()
SWEEP_SCRIPTS = [p for p in _ALL if p.relative_to(REPO_ROOT).as_posix() not in _XFAIL]
XFAIL_SCRIPTS = [p for p in _ALL if p.relative_to(REPO_ROOT).as_posix() in _XFAIL]


class TestSweepScriptsDsrContract:
    """CLAUDE.md §5: 每个 sweep 脚本必须使用 dna_stats.deflated (DSR / Bonferroni)."""

    @pytest.mark.parametrize("sweep_path", SWEEP_SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_sweep_references_dna_stats_deflated(self, sweep_path: Path):
        """每个 sweep 脚本必须 import dna_stats.deflated 模块.

        Symbols expected: deflated_sharpe_ratio, bonferroni_correct, or
        a `from dna_stats.deflated import ...` statement.
        """
        source = sweep_path.read_text()
        has_dsr_import = (
            "from dna_stats.deflated" in source
            or "import dna_stats.deflated" in source
        )
        has_dsr_call = (
            "deflated_sharpe_ratio" in source
            or "bonferroni_correct" in source
            or "DSR" in source
        )
        assert has_dsr_import or has_dsr_call, (
            f"CLAUDE.md §5 violation: {sweep_path.relative_to(REPO_ROOT)} "
            f"未引用 dna_stats.deflated (DSR / Bonferroni). "
            f"多参数 sweep 必须报告 deflated_sharpe_ratio 或 bonferroni_correct "
            f"以校正 selection bias."
        )


class TestSweepScriptInventory:
    """Inventory check — make sure test discovers at least one sweep script."""

    def test_at_least_one_sweep_script_collected(self):
        """至少要发现一个 sweep 脚本, 否则测试设置错误."""
        assert len(SWEEP_SCRIPTS) >= 1, (
            "未发现任何 sweep 脚本, 请检查 glob pattern 或文件位置"
        )


class TestKnownGapsAreExplicitAndSelfInvalidating:
    """§13.101: 已知缺口必须**具名 + 自失效**, 不得靠"注释里提过"来当覆盖。

    ⚠️ 用 `strict=True`: 一旦这些文件真的有了 §5 指标, 测试会 **XPASS ⇒ 红**,
    逼人回来删掉豁免。**豁免若不设过期条件, 它就是永久的盲区。**
    """

    @pytest.mark.parametrize("sweep_path", XFAIL_SCRIPTS,
                             ids=lambda p: str(p.relative_to(REPO_ROOT)))
    @pytest.mark.xfail(strict=True, reason="见 _XFAIL: 已知缺口, 待口径决定")
    def test_known_gap_still_lacks_s5_metrics(self, sweep_path: Path):
        source = sweep_path.read_text(encoding="utf-8")
        has_any = (
            "deflated_sharpe_ratio" in source
            or "bonferroni_correct" in source
            or "from dna_stats.deflated" in source
        )
        assert has_any, (
            f"{sweep_path.relative_to(REPO_ROOT)} 仍无 §5 指标 —— 这是**已知缺口**, "
            f"理由见 _XFAIL。若已补上, 本测试会 XPASS ⇒ 请删掉 _XFAIL 里那一条。"
        )

    def test_the_xfail_set_is_not_empty_and_the_main_set_still_has_coverage(self):
        """反空转: 两组都必须非空, 且**主力那组不得被豁免吞光**。"""
        assert XFAIL_SCRIPTS, "豁免集为空 ⇒ 这条测试在空转"
        assert len(SWEEP_SCRIPTS) >= len(XFAIL_SCRIPTS), (
            f"豁免 {len(XFAIL_SCRIPTS)} 个 vs 主力 {len(SWEEP_SCRIPTS)} 个 —— 豁免吞太多了"
        )
