"""参数拆分与 overrides 校验。"""
from __future__ import annotations

import pytest

from web.params import (
    PARAM_METADATA,
    OverrideError,
    split_params,
    validate_overrides,
)


def test_split_separates_tunable_from_declarations():
    out = split_params("short_reversal", "v50_slope")
    assert set(out) == {"tunable", "declarations", "metadata"}
    # 声明字段必须落在 declarations 里，且不得出现在 tunable
    assert "n_comparisons" in out["declarations"]
    assert "price_source_for_signal" in out["declarations"]
    assert not (set(out["tunable"]) & {"n_comparisons", "universe"})


def test_tunable_contains_real_strategy_parameters():
    out = split_params("short_reversal", "v50_slope")
    assert {"tp_pct", "sl_pct", "max_hold"} <= set(out["tunable"])


def test_metadata_covers_every_tunable_key():
    """双向之一：可调键必须有元数据，否则 UI 会静默漏掉一个参数。"""
    for engine in ("short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"):
        from web.catalog import all_presets

        for preset in all_presets()[engine]:
            out = split_params(engine, preset)
            missing = set(out["tunable"]) - set(out["metadata"])
            assert not missing, f"{engine}/{preset} 缺少元数据: {sorted(missing)}"


def test_metadata_has_no_ghost_keys():
    """双向之二：元数据不得引用不存在的可调键。

    必须比对**原始** `PARAM_METADATA`，而不是 `split_params` 的输出——后者的
    `metadata` 是按 `tunable` 过滤出来的（`{k: meta[k] for k in tunable if k in meta}`），
    于是 `set(out["metadata"]) - set(out["tunable"])` 恒为空集，这条测试会退化成永真。

    真正的幽灵：登记在 `PARAM_METADATA[引擎]` 里、却不出现在该引擎**任何 preset**
    的可调键并集中的键。`overrides` 永远暴露不到它、UI 也永远编辑不到它。
    """
    from web.catalog import DECLARATION_KEYS, all_presets

    for engine, engine_presets in all_presets().items():
        tunable_union = {
            k
            for params in engine_presets.values()
            for k in params
            if k not in DECLARATION_KEYS
        }
        ghosts = set(PARAM_METADATA.get(engine, {})) - tunable_union
        assert not ghosts, f"{engine} 元数据有幽灵键: {sorted(ghosts)}"


def test_declaration_values_are_present_in_declarations():
    out = split_params("short_reversal", "v50_slope")
    assert out["declarations"]["price_source_for_signal"] == "adj_close"
    assert out["declarations"]["price_source_for_execution"] == "raw_close"


def test_overrides_accepts_a_tunable_key():
    got = validate_overrides("short_reversal", "v50_slope", {"tp_pct": 0.09})
    assert got == {"tp_pct": 0.09}


def test_overrides_rejects_a_declaration_key():
    """改声明字段会产出过不了合规审计的预设。"""
    with pytest.raises(OverrideError, match="declaration"):
        validate_overrides("short_reversal", "v50_slope", {"position_fraction": 0.5})


def test_overrides_rejects_an_unknown_key():
    """未知键必须报错，不能静默忽略——否则用户以为改了但没改。"""
    with pytest.raises(OverrideError, match="unknown"):
        validate_overrides("short_reversal", "v50_slope", {"no_such_param": 1})


def test_overrides_rejects_a_non_numeric_value_for_a_numeric_param():
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"tp_pct": "high"})
