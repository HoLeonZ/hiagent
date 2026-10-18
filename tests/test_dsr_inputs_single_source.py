"""§5 守卫:DSR 的**输入口径**必须与生产者一致,不得硬编码。

## 缺陷(2026-10-16 复核确认,两处)

### (a) 年化常量两处定义:引擎 243,`dna_stats` 252

`deflated_sharpe_ratio` 把 `observed_sharpe` **除回逐期**
(`sr = observed_sharpe / sqrt(trading_days_per_year)`)再与逐期阈值比较,
所以消费者用的常数**必须**等于生产者算它时用的常数。而:

| 层 | 常数 |
|---|---|
| 引擎(`chase_up` / `uptrend_pullback` / `short_reversal` 的 `sharpe`) | `mean/std × sqrt(243)` |
| `dna_stats`(消费者,4 处默认) | `252` |

⇒ 逐期 Sharpe 被系统性缩放 `sqrt(243/252) ≈ 0.982`(1.8%),DSR 随之偏离。
同一层里的 `annualized_sharpe()`(生产者)也是 252 —— 即**同一量两处定义**,
而真正的边界(引擎 → DSR)**恰好跨在这两份定义之间**。

实测影响(DSR 相对变化):`(0.84, k=19, T=1071)` +2.84%、
`(0.60, k=30, T=500)` +2.67%、`(1.50, k=10, T=250)` +2.32%;
极端值几乎不变(`(2.50, k=50, T=1200)` +0.02%)—— 即"中段"最受影响。

### (b) `n_returns` 被硬编码为 252(7 处)

`n_returns` 是"Sharpe 用了多少个收益观测"(T),用于标准误修正。7 处写成常数 `252`:
`uptrend_pullback/sweep_v33_long{,_v2..v6}.py` 与 `short_reversal/grid_runner.py`。
而这两个 sweeps 的窗口实测只有 **243 / 242** 个交易日 ⇒ T 被高估 **+3.7% / +4.1%**,
标准误被低估约 2% ⇒ DSR **系统性偏乐观** —— 偏偏 §5 的惩罚指标就是要用在
"看起来不错"的结果上。窗口恰好约一年只是让它**碰巧**没差太远;而 sweep 脚本的
全部用途就是换窗口重跑,那时它会错得更多。

## 修法

(a) 四处默认值改为 `core.trade_schema.TRADING_DAYS_PER_YEAR`(单源,与引擎同源);
(b) 6 个 sweep 改为 `n_returns=int(panel["date"].nunique())`;
    `grid_runner` 改为读本次运行的 `n_trading_days`(顺带把它写进落盘 CSV),
    **取不到即 fail-fast**,不用常数兜底。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from core.trade_schema import TRADING_DAYS_PER_YEAR  # noqa: E402

#: dna_stats 里所有带 `trading_days_per_year` 的公开入口
_DSR_ENTRIES = [
    ("dna_stats.deflated", "annualized_sharpe"),
    ("dna_stats.deflated", "deflated_sharpe_ratio"),
    ("dna_stats.deflated", "sharpe_significance_pvalue"),
    ("dna_stats.walkforward_report", "format_walkforward_stats"),
]


@pytest.mark.parametrize("module_name,func_name", _DSR_ENTRIES)
def test_dsr_layer_defaults_to_the_canonical_constant(
    module_name: str, func_name: str
) -> None:
    """§2/§5: 统计层的年化常数必须与引擎**同源**,不得是美国惯例的 252。"""
    import importlib

    fn = getattr(importlib.import_module(module_name), func_name)
    default = inspect.signature(fn).parameters["trading_days_per_year"].default
    assert default == TRADING_DAYS_PER_YEAR, (
        f"{module_name}.{func_name} 的年化默认 {default} != 规范值 "
        f"{TRADING_DAYS_PER_YEAR} —— 引擎用 243 算出 observed_sharpe,"
        "消费者必须用同一个数除回逐期,否则逐期 Sharpe 被缩放 sqrt(243/252)"
    )


def test_the_constant_actually_matters() -> None:
    """行为层:两种常数给出**不同**结论(否则上面的单源断言毫无意义)。"""
    from dna_stats.deflated import deflated_sharpe_ratio

    kw = dict(n_returns=1071)
    canonical = deflated_sharpe_ratio(0.84, 19, **kw)["deflated_sharpe"]
    us_market = deflated_sharpe_ratio(
        0.84, 19, trading_days_per_year=252, **kw
    )["deflated_sharpe"]
    assert canonical != pytest.approx(us_market), (
        "两种年化常数给出同一结果 ⇒ 本组断言失去了判别力"
    )


# ---------------------------------------------------------------------------
# n_returns 不得是字面量(AST 判定,不做子串匹配)
# ---------------------------------------------------------------------------


def _dsr_call_sites() -> tuple[list[tuple[Path, ast.Call]], list[str]]:
    """所有调用 `deflated_sharpe_ratio(...)` 的位置(排除 dna_stats 自身与 tests)。

    返回 (调用点, **无法解析的文件**)。附六十:此前无法解析的文件被**静默跳过**
    (`except SyntaxError: continue`)⇒ 任何带语法错误的文件对全套 DSR 守卫**不可见**
    (我自己的一次两向验证就因此变成了空转 —— 模拟出来的"违规"根本没被扫到,守卫全绿,
    看起来像"守卫放过了它")。现在把无法解析的文件**报出来**,由
    `test_there_are_call_sites_to_guard` 断言为空。
    """
    out: list[tuple[Path, ast.Call]] = []
    unparseable: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", "dna_stats"} or "__pycache__" in rel.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as e:
            unparseable.append(f"{rel}: {type(e).__name__}")
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "deflated_sharpe_ratio"
            ):
                out.append((path, node))
    return out, unparseable


def test_there_are_call_sites_to_guard() -> None:
    """守卫自身:若一处都没扫到,下面的断言就是真空的绿。"""
    sites, unparseable = _dsr_call_sites()
    assert not unparseable, (
        "§0: 以下文件**无法解析**,对全套 DSR 守卫不可见(静默跳过 = 静默失去覆盖):\n  "
        + "\n  ".join(unparseable)
    )
    assert len(sites) >= 5, f"只扫到 {len(sites)} 个 DSR 调用点,扫描面可能已失效"


def test_n_returns_is_never_a_hardcoded_literal() -> None:
    """§5: `n_returns`(观测数 T)必须来自本次运行,不得写常数。

    写死 252 的后果不是"粗略"而是**方向性错误**:窗口实际 242/243 个交易日时
    T 被高估约 4%,标准误被低估约 2%,DSR 偏乐观。
    """
    offenders: list[str] = []
    for path, call in _dsr_call_sites()[0]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for kw in call.keywords:
            if kw.arg in {"n_returns", "trading_days_per_year"} and any(
                isinstance(e, ast.Constant) for e in _expressions_feeding(call, tree)
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno} {kw.arg}=<字面量>"
                )
    assert not offenders, (
        "§5 VIOLATION: DSR 的输入被写成字面量 —— 它必须来自本次运行:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 附六十 —— 上面那条守卫只拦**字面量**,于是"常数伪装成变量"从它眼皮下走过
# ---------------------------------------------------------------------------
#
# 实测:`cycle_price_action/sweep_thresholds.py` 曾写
#     n_returns=WINDOW_TRADING_DAYS      # 模块级 = 126
# 而 CLI 的 `--test-months` 默认 **12**(≈243 交易日)⇒ T 被低估 **1.92 倍**
# (实测默认两个窗口 T = 243 / 242)。DSR 里 `sqrt(T-1)` 随之变小 ⇒ DSR 系统性
# **偏悲观**。这与附三十二 修的那个(252 vs 242,偏乐观)是**同一个缺陷**,
# 只是形状从 `ast.Constant` 变成了 `ast.Name` —— 而守卫只检查前者,所以它一直绿。
#
# 判据改成"**不得来自模块级常量**":`n_returns` 要么是字面量(现任守卫已拦),
# 要么必须是函数内的**局部**名字(由本次运行算出);若它解析到一个**模块级**变量,
# 那就还是常数,只是被起了个名字。


def _expressions_feeding(call: ast.Call, tree: ast.Module) -> list[ast.AST]:
    """找出**决定这次调用的 T 的表达式** —— 若有间接,追一层。

    为什么需要:`uptrend_pullback/iter_reverse.py` 的真实形状是

        n_returns = WINDOW_TRADING_DAYS_PER_MONTH * args.window_months   # ← 本地赋值
        ...
        n_returns=n_returns                                              # ← 调用点只传名字

    只看调用点的三条规则**全都看不见它**(我第一版就是这样:复现那个形状后守卫依然全绿 ——
    **两向验证当场证伪了我自己的判据**)。故此处做**一层数据流**:若调用点传的是裸名字,
    就把该名字在**同一函数/模块**里的赋值表达式也纳入检查对象。
    """
    targets: list[ast.AST] = []
    for kw in call.keywords:
        if kw.arg not in {"n_returns", "trading_days_per_year"}:
            continue
        targets.append(kw.value)
        if isinstance(kw.value, ast.Name):
            name = kw.value.id
            # 一层:同模块或同函数内的 `name = <expr>`
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == name:
                            targets.append(node.value)
    return targets


def _module_level_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def _names_assigned_inside_functions(tree: ast.Module) -> set[str]:
    """所有函数体内被赋值过的名字(粗粒度:不区分作用域,偏宽松以免误报)。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    names.add(sub.target.id)
                elif isinstance(sub, ast.For) and isinstance(sub.target, ast.Name):
                    names.add(sub.target.id)
    return names


