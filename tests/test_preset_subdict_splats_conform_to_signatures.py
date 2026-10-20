r"""§0/§6 守卫:**把 preset 子字典 `**` 展开给某个函数时,键必须被那个函数的签名接受。**

## 为什么这条是"机械化"的(附一百一十)

附一百零九 的缺陷是:`uptrend_pullback/grid.py` 无条件
`select_entries(**cfg["signal"])`,而三个活 preset 的 `signal` 带 `pct_chg_low` / `pct_chg_high`
—— `select_entries()` **没有这两个形参** ⇒ **第一个 combo 就 `TypeError`,工具零产出**。

那个缺陷**不需要读懂语义**就能判:把 `**` 展开的字典的键与形参集合比一下就够。
本文件就是那个比对,全库、四引擎。

**牙齿(当场实测)**:把 `grid.py` 换回修复前的版本(`git show 2a2d58e:uptrend_pullback/grid.py`),
本判据**精确报出**

    uptrend_pullback/grid.py:134  select_entries(**cfg['signal'])
      ← preset v33_long_reverse_v19/v20/v21 多出 ['pct_chg_high', 'pct_chg_low']

⇒ 它对本仓库**真实发生过的**缺陷会响,不是一条只对假想注入有效的断言。

## ⚠️ 解析必须按**本文件的 import** 做(我第一版栽在这上面)

第一版按**全局函数名**建索引(`setdefault(name, …)[0]`),于是
`chase_up/backtrader_engine.py` 的 `select_entries` 被解析到
**`uptrend_pullback/signals.py`** 那一份 —— 两个包各有一个同名函数。
**一个"看名字"的解析器,会把检查做在错的文件上。**

## 口径与边界

* 只查 `**X["signal"|"regime"]` 这一形态(`X` 必须是 `preset/cfg/p/base/params/profile` 这类名字),
  因为它们是 preset 里**真会整块展开**的子字典;**全库共 9 处**(8 处本判据覆盖 + 1 处构造器形态,见下);
* 函数**在本文件内定义**时,形参从 **AST** 取 —— **不 import 脚本**(import 会执行其模块级代码,
  那是副作用);
* `**strategy_kwargs(…)` 这类**构造器**调用不在覆盖内:它不是"某个 preset 子字典",
  而是一个**单源构造器**的返回值(`short_reversal/engine.py:85`,docstring: 新增策略参数时只改这里)
  —— 正是本批给 uptrend 补上的那种形状。**不假装覆盖它,也不为它建登记表**(登记表只为
  "本该覆盖而暂时没覆盖"的东西存在)。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PACKAGES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

#: preset 里那些"作为子字典整块展开"的键。
SUBDICT_KEYS = ("signal", "regime")

#: 支持 `X["signal"]` 与 `X["signal"] or {}` 两种写法;`X` 必须是 preset 类变量名。
_SPLAT = re.compile(
    r'^(\w+)\s*\[\s*["\'](\w+)["\']\s*\](?:\s*or\s*\{.*\})?$'
)
_VARISH = re.compile(r"^(?:preset|preset_cfg|cfg|p|base|params|profile)$")


def _live_presets(engine: str) -> dict[str, dict]:
    if engine not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if engine == "chase_up":
        from chase_up.presets import PRESETS
    elif engine == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
    elif engine == "short_reversal":
        from short_reversal.presets import PRESETS
    else:
        from cycle_price_action.presets import PRESET_V1

        return {"PRESET_V1": PRESET_V1}
    return dict(PRESETS)


def _engine_of(rel: str) -> str:
    head = rel.split("/", 1)[0]
    if head in ENGINE_PACKAGES:
        return head
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    return next(
        (e for e in ENGINE_PACKAGES if re.search(rf"(?:from|import)\s+{e}\.", src)), ""
    )


def _params_of_imported(rel: str, fname: str):
    """按本文件 `from <mod> import <fname>` 解析,返回 `(形参集合 | None, 是否有 **kwargs, 说明)`。"""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            if any((a.asname or a.name) == fname for a in n.names):
                try:
                    fn = getattr(importlib.import_module(n.module), fname, None)
                except Exception as e:  # pragma: no cover - 环境问题
                    return None, False, f"import {n.module} 失败: {e}"
                if fn is None:
                    return None, False, f"{n.module} 里没有 `{fname}`"
                sig = inspect.signature(fn)
                return (
                    set(sig.parameters),
                    any(q.kind is inspect.Parameter.VAR_KEYWORD for q in sig.parameters.values()),
                    f"{n.module}.{fname}",
                )
    # 本文件内定义的顶层函数:从 AST 取形参(**不** import,避免执行脚本模块级代码)
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname:
            a = n.args
            names = {x.arg for x in (*a.args, *a.kwonlyargs, *a.posonlyargs)}
            return names, a.kwarg is not None, f"{rel}(本文件定义)"
    return None, False, "未从任何模块 import,也不在本文件顶层"


def _splat_sites() -> list[tuple[str, int, str, str, str]]:
    """`(相对路径, 行号, 被调函数名, 展开表达式, 子字典键)`。"""
    out = []
    for pkg in ENGINE_PACKAGES:
        for p in sorted((REPO_ROOT / pkg).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            rel = str(p.relative_to(REPO_ROOT))
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                for kw in node.keywords:
                    if kw.arg is not None:
                        continue
                    text = ast.unparse(kw.value)
                    m = _SPLAT.match(text)
                    if not m or m.group(2) not in SUBDICT_KEYS:
                        continue
                    if not _VARISH.match(m.group(1)):
                        continue
                    out.append((rel, node.lineno, node.func.id, text, m.group(2)))
    return out


def test_every_preset_subdict_splat_is_accepted_by_its_callee() -> None:
    """主判据:每个 `f(**X["signal"|"regime"])` 的键都必须被 `f` 接受。"""
    sites = _splat_sites()
    # 实测基线:8 个(全库另有 1 个构造器形态 `**strategy_kwargs(…)`,按设计不在覆盖内)。
    # 少一个 ⇒ 有人删了调用点;多一个 ⇒ 新调用点出现 —— 两种情况都要人看一眼。
    assert len(sites) >= 8, (
        f"扫描面异常小({len(sites)} 个调用点)—— 本条可能已空转(实测基线 8 个)"
    )

    bad, compared, resolved = [], 0, 0
    for rel, lineno, fname, text, key in sites:
        params, has_kwargs, how = _params_of_imported(rel, fname)
        if params is None:
            bad.append(f"{rel}:{lineno} {fname}(**{text}) —— 解析失败:{how}")
            continue
        resolved += 1
        engine = _engine_of(rel)
        if not engine:
            bad.append(f"{rel}:{lineno} 推不出引擎,无法取活 preset")
            continue
        for pname, preset in _live_presets(engine).items():
            sub = preset.get(key)
            if not isinstance(sub, dict):
                continue
            compared += 1
            extra = sorted(set(sub) - params)
            if extra and not has_kwargs:
                bad.append(
                    f"{rel}:{lineno} {fname}(**{text}) ← preset `{pname}`:{key} "
                    f"多出 {extra}  (来自 {how})"
                )
    assert not bad, (
        "§0/§6:以下调用点把 preset 的键 `**` 展开给一个**不接受它们**的函数 ⇒ "
        "调用当场 `TypeError`,工具零产出(附一百零九 就是这一形态):\n  "
        + "\n  ".join(bad)
    )
    # 非空转:必须真的解析到函数、并真的与活 preset 比过
    assert resolved == len(sites), f"只解析了 {resolved}/{len(sites)} 个调用点"
    assert compared >= 10, f"只比对了 {compared} 个 (调用点 × preset) —— 判据可能空转"


def test_the_guard_has_teeth_against_the_historical_defect() -> None:
    """**牙齿**:把 `grid.py` 换回修复前的源码,本判据必须报出 `pct_chg_low/high`。

    不落盘 —— 直接在内存里跑同一个判据核心(`_splat_sites` 只读磁盘,故这里手工构造
    那次调用的两个量:被调函数的形参集合 × 活 preset 的 `signal` 键)。
    这条**不依赖** grid.py 现在的写法,所以将来 grid.py 再改也不会让它失效。
    """
    from uptrend_pullback.signals import select_entries

    params = set(inspect.signature(select_entries).parameters)
    offenders = {
        name: sorted(set(p["signal"]) - params)
        for name, p in _live_presets("uptrend_pullback").items()
        if set(p["signal"]) - params
    }
    assert offenders, (
        "活 preset 的 signal 键现在**全部**被 `select_entries` 接受了 —— "
        "这条牙齿检验的对象消失了(要么签名扩了,要么 preset 改了)。"
        "若那是**有意的**,请删掉本用例并在 docstring 里记一句:附一百零九 的形态已不可能再发生。"
    )
    assert "pct_chg_low" in offenders[next(iter(offenders))], (
        "预期 `pct_chg_low` 是那个不被接受的键 —— 若它已被改名/移除,请同步本条"
    )
