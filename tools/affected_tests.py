#!/usr/bin/env python3
"""改了哪些生产文件 → **该跑哪些测试** (2026-10-19, §13.60)。

## 为什么要有这个
§13.59 记了一次我自己造成的回归: 重构 `short_reversal/lookahead_trade_trace.py` 之后,
两条钉在它身上的测试变红, 而我**七轮之后**才发现 —— 因为那期间我没跑全套件。
**没跑的原因是套件要 37 分钟。**

> **当一条规矩的执行成本很高时, 人会跳过它 —— 而"跳过"的代价会在七轮后以红灯的形式出现。**

⇒ 本工具把那件事变便宜: **只跑与改动文件有关的测试**(通常几秒到一两分钟)。

## 它比"tests 里 import 了谁"更宽一层 —— 而这一层正是必需的
§13.59 那两条钉桩**没有 import 被测的模块**; 它们是用 `inspect.getsourcefile()`
**读源码文本**再正则匹配。所以"找 import"会**漏掉它们**。
⇒ 本工具按**符号名**匹配: 改动文件的顶层类/函数名若在某个测试的**源码里出现过**,
那个测试就入名单。`TraceStrategy` 正是这样被找出来的。

## 用法
    python tools/affected_tests.py                 # 用 git 找改动 (HEAD + 未跟踪)
    python tools/affected_tests.py short_reversal/engine.py ...
    python tools/affected_tests.py --run           # 直接跑 (加在末尾)
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 太短/太通用的名字会引来大量假匹配 —— 宁可漏一点, 也不要给出一份噪声名单。
MIN_SYMBOL_LEN = 5


def changed_files(argv: list[str]) -> list[str]:
    if argv:
        return argv
    out = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    files = []
    for line in out.splitlines():
        path = line[3:].strip()
        if " -> " in path:                      # 重命名
            path = path.split(" -> ")[-1]
        files.append(path)
    return files


def symbols_of(path: Path) -> set[str]:
    """该文件的顶层类名/函数名 (以及模块 basename)。"""
    names: set[str] = set()
    stem = path.stem
    if len(stem) >= MIN_SYMBOL_LEN:
        names.add(stem)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return names
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.name) >= MIN_SYMBOL_LEN and not node.name.startswith("_"):
                names.add(node.name)
    return names


def main(argv: list[str]) -> int:
    do_run = "--run" in argv
    argv = [a for a in argv if a != "--run"]

    prod = [f for f in changed_files(argv) if not f.startswith("tests/")]
    if not prod:
        print("没有改动的生产文件 ⇒ 无需额外跑测试。")
        return 0

    tokens: dict[str, set[str]] = {}
    for rel in prod:
        p = ROOT / rel
        if p.suffix != ".py" or not p.exists():
            continue
        toks = symbols_of(p) | {rel[:-3].replace("/", "."), rel}
        tokens[rel] = toks

    print(f"改动的生产文件 {len(tokens)} 个; 按**符号名/模块路径**在 tests/ 里匹配:")
    for rel, toks in tokens.items():
        print(f"   {rel}  ->   token: {sorted(toks)[:6]}")

    hits: dict[str, set[str]] = {}
    for t in sorted(TESTS.glob("test_*.py")):
        src = t.read_text(encoding="utf-8")
        for rel, toks in tokens.items():
            hit = {tok for tok in toks
                   if re.search(rf"\b{re.escape(tok)}\b", src)}
            if hit:
                hits.setdefault(t.as_posix(), set()).update(hit)

    if not hits:
        print("\n⇒ 没有测试提及这些符号 —— 但仍建议在**改动引擎/工具**后跑一次全套件。")
        return 0

    print(f"\n⇒ 相关测试 {len(hits)} 个 (按 token 命中):")
    for t, toks in sorted(hits.items()):
        print(f"   {t}   ← {sorted(toks)}")

    cmd = [sys.executable, "-m", "pytest", *sorted(hits), "-q"]
    print("\n跑法:\n   " + " ".join(cmd))
    if do_run:
        return subprocess.call(cmd, cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
