"""参数层：清单完整性、cycle 特判、声明字段只读。"""
from __future__ import annotations

import pytest

from web.catalog import DECLARATION_KEYS, ENGINES, all_presets

EXPECTED_COUNTS = {
    "short_reversal": 75,
    "chase_up": 22,
    "uptrend_pullback": 3,
    "cycle_price_action": 1,
}


def test_all_four_engines_are_present():
    assert set(ENGINES) == set(EXPECTED_COUNTS)


def test_every_engine_yields_its_presets():
    got = {eng: len(presets) for eng, presets in all_presets().items()}
    assert got == EXPECTED_COUNTS
    assert sum(got.values()) == 101


def test_cycle_price_action_is_not_silently_dropped():
    """cycle 没有 PRESETS 属性，只有 PRESET_V1。

    任何“遍历 PRESETS”的清单逻辑都会静默丢掉它——这条测试就是为了钉住那个特判。
    """
    presets = all_presets()["cycle_price_action"]
    assert list(presets) == ["PRESET_V1"]
    assert presets["PRESET_V1"], "PRESET_V1 不应为空"


def test_every_preset_is_json_serialisable():
    """tuple（如 cycle 的 periods）必须能被前端吃到。"""
    import json

    for eng, presets in all_presets().items():
        for name, params in presets.items():
            json.dumps(params, default=list)  # 不抛即通过


def test_declaration_keys_are_the_ten_contract_fields():
    assert DECLARATION_KEYS == {
        "universe", "intraday_tiebreak", "max_volume_participation",
        "price_source_for_signal", "price_source_for_execution",
        "n_comparisons", "position_sizing", "max_positions",
        "position_fraction", "MAX_POSITION_PCT",
    }
