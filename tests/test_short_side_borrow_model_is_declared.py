"""附九十九 —— §4 Short-Side Feasibility:做空必须**显式声明借券假设**,而且声明要**载重**。

## §4 原文

> **Short-Side Feasibility:** Any short strategy MUST explicitly declare its securities-lending
> assumption (availability, borrow cost). **A short backtest without a declared borrow model is
> invalid by construction.**

## 实测:这一条**做到了**,但没有任何守卫

本仓库只有一个做空引擎 `short_reversal`。它的问题**不是缺失,是没有守卫**:

* `short_reversal/presets.py` 有 `BORROW_ASSUMPTION`,三个键齐全
  (`availability` / `borrow_cost_model` / `borrow_cost_rate`),并**如实写了现实差距**
  ("A 股个股融券券源稀缺…回测数字是上界,不构成可执行预期");
* 而它是**载重**的:`core.dual_price.BORROW_RATE_ANNUAL`(单源)→ `engine.py` 的
  `MARGIN_RATE = BORROW_RATE_ANNUAL` → `replay_strategy_v3.py` 的 `margin_rate=BORROW_RATE_ANNUAL`
  ⇒ 每 bar 按 position notional 计提融券费。

⇒ 本文件钉四件事:**声明在**、**三键齐**、**费率与 core 单源一致**、**引擎真的消费它**。
第 4 条是关键:本仓库反复吃过"声明了却无人读取 = 装饰"的亏(§0/§2 那几次修复都是这个形态),
所以守卫不能只查"有没有那个字典"。

## 边界

只对**做空引擎**适用。本仓库的做空引擎是 `short_reversal` 一个;若将来新增,
`SHORT_ENGINES` 必须同步(由 `test_the_short_engine_list_is_complete` 对账)。

## 附一百三十八(2026-10-21):这条守卫的**式**两个方向都坏,而且中间一段是**死 pattern**

上面第 4 条("载重")原用**正则匹配源码文本**。实测四个读数:

| 写法 | 旧判据 | 问题 |
|---|---|---|
| 现状代码行 | 已消费 ✓ | —— |
| **注释掉**、只留那句文本 | **仍判"已消费"** | **假绿**(判据读的是文本形状,不是行为)|
| `margin_rate = BORROW_RATE_ANNUAL`(等号带空格)| 判"未消费" | **假红** |
| 经**局部变量载体**(`m = BORROW_RATE_ANNUAL` 再 `margin_rate=m`)| 判"未消费" | **假红**(附一百二十一 记过这个形态)|
| 经模块限定名(`dual_price.BORROW_RATE_ANNUAL`)| 判"未消费" | **假红** |

而且它声明了**两个** pattern,其中 `MARGIN_RATE\\s*=\\s*BORROW_RATE_ANNUAL` 在它读的那个文件
(`replay_strategy_v3.py`)里 **0 命中且永不可能命中**(那一行在 `engine.py`)
⇒ **死 pattern**:它自陈的链路 "`core` → `engine.py` → `replay_strategy_v3.py`" 的**中段从未被查**。

已改为 **AST**,并**两段都查**;`consumer_patterns` 换成一对显式的 (文件, 名字)。
牙齿 `test_the_accrual_point_criterion_has_teeth`:四种合法写法必判消费、四种非消费必不判消费。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 做空引擎 —— §4 的打分对象。新增做空引擎时要同步这里(下面有对账用例)。
SHORT_ENGINES: dict[str, dict] = {
    "short_reversal": {
        "presets": "short_reversal/presets.py",
        "declaration": "BORROW_ASSUMPTION",
        # 链路两段(**都要在**):常量再导出 → 计提点的关键字参数。
        # 判据是 **AST**,不是正则 —— 附一百三十八 实测旧的正则两个方向都坏:
        # 把代码行**注释掉**它照样绿(只认文本形状),而三种合法写法被它假红。
        "rate_constant_reexport": ("short_reversal/engine.py", "MARGIN_RATE"),
        "accrual_keyword": ("short_reversal/replay_strategy_v3.py", "margin_rate"),
    },
}

_REQUIRED_KEYS = ("availability", "borrow_cost_model", "borrow_cost_rate")

#: 单源常量名(`core.dual_price.BORROW_RATE_ANNUAL`)。
_RATE_CONST = "BORROW_RATE_ANNUAL"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _references_rate(node: ast.AST) -> bool:
    """表达式是否引用了单源费率 —— 允许限定名(`dual_price.BORROW_RATE_ANNUAL`)。"""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == _RATE_CONST:
            return True
        if isinstance(inner, ast.Attribute) and inner.attr == _RATE_CONST:
            return True
    return False


def _carriers_of_rate(tree: ast.AST) -> set[str]:
    """`X = …BORROW_RATE_ANNUAL…` 的载体名集合。

    (附一百二十一 的教训:判据必须接受**经局部变量传递**这种合法写法 ——
     那次 DSR 的判据就曾对走局部变量的文件误报。)
    """
    carriers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _references_rate(node.value):
            carriers.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return carriers


def _keyword_receives_rate(tree: ast.AST, keyword: str) -> bool:
    """是否有调用把 `keyword=` 设成借券费率(**直接引用**或**经载体变量**)。"""
    carriers = _carriers_of_rate(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != keyword:
                continue
            if _references_rate(kw.value):
                return True
            if isinstance(kw.value, ast.Name) and kw.value.id in carriers:
                return True
    return False


def test_every_short_engine_declares_a_borrow_model() -> None:
    """§4:做空回测**没有声明的借券模型就是 invalid by construction**。"""
    missing = []
    for engine, spec in SHORT_ENGINES.items():
        src = _src(spec["presets"])
        if spec["declaration"] not in src:
            missing.append(f"{engine}: {spec['presets']} 里没有 {spec['declaration']}")
            continue
        for key in _REQUIRED_KEYS:
            if f'"{key}"' not in src:
                missing.append(f"{engine}: {spec['declaration']} 缺 {key!r}")
    assert not missing, (
        "§4 VIOLATION: 做空引擎的借券假设不完整 —— §4 要求显式声明 availability 与 borrow cost:\n  "
        + "\n  ".join(missing)
    )


def test_the_declared_borrow_rate_is_single_sourced() -> None:
    """§2 单源:声明的费率必须**取自** `core.dual_price.BORROW_RATE_ANNUAL`,不许再写一遍数值。

    (仓库此前吃过"两处同值不同源"的亏 —— `core/dual_price.py` 与 `engine.py` 的注释
     都专门记了这件事。)
    """
    src = _src("short_reversal/presets.py")
    assert "BORROW_RATE_ANNUAL" in src, (
        "§2: `BORROW_ASSUMPTION['borrow_cost_rate']` 必须引用 `core.dual_price.BORROW_RATE_ANNUAL`"
        "(单源),而不是就地写一个数字"
    )
    # 事故形态:在声明里直接写死 0.086
    m = re.search(r'"borrow_cost_rate"\s*:\s*([^,\n]+)', src)
    assert m and "BORROW_RATE_ANNUAL" in m.group(1), (
        f"§2: borrow_cost_rate 不是引用单源而是 {m.group(1).strip() if m else '(找不到)'}"
    )


def test_the_declaration_is_load_bearing() -> None:
    """**声明必须被消费** —— 不是装饰,而且**两段链路都要在场**。

    本仓库反复栽在"声明了却无人读取";§4 这条规矩的实质是"回测的融券成本是**按声明的模型
    真的计提的**",所以守卫要看到费率**流到计提点**:
    `core.dual_price.BORROW_RATE_ANNUAL` → `engine.py` 的 `MARGIN_RATE` → 计提点的 `margin_rate=`。

    附一百三十八 实测旧判据(正则子串)两个方向都坏:
      * **太松**:把代码行注释掉、只留那句文本 ⇒ 仍判"已消费"(它在读**文本形状**,不是行为);
      * **太紧**:`margin_rate = BORROW_RATE_ANNUAL`(等号带空格)/ 经**局部变量载体** /
        经**模块限定名** —— 三种合法写法都被判成"未消费";
      * 且它声明的第二个 pattern 在它读的那个文件里**一次都不可能命中**(那行在 `engine.py`)
        ⇒ **死 pattern**,链路中段从未被查(这正是"守卫声明了却没接上"的又一例)。
    """
    for engine, spec in SHORT_ENGINES.items():
        cfile, cname = spec["rate_constant_reexport"]
        assert cname in _carriers_of_rate(ast.parse(_src(cfile))), (
            f"§4: {engine} 的 `{cfile}` 里,`{cname}` 不再由 `{_RATE_CONST}` 赋值 —— "
            f"链路第一段断了(旧判据对这一段只是**死 pattern**,永远查不到)。"
        )
        afile, akeyword = spec["accrual_keyword"]
        assert _keyword_receives_rate(ast.parse(_src(afile)), akeyword), (
            f"§4: {engine} 的 `{afile}` 里没有任何调用把 `{akeyword}=` 设成 "
            f"`{_RATE_CONST}`(直接或经载体变量)—— 借券费率没流到计提点,声明成了装饰。"
        )


def test_the_accrual_point_criterion_has_teeth() -> None:
    """**牙齿**:两个方向各测 —— 注释不算消费;四种合法写法都算。

    (与线上判据**共用**同一批 AST helper,故这里钉的就是那条口径。)
    """
    consuming = [
        "f(margin_rate=BORROW_RATE_ANNUAL,)",
        "f(margin_rate = BORROW_RATE_ANNUAL,)",              # 等号带空格
        "m = BORROW_RATE_ANNUAL\nf(margin_rate=m)",          # 经局部变量载体
        "f(margin_rate=dual_price.BORROW_RATE_ANNUAL)",      # 模块限定名
    ]
    escaped = [s for s in consuming if not _keyword_receives_rate(ast.parse(s), "margin_rate")]
    assert not escaped, f"这些**合法写法**被判成未消费(假红):{escaped}"

    not_consuming = [
        "# f(margin_rate=BORROW_RATE_ANNUAL,)",              # 只留注释
        "f(margin_rate=0.086)",                              # 写死数值
        "f(other=BORROW_RATE_ANNUAL)",                       # 传给了别的参数
        "m = 0.086\nf(margin_rate=m)",                       # 载体不是单源
    ]
    over_read = [s for s in not_consuming
                 if _keyword_receives_rate(ast.parse(s), "margin_rate")]
    assert not over_read, f"这些**并没有消费**却被判成消费(假绿):{over_read}"

    assert _carriers_of_rate(ast.parse("MARGIN_RATE = BORROW_RATE_ANNUAL")) == {"MARGIN_RATE"}
    assert _carriers_of_rate(ast.parse("# MARGIN_RATE = BORROW_RATE_ANNUAL")) == set(), (
        "注释不算载体"
    )


def test_the_declaration_states_the_reality_gap() -> None:
    """**如实**:A 股融券券源稀缺 —— 声明里必须写出"这是上界、不是可执行预期"这类话。

    (这不是 §4 的字面要求,而是 §0 Pessimistic Default 在**声明层**的体现:
     一个"假设无限券源"的声明若不加注,读者会把回测数字当成可执行收益。)
    """
    src = _src("short_reversal/presets.py")
    assert re.search(r"券源|稀缺|上界|不可融", src), (
        "§0: BORROW_ASSUMPTION 没有写明现实差距(A 股个股融券券源稀缺/回测数字是上界)"
    )


def test_the_short_engine_list_is_complete() -> None:
    """**对账**:`SHORT_ENGINES` 必须等于"**全库**声明了借券假设的那些引擎"。

    (与其它登记表同型:名单不能悄悄变短。新增做空引擎 ⇒ 这里红。)
    的面此前只 glob `short_reversal/` 一个目录 —— 而它自陈的是「四个引擎里…」;
    若**别的**引擎将来声明 `BORROW_ASSUMPTION`,旧写法看不见。现改为扫全库顶层包。
    """
    declared = {
        p.parent.name
        for p in REPO_ROOT.glob("*/presets.py")
        if "BORROW_ASSUMPTION" in p.read_text(encoding="utf-8")
    }
    assert declared, "一个声明了借券假设的引擎都没扫到 —— 对账面失效"
    assert declared == set(SHORT_ENGINES), (
        f"做空引擎名单与实际不符:声明了借券假设的是 {sorted(declared)},"
        f"而 SHORT_ENGINES 写的是 {sorted(SHORT_ENGINES)}"
    )


@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_the_rule_has_teeth(key: str) -> None:
    """**牙齿**:三个必需键逐个删掉,判据必须认出(用合成源码,不碰真仓库)。"""
    good = 'BORROW_ASSUMPTION: dict = {"availability": "x", "borrow_cost_model": "y", "borrow_cost_rate": Z}\n'
    bad = good.replace(f'"{key}": ', "")
    assert f'"{key}"' in good and f'"{key}"' not in bad
    assert not all(f'"{k}"' in bad for k in _REQUIRED_KEYS), f"删掉 {key} 却仍被判为齐全"
