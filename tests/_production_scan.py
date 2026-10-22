"""生产侧 Python 文件的**单源**扫描面 —— 供多条审计共用。

## 为什么要有这个模块(附一百三十四 实测)

「哪些 `.py` 算生产代码」这段定义,此前在 **4 个**测试文件里**各写了一份**
(`SCAN_DIRS` + `EXCLUDE_DIR_NAMES` + `_iter_python_files()`):

`test_banned_functions_section1`、`test_fail_fast_deep_scan_section2`、
`test_assert_vs_raise_audit`、`test_exception_specificity_audit`。

四份**并不一致**,实测:

| 文件 | 目录数 | 缺什么 |
|---|---|---|
| `test_banned_functions_section1.py` | 8 | ——(2026-10-15 附十五 补过 `dna_data` / `tools`)|
| `test_fail_fast_deep_scan_section2.py` | 6 | `dna_data`、`tools` |
| `test_exception_specificity_audit.py` | 6 | `dna_data`、`tools` |
| `test_assert_vs_raise_audit.py` | 6 | `dna_data`、`tools`,**且把 `uptrend_pullback` 拼成了 `uptrend_pulback`** |

⇒ 两件事:

1. **附十五 的补丁只落到了 4 份里的 1 份** —— 本册记过的「同一处修法只落到孪生文件之一」形状。
2. 那个拼写错让 `base.exists()` 为假、`except`/`continue` 静默跳过 ⇒ **整个 `uptrend_pullback`
   族在那条审计里从未被扫过**,而那条审计显示为绿。**"未扫到的"与"合规的"看起来一样。**

还有第三件:四份都只扫**写死的目录**,不含**仓库根下的 `.py`** —— 实测漏掉
`hiagent_config.py`(全库唯一的 `DB_PATH` 来源)与 `run_sizing_comparison.py`。

## 口径

从 `git ls-files '*.py'` **派生**,再排除:

* `tests/` 下的 —— 测试**故意**使用生产侧被禁的写法(如构造对抗夹具),它们不是生产代码;
* 文件名以 `test_` 开的 —— 命名约定,可能出现在任何目录。

用 `git ls-files` 而不是 `rglob`,是为了**顺带**尊重 `.gitignore`:虚拟环境、`results/` 之类
按定义就不是"仓库里的生产代码",不该让审计把它们扫进来(而 `rglob` 会把它们全扫)。

**新包、新顶层脚本自动进面** —— 不再需要谁记得去改一份清单(那正是本模块存在的理由)。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 视为**非生产代码**的路径前缀(相对仓库根)。
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = ("tests/",)


def tracked_python_files() -> list[str]:
    """`git ls-files '*.py'` 的结果,仓库相对路径,已排序。"""
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line for line in out.splitlines() if line)


def production_python_files() -> list[Path]:
    """仓库里所有生产侧 `.py` 的绝对路径,按路径排序。"""
    return [
        REPO_ROOT / rel
        for rel in tracked_python_files()
        if not rel.startswith(EXCLUDED_PATH_PREFIXES)
        and not Path(rel).name.startswith("test_")
    ]


#: 视为**开发者工具**(非生产路径)的路径前缀。
#:
#: 与 `EXCLUDED_PATH_PREFIXES` 是两种东西:tests/ 是「测试故意使用被禁写法」,
#: 而这里是「**标准本身不适用于它**」。§0 明写 scan/grid 循环允许
#: "warn-log + continue";这些工具的失败口径是「单项失败继续、末尾由退出码或汇总表报出」。
#:
#: §13.47 已就该裁定实测并记录(在 `test_exception_specificity_audit` 里):
#: 把 tools/ 加进来会新增一批**合法**命中,而当时的判据是**阈值式** ⇒ 后果不是
#: "多一条红",而是"吃掉余量"。合并到当前 main 后实测:该裕度已从 7 处涨到 **13** 处
#: (main 新增了多个 tools/ 脚本),另有 `assert` 式 fail-fast 5 处,同样全在 tools/。
#:
#: 所以面**分两种**,但**在同一处定义**(这才是单源的意义):
#:   * `production_python_files()` —— 全部非测试代码(含 tools/)。§1 禁用函数审计用**这个**:
#:     `bfill` 出现在**生成 panel** 的脚本里,会污染下游**每一个**回测,与它是不是"工具"无关。
#:   * `engine_python_files()` —— 再去掉 tools/。只对**生产路径**立标准的审计用这个
#:     (断言/例外具体性:标准是给引擎与共享层的,不是给开发者脚本的整洁度)。
ENGINE_TOOL_EXCLUDED_PREFIXES: tuple[str, ...] = ("tools/",)


def is_developer_tool(path: Path) -> bool:
    """`path` 是否落在开发者工具范围(接受绝对路径或仓库相对路径)。"""
    rel = (path.relative_to(REPO_ROOT) if path.is_absolute() else path).as_posix()
    return rel.startswith(ENGINE_TOOL_EXCLUDED_PREFIXES)


def engine_python_files() -> list[Path]:
    """生产路径:比 `production_python_files()` 再排除开发者工具。

    ⚠️ 排除是**具名的**(只排 `tools/`),不是白名单 ⇒ 将来新增的顶层目录**默认进面**
    (失败方向是"多报",不是"静默漏报")。
    """
    return [p for p in production_python_files() if not is_developer_tool(p)]