def test_n_returns_is_never_a_module_level_constant() -> None:
    """§5: `n_returns` 不得解析到**模块级常量** —— 常数换个名字还是常数。"""
    offenders: list[str] = []
    for path, call in _dsr_call_sites()[0]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_names = _module_level_names(tree)
        assigned_in_funcs = _names_assigned_inside_functions(tree)
        for kw in call.keywords:
            if kw.arg != "n_returns" or not isinstance(kw.value, ast.Name):
                continue
            name = kw.value.id
            if name in module_names and name not in assigned_in_funcs:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno} "
                    f"n_returns={name}(模块级常量)"
                )
    assert not offenders, (
        "§5 VIOLATION: DSR 的观测数 T 解析到模块级常量 —— 它必须来自本次运行:\n  "
        + "\n  ".join(offenders)
    )


def test_the_module_level_constant_rule_actually_bites() -> None:
    """**元测试**:合成一个"常数伪装成变量"的调用点 ⇒ 判据必须认出来。

    没有这条,"规则恒绿"就无法区分"代码干净"与"规则不工作"。
    """
    src = (
        "WINDOW_TRADING_DAYS = 126\n"
        "def f():\n"
        "    return deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                                 n_returns=WINDOW_TRADING_DAYS)\n"
    )
    tree = ast.parse(src)
    module_names = _module_level_names(tree)
    assigned_in_funcs = _names_assigned_inside_functions(tree)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    kw = next(k for k in call.keywords if k.arg == "n_returns")
    assert isinstance(kw.value, ast.Name), "夹具失效:不是 Name 节点"
    name = kw.value.id
    assert name in module_names and name not in assigned_in_funcs, (
        "元测试夹具失效:构造出的调用点没有命中判据"
    )


