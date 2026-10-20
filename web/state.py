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
    # ⚠️ **缓存键必须是解析后的路径。**
    # 原实现存的是 `state_home()` 的**原始**值。`HIAGENT_PLATFORM_HOME` 可以是相对路径，
    # 于是**同一个字符串**在不同的 cwd 下解析到**不同的目录** —— 而缓存只看字符串。
    # 实测（2026-10-19）：
    #   cwd=/tmp/hp_rel、HOME="../hiagent_evil" → 解析到 /tmp/hiagent_evil（仓库外）→ 放行并缓存
    #   chdir 到仓库根、**同一个 HOME 字符串** → 解析到 <repo>/hiagent_evil（**仓库内**）
    #     → 缓存命中 → **放行**，产物就落进仓库了。
    # 判据是"解析后的路径是否在仓库内"，缓存键就必须是解析后的路径 —— 否则缓存的是**输入**，
    # 而输入在这里恰恰是**会随环境变的那一半**。
    home = state_home().resolve()
    if home in _ASSERTED:
        return
    assert_outside_repo(home)
    _ASSERTED.add(home)


def _under_runs(run_id: str, name: str | None) -> Path:
    """拼出 `runs/<id>[/<name>]` 并**断言它确实在 `runs/` 底下**。

    为什么要有这一层：闸原先只检查 `state_home()` **本身**在不在仓库内，
    却**不知道拼接之后的路径已经跑出去了**。实测（2026-10-19）：
    `run_artifact("../../../../../../etc/hostname", "x")` 解析后落在
    `/private/etc/hostname/x`。

    **今天经 HTTP 到不了**（FastAPI/Starlette 在路由层就拒掉带 `/` 的路径参数，
    三种编码写法实测都是 404）—— 但 `list_runs()` 会拿**账本行里的 run_id**来调它，
    而账本是可以被手改/被损坏的。**靠调用方凑巧安全**正是我已经修过四次的那个形状。

    判据取"**解析后仍在 `runs/` 之下**"，而不是"`run_id` 长得像不像 id"：
    后者会把测试里那些可读的 id（`r1`/`abc123`）一并拒掉，而它并不提供更多保证。
    """
    runs_root = (state_home() / "runs").resolve()
    p = runs_root / run_id if name is None else runs_root / run_id / name
    resolved = p.resolve()
    if resolved != runs_root and runs_root not in resolved.parents:
        raise RuntimeError(
            f"run_id/name escapes the runs directory: {run_id!r} -> {resolved}; "
            f"must stay under {runs_root}"
        )
    return resolved


def run_dir(run_id: str) -> Path:
    """单次运行的产物目录，不存在则创建。**写盘前唯一的 §7 闸。**"""
    assert_state_writable()
    d = _under_runs(run_id, None)
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_artifact(run_id: str, name: str) -> Path:
    """`runs/<id>/<name>` 的路径 —— **布局的单一来源**，供**读**用。

    为什么需要它（2026-10-19 实测）：`runs/<id>` 这个布局当时被**手工拼了 7 处**
    （jobs.py 的 5 处、app.py 的 1 处，加上这里），而**只有 `submit()` 走 `run_dir()`**——
    于是 `_persist_result` 自己是"拼路径 + mkdir + 写"，**没经过闸**。
    今天能安全只是因为 `submit()` 先建好了目录：**靠顺序，不靠结构**。
    下一次有人加一个"别的入口写产物"，闸就被绕过去了 —— 这已经是我第四次修同一个形状。

    **写**一律用 `run_dir()`（它过闸并建目录）；**读**用本函数（不建目录、不开闸）。
    """
    return _under_runs(run_id, name)
