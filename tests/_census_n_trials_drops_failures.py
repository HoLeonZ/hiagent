"""普查工具(**不是门禁**):`n_trials` 是否把**跑失败的配置**从"试过多少次"里剔除了。

起因(附八十二):§5 Iterative-Tuning Accounting 的原话是"每一次迭代都计入"(含失败)。
而多个 sweep 脚本把失败配置记成一行(只带 `error`、不带 Sharpe),然后在算 DSR 时:

    sharpes = df["sharpe"].dropna()                                  # 失败行被剔
    sharpes = [r["Sharpe"] for r in all_rows if r.get("error") is None]  # 显式剔

于是 `n_trials = len(sharpes)` **少计** ⇒ E[max] 偏小 ⇒ **DSR 偏乐观**。
`observed = max(...)` 取成功者的最大是**对的**(选择只在有数的配置间发生),
错的是同一批被喂给 `n_trials`。

判据(针对已观测到的三种形状):
  1. `n_trials=` 的表达式子树里直接出现 `.dropna()` / `.isna()` / 与 `"error"` 的比较;
  2. `n_trials=len(NAME)`,而 `NAME` 在同一函数内被赋值为含上述形状的表达式(浅数据流);
  3. `n_trials=` 的表达式子树里出现 `.get("error")`。

**已知漏报**(如实声明):跨函数的赋值链、以及"用别的名字表达同一件事"(例如先
`ok = [r for r in rows if r['ok']]` 再 `len(ok)`)。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _looks_like_a_success_filter(expr: ast.AST) -> list[str]:
    """子树里"只保留跑成功的那些"的写法。"""
    found: list[str] = []
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Attribute) and f.attr in ("dropna", "isna"):
                found.append(ast.unparse(sub))
            if isinstance(f, ast.Attribute) and f.attr == "get" and sub.args:
                a0 = sub.args[0]
                if isinstance(a0, ast.Constant) and a0.value == "error":
                    found.append(ast.unparse(sub))
        elif isinstance(sub, ast.Compare):
            for c in [sub.left, *sub.comparators]:
                if isinstance(c, ast.Constant) and c.value == "error":
                    found.append(ast.unparse(sub))
    return found


def find_n_trials_that_drop_failures(path: Path) -> list[tuple[int, str]]:
    """返回 `[(行号, 有问题的表达式), …]`。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[int, str]] = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        # 浅数据流:`NAME = <expr>` 在同函数内的赋值(只记第一个,够用且保守)
        assigned: dict[str, ast.AST] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name):
                    assigned.setdefault(t.id, node.value)
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            for kw in call.keywords:
                if kw.arg != "n_trials":
                    continue
                bad = _looks_like_a_success_filter(kw.value)
                if not bad and isinstance(kw.value, ast.Call):
                    f = kw.value.func
                    if (isinstance(f, ast.Name) and f.id == "len"
                            and len(kw.value.args) == 1
                            and isinstance(kw.value.args[0], ast.Name)
                            and kw.value.args[0].id in assigned):
                        bad = _looks_like_a_success_filter(assigned[kw.value.args[0].id])
                for b in bad:
                    out.append((kw.value.lineno, b))
    return out


def main(argv: list[str] | None = None) -> int:
    total = 0
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(ROOT).parts:
            continue
        hits = find_n_trials_that_drop_failures(path)
        if hits:
            total += len(hits)
            print(f"{path.relative_to(ROOT)}:")
            for ln, expr in hits:
                print(f"    :{ln}  n_trials ← {expr}")
    print(f"\n共 {total} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
