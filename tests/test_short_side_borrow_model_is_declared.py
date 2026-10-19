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
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 做空引擎 —— §4 的打分对象。新增做空引擎时要同步这里(下面有对账用例)。
SHORT_ENGINES: dict[str, dict] = {
    "short_reversal": {
        "presets": "short_reversal/presets.py",
        "declaration": "BORROW_ASSUMPTION",
        # 引擎侧必须真的把费率传下去(证明声明不是装饰):
        "consumer_patterns": (
            r"margin_rate=BORROW_RATE_ANNUAL",
            r"MARGIN_RATE\s*=\s*BORROW_RATE_ANNUAL",
        ),
    },
}

_REQUIRED_KEYS = ("availability", "borrow_cost_model", "borrow_cost_rate")


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


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
    """**声明必须被消费** —— 不是装饰。

    本仓库反复栽在"声明了却无人读取";§4 这条规矩的实质是"回测的融券成本是**按声明的模型
    真的计提的**",所以守卫要看到费率**流到计提点**。
    """
    src = _src("short_reversal/replay_strategy_v3.py")
    patterns = SHORT_ENGINES["short_reversal"]["consumer_patterns"]
    hit = [p for p in patterns if re.search(p, src)]
    assert hit, (
        "§4: 借券费率**没有被任何计提点消费** —— 声明成了装饰。"
        f"期望在 short_reversal/replay_strategy_v3.py 里看到 {patterns} 之一"
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
    """**对账**:`SHORT_ENGINES` 必须等于"四个引擎里声明了借券假设的那些"。

    (与其它登记表同型:名单不能悄悄变短。新增做空引擎 ⇒ 这里红。)
    """
    declared = {
        p.parent.name
        for p in (REPO_ROOT / "short_reversal").glob("presets.py")
        if "BORROW_ASSUMPTION" in p.read_text(encoding="utf-8")
    }
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
