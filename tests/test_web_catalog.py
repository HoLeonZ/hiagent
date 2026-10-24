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
    """清单必须能被前端原样消费：每个 preset 的取值只能是 JSON 原生类型。

    具名回归：preset 里混入非 JSON 原生值（如 numpy.int64、decimal.Decimal、
    datetime.date）——引擎在 Python 层跑得动，但 API 序列化时 `json.dumps` 抛
    TypeError → HTTP 500。这条测试把该回归钉死在单测层。

    早先版本写的是 `json.dumps(params, default=list)`：实测对全部 101 个 preset，
    `default` 回调被调用 **0 次**——tuple 本就是 JSON 原生类型，那条“tuple 要能被
    前端吃到”的声明从未经过这条测试；`default=list` 还会把 set 这类可迭代的非原生值
    悄悄转成 list 放行。去掉 `default` 后，任何非原生值都会真的变红。
    """
    import json

    for eng, presets in all_presets().items():
        for name, params in presets.items():
            try:
                json.dumps(params)
            except TypeError as exc:
                pytest.fail(f"{eng}/{name} 含非 JSON 原生值，前端序列化会 500: {exc}")


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


def test_the_engine_notes_say_what_they_measure_and_carry_no_markdown():
    """**引擎口径说明**：讲清"这些数是什么口径"，且不许带 markdown 星号。

    `cycle_price_action` 是**逐票独立账户**回测（每票一个账户），不产生组合净值曲线；
    它的胜率/总盈亏是各票账户的汇总，与另外三个引擎的**组合口径**不可比。
    不说明，用户会把两者并排着看。

    判别力：`cycle_price_action` **必须**有说明，而另外三个引擎没有组合口径问题
    （它们都产出净值曲线），不该被无差别地加上一句。
    """
    from web.catalog import ENGINE_NOTES

    assert "cycle_price_action" in ENGINE_NOTES, "逐票独立账户的引擎必须说明口径"
    note = ENGINE_NOTES["cycle_price_action"]
    assert "独立账户" in note and "净值曲线" in note, f"说明没说到点子上：{note!r}"
    assert "**" not in note, "这段会被 textContent 原样显示，星号会露出来"
    for eng in ("short_reversal", "chase_up", "uptrend_pullback"):
        assert eng not in ENGINE_NOTES, f"{eng} 产出组合曲线，不需要逐票账户的说明"
