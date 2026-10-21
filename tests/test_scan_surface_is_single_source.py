"""扫描面必须**单源**,且真的盖住全部生产侧 `.py`(附一百三十四)。

## 背景(实测)

「哪些 `.py` 算生产代码」这段定义此前在 **4 个**测试文件里各写一份,四份**不一致**:

| 文件 | 面里的文件数 | 缺什么 |
|---|---|---|
| `test_banned_functions_section1.py` | 120 | ——(附十五 补过 `dna_data` / `tools`)|
| `test_fail_fast_deep_scan_section2.py` | 112 | `dna_data`、`tools` |
| `test_exception_specificity_audit.py` | 112 | `dna_data`、`tools` |
| `test_assert_vs_raise_audit.py` | **84** | `dna_data`、`tools`,并把 `uptrend_pullback` 拼成 `uptrend_pulback` |

最后那个拼写错让 `base.exists()` 为假、异常分支里静默 `continue` ⇒ **整个 `uptrend_pullback`
族在那条审计里从未被扫过**,而那条审计显示为绿 —— **"未扫到的"与"合规的"看起来一样**。
四份也都不含**仓库根下的 `.py`**:漏掉 `hiagent_config.py`(全库唯一的 `DB_PATH` 来源)与
`run_sizing_comparison.py`。

现在面由 `tests/_production_scan.py` **单源**提供,四份统一为 **122**。本文件钉住"它不许退回去"。
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from tests._production_scan import (
    EXCLUDED_PATH_PREFIXES,
    REPO_ROOT,
    production_python_files,
)

_ENGINE_FAMILIES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

#: 审计**不许**再自带的扫描面定义(名字是历史包袱,但正是它们分叉成 4 份)。
_BANNED_SURFACE_NAMES = ("_iter_python_files", "_iter_production_files")
_BANNED_SURFACE_ASSIGN = "SCAN_DIRS"


def _tracked_python() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line for line in out.splitlines() if line)


def test_the_shared_surface_covers_every_tracked_production_file() -> None:
    """面 == 总体。总体在这里**独立**算一遍(不走 `_production_scan` 的函数)——
    于是把面改回写死清单时,这条会红。
    """
    expected = {
        rel for rel in _tracked_python()
        if not rel.startswith(EXCLUDED_PATH_PREFIXES)
        and not Path(rel).name.startswith("test_")
    }
    surface = {str(p.relative_to(REPO_ROOT)) for p in production_python_files()}
    assert surface, "扫描面是空的 —— 下面两条会恒真"
    missing = sorted(expected - surface)
    assert not missing, f"这些生产侧文件不在扫描面上(面又被写窄了):{missing}"
    unexpected = sorted(surface - expected)
    assert not unexpected, f"扫描面里混进了非生产侧文件:{unexpected}"


def test_no_audit_defines_its_own_scan_surface() -> None:
    """**单源**:审计不许再自带一份目录清单(那正是分叉成 4 份的原因)。"""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "tests").glob("*.py")):
        if path.name.startswith("_") or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == _BANNED_SURFACE_ASSIGN
                for target in node.targets
            ):
                offenders.append(f"{path.name}:{node.lineno} 自己定义了 {_BANNED_SURFACE_ASSIGN}")
            if isinstance(node, ast.FunctionDef) and node.name in _BANNED_SURFACE_NAMES:
                offenders.append(f"{path.name}:{node.lineno} 自己定义了 {node.name}()")
    assert not offenders, (
        "扫描面必须单源(`tests/_production_scan.py`),这些地方又自己写了一份:\n  "
        + "\n  ".join(offenders)
    )


def test_the_surface_reaches_every_engine_family() -> None:
    """面不许**静默少一族** —— 拼写错曾经让 `uptrend_pullback` 整族掉出某条审计。"""
    tops = {p.relative_to(REPO_ROOT).parts[0] for p in production_python_files()}
    missing = sorted(set(_ENGINE_FAMILIES) - tops)
    assert not missing, f"这些策略族在扫描面上一个文件都没有:{missing}"


def test_every_production_file_exists_and_parses() -> None:
    """**静默跳过的反面**:四个审计的迭代函数都在 `except ...: continue` 里吞掉解析失败 ——
    那会让"扫不到的"与"合规的"看起来一样。实测今天 0 个失败 ⇒ 把它钉成 0 是安全的。

    (顺带当工作树体检:被 git 跟踪、却不在盘上的文件 = 索引与工作树不一致。)
    """
    problems: list[str] = []
    for path in production_python_files():
        rel = path.relative_to(REPO_ROOT)
        if not path.is_file():
            problems.append(f"{rel}: 被 git 跟踪,但盘上不存在")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            problems.append(f"{rel}: {type(exc).__name__}: {exc}")
    assert not problems, (
        "生产侧文件有不能解析(或不在盘上)的 —— 四个审计都会**静默跳过**它们:\n  "
        + "\n  ".join(problems)
    )
