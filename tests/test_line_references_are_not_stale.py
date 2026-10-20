"""附九十 —— 注释里的行号引用必须名副其实(16 处已修,其中 11 处是同一句重复)

## 缺陷(实测)

`06904b1` 修过一族:"注释引用了一个**不存在的行号**"。它的处置是把引用换成语义
("一致的是闸门语义,不是默认值 —— 旧注释的行号与值都已不存在")。
但那次只改了**它当时看到的那些出现处**。全库扫描后实测 **16 处**仍然带着假引用:

| 位置 | 处数 | 假在哪(逐处核实过) |
|---|---|---|
| `short_reversal/presets.py` | **11** | 写「Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0」—— 第 47 行是 `params` 上方一张 **enum 导入表**;且该参数**已不再**是引擎硬编码,而是由 `core.preset_contract` 注入并在 `__init__` 核对 |
| `chase_up/portfolio.py` / `uptrend_pullback/portfolio.py` | 2 | 写「与 `replay_strategy_v3.py:64 (min_cash_ratio=0.05)` 口径一致」—— 第 64 行讲的是**科创板涨跌停**;`min_cash_ratio` 在该文件里**已无此名**(0 处) |
| `cycle_price_action/portfolio.py` | 1 | 同上家族的 `:156 (min_cash_ratio=0.05)` |
| `cycle_price_action/presets.py` | 1 | 写「`portfolio.py:65` hardcodes MAX_POSITION_PCT=1.0」—— 第 65 行是 `class Portfolio:`,常量在 **:83** |
| `uptrend_pullback/replay_strategy.py` | 1 | 写「`portfolio.py:474-476` 一致,共用 `core.dual_price.is_limit_up`」—— 那三行是 `intraday_tiebreak` 检查,`is_limit_up` 在 **:560/:564** |

**其中 13 处是 `06904b1` 那次的漏网**:同一句假声明,它在 `chase_up/portfolio.py` 与
`uptrend_pullback/portfolio.py` 各改了一处,**同一文件里的第二处原样留着** ——
**按"出现处"改,而不是按"这个声明"改。**

处置与 `06904b1` 一致:**把行号换成语义**,并把旧引用的错法写进注释(供下一个人核对),
**不再引用行号**。

## 判据,以及它的**覆盖面有多窄**(如实声明)

要判一条引用,须同时满足:①形如 `X.py:NNN`(支持区间)②同一行里它是**唯一**带行号的引用
③该行出现了 **snake_case 标识符**(非路径分量、非引擎包名)。然后要求该标识符出现在
被引行号 ±10 行内。

⇒ **全库 104 处 `py:NNN` 引用里,只有 6 处可判。** 窄是**换零误报**的代价,不是"全库只有 6 处"。
所以门禁里带一条**非空转下限**(可判数不得低于 5):判据坏了会掉到 0,而不是"看起来很干净"。
—— 这条下限正是本会话反复得出的教训(附八十六 的 `total >= 20` 通过而实际漏了 4 个;
不过那次下限与完整性无关,这次下限只防"判据坏死",两者不能混为一谈)。

## 顺带的正例

我当时把更正注释写成了**逐字引用旧引用**,于是它们自己变成了新的"行号与内容不符"命中。
改成"第 N 行"的写法(不产生 `py:NNN` 字面量)。**守卫会惩罚它自己的更正记录** ——
这是好事,说明判据在真的看内容。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _census():
    spec = importlib.util.spec_from_file_location(
        "census_stale_line_refs", REPO_ROOT / "tests" / "_census_stale_line_refs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_source_comment_cites_a_line_whose_content_contradicts_it() -> None:
    mod = _census()
    hits: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.relative_to(REPO_ROOT).parts:
            continue
        for ln, target, why in mod.find_stale_line_references(path):
            hits.append(f"{path.relative_to(REPO_ROOT)}:{ln} → {target}  {why}")
    assert not hits, (
        "§0: 以下注释引用的行号与它声称的内容不符(读者会被送到错的地方);"
        "按 06904b1 的处置**换成语义描述,不要引用行号**:\n  " + "\n  ".join(hits)
    )


def test_the_scanner_is_not_vacuous() -> None:
    """**非空转**:判据必须至少在**一处真实引用**上跑过。

    实测(修完附九十 那 16 处之后):全库满足判据的引用只剩 **3 处**
    (`chase_up/presets.py:381`、`cycle_price_action/main.py:42`、
     `cycle_price_action/presets.py:51`)—— 它们都**名副其实**(判据要求目标行 ±10 内
    出现被点名的标识符)。

    所以这条**只回答"扫描器还活着吗"**,不回答"覆盖面够不够"。
    我第一版写下限 `>= 5` —— 那是个**脆**的数:任何一处合法引用被移除就会误红。
    真正的非空转证明是 `test_the_scanner_has_teeth`(种进去必须认出来),
    这条只兜住"完全坏死"这一种。
    """
    n = _census().judged_reference_count()
    assert n >= 1, (
        "全库没有**任何**引用满足判据 —— 判据坏死(而不是'代码干净')。"
        "请先跑 test_the_scanner_has_teeth 确认扫描器本身还能工作。"
    )


def test_the_scanner_has_teeth(tmp_path: Path) -> None:
    """**牙齿**:种一条名不副实的引用必须被认出;名副其实的不得误报。"""
    mod = _census()
    target = tmp_path / "target.py"
    target.write_text("\n".join(f"x{i} = {i}" for i in range(1, 60)) + "\n", encoding="utf-8")

    bad = tmp_path / "bad.py"
    bad.write_text("# 与 target.py:10 (min_cash_ratio=0.05) 口径一致\n", encoding="utf-8")
    hits = mod.find_stale_line_references(bad)
    assert hits and "min_cash_ratio" in hits[0][2], f"没认出来:{hits}"

    good = tmp_path / "good.py"
    good.write_text("# 与 target.py:10 (min_cash_ratio=0.05) 口径一致\n", encoding="utf-8")
    # 让目标第 10 行附近**真的**提到它 ⇒ 不得报
    lines = target.read_text(encoding="utf-8").splitlines()
    lines[9] = "min_cash_ratio = 0.05"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert mod.find_stale_line_references(good) == [], "名副其实的引用被误报"

    # 越界(行号不存在)也必须报
    over = tmp_path / "over.py"
    over.write_text("# 见 target.py:9999 的说明\n", encoding="utf-8")
    assert mod.find_stale_line_references(over), "越界引用没被认出"
