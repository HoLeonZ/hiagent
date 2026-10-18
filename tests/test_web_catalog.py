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


def test_declaration_keys_cover_the_audited_contract_set():
    """DECLARATION_KEYS 必须覆盖合规审计**实际执行校验**的键集。

    不抓测试源码里的字符串（脆弱正则），而是用**可执行探针**：取每个引擎的一个
    真实预设，逐键篡改成一个必然违规的值，跑两个审计函数，记录被报缺口的键。
    并集即「真实被守集合」，与 DECLARATION_KEYS 独立计算 —— 因此若审计将来开始
    守着某个尚未登记进 DECLARATION_KEYS 的键，这条测试立刻变红。

    覆盖的审计函数：
      - tests/test_compliance_audit_all_presets.py::_audit_presets（§4/§5）
      - tests/test_claudemd_full_audit.py::_audit_full（§2/§3/§4/§5）

    注：`universe` 不在本探针结果里 —— 上面两个审计都不校验它的取值；它由
    tests/test_presets.py（存在性 + 取值 'mainboard_only'）守，因此属于
    DECLARATION_KEYS 但并不出现在本探针的 guarded 集内。
    """
    from tests.test_claudemd_full_audit import _audit_full
    from tests.test_compliance_audit_all_presets import _audit_presets

    def _bad(orig):
        """给一个原值造一个**类型兼容**的必然违规值（避免审计里的比较抛错）。"""
        if isinstance(orig, bool):
            return not orig
        if isinstance(orig, (int, float)):
            return -999999  # < 1 且 ≠ 任何正期望值（n_comparisons/max_positions/…）
        if isinstance(orig, str):
            return "__BAD__"
        if isinstance(orig, dict):
            return {"__BAD__": True}
        if isinstance(orig, list):
            return ["__BAD__"]
        if isinstance(orig, tuple):
            return ("__BAD__",)
        return "__BAD__"

    guarded: set[str] = set()
    for eng, presets in all_presets().items():
        name = next(iter(presets))  # 每个引擎取一个真实合规预设
        base = presets[name]
        for key, value in base.items():
            mutated = dict(base)
            mutated[key] = _bad(value)
            if _audit_presets({name: mutated}, eng) or _audit_full({name: mutated}, eng):
                guarded.add(key)

    # 探针非退化：§4 的 4 个键 + §5 的 n_comparisons 必须被抓到
    assert len(guarded) >= 5, f"探针失效，仅抓到 {sorted(guarded)}"

    uncovered = guarded - set(DECLARATION_KEYS)
    assert not uncovered, (
        "合规审计开始守这些键，但 DECLARATION_KEYS 未同步（真实被守集合漂移了）: "
        f"{sorted(uncovered)}"
    )
