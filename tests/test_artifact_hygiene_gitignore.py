"""§7 守卫:运行产物必须按**文件名**全局忽略,不能只靠 `results/` 目录。

## 缺陷(审计 §3.3 的 LOW,**本轮复核确认成立**)

`.gitignore` 当时只忽略 `results/` **目录**(以及四个引擎各自的 `<engine>/results/`)。
于是**散落在别处**的同名产物仍然可以被提交:

- `python -m chase_up.main --out .`(产物落到仓库根)
- 手工把 `v5_trades.csv` 复制到别处做对比
- 某个新脚本忘了走 `results/`

而 §7 verbatim:

> "**Results Stay Local:** `results/`, trades.csv, metrics JSON, and generated
> reports MUST remain gitignored. Committing them is a contract violation —
> a fresh clone must contain zero historical performance claims."

目录级忽略挡不住**文件名**,所以这条要求实际上没有被强制执行。

## 修法

补一组**文件名级**全局模式(`trades.csv` / `*_trades.csv` / `equity_curve.csv` /
`cash_walk.csv` / `*_metrics.json` / `backtest.json` / `all_strategies_report*` /
`*_report_*.html`),并核对**不误伤任何已跟踪文件**(tracked 的 html 只有
`short_reversal/docs/d_condition_explained.html`,是文档,不受影响)。

本文件用 `git check-ignore` 断言这些形态**确实**被忽略 —— 即"§7 这条要求被强制执行",
而不是只写在文档里。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: §7 点名必须永不入库的产物形态(含各自的常见命名)。
ARTIFACT_NAMES = [
    "trades.csv",
    "v5_trades.csv",                    # 各引擎的 per-preset 命名
    "equity_curve.csv",
    "cash_walk.csv",
    "metrics.json",
    "v5_metrics.json",                  # per-preset metrics
    "backtest.json",
    "all_strategies_report.json",
    "chase_v5_report_20260101_120000.html",
]


def _is_ignored(rel: str) -> bool:
    return subprocess.run(
        ["git", "check-ignore", "-q", rel], cwd=str(REPO_ROOT)
    ).returncode == 0


@pytest.mark.parametrize("name", ARTIFACT_NAMES)
def test_run_artifact_names_are_ignored_anywhere_in_the_tree(name: str) -> None:
    """§7: 产物按**文件名**忽略 —— 位置不该决定它能不能被提交。"""
    assert _is_ignored(name), (
        f"§7 VIOLATION: `{name}` 在仓库根不被忽略 —— "
        "它可以被提交,而 §7 要求 trades.csv / metrics JSON / 生成的报告永不入库。"
        "只忽略 results/ 目录挡不住散落别处的同名产物。"
    )


def test_directory_level_ignores_are_still_present() -> None:
    """目录级忽略不得被文件名级模式取代(两者互补)。"""
    for d in ("results/", "chase_up/results/", "short_reversal/results/"):
        assert _is_ignored(d), f"§7: {d} 不再被忽略"


def test_no_tracked_file_is_newly_ignored() -> None:
    """补模式不得误伤**已跟踪**文件。

    唯一允许出现在"被忽略但已跟踪"里的,是 `results/` 下的 `.gitkeep` 占位
    (它本就被既有的目录级模式覆盖,是人为 force-add 的)。
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=str(REPO_ROOT), capture_output=True, text=True, check=True
    ).stdout.splitlines()
    ignored = subprocess.run(
        ["git", "check-ignore", "--stdin", "--no-index"],
        cwd=str(REPO_ROOT), input="\n".join(listed), capture_output=True, text=True,
    ).stdout.splitlines()
    unexpected = [p for p in ignored if not p.endswith(".gitkeep")]
    assert not unexpected, f"以下**已跟踪**文件被新规则忽略,必须先取消跟踪:{unexpected}"
