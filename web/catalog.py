"""预设清单与参数元数据。

单一职责：把四个异构的 presets 模块整理成一份统一的、可 JSON 化的清单。
不接触回测、不接触 DB、不接触 HTTP。
"""
from __future__ import annotations

import importlib
from typing import Any

#: 四个引擎 → 其 presets 模块路径
ENGINES: dict[str, str] = {
    "short_reversal": "short_reversal.presets",
    "chase_up": "chase_up.presets",
    "uptrend_pullback": "uptrend_pullback.presets",
    "cycle_price_action": "cycle_price_action.presets",
}

#: §2/§3/§4/§5 的契约声明字段。在 UI 中**只读**：
#: 改动它们会产出过不了 tests/test_compliance_audit_all_presets.py 的预设。
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


def _module_presets(engine: str) -> dict[str, dict]:
    """取一个引擎的全部预设，吸收 `PRESETS` 与 `PRESET_*` 两种形态。

    `cycle_price_action` **没有** `PRESETS` 属性，只有一个模块级 `PRESET_V1`。
    这里必须显式兜住它，否则它会从清单里静默消失。
    """
    mod = importlib.import_module(ENGINES[engine])
    if hasattr(mod, "PRESETS"):
        return {name: dict(params) for name, params in mod.PRESETS.items()}
    # cycle 形态：模块级 PRESET_* 常量
    return {
        name: dict(getattr(mod, name))
        for name in dir(mod)
        if name.startswith("PRESET_") and isinstance(getattr(mod, name), dict)
    }


def all_presets() -> dict[str, dict[str, dict]]:
    """返回 `{引擎: {预设名: 参数字典}}`，四个引擎齐全。"""
    return {engine: _module_presets(engine) for engine in ENGINES}


def engine_of(preset: str) -> str | None:
    """反查预设属于哪个引擎；多个引擎同名时返回第一个（当前不存在同名）。"""
    for engine, presets in all_presets().items():
        if preset in presets:
            return engine
    return None
