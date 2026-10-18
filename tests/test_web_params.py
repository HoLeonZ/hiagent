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


# --- Important 1: bool/list/dict 三类此前零校验 ---


def test_overrides_rejects_a_string_for_a_bool_param():
    """Important 1: bool 参数此前任意值放行，现必须类型校验。"""
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"require_ma20_slope_neg": "notabool"})


def test_overrides_accepts_a_real_bool():
    got = validate_overrides("short_reversal", "v50_slope", {"require_ma20_slope_neg": True})
    assert got == {"require_ma20_slope_neg": True}


def test_overrides_rejects_a_string_for_a_list_param():
    """Important 1: list 参数（periods / ensemble_substrategies）此前任意值放行。"""
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("cycle_price_action", "PRESET_V1", {"periods": "abc"})


def test_overrides_accepts_a_list_for_a_list_param():
    got = validate_overrides("cycle_price_action", "PRESET_V1", {"periods": [3, 5, 8]})
    assert got == {"periods": [3, 5, 8]}


def test_overrides_rejects_a_string_for_a_dict_param():
    """Important 1: dict 参数（signal / regime）此前任意值放行。"""
    from web.catalog import all_presets

    eng = "chase_up"
    preset = next(iter(all_presets()[eng]))
    with pytest.raises(OverrideError, match="type"):
        validate_overrides(eng, preset, {"signal": "notadict"})


def test_overrides_accepts_a_dict_for_a_dict_param():
    from web.catalog import all_presets

    eng = "chase_up"
    preset = next(iter(all_presets()[eng]))
    got = validate_overrides(eng, preset, {"signal": {"foo": 1}})
    assert got == {"signal": {"foo": 1}}


# --- Minor 6: bool 是 int 子类，不得冒充数值 ---


def test_overrides_rejects_bool_for_a_numeric_param():
    """Minor 6: isinstance(True, (int, float)) 为真，`{"tp_pct": True}` 必须被拒。"""
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"tp_pct": True})
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"max_hold": False})


# --- Important 2: 空 overrides 不得绕过引擎/预设合法性 ---


def test_empty_overrides_still_validates_engine_and_preset():
    """Important 2: 同一个未知引擎，空 overrides 之前静默过、非空抛错——现在都抛。"""
    with pytest.raises(KeyError, match="unknown engine"):
        validate_overrides("bogus", "bogus", {})
    with pytest.raises(KeyError, match="unknown engine"):
        validate_overrides("bogus", "bogus", None)
    # 未知预设（引擎合法）也要抛
    with pytest.raises(KeyError, match="unknown preset"):
        validate_overrides("short_reversal", "no_such_preset", {})


def test_empty_overrides_on_a_real_preset_is_still_a_no_op():
    assert validate_overrides("short_reversal", "v50_slope", {}) == {}
    assert validate_overrides("short_reversal", "v50_slope", None) == {}


# --- Important 3: 无元数据的可调键 fail-fast + choices 校验 ---


def test_tunable_key_without_metadata_fails_fast(monkeypatch):
    """Important 3: 可调键漏登记元数据时必须抛错，绝不 `continue` 静默放行。"""
    import web.params as params_mod

    patched = {eng: dict(meta) for eng, meta in params_mod.PARAM_METADATA.items()}
    del patched["short_reversal"]["tp_pct"]  # 制造一个元数据缺口
    monkeypatch.setattr(params_mod, "PARAM_METADATA", patched)
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"tp_pct": 0.05})


def test_overrides_rejects_a_value_outside_choices():
    """Important 3: choices 此前从不被校验，`{"d_mode": "zzz"}` 会通过。"""
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v50_slope", {"d_mode": "zzz"})


def test_overrides_accepts_every_declared_choice():
    for choice in ("strict", "converge_strict", "d_only"):
        got = validate_overrides("short_reversal", "v50_slope", {"d_mode": choice})
        assert got == {"d_mode": choice}


# --- Important 4: 返回深拷贝，与引擎全局不共享嵌套结构 ---


def test_split_params_periods_is_not_the_engine_global():
    """Important 4 要求的 `is not` 实测：cycle 的 periods（tuple）不再同引用。"""
    import cycle_price_action.presets as cp

    out = split_params("cycle_price_action", "PRESET_V1")
    assert out["tunable"]["periods"] is not cp.PRESET_V1["periods"]


def test_catalog_output_is_detached_from_engine_globals():
    """Important 4: 任何嵌套容器都不得与引擎模块的全局 PRESETS 同引用。

    覆盖四个引擎的每一个预设：逐键比对容器型取值（dict/list/tuple）的 identity，
    并证明原地改返回结构不会污染引擎全局。
    """
    import importlib

    from web.catalog import ENGINES, all_presets

    presets = all_presets()
    for eng, ps in presets.items():
        mod = importlib.import_module(ENGINES[eng])
        if hasattr(mod, "PRESETS"):
            engine_globals = mod.PRESETS
        else:
            engine_globals = {
                n: getattr(mod, n)
                for n in dir(mod)
                if n.startswith("PRESET_") and isinstance(getattr(mod, n), dict)
            }
        for name, cfg in ps.items():
            global_cfg = engine_globals[name]
            for key, value in cfg.items():
                if isinstance(value, (dict, list, tuple)):
                    assert value is not global_cfg[key], (
                        f"{eng}/{name}.{key} 与引擎全局同引用（浅拷贝没修干净）"
                    )
            # 原地改返回副本，全局必须不动
            for key, value in cfg.items():
                if isinstance(value, dict):
                    value["__poison__"] = 1
                    assert "__poison__" not in global_cfg[key]
                elif isinstance(value, list):
                    value.append("__poison__")
                    assert "__poison__" not in global_cfg[key]
