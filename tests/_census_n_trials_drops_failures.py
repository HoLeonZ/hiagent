"""普查工具(**不是门禁**):`n_trials` 是否把**跑失败的配置**从"试过多少次"里剔除了。

起因(附八十二):§5 Iterative-Tuning Accounting 的原话是"每一次迭代都计入"(含失败)。
而多个 sweep 脚本把失败配置记成一行(只带 `error`、不带 Sharpe),然后在算 DSR 时:

    sharpes = df["sharpe"].dropna()                                  # 失败行被剔
    sharpes = [r["Sharpe"] for r in all_rows if r.get("error") is None]  # 显式剔

于是 `n_trials = len(sharpes)` **少计** ⇒ E[max] 偏小 ⇒ **DSR 偏乐观**。
`observed = max(...)` 取成功者的最大是**对的**(选择只在有数的配置间发生),
错的是同一批被喂给 `n_trials`。

判据(针对已观测到的四种形状):
  1. `n_trials=` 的表达式子树里直接出现 `.dropna()` / `.isna()` / 与 `"error"` 的比较;
  2. `n_trials=len(NAME)`,而 `NAME` 在同一函数内被赋值为含上述形状的表达式(浅数据流);
  3. `n_trials=` 的表达式子树里出现 `.get("error")`;
  4. `n_trials = len(NAME)` / `n_trials=len(NAME)`,而同一函数里有个 `for` 循环**既** `continue`(跳过) **又**
     `NAME.append/extend(...)`,且 `continue` 在 append **之前** —— 即"崩掉的配置不进 NAME"
     (`uptrend_pullback/iter_reverse.py` 就是这个形状:它跨在 `score_windows()`
     与汇总之间,前三条判据都看不见)。

**已知漏报**(如实声明):跨函数的赋值链;用别的名字表达同一件事(如 `ok = [r for r in rows
if r['ok']]`);以及"失败项根本不在这个集合里"的语义型漏计(`chase_up/sweep_all.py`
把失败项放进 `failed` 列表 —— 没有任何表达式特征可抓,只能靠读)。

**判据 4 的取舍**:它只认"同一个函数内、同一个循环里"的 `continue`+append。
`uptrend_pullback/sweep_v33_long*.py` 那 6 处的 `continue` 在 `sweep()` 里、而 `n_trials=len(sharpes)`
在 `main()` 里(跨函数)—— **这一条抓不到那 6 处**(它们是被判据 1 抓住的,因为
`sharpes` 由 `df["sharpe"].dropna()` 而来)。跨函数的数据流不打算做:误报风险大于收益。
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


def _fields_skipped_on_continue(fn: ast.AST) -> set[str]:
    """同一函数里"循环内先 `continue`、后 `NAME.append/extend(...)`"的那些 NAME。

    即:崩掉/被跳过的那些元素**不进 NAME** ⇒ `len(NAME)` 不是"试过多少"。
    """
    out: set[str] = set()
    for loop in ast.walk(fn):
        if not isinstance(loop, (ast.For, ast.While)):
            continue
        cont_lines = [n.lineno for n in ast.walk(loop) if isinstance(n, ast.Continue)]
        if not cont_lines:
            continue
        for sub in ast.walk(loop):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if (isinstance(f, ast.Attribute) and f.attr in ("append", "extend")
                    and isinstance(f.value, ast.Name)):
                # `continue` 在 append **之前**:循环体的这一轮会跳过 append
                if any(cl < sub.lineno for cl in cont_lines):
                    out.add(f.value.id)
    return out


def _candidate_exprs(fn: ast.AST) -> list[tuple[int, ast.AST]]:
    """函数里所有"决定了 `n_trials` 取值"的表达式。

    两种写法都要看(**这是本工具第一次失手的地方**:只扫调用点的 `n_trials=` 关键字,
    就漏掉了 `n_trials = len(rows)` 这种**先赋值、再传进去**的写法 —— 正是附六十
    那次守卫失效的同一个坑:只看调用点表达式,漏掉"先算好再传"的形状):
      * `f(..., n_trials=<expr>)`
      * `n_trials = <expr>`
    """
    out: list[tuple[int, ast.AST]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "n_trials":
                    out.append((kw.value.lineno, kw.value))
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "n_trials" for t in node.targets):
                out.append((node.value.lineno, node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "n_trials":
                out.append((node.value.lineno, node.value))
    return out


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
        skipped = _fields_skipped_on_continue(fn)
        for lineno, value in _candidate_exprs(fn):
            bad = _looks_like_a_success_filter(value)
            if not bad and isinstance(value, ast.Call):
                f = value.func
                if (isinstance(f, ast.Name) and f.id == "len"
                        and len(value.args) == 1
                        and isinstance(value.args[0], ast.Name)):
                    nm = value.args[0].id
                    if nm in assigned:
                        bad = _looks_like_a_success_filter(assigned[nm])
                    if not bad and nm in skipped:
                        bad = [f"len({nm}) —— 而 {nm} 所在的循环里有 `continue` 跳过 append"]
            for b in bad:
                out.append((lineno, b))
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
