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

import ast
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

#: §5 惩罚指标的单一来源。
_DEFLATED_MODULE = "dna_stats.deflated"
_PENALTY_SYMBOLS = frozenset({"deflated_sharpe_ratio", "bonferroni_correct"})


def _imports_deflated(tree: ast.AST) -> bool:
    """是否**真的导入**了 `dna_stats.deflated`(模块式或 from 式)。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == _DEFLATED_MODULE for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == _DEFLATED_MODULE:
            return True
    return False


def _local_penalty_names(tree: ast.AST) -> set[str]:
    """从该模块导入的符号在本文件里的**本地名**(处理 `as` 别名与 `import *`)。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _DEFLATED_MODULE:
            for alias in node.names:
                if alias.name in _PENALTY_SYMBOLS or alias.name == "*":
                    names.add(alias.asname or alias.name)
    return names


def _calls_penalty_metric(tree: ast.AST) -> bool:
    """源码里是否**真的调用**了惩罚指标(接受别名与 `dna_stats.deflated.xxx(...)`)。"""
    local = _local_penalty_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in local:
            return True
        if isinstance(func, ast.Attribute) and func.attr in _PENALTY_SYMBOLS:
            return True
    return False


class TestSweepScriptsDsrContract:
    """CLAUDE.md §5: 每个 sweep 脚本必须使用 dna_stats.deflated (DSR / Bonferroni)."""

    @pytest.mark.parametrize("sweep_path", SWEEP_SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_sweep_references_dna_stats_deflated(self, sweep_path: Path):
        """每个 sweep 脚本必须**导入并调用** dna_stats.deflated 的惩罚指标。

        附一百三十九(2026-10-21)改:原判据是**文本子串**,三条分支各有一处漏洞 ——

        * `has_dsr_call` 里有 `or "DSR" in source` ⇒ 文件里**任何地方**出现这三个字母
          (注释 / 文档串 / 无关标识符)都算"用了 DSR";
        * 而整体是 `import **or** call` ⇒ 一个**既不 import 也不调用**、只在注释里写了
          `# DSR` 的 sweep 脚本**照样通过**;
        * 另两条分支同样可被注释满足。

        现改为 **AST**:必须(1)从 `dna_stats.deflated` 导入,且(2)源码里**真的有调用**
        (接受 `as` 别名与 `dna_stats.deflated.xxx(...)` 限定名)。
        实测:全部 10 个被收脚本在**旧口径与新的严格口径下都通过** ⇒ 收紧不产生假红。
        """
        tree = ast.parse(sweep_path.read_text(encoding="utf-8"))
        imported = _imports_deflated(tree)
        called = _calls_penalty_metric(tree)
        assert imported and called, (
            f"CLAUDE.md §5 violation: {sweep_path.relative_to(REPO_ROOT)} "
            f"未**导入并调用** dna_stats.deflated(imported={imported}, called={called})。"
            "多参数 sweep 必须报告 deflated_sharpe_ratio 或 bonferroni_correct 以校正 selection bias;"
            "**注释里提到不算**。"
        )


class TestSweepScriptInventory:
    """Inventory check — make sure test discovers at least one sweep script."""

    def test_at_least_one_sweep_script_collected(self):
        """至少要发现一个 sweep 脚本, 否则测试设置错误."""
        assert len(SWEEP_SCRIPTS) >= 1, (
            "未发现任何 sweep 脚本, 请检查 glob pattern 或文件位置"
        )


def test_the_penalty_metric_criterion_has_teeth() -> None:
    """**牙齿**:两个方向各测 —— 注释不算「用了 DSR」;四种合法写法都算。

    (与线上判据**共用**同一批 AST helper,故这里钉的就是那条口径。)
    """
    consuming = [
        "from dna_stats.deflated import deflated_sharpe_ratio\ndsr = deflated_sharpe_ratio([])",
        "import dna_stats.deflated\nx = dna_stats.deflated.deflated_sharpe_ratio([])",
        "from dna_stats.deflated import deflated_sharpe_ratio as dsr\nx = dsr([])",
        "from dna_stats.deflated import bonferroni_correct\nx = bonferroni_correct([], 3)",
    ]
    false_red = [
        src for src in consuming
        if not (_imports_deflated(ast.parse(src)) and _calls_penalty_metric(ast.parse(src)))
    ]
    assert not false_red, f"这些**合法写法**被判成未使用(假红):{false_red}"

    not_consuming = [
        "# DSR\n",                                                    # 只有注释
        "# from dna_stats.deflated import deflated_sharpe_ratio\n",    # 注释里的 import
        "# 这里以后要调用 deflated_sharpe_ratio 校正 selection bias\n",  # 注释里的整句话
        "from dna_stats.deflated import deflated_sharpe_ratio\n",     # 只导入,不调用
        "def dsr():\n    pass\nx = dsr()\n",                          # 自造同名函数
    ]
    false_green = [
        src for src in not_consuming
        if _imports_deflated(ast.parse(src)) and _calls_penalty_metric(ast.parse(src))
    ]
    assert not false_green, f"这些**并没有使用**却被判成使用(假绿):{false_green}"