"""普查工具(**不是门禁**):模块里引用了**未定义名字**的函数 —— 即潜在 `NameError`。

起因(附八十一):`short_reversal/walkforward.py` 的 §5 DSR 段调用 `get_preset(...)`,
而该模块**没有 import 它** ⇒ 那段一执行就 `NameError`,连它后面的 `--out` 落盘也永远走不到。
那条缺陷活了很久,原因是**没有人真的运行过那个脚本**(它不进套件)。

判据(保守,宁少报不多报):
  * 只扫模块级 `def`(含嵌套 def 里的自由名字一起算作"模块级函数用到的名字");
  * "已定义"= 导入名 + 模块级赋值/def/class + 该函数内的赋值/参数/for 目标/with 目标/
    except 名/comprehension 目标 + builtins;
  * 属性名(`x.y`)不算;`self.x` 不算(那是实例属性);
  * 只有**完全没有绑定**的名字才报告。

已知漏报(如实声明):跨模块的动态导入、`globals()[...]`、以及"名字由星号导入提供"
(本仓库没有 `import *`,故不处理)。
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__"}


def _bound_names(node: ast.AST) -> set[str]:
    """node 子树里"被绑定"的名字(赋值/参数/for/with/except/comprehension/import)。"""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            out.add(sub.id)
        elif isinstance(sub, ast.arg):
            out.add(sub.arg)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(sub.name)
        elif isinstance(sub, ast.Import):
            for a in sub.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(sub, ast.ImportFrom):
            for a in sub.names:
                if a.name != "*":
                    out.add(a.asname or a.name)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            out.add(sub.name)
    return out


def find_undefined_names(path: Path) -> list[tuple[str, int, str]]:
    """返回 `[(函数名, 行号, 未定义名), …]`。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    module_bound = _bound_names(tree)
    out: list[tuple[str, int, str]] = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound = module_bound | _bound_names(fn)
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in bound and sub.id not in _BUILTINS:
                    out.append((fn.name, sub.lineno, sub.id))
    return out


def main(argv: list[str] | None = None) -> int:
    total = 0
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(ROOT).parts:
            continue
        hits = find_undefined_names(path)
        if hits:
            total += len(hits)
            print(f"{path.relative_to(ROOT)}:")
            for fn, ln, name in hits:
                print(f"    :{ln}  {fn}()  未定义名 {name!r}")
    print(f"\n共 {total} 处(含少量误报:动态导入 / globals() / 星号导入)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
