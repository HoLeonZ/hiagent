"""运行产物与账本的落地位置。

单一职责：决定写到哪、并保证不在仓库内。
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

#: 覆盖用环境变量
ENV_HOME = "HIAGENT_PLATFORM_HOME"


def state_home() -> Path:
    """平台状态根目录。默认 `~/.hiagent_platform`。"""
    override = os.environ.get(ENV_HOME)
    return Path(override) if override else Path.home() / ".hiagent_platform"


@functools.lru_cache(maxsize=1)      # 仓库根在一个进程里不会变
def repo_root() -> Path | None:
    """本平台所在仓库的根目录。**从本文件的位置推出，不依赖 cwd。**

    为什么不能靠 cwd 或 `git rev-parse`：平台可以从任意目录启动（`cwd=/` 是一例），
    那时 `git rev-parse` 失败，而"失败"被当成"不在仓库内"→ **闸静默放行**，
    账本照样落进仓库。**闸的判据不能依赖调用者的 cwd**——那等于把闸交给环境。

    顺带：不再 fork 子进程，每次调用都快。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():   # 普通仓库是目录；worktree 里 .git 是文件，exists 两者都覆盖
            return parent
    return None


def assert_outside_repo(path: Path) -> None:
    """断言 `path` 不在 Git 仓库内。

    CLAUDE.md §7：trades.csv / metrics JSON / results/ 必须留在 gitignore 内。
    写到仓库外同时满足 §7，且不受 .gitignore 疏漏影响——
    这正是上一次审计被一个新测试文件的字典键名解除武装的教训。
    """
    root = repo_root()
    if root is None:
        return          # 本文件不在任何仓库内（例如被拷到别处运行）——没有可违反的 §7
    target = path.resolve()
    if target == root or root in target.parents:
        raise RuntimeError(
            f"state directory {target} is inside the git repository ({root}); "
            "run artifacts would be committable — set HIAGENT_PLATFORM_HOME to a path outside the repo"
        )


#: 已验证过的根目录。**每个进程每个路径只验一次**——写盘路径每次调用都要过闸，
#: 而 `path.resolve()` 会打真实文件系统（网络盘/软链上不免费），验过就不必重复付。
#: 注意这里缓存的是**结果**、不是判据：判据（`repo_root`）本身来自本文件位置，不受环境变化影响。
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
