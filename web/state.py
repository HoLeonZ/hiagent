"""运行产物与账本的落地位置。

单一职责：决定写到哪、并保证不在仓库内。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: 覆盖用环境变量
ENV_HOME = "HIAGENT_PLATFORM_HOME"


def state_home() -> Path:
    """平台状态根目录。默认 `~/.hiagent_platform`。"""
    override = os.environ.get(ENV_HOME)
    return Path(override) if override else Path.home() / ".hiagent_platform"


def assert_outside_repo(path: Path) -> None:
    """断言 `path` 不在 Git 仓库内。

    CLAUDE.md §7：trades.csv / metrics JSON / results/ 必须留在 gitignore 内。
    写到仓库外同时满足 §7，且不受 .gitignore 疏漏影响——
    这正是上一次审计被一个新测试文件的字典键名解除武装的教训。
    """
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, cwd=path if path.exists() else Path.cwd(),
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # 不在仓库内（或没有 git），无需拒绝
    if not root:
        return
    root_p = Path(root).resolve()
    target = path.resolve()
    if target == root_p or root_p in target.parents:
        raise RuntimeError(
            f"state directory {target} is inside the git repository ({root_p}); "
            "run artifacts would be committable — set HIAGENT_PLATFORM_HOME to a path outside the repo"
        )


#: 已验证过的根目录。**每个进程每个路径只验一次**——`assert_outside_repo` 要 fork
#: `git rev-parse`，不该每次调用都付这个代价。
_ASSERTED: set[Path] = set()


def assert_state_writable() -> None:
    """**写盘前的闸**：状态根目录必须在仓库外（§7）。

    为什么要有这一层：`assert_outside_repo` 原先**只在 `run_dir()` 里**被调用，
    而 `trials.py` / `configs.py` 各自 `state_home()` 拼路径、**绕过了它**——
    于是把 `HIAGENT_PLATFORM_HOME` 设成仓库内的路径时，**账本与配置会静默写进仓库**，
    要等到某次提交作业触发 `run_dir()` 才会报错（而那时东西已经写进去了）。

    **闸要设在咽喉处，不是设在一个消费者身上。** 任何写状态的模块都先调它。
    """
    home = state_home()
    if home in _ASSERTED:
        return
    assert_outside_repo(home)
    _ASSERTED.add(home)


def run_dir(run_id: str) -> Path:
    """单次运行的产物目录，不存在则创建。"""
    assert_state_writable()
    d = state_home() / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d
