#!/usr/bin/env python3
"""注册核验: **提交信息声称写了的那个 §, 在文件里真的在吗?**  (2026-10-19, §13.92)

## 为什么要有这个
今天同一个失败模式发生了 **两次** (§13.64 / round 164, 与 §13.91):
写文档的那个 `python3 - <<PY` 因**引号嵌套**语法错**中止**, 而同一个 `bash` 里的
`git add -A && git commit` **照常执行** ⇒ **提交信息声称写了 §13.NN, 而磁盘上 0 处**。
> **"我写了"与"它落盘了"是两件事 —— 而失败时, 退出码与提交信息都不会告诉你。**

同一天还有更广的一族: **编辑/检查工具本身出错** (8 次)。
⇒ 本工具把"回读核验"从**人工纪律**变成**一条命令**。

## 它查什么
对每个提交: 取**主题行里最大的 `§N.M`**, 再到**该提交的** `docs/strategy_mining_log.md` 里
找 `### N.M` 小节标题。**找不到 ⇒ 报"声称写了但不在"**。

## 用法
    python3 tools/verify_registration.py              # 只查 HEAD
    python3 tools/verify_registration.py --all        # 查全部历史
    python3 tools/verify_registration.py --all -n 40  # 最近 40 个
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_REL = "docs/strategy_mining_log.md"
SEC_RE = re.compile(r"§\s*(\d+\.\d+)")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


def _max_section(msg: str) -> str | None:
    """**主题行**里最大的 `§N.M`。

    ⚠️ §13.92 —— 第一版取的是**全信息**里最大的, 于是**假报**了一次:
    `e357897a` 的主题是 `refactor(§6/§3): …` (没有 `N.M` 形式的 §), 而**正文**里写着
    "## 发现 (§13.14 **的形状**)" —— 那是**引用**一个尚未写下的小节, 不是"声称写了"。
    ⇒ 判据收窄为**只看主题行**: 真正"声称写了"的提交, 主题长这样 `fix(§13.91): …`。
    (两条真报都写在主题里; 收窄后它们仍然被抓住。)
    """
    subject = msg.splitlines()[0] if msg.strip() else ""
    hits = SEC_RE.findall(subject)
    if not hits:
        return None
    return max(hits, key=lambda s: (int(s.split(".")[0]), int(s.split(".")[1])))


def _log_at(sha: str) -> str | None:
    try:
        return _git("show", f"{sha}:{LOG_REL}")
    except subprocess.CalledProcessError:
        return None


def check(sha: str) -> tuple[bool, str]:
    msg = _git("log", "-1", "--format=%B", sha).strip()
    sec = _max_section(msg)
    if sec is None:
        return True, f"{sha[:8]}  (信息里没有 §N.M, 跳过)"
    log = _log_at(sha)
    if log is None:
        return True, f"{sha[:8]}  §{sec}  (该提交没有日志文件, 跳过)"
    ok = f"### {sec}" in log
    subject = msg.splitlines()[0][:64]
    if ok:
        return True, f"{sha[:8]}  §{sec}  ✅  {subject}"
    return False, f"{sha[:8]}  §{sec}  ❌ **声称写了, 而该提交的日志里没有**  {subject}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="查全部历史")
    ap.add_argument("-n", type=int, default=0, help="只查最近 N 个")
    ap.add_argument("--expect", default="", help="提交**前**用: 断言这一节已在**工作区**的日志里, 例 --expect 13.92")
    a = ap.parse_args(argv)

    if a.expect:
        log = (REPO / LOG_REL).read_text(encoding="utf-8")
        ok = f"### {a.expect}" in log
        print(f"工作区日志里 {'✅ 有' if ok else '❌ **没有**'} `### {a.expect}`")
        if not ok:
            print(f"⇒ 你正要提交 §{a.expect}, 但它在**磁盘上不存在**。"
                  "\n   (今天这个模式已发生 2 次: 文档脚本语法错中止, 而同一 bash 里的 commit 照跑。)")
            return 1
        return 0

    if not a.all:
        shas = [_git("rev-parse", "HEAD").strip()]
    else:
        args = ["rev-list", "HEAD"] + (["-n", str(a.n)] if a.n else [])
        shas = _git(*args).split()

    bad = []
    for sha in shas:
        ok, line = check(sha)
        if not ok:
            bad.append(line)
    print(f"核验 {len(shas)} 个提交; **声称写了但不在** {len(bad)} 处")
    for line in bad:
        print("   " + line)
    if bad:
        print("\n⇒ 这些提交的**信息与磁盘内容不一致**。补救: 把缺的那段**经文件传递**再写一次,"
              "\n  然后 `grep -c` 回读核验 (别信退出码、别信提交信息)。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