# ---------------------------------------------------------------------------
# 附六十五 —— 第三种形状:**内联表达式**里的常数
# ---------------------------------------------------------------------------
#
# 前面两条守卫覆盖了 `n_returns=252`(字面量)与 `n_returns=WINDOW_TRADING_DAYS`
# (模块级常量)。而实测**已接线**的 `dna_stats/walkforward_report.py` 是第三种:
#
#     n_returns=max(n_windows * 63, 100)      # 注释自认 "rough estimate"
#
# 它既不是字面量也不是模块级名字 ⇒ **两条规则都看不见它**。而后果最重:
# 在 23 个 2 个月窗口的调用点上给它 1,449(真实 ~42)⇒ DSR 从 **0.072** 变成
# **0.995** —— §5 的选中偏差惩罚被整条抹平(附六十四)。
#
# 这三种形状的共同点是**把某个数烤进了 T**。而"由本次运行算出来"的那些写法
# 都不需要烤任何数:
#
#     n_returns=_observed_t                       ✓ 变量
#     n_returns=n_obs                             ✓ 变量
#     n_returns=int(panel["date"].nunique())      ✓ 由面板算
#     n_returns=int(m["n_trades"])                ✓ 由产物算
#     n_returns=max(n_windows * 63, 100)          ✗ 烤了 63 与 100
#
# 故判据:**`n_returns` 的表达式里不得出现 0/1 以外的数字字面量**。
# (允许 0/1 是因为 `len(x) - 1` 这类"观测数 = 长度减一"的常规写法需要它们。)


