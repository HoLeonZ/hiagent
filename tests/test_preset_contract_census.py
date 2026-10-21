"""§2 的 preset 声明契约必须对**每一个** preset 成立 —— 而它此前只在"有人跑那个 preset"时才成立。

## §2 原文

> Every preset MUST explicitly declare `max_positions` and `position_fraction` —
> a preset that leaves them implicit is a contract violation.

## 现状(实测 2026-10-21)

* `core/preset_contract.py::_declared()` **缺键即抛** `PresetDeclarationMissing` —— 机制是对的;
* 四族**在生产里都消费**这两个解析器(`chase_up/backtrader_engine`、`uptrend/backtest` +
  `backtrader_engine`、`short_reversal/engine`、`cycle/backtest`)—— 声明是**载重**的;
* 但**没有任何测试**调用过 `resolve_max_positions` / `resolve_position_fraction`
  ⇒ 少一个键只会在**真跑到那个 preset 时**才炸(而"没跑到的 preset"与"合规的"看起来一样);
* 今天全部 **101** 个 preset(22 + 3 + 75 + 1)**都合规** ⇒ 钉它是安全的,且不产生假红。

⇒ 本文件把「契约对**每一个** preset 成立」变成一条**普查**判据,并把四个注册表**枚举清楚**
(`PRESETS` × 3 + cycle 的单个 `PRESET_V1`,与 `test_preset_to_engine_api_conformance.py` 同口径)。
"""
from __future__ import annotations

import importlib

import pytest

from core.preset_contract import (
    PresetDeclarationMissing,
    resolve_max_positions,
    resolve_position_fraction,
)

#: (引擎, 模块, 属性名)。cycle 只暴露**单个** cfg(`PRESET_V1`),故按一个 preset 处理。
REGISTRIES: tuple[tuple[str, str, str], ...] = (
    ("chase_up", "chase_up.presets", "PRESETS"),
    ("uptrend_pullback", "uptrend_pullback.presets", "PRESETS"),
    ("short_reversal", "short_reversal.presets", "PRESETS"),
    ("cycle_price_action", "cycle_price_action.presets", "PRESET_V1"),
)

_RESOLVERS = (
    (resolve_max_positions, "max_positions"),
    (resolve_position_fraction, "position_fraction"),
)


def presets_of(module_path: str, attr: str) -> dict[str, dict]:
    """取出该引擎的 preset 注册表;`PRESET_V1` 这种**单个** cfg 包一层。"""
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    if attr == "PRESETS":
        return dict(obj)
    return {obj.get("name", attr): obj}


def contract_failures(presets: dict[str, dict]) -> list[str]:
    """对每个 preset 调两个解析器;返回所有不合规项(空 = 全部合规)。"""
    failures: list[str] = []
    for name, cfg in presets.items():
        for resolver, key in _RESOLVERS:
            try:
                resolver(cfg, name)
            except PresetDeclarationMissing as exc:
                failures.append(f"{key}: {exc}")
    return failures


@pytest.mark.parametrize("engine,module_path,attr", REGISTRIES,
                         ids=[entry[0] for entry in REGISTRIES])
def test_every_preset_declares_both_sizing_keys(engine: str, module_path: str, attr: str) -> None:
    """§2:每个 preset 都必须**显式**声明 `max_positions` 与 `position_fraction`。"""
    presets = presets_of(module_path, attr)
    assert presets, f"{engine}: 注册表 {module_path}.{attr} 是空的 —— 普查会变成空转"
    failures = contract_failures(presets)
    assert not failures, (
        f"§2 CONTRACT VIOLATION: {engine} 有 {len(failures)} 处声明不合规"
        f"(preset 共 {len(presets)} 个):\n  " + "\n  ".join(failures[:10])
    )


def test_the_census_enumerates_all_four_engines() -> None:
    """**对账**:四个引擎的注册表都要真的取到,且合计覆盖到全部 preset。

    (单个引擎枚举失效时,上面那条会因为"0 个 preset"而**空转** —— 它自己看不出来。)
    """
    totals = {}
    for engine, module_path, attr in REGISTRIES:
        totals[engine] = len(presets_of(module_path, attr))
    assert set(totals) == {entry[0] for entry in REGISTRIES}, totals
    empty = sorted(name for name, count in totals.items() if count == 0)
    assert not empty, f"这些引擎一个 preset 都没枚举到:{empty}"
    assert sum(totals.values()) > 0


def test_the_census_checker_has_teeth() -> None:
    """**牙齿**:缺键 / 越界必须报,合规不得报。

    (`position_fraction=1.5` 也要报 —— 契约除了"在不在",还管"越不越界"。)
    """
    clean = {"ok": {"max_positions": 1, "position_fraction": 1.0}}
    assert contract_failures(clean) == []

    missing_max = {"bad": {"position_fraction": 1.0}}
    assert any("max_positions" in item for item in contract_failures(missing_max)), (
        "缺 max_positions 却没报"
    )

    missing_fraction = {"bad": {"max_positions": 1}}
    assert any("position_fraction" in item for item in contract_failures(missing_fraction)), (
        "缺 position_fraction 却没报"
    )

    out_of_range = {"bad": {"max_positions": 1, "position_fraction": 1.5}}
    assert contract_failures(out_of_range), "position_fraction=1.5 越界却没报"