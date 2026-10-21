"""普查: 文本钉桩**指向的文件**是不是它以为的那个文件 (§13.122)。

动机
----
2026-10-19 分拣 §13.121 的 B 类失败时抓到一条:
    `tests/test_short_reversal_trailing_no_lookahead.py` 的 6 条钉桩
    全部读 `short_reversal/engine.py`, 而浮动止损的**全部**实现
    (`prev_lowest` / `lowest_price` / `trailing_stop_pct`) 住在
    `short_reversal/replay_strategy_v3.py` —— 钉桩页面上一个字都没有。
    ⇒ 这个文件**永远不可能通过**, 与它守的东西在不在无关。

这是 §13.20/§13.21「跑了却不可能失败的守卫」的**对偶**:
    跑了却**不可能通过**的守卫 —— 看起来是覆盖, 实际上零信息量。

判据 (带牙齿, 不是"有没有写 assert")
------------------------------------
对每个测试文件做**局部静态求值**: 把模块级 `NAME = ...read_text(...)` 里的路径
算出来, 再收集 `assert "<LIT>" in NAME` / `not in NAME`, 拿 LIT 到**那个文件**
里找:

  * `"LIT" in SRC`  而 LIT **不在**文件里 ⇒ **死钉桩**(永不可能通过)
  * `"LIT" not in SRC` 而 LIT **在**文件里 ⇒ **死钉桩**(永不可能通过)

⚠️ 只报**当前为真**的这一类。`in` 命中 / `not in` 未命中都是正常的**活**钉桩,
不报 —— 否则清单会淹没在噪音里, 那就又变成"没有牙齿的普查"。

⚠️ **本工具只报, 不改。** 修一条死钉桩要先判定是"钉错了文件"还是"代码搬走了",
那是口径决定, 按长期授权属于**先登记**的一类。

用法:
    python3 tools/scan_dead_text_pins.py            # 全 tests/
    python3 tools/scan_dead_text_pins.py --verbose  # 连活钉桩计数一起打
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 允许出现在 read_text 之前的表达式形态 (只为我们自己的测试文件服务)
_SAFE_CALLS = {"Path", "read_text", "read_bytes", "resolve", "joinpath", "open"}


def _ambig_names(scope: ast.AST, body: list[ast.stmt]) -> set[str]:
    """在 `scope` 的**整个子树**里被赋多次的名字 (拿不准就不收)。

    ⚠️ 只看直接子节点不够 —— `s = (ROOT / rel).read_text(...)` 住在 for 体里,
    直接子节点只有循环之后那一次赋值 ⇒ 计数=1 ⇒ 被当成唯一值,
    于是拿 chase 的字面量去 allocator.py 里找, 把**活的**判成死的 (实测)。
    """
    counts: dict[str, int] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    counts[tgt.id] = counts.get(tgt.id, 0) + 1
    # 复合赋值 (+= 等) 也算第二次写
    for node in ast.walk(scope):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            counts[node.target.id] = counts.get(node.target.id, 0) + 1
    out = {k for k, v in counts.items() if v > 1}
    # 函数参数也是"已经存在"的名字, 再赋值即歧义
    for node in ast.walk(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for a in list(node.args.args) + list(node.args.kwonlyargs):
                if a.arg in counts:
                    out.add(a.arg)
    return out



def _bind_local_imports(node: ast.AST, ns: dict) -> None:
    """把作用域内的 import 绑进 ns (只绑真实存在的模块名, 失败就跳过)。"""
    import importlib

    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for a in sub.names:
                mod = a.asname or a.name.split(".")[0]
                if mod in ns:
                    continue
                try:
                    ns[mod] = importlib.import_module(a.name)
                except Exception:
                    continue
        elif isinstance(sub, ast.ImportFrom) and sub.module:
            for a in sub.names:
                mod = a.asname or a.name
                if mod in ns:
                    continue
                try:
                    ns[mod] = getattr(importlib.import_module(sub.module), a.name)
                except Exception:
                    continue


def _resolve_assigns(assigns: list[ast.stmt], ns: dict,
                     ambiguous: set[str] | None = None) -> dict:
    """迭代求值一组赋值, 直到不动点。

    **健全性 > 覆盖率** (§13.122)。本工具只报"死钉桩", 而**误报**会让人去改一条
    本来好的守卫 —— 比漏报更坏。所以两条硬规则, 拿不准就**不进 ns**(=跳过):

    ① **只接受「文件路径」或「读进来的正文」**。`params_block = src[a:b]` 这种
       派生串一律不收 —— 实测它被求成了一个空串(因为 `end` 定义在 for 里),
       于是把一条**活的**断言 `assert "initial_capital" in params_block` 判成了死。
    ② **同一个名字在同一作用域里赋多次 ⇒ 整个不收**。实测:
         for rel in (...):
             s = (ROOT / rel).read_text(...)
             assert "rets = np.diff(eq) / eq[:-1]" in s
         s = (ROOT / "cycle_price_action" / "allocator.py").read_text(...)
       `s` 被解成**最后一个**(allocator), 于是拿 chase 的字面量去 allocator 里找
       ⇒ 又一次把活的判成死的。
    """
    # 函数体内的 `import pathlib` / `from pathlib import Path` 也要认 ——
    # 否则 `s = pathlib.Path(__file__).read_text(...)` 这一形态完全解析不出来
    # (实测: 注入到函数里会被漏掉, 那**不是**判据有牙, 是判据没看见)。
    for node in assigns:
        _bind_local_imports(node, ns)

    counts: dict[str, int] = {}
    for node in assigns:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            counts[node.targets[0].id] = counts.get(node.targets[0].id, 0) + 1
    ambiguous = set(ambiguous or set()) | {k for k, v in counts.items() if v > 1}

    for _ in range(4):
        progressed = False
        for node in assigns:
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            if name in ns or name in ambiguous:             # 规则 ②
                continue
            try:
                src = ast.unparse(node.value)
            except Exception:
                continue
            if any(bad in src for bad in ("__import__", "eval(", "exec(", "globals(")):
                continue
            try:
                val = eval(src, {"__builtins__": {}}, ns)  # noqa: S307 - 见模块 docstring
            except Exception:
                continue
            # 规则 ①: 只收 Path, 或**以 `.read_text(...)` 结尾**的表达式出来的正文。
            # ⚠️ 不能写成 `^\w+\.read_text\(` —— `Path("a/b.py").read_text(...)`
            # 的接收者是**调用**而不是名字, 那样会把 §13.122 里两条**真**死钉桩
            # (`assert "initial_capital" in src`) 静默漏掉。实测过。
            is_path = isinstance(val, Path)
            m = re.fullmatch(r"(.+)\.read_(?:text|bytes)\(.*\)", src, re.S)
            if not (is_path or m):
                continue
            if isinstance(val, (str, Path)):
                ns[name] = val
                if m:
                    recv = m.group(1).strip()
                    if re.fullmatch(r"\w+", recv) and recv in ns:
                        ns.setdefault("__srcfile__", {})[name] = ns[recv]
                progressed = True
        if not progressed:
            break
    return ns


def _eval_module_assigns(tree: ast.Module, filename: str) -> dict:
    """模块级赋值。"""
    ns: dict = {
        "Path": Path,
        "__file__": filename,
        "ROOT": ROOT,
    }
    return _resolve_assigns(
        [n for n in tree.body if isinstance(n, ast.Assign)], ns,
        _ambig_names(tree, tree.body),
    )

def _pins_in(tree: ast.Module) -> list[tuple[str, str, bool, int]]:
    """收集 (src_name, literal, is_membership, lineno)。

    is_membership=True  ⇒ `"LIT" in SRC`  (期望命中)
    is_membership=False ⇒ `"LIT" not in SRC` (期望不命中)

    ⚠️ 本工具第一版**只认 `assert`**。于是它把下面这条**已确认的死钉桩**判成了活:
        `close_at = SRC.index('self._close(d, price, reason)\\n            return')`
    —— `SRC.index(lit)` 找不到就抛 `ValueError: substring not found`,
    **语义上等价于 `assert lit in SRC`**, 而它不在 `assert` 里。
    ⇒ `.index` / `.rindex` 必须一起收 (`.find` 返回 -1 不抛, `.count` 可以是 0,
       `.split` 允许落空 —— 这三类**不能**当判据, 否则普查又会变成没有牙齿的)。
    """
    out = []
    # (a) assert "LIT" in SRC  /  not in
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        cmp = node.test
        if len(cmp.ops) != 1 or len(cmp.comparators) != 1:
            continue
        left, op, right = cmp.left, cmp.ops[0], cmp.comparators[0]
        if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
            continue
        if isinstance(op, ast.In):
            want = True
        elif isinstance(op, ast.NotIn):
            want = False
        else:
            continue
        # 右操作数可能是 Name, 也可能是 (NAME) —— 解包括号
        if isinstance(right, ast.Name):
            out.append((right.id, left.value, want, node.lineno, "assert"))

    # (b) SRC.index("LIT") / SRC.rindex("LIT") —— 落空即抛, 等价于 assert in
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in ("index", "rindex")
                and isinstance(fn.value, ast.Name)):
            continue
        if not node.args:
            continue
        a0 = node.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            out.append((fn.value.id, a0.value, True, node.lineno, "index"))
    return out


def _guarded_pairs(scope: ast.AST) -> set[tuple[str, str]]:
    """`"LIT" not in NAME` 出现过的 (NAME, LIT) 对。

    ⚠️ 规则 ③ (§13.122): `NAME.index("LIT")` **前面**若已有
        `if "LIT" not in NAME: return`
    那么这一行根本不会在 LIT 缺席时执行 —— 它**不是**死钉桩。
    实测实例: `tests/test_nav_gate_cross_preset.py:108-110` 正是这个形状,
    本工具上一版把它报成了死钉桩 (误报会让**好守卫**被改)。
    """
    out: set[tuple[str, str]] = set()
    for node in ast.walk(scope):
        if not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        op = node.ops[0]
        left, right = node.left, node.comparators[0]
        if not isinstance(op, (ast.NotIn, ast.In)):
            continue
        if isinstance(left, ast.Constant) and isinstance(left.value, str) \
                and isinstance(right, ast.Name):
            out.add((right.id, left.value))
    return out


def _content_of(target, src_name: str, ns: dict):
    """把解析出来的目标变成 (正文, 可读的名字)。拿不到返回 None。"""
    # ⚠️ 目标可能是「路径」也可能是「已经读进来的正文」——
    # `SRC = ENGINE.read_text(...)` 求值出来是**正文**, 不是路径。
    # 本工具第一版把 str 一律当路径 => 每个文件都 OSError 跳过 =>
    # 打出 "活钉桩 0 / 死钉桩 0" 这个**假的绿**。判据是"能不能按路径打开",
    # 打不开就说明这个 str 本身就是正文。
    if isinstance(target, str):
        p = Path(target)
        if p.exists() and p.is_file():
            try:
                return p.read_text(encoding="utf-8"), target
            except (OSError, UnicodeDecodeError):
                return None
        _f = ns.get("__srcfile__", {}).get(src_name)
        try:
            rel = str(Path(_f).relative_to(ROOT)) if _f else "(已读取的正文)"
        except ValueError:
            rel = str(_f)
        return target, rel          # 它自己就是正文
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        rel = str(target.relative_to(ROOT))
    except ValueError:
        rel = str(target)
    return content, rel


def scan_file(path: Path) -> tuple[list[dict], int]:
    """返回 (死钉桩列表, 活钉桩计数)。

    ⚠️ 作用域: 模块级 + **每个函数体** 各解析一次 (§13.122)。只在模块级解析
    会漏掉"函数里读文件"的同一类钉桩 —— 实测那一版的注入打不响。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        return ([{"lineno": e.lineno or 0, "lit": "<语法错误>", "src": "",
                  "why": f"SyntaxError: {e.msg}"}], 0)

    module_ns = _eval_module_assigns(tree, str(path))

    # (作用域节点, 该作用域的 ns)
    scopes: list[tuple[ast.AST, dict]] = [(tree, module_ns)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_ns = dict(module_ns)
            fn_ns.pop("__srcfile__", None)
            fn_ns["__srcfile__"] = dict(module_ns.get("__srcfile__", {}))
            _resolve_assigns(
                [n for n in node.body if isinstance(n, ast.Assign)], fn_ns,
                _ambig_names(node, node.body),
            )
            scopes.append((node, fn_ns))

    dead: list[dict] = []
    alive = 0
    seen: set[tuple[int, str, bool]] = set()
    for node, ns in scopes:
        guarded = _guarded_pairs(node)
        for src_name, lit, want_in, lineno, kind in _pins_in(node):
            key = (lineno, lit, want_in)
            if key in seen:
                continue
            # 规则 ③: 被 `not in` 守卫住的 `.index(...)` 不是死钉桩
            if kind == "index" and (src_name, lit) in guarded:
                seen.add(key)
                continue
            target = ns.get(src_name)
            if not isinstance(target, (str, Path)):
                continue
            got = _content_of(target, src_name, ns)
            if got is None:
                continue
            content, rel = got
            seen.add(key)
            present = lit in content
            if want_in and not present:
                dead.append({"lineno": lineno, "lit": lit, "src": rel,
                             "why": "`in` 命中不了 ⇒ 该断言永不可能通过"})
            elif not want_in and present:
                dead.append({"lineno": lineno, "lit": lit, "src": rel,
                             "why": "`not in` 命中得了 ⇒ 该断言永不可能通过"})
            else:
                alive += 1
    return dead, alive



def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verbose", action="store_true", help="连活钉桩计数一起打")
    args = ap.parse_args()

    files = sorted((ROOT / "tests").glob("test_*.py"))
    total_dead = 0
    total_alive = 0
    affected: list[str] = []

    for f in files:
        dead, alive = scan_file(f)
        total_alive += alive
        if not dead:
            continue
        affected.append(f.name)
        total_dead += len(dead)
        print(f"\n{f.relative_to(ROOT)}  —— {len(dead)} 条死钉桩")
        for d in dead:
            print(f"  L{d['lineno']:<4} 目标={d['src']}")
            print(f"          {d['why']}")
            print(f"          钉的是: {d['lit'][:110]!r}")

    print("\n" + "=" * 72)
    print(f"扫描 {len(files)} 个测试文件; 活钉桩 {total_alive}; "
          f"**死钉桩 {total_dead}** (分布在 {len(affected)} 个文件)")
    if affected:
        print("受影响文件: " + ", ".join(affected))
    sys.exit(1 if total_dead else 0)


if __name__ == "__main__":
    main()