def test_n_returns_contains_no_baked_in_number() -> None:
    """§5: T 的表达式里不得有 0/1 以外的数字字面量 —— 有,就是把假设烤进了 T。

    这条补的是另两条守卫的空隙:字面量(第一条)与模块级常量(第二条)之外的
    **内联表达式**(附六十四 实测的形状)。
    """
    numeric = (ast.Constant,)

    def has_baked_number(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, numeric) and isinstance(sub.value, (int, float)) \
                    and not isinstance(sub.value, bool) and sub.value not in (0, 1):
                return True
        return False

    offenders: list[str] = []
    for path, call in _dsr_call_sites()[0]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for kw in call.keywords:
            if kw.arg in {"n_returns", "trading_days_per_year"} and any(
                has_baked_number(e) for e in _expressions_feeding(call, tree)
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno} {kw.arg}=<expr with 数字> "
                    f"({ast.unparse(kw.value)[:40]})"
                )
    assert not offenders, (
        "§5 VIOLATION: DSR 的输入表达式里烤进了数字 —— 它必须由本次运行算出:\n  "
        + "\n  ".join(offenders)
    )


def test_the_baked_number_rule_actually_bites() -> None:
    """元测试:构造附六十四 那个真实形状 ⇒ 判据必须认出来(否则等于没写)。"""
    tree = ast.parse(
        "def f(n_windows):\n"
        "    return deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                                 n_returns=max(n_windows * 63, 100))\n"
    )
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    kw = next(k for k in call.keywords if k.arg == "n_returns")
    found = [
        s for s in ast.walk(kw.value)
        if isinstance(s, ast.Constant) and isinstance(s.value, (int, float))
        and s.value not in (0, 1)
    ]
    assert {s.value for s in found} == {63, 100}, "元测试夹具失效"

    # 反向:合法写法不得被误伤
    ok = ast.parse(
        "def f(panel, m):\n"
        "    a = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                              n_returns=int(panel['date'].nunique()))\n"
        "    b = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                              n_returns=len(panel) - 1)\n"
    )
    for c in [n for n in ast.walk(ok) if isinstance(n, ast.Call)]:
        for k in c.keywords:
            if k.arg == "n_returns":
                bad = [
                    s for s in ast.walk(k.value)
                    if isinstance(s, ast.Constant) and isinstance(s.value, (int, float))
                    and s.value not in (0, 1)
                ]
                assert not bad, f"合法写法被误伤:{ast.unparse(k.value)}"


# ---------------------------------------------------------------------------
# 附六十六 —— 第四种形状:引用**模块级数字常量**
# ---------------------------------------------------------------------------
#
# `uptrend_pullback/iter_reverse.py` 曾写:
#
#     WINDOW_TRADING_DAYS_PER_MONTH = 21
#     n_returns = WINDOW_TRADING_DAYS_PER_MONTH * args.window_months
#
# 这个表达式里**一个数字字面量都没有**(两个操作数都是名字)⇒ 第三条规则看不见;
# 名字也不是"那个常数自身被直接传进去"⇒ 第二条规则看不见。而它的理由更值得记:
# 「取自**仓库既有口径**:walk-forward 家族用 6 个月 = 126 个交易日,即 126/6 = 21」——
# 那个"既有口径"(126)本身就是附六十 修掉的那个猜。**用一个猜给另一个猜背书。**
#
# 判据:把表达式里出现的模块级名字**解析回它的值**;值是数字且不是 0/1 ⇒ 违规。
# 这样"由本次运行算出的变量"(函数内赋值)不受影响,而"从别处的估计借来的数"会被拦。


def _module_level_numbers(tree: ast.Module) -> dict[str, object]:
    """模块级 `NAME = <数字字面量>` 映射(用于把名字解析回值)。"""
    out: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
            and not isinstance(node.value.value, bool)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def test_n_returns_does_not_borrow_a_module_level_number() -> None:
    """§5: T 不得引用模块级数字常量 —— 那还是"从别处借来的数"。"""
    offenders: list[str] = []
    for path, call in _dsr_call_sites()[0]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_level_numbers(tree)
        for kw in call.keywords:
            if kw.arg not in {"n_returns", "trading_days_per_year"}:
                continue
            for _e in _expressions_feeding(call, tree):
              for sub in ast.walk(_e):
                if not isinstance(sub, ast.Name):
                    continue
                val = consts.get(sub.id)
                if isinstance(val, (int, float)) and not isinstance(val, bool) \
                        and val not in (0, 1):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{call.lineno} "
                        f"{kw.arg} 引用了模块级数字常量 {sub.id} = {val!r}"
                    )
    assert not offenders, (
        "§5 VIOLATION: DSR 的输入引用了模块级数字常量 —— T 必须由本次运行算出:\n  "
        + "\n  ".join(offenders)
    )


def test_the_module_level_number_rule_actually_bites() -> None:
    """元测试:复现 iter_reverse 那个形状 ⇒ 必被认出来;运行算出的变量 ⇒ 不误伤。"""
    bad = ast.parse(
        "WINDOW_TRADING_DAYS_PER_MONTH = 21\n"
        "def f(args):\n"
        "    return deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                                 n_returns=WINDOW_TRADING_DAYS_PER_MONTH * args.m)\n"
    )
    consts = _module_level_numbers(bad)
    call = next(n for n in ast.walk(bad) if isinstance(n, ast.Call))
    kw = next(k for k in call.keywords if k.arg == "n_returns")
    hits = [
        s.id for s in ast.walk(kw.value)
        if isinstance(s, ast.Name) and isinstance(consts.get(s.id), (int, float))
    ]
    assert hits == ["WINDOW_TRADING_DAYS_PER_MONTH"], f"元测试夹具失效:{hits}"

    good = ast.parse(
        "def f(df):\n"
        "    _observed_t = int(df['n_daily_returns'].mean())\n"
        "    return deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=3,\n"
        "                                 n_returns=_observed_t)\n"
    )
    gconsts = _module_level_numbers(good)
    # 注意:必须挑 **deflated_sharpe_ratio** 那个 call —— `ast.walk` 的次序会把
    # 夹具里先出现的 `int(df[...].mean())` 当作第一个 Call(我第一版就是这么写的,
    # 于是元测试自己 StopIteration)。
    gcall = next(
        n for n in ast.walk(good)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "deflated_sharpe_ratio"
    )
    gkw = next(k for k in gcall.keywords if k.arg == "n_returns")
    ghits = [
        s.id for s in ast.walk(gkw.value)
        if isinstance(s, ast.Name) and isinstance(gconsts.get(s.id), (int, float))
    ]
    assert ghits == [], f"运行算出的变量被误伤:{ghits}"
