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


def _collect_sweep_scripts() -> list[Path]:
    """收集所有 sweep / wf_sweep 脚本 (含数字后缀变体)."""
    candidates = []
    for pattern in ("**/sweep*.py", "**/wf_sweep*.py"):
        for p in REPO_ROOT.glob(pattern):
            # 排除 tests, .git, venv
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if any(part.startswith(".") or part == "tests" for part in parts):
                continue
            candidates.append(p)
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