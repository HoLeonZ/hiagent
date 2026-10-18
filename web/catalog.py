"""预设清单与参数元数据。

单一职责：把四个异构的 presets 模块整理成一份统一的、可 JSON 化的清单。
不接触回测、不接触 DB、不接触 HTTP。
"""
from __future__ import annotations

import copy
import importlib
from typing import Any

#: 四个引擎 → 其 presets 模块路径
ENGINES: dict[str, str] = {
    "short_reversal": "short_reversal.presets",
    "chase_up": "chase_up.presets",
    "uptrend_pullback": "uptrend_pullback.presets",
    "cycle_price_action": "cycle_price_action.presets",
}

#: §2/§3/§4/§5 的契约声明字段。在 UI 中**只读**：改动它们会产出过不了合规审计的预设。
#:
#: 各键**分别**由哪条测试守（此前注释把 10 个键一律归给
#: test_compliance_audit_all_presets.py，该文件实测只守其中 5 个）：
#:   - tests/test_compliance_audit_all_presets.py：intraday_tiebreak /
#:     max_volume_participation / price_source_for_signal /
#:     price_source_for_execution / n_comparisons（4 键 + n_comparisons = 5 键）
#:   - tests/test_claudemd_full_audit.py：在上一组之外补 position_sizing /
#:     position_fraction / max_positions / MAX_POSITION_PCT（§2 Capital, 4 键）
#:   - tests/test_presets.py：universe（存在性 + 取值 'mainboard_only'）
#:
#: 「真实被守集合」由 tests/test_web_catalog.py::
#: test_declaration_keys_cover_the_audited_contract_set 用**可执行探针**主动核对
#: （篡改预设 → 审计函数报缺口），审计一旦开始守新键而这里未跟上，立即变红。
DECLARATION_KEYS: frozenset[str] = frozenset({
    "universe",
    "intraday_tiebreak",
    "max_volume_participation",
    "price_source_for_signal",
    "price_source_for_execution",
    "n_comparisons",
    "position_sizing",
    "max_positions",
    "position_fraction",
    "MAX_POSITION_PCT",
})


def _detach(value: Any) -> Any:
    """递归重建一份与入参**不共享任何容器**的私有副本（深拷贝）。

    为什么不用 `copy.deepcopy` 了事：`deepcopy` 对**全由不可变量组成的 tuple**
    会原样返回同一个对象（CPython 的 `_deepcopy_tuple` 优化），于是
    `deepcopy(("a", "b")) is ("a", "b")` 为真。清单里的 `periods` 恰好是这种
    tuple，会继续与引擎全局 `PRESETS` 同引用。这里对 list/tuple 显式重建，
    保证连 tuple 都是新对象；标量叶子再走 `deepcopy`，对未来出现的新类型安全。
    """
    if isinstance(value, dict):
        return {k: _detach(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_detach(v) for v in value]
    if isinstance(value, tuple):
        # 从生成器构造 tuple 一定得到新对象，绝不会命中上面的 deepcopy 别名优化。
        return tuple(_detach(v) for v in value)
    return copy.deepcopy(value)


def _module_presets(engine: str) -> dict[str, dict]:
    """取一个引擎的全部预设，吸收 `PRESETS` 与 `PRESET_*` 两种形态。

    `cycle_price_action` **没有** `PRESETS` 属性，只有一个模块级 `PRESET_V1`。
    这里必须显式兜住它，否则它会从清单里静默消失。

    每个预设都返回 `_detach` 出来的**私有深拷贝**，不是 `dict(params)` 那样的
    浅拷贝。原因：`signal` / `regime` / `periods` / `ensemble_substrategies`
    等嵌套值在浅拷贝下与引擎模块的全局 `PRESETS` **同引用**，任何 handler
    原地修改都会污染进程级全局、跨请求串味（§0 确定性）。深拷贝把返回值
    变成调用方私有对象，可安全原地改。
    """
    mod = importlib.import_module(ENGINES[engine])
    if hasattr(mod, "PRESETS"):
        return {name: _detach(params) for name, params in mod.PRESETS.items()}
    # cycle 形态：模块级 PRESET_* 常量
    return {
        name: _detach(getattr(mod, name))
        for name in dir(mod)
        if name.startswith("PRESET_") and isinstance(getattr(mod, name), dict)
    }


def all_presets() -> dict[str, dict[str, dict]]:
    """返回 `{引擎: {预设名: 参数字典}}`，四个引擎齐全。

    **返回值是调用方私有**：每个预设都是深拷贝，可安全原地修改，不会影响
    引擎模块的全局 `PRESETS`。修改本函数返回值（含嵌套 dict/list/tuple）
    不会污染其它调用方或引擎模块。
    """
    return {engine: _module_presets(engine) for engine in ENGINES}


def engine_of(preset: str) -> str | None:
    """反查预设属于哪个引擎；多个引擎同名时返回第一个（当前不存在同名）。"""
    for engine, presets in all_presets().items():
        if preset in presets:
            return engine
    return None
