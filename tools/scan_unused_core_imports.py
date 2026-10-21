#!/usr/bin/env python3
"""扫「**导入了 `core.*` 的符号却从未在可执行代码里引用**」 (§13.120, 2026-10-19)。

## 为什么是这一族
本册反复出现「**声明/导入 vs 实际做**」, 而我一直是**一次发现一个**:
§13.83 ("自动套 DSR + Bonferroni" ×23) / §13.95 (`atr_slippage` "用于 chase_up") /
§13.106(e) (`is_list_up` 导入却未调用 + 假称"共用单一来源") / §13.107 ("60d rolling mean") …

## 判据 (**精确版 —— 上一版太吵, 已废弃**)
* **只看 `core.*` 的导入**: `core` 是共享层, 它的符号"导入了没用"信号最强
  (`__future__ import annotations` 是**编译器指令**, 天然排除);
* **只看可执行代码**: 用 AST 取 `ast.Name` 与属性链的**根名**;
  **docstring 是 `ast.Constant`, 不是 `Name`** ⇒ 注释与文档天然不算"引用" ✓;
* **re-export 存根单列**: 若文件里该名字出现在 `__all__` 里, 标 `[reexport]`
  —— 那是**合法**的导入(导入即导出, §13.77 记过 `cycle/walkforward.py` 就是这种)。

## 它**不**判什么
它**判不了**语义(某个名字被"提到"但用别的方式实现)。⇒ 输出是**候选清单**, 要人看。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKGS = ["core", "chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action",
        "dna_stats", "tests", "tools"]


def scan(path: Path) -> list[tuple[int, str, str, bool]]:
    src = path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(src)
    imported: dict[str, tuple[int, str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("core"):
            for a in n.names:
                if a.name == "*":
                    continue
                imported[a.asname or a.name] = (n.lineno, a.name)
    if not imported:
        return []
    used: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            x = n
            while isinstance(x, ast.Attribute):
                x = x.value
            if isinstance(x, ast.Name):
                used.add(x.id)
    # __all__ 里的字符串 —— re-export 的标志
    reexport: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == "__all__" for t in n.targets):
            for e in ast.walk(n.value):
                if isinstance(e, ast.Constant) and isinstance(e.value, str):
                    reexport.add(e.value)
    out = []
    for local, (ln, orig) in sorted(imported.items(), key=lambda kv: kv[1][0]):
        if local in used:
            continue
        out.append((ln, orig, local, orig in reexport))
    return out


def main(argv: list[str]) -> int:
    total = 0
    for pkg in PKGS:
        root = REPO / pkg
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                hits = scan(p)
            except SyntaxError:
                continue
            if not hits:
                continue
            rel = p.relative_to(REPO).as_posix()
            print(f"\n{rel}")
            for ln, orig, local, is_reexport in hits:
                tag = "  [reexport —— 合法]" if is_reexport else "  ⚠️"
                print(f"   行 {ln:>4}: `{orig}` (as `{local}`){tag}")
                total += 0 if is_reexport else 1
    print(f"\n⇒ 非 re-export 的「导入未引用」: **{total}** 处")
    print("⚠️ 这是**候选清单**, 不是判决: 它判不了某个名字是否以别的方式被用到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
