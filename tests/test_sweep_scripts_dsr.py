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


#: 引擎包 —— sweep 脚本只住在这些目录里。**不**在 `core/`:
#: `core/` 是共享纯函数层,里面任何名字以 `sweep` 开头的文件都是**供 sweep 用的工具**,
#: 不是 sweep 脚本本身。
_ENGINE_PACKAGES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")


def _collect_sweep_scripts() -> list[Path]:
    """收集所有 sweep / wf_sweep 脚本 (含数字后缀变体)。

    §0 (附八十七): 扫描面**限制在引擎包内**。
    此前是仓库级 `REPO_ROOT.glob("**/sweep*.py")`,而本批新增的共享工具
    `core/sweep_axes.py` 名字正好以 `sweep` 开头 ⇒ 被当成"一个有 27 个 combo 却没报 DSR 的
    sweep 脚本"而误报。这是本会话第三次同一个形态(按**文件名前缀**划族,漏/多收了不按
    前缀命名的成员;前两次是 `wf_v*_focused.py` 漏掉 `walkforward.py`、`SCRIPT_GLOBS`
    漏掉 4 个 DSR 调用点)。
    本测试自己的 docstring 早就写明锁定的都是引擎包内的脚本 —— 是 glob 比 docstring 宽。

    Note: 额外 glob `**/grid*.py` 由 test_sweep_dsr_test_coverage_catches_grid_runner
    单独 verify (避免与 uptrend_pullback/grid.py 共触发新 RED)。
    """
    candidates = []
    for pkg in _ENGINE_PACKAGES:
        base = REPO_ROOT / pkg
        if not base.is_dir():
            continue
        for pattern in ("sweep*.py", "wf_sweep*.py"):
            candidates.extend(base.glob(pattern))
    return sorted(candidates)


SWEEP_SCRIPTS = _collect_sweep_scripts()


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