"""普查工具(**不是门禁**):断言"源码里有某词"、而那个词只出现在**注释/docstring** 里的守卫。

用法:
    python3 tests/_census_comment_guards.py        # 打印候选,人工分类

## 为什么要有这个形状的检测器

本会话里我**亲手**踩过两次同一个形状:
  * 附五十七:`replay_broker.py` 里找 "RuntimeError",而该文件**没有** raise(只有注释);
  * 附七十六:我新写的更正说明里含 "backward-adjusted",于是把描述行改回错标后守卫**仍然绿**。
两次都是"判词不判事"。这个工具把那一类**机械化**地列出来。

## 已知误报模式(必须人工分类,别当成结论)

**当守卫的主题本身就是注释时,它必然命中**:

  * `test_fail_fast_cross_engine.py` 断言那些 sweep 脚本带 `# noqa: BLE001` ——
    那个 token **按设计**就在注释里;
  * `test_dual_view_semantics.py` 断言加载器 docstring 的**措辞** —— 主题就是文档。

故本工具只**列候选**,不判对错。(2026-10-18 实跑:4 个候选,全部属上述两类误报,
无真实空转守卫 —— 两处真实的已在附五十七/七十六 修掉。)

## 牙齿

`tests/test_census_detector_has_teeth.py` 会把"真形状"种进临时树并断言本工具能认出来 ——
**没有那条,本工具返回 0 时无法区分"代码干净"与"检测器坏了"**(第一版就坏在
只认双引号的正则上,过滤掉了全部单引号路径,当时报的就是 0)。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _strip_comments_and_docstrings(src: str) -> str:
    """把注释与 docstring 抹掉,其余源码保留(保留行号以便定位)。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    lines = src.splitlines()
    kill: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                d = body[0]
                for ln in range(d.lineno, (d.end_lineno or d.lineno) + 1):
                    kill.add(ln)
    out = []
    for i, ln in enumerate(lines, 1):
        if i in kill:
            out.append("")
            continue
        if "#" in ln:
            head = ln.split("#")[0]
            if head.count('"') % 2 == 0 and head.count("'") % 2 == 0:
                ln = head
        out.append(ln)
    return "\n".join(out)


_QUOTED_PY = re.compile(r"""['"]([^'"\n]+\.py)['"]""")


def _file_consts(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            segs = _QUOTED_PY.findall(ast.unparse(node.value))
            if segs:
                out[node.targets[0].id] = segs[-1]
    return out


def find_comment_only_guards(
    tests_dir: Path, repo_root: Path
) -> list[tuple[str, str, str, str, int]]:
    """返回 `[(测试文件, 函数名, 目标文件, token, 行号), …]`。

    只挑 `assert "<token>" in <源码文本>` 这种形状;再要求该 token 在目标文件里
    **去注释/docstring 后不存在、原文里存在**。
    """
    hits: list[tuple[str, str, str, str, int]] = []
    for tp in sorted(tests_dir.glob("*.py")):
        try:
            tree = ast.parse(tp.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        consts = _file_consts(tree)
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            targets: set[str] = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "read_text":
                    segs = _QUOTED_PY.findall(ast.unparse(node.func.value))
                    if segs:
                        targets.add(segs[-1])
                if isinstance(node, ast.Name) and node.id in consts:
                    targets.add(consts[node.id])
            if not targets:
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
                    continue
                cmp = node.test
                if not (isinstance(cmp.left, ast.Constant)
                        and isinstance(cmp.left.value, str)
                        and len(cmp.left.value) >= 3):
                    continue
                if not (len(cmp.ops) == 1 and isinstance(cmp.ops[0], ast.In)):
                    continue
                token = cmp.left.value
                for tgt in sorted(targets):
                    for cand in repo_root.rglob(Path(tgt).name):
                        if "tests" in cand.relative_to(repo_root).parts:
                            continue
                        try:
                            raw = cand.read_text(encoding="utf-8")
                        except (OSError, UnicodeDecodeError):
                            continue
                        if token in raw and token not in _strip_comments_and_docstrings(raw):
                            hits.append((str(tp.name), fn.name, tgt, token, node.lineno))
    return hits


def main(argv: list[str] | None = None) -> int:
    hits = find_comment_only_guards(ROOT / "tests", ROOT)
    print(f"候选(断言 'token in 源码',而 token 只在注释/docstring 里):{len(hits)}\n")
    for f, fn, tgt, tok, ln in hits:
        print(f"  tests/{f}:{ln}  [{fn}]  {tgt}   token={tok!r}")
    print("\n⚠ 候选**不是结论**:守卫的主题若本身就是注释(`# noqa: …`、docstring 措辞),"
          "\n   它必然命中。逐条人工分类。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
