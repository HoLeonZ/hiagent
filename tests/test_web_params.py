"""参数拆分与 overrides 校验。"""
from __future__ import annotations

import pytest

from web.params import (
    IGNORED_KEYS,
    PARAM_METADATA,
    OverrideError,
    split_params,
    validate_overrides,
)


def test_split_separates_tunable_from_declarations():
    out = split_params("short_reversal", "v50_slope")
    assert set(out) == {"tunable", "declarations", "ignored", "metadata"}
    # 声明字段必须落在 declarations 里，且不得出现在 tunable
    assert "n_comparisons" in out["declarations"]
    assert "price_source_for_signal" in out["declarations"]
    assert not (set(out["tunable"]) & {"n_comparisons", "universe"})


def test_tunable_contains_real_strategy_parameters():
    out = split_params("short_reversal", "v50_slope")
    assert {"tp_pct", "sl_pct", "max_hold"} <= set(out["tunable"])


def test_metadata_covers_every_tunable_key():
    """双向之一：可调键必须有元数据，否则 UI 会静默漏掉一个参数。

    忽略键（引擎不消费、覆盖无效）**不属于** `tunable`，故此处**不**要求它们有元数据。
    但它们与 `tunable` / `declarations` 必须是互斥划分——这里一并钉住
    `ignored ∩ tunable == ∅`（否则忽略键会既"可调"又"被忽略"，语义自相矛盾）。
    """
    for engine in ("short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"):
        from web.catalog import all_presets

        for preset in all_presets()[engine]:
            out = split_params(engine, preset)
            missing = set(out["tunable"]) - set(out["metadata"])
            assert not missing, f"{engine}/{preset} 缺少元数据: {sorted(missing)}"
            assert not (set(out["ignored"]) & set(out["tunable"])), (
                f"{engine}/{preset} 的 ignored 与 tunable 重叠: "
                f"{sorted(set(out['ignored']) & set(out['tunable']))}"
            )
            assert not (set(out["ignored"]) & set(out["declarations"])), (
                f"{engine}/{preset} 的 ignored 与 declarations 重叠: "
                f"{sorted(set(out['ignored']) & set(out['declarations']))}"
            )


def test_metadata_has_no_ghost_keys():
    """双向之二：元数据不得引用不存在的可调键。

    必须比对**原始** `PARAM_METADATA`，而不是 `split_params` 的输出——后者的
    `metadata` 是按 `tunable` 过滤出来的（`{k: meta[k] for k in tunable if k in meta}`），
    于是 `set(out["metadata"]) - set(out["tunable"])` 恒为空集，这条测试会退化成永真。

    真正的幽灵：登记在 `PARAM_METADATA[引擎]` 里、却不出现在该引擎**任何 preset**
    的可调键并集中的键。`overrides` 永远暴露不到它、UI 也永远编辑不到它。

    **忽略键也算"真实键"**，必须被本检查覆盖：它们仍出现在 preset 里（只是引擎不消费），
    故 `PARAM_METADATA` 里为它们留的条目不是幽灵。合法键域 = `tunable ∪ ignored`
    （二者恰好是该引擎 preset 里全部非声明键）。
    """
    from web.catalog import all_presets

    for engine, engine_presets in all_presets().items():
        referenced: set[str] = set()
        for preset in engine_presets:
            out = split_params(engine, preset)
            referenced |= set(out["tunable"]) | set(out["ignored"])
        ghosts = set(PARAM_METADATA.get(engine, {})) - referenced
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
    """Important 1: list 参数（ensemble_substrategies）此前任意值放行。

    注：cycle 的 `periods` 也曾在旧版被用作 list 参数样例，但它现已是**引擎忽略键**
    （见 test_overrides_rejects_an_engine_ignored_key），故换成 short_reversal 的
    真正可调 list 参数 `ensemble_substrategies`。
    """
    with pytest.raises(OverrideError, match="type"):
        validate_overrides("short_reversal", "v63_ensemble", {"ensemble_substrategies": "abc"})


def test_overrides_accepts_a_list_for_a_list_param():
    got = validate_overrides(
        "short_reversal", "v63_ensemble", {"ensemble_substrategies": ["v50_slope", "v44_ratio02_buf07"]}
    )
    assert got == {"ensemble_substrategies": ["v50_slope", "v44_ratio02_buf07"]}


def test_overrides_rejects_a_string_for_a_dict_param():
    """Important 1: dict 参数（signal / regime）此前任意值放行。"""
    from web.catalog import all_presets

    eng = "chase_up"
    preset = next(iter(all_presets()[eng]))
    with pytest.raises(OverrideError, match="type"):
        validate_overrides(eng, preset, {"signal": "notadict"})


def test_overrides_accepts_a_dict_for_a_dict_param():
    """dict 参数接受 dict —— **键取引擎真实的键**。

    原稿写的是 `{"foo": 1}`：一个**编造的占位键**。它本意是验"容器类型对不对"，
    却顺带断言了"任意键都放行"——而那已确认是错的（未知键在引擎里会变成 `TypeError`
    → 500 而不是 400）。占位键让这条测试在**该红的时候一直绿着**。
    """
    from web.catalog import all_presets
    from web.params import split_params

    eng = "chase_up"
    preset = next(iter(all_presets()[eng]))
    real = dict(split_params(eng, preset)["tunable"]["signal"])
    got = validate_overrides(eng, preset, {"signal": dict(real)})
    assert got == {"signal": dict(real)}


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
    """Important 4 要求的 `is not` 实测：cycle 的 periods（tuple）不再同引用。

    `periods` 是引擎忽略键，现归 `ignored`（而非 `tunable`），但深拷贝保证不变。
    """
    import cycle_price_action.presets as cp

    out = split_params("cycle_price_action", "PRESET_V1")
    assert out["ignored"]["periods"] is not cp.PRESET_V1["periods"]


def test_every_preset_accepts_its_own_values():
    """每个 preset 的真实可调取值都必须能通过 validate_overrides。

    不变量：校验器不得拒掉引擎自己的取值。
    缺这条时，cycle 的 tuple `periods` 被拒而 29 条测试全绿——用户在 UI 里
    不动参数直接提交会拿到 400，而参数是对的。

    排除 `declarations`（只读契约字段）与 `ignored`（引擎忽略键，覆盖**本应**被拒）
    ——这两类都不是"可调取值"。
    """
    from web.catalog import DECLARATION_KEYS, all_presets

    bad = []
    for engine, presets in all_presets().items():
        ignored = IGNORED_KEYS.get(engine, frozenset())
        for name, params in presets.items():
            tunable = {
                k: v for k, v in params.items()
                if k not in DECLARATION_KEYS and k not in ignored
            }
            try:
                validate_overrides(engine, name, tunable)
            except Exception as exc:
                bad.append(f"{engine}/{name}: {type(exc).__name__}: {exc}")
    assert not bad, "校验器拒掉了 preset 自己的取值:\n  " + "\n  ".join(bad)


# --- 引擎忽略键（焦点 3）：存在于 preset 但引擎不消费，覆盖必须 fail-fast ---


def test_cycle_engine_declares_its_lazy_keys_as_ignored():
    """cycle 的 4 个惰性键必须被登记为 ignored，且声明字段优先。

    回归守卫：若 `IGNORED_KEYS` 被整体删掉，这 4 个键会重新落回 `tunable`，
    用户又能"填了没用"——本测试即变红。
    """
    out = split_params("cycle_price_action", "PRESET_V1")
    lazy = {"weight_kline", "weight_cycle", "weight_calendar", "periods"}
    assert lazy <= set(out["ignored"]), (
        f"cycle 惰性键未全部登记为 ignored: {sorted(lazy - set(out['ignored']))}"
    )
    # 声明优先：max_volume_participation 同时是 DECLARATION_KEYS，落在 declarations，
    # 不得因出现在 IGNORED_KEYS 里就挪进 ignored 或 tunable。
    assert "max_volume_participation" in out["declarations"]
    assert "max_volume_participation" not in out["ignored"]
    assert "max_volume_participation" not in out["tunable"]


def test_overrides_rejects_an_engine_ignored_key():
    """覆盖引擎忽略键必须 fail-fast（不再静默丢弃，§本任务焦点 3）。"""
    for key in ("weight_kline", "weight_cycle", "weight_calendar", "periods"):
        with pytest.raises(OverrideError, match="ignored"):
            validate_overrides("cycle_price_action", "PRESET_V1", {key: 1.0})


def test_declaration_wins_over_ignored_on_the_overlap():
    """重叠加键（max_volume_participation）必须以 declaration 名义被拒，而非 ignored。"""
    with pytest.raises(OverrideError, match="declaration"):
        validate_overrides("cycle_price_action", "PRESET_V1", {"max_volume_participation": 0.2})


def test_ignored_keys_point_at_real_preset_keys_and_respect_declaration_priority():
    """IGNORED_KEYS 不得有幽灵/错别字：每个键必须是该引擎某个 preset 的真实键。

    与 `DECLARATION_KEYS` 的**重叠是允许且有意的**（cycle 的
    `max_volume_participation` 既被引擎过滤、又是 §4 契约字段），故此处**不**要求
    二者互斥，而是钉住"重叠时声明优先"的落地：这类键必须出现在 `split_params` 的
    `declarations` 里、不出现在 `ignored` / `tunable` 里。
    """
    from web.catalog import DECLARATION_KEYS, all_presets

    presets = all_presets()
    for engine, ignored in IGNORED_KEYS.items():
        engine_keys = {k for params in presets.get(engine, {}).values() for k in params}
        assert ignored <= engine_keys, (
            f"{engine} 的 IGNORED_KEYS 含幽灵键: {sorted(ignored - engine_keys)}"
        )
        # 声明优先落地：与 DECLARATION_KEYS 重叠的键归 declarations，不进 ignored/tunable。
        overlap = set(ignored) & set(DECLARATION_KEYS)
        for name in presets.get(engine, {}):
            out = split_params(engine, name)
            assert overlap <= set(out["declarations"]), (
                f"{engine}/{name} 声明/忽略重叠键未落入 declarations: "
                f"{sorted(overlap - set(out['declarations']))}"
            )
            assert not (overlap & (set(out["ignored"]) | set(out["tunable"]))), (
                f"{engine}/{name} 声明/忽略重叠键出现了二义归属"
            )


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


# --- Minor: 非 dict 的 overrides 必须是 400（OverrideError），不能漏成 500 ---


def test_non_dict_overrides_are_rejected_as_override_error():
    """非 dict 入参必须走 OverrideError（接入方用它映射 400）。

    实测旧行为：`['tp_pct']` → AttributeError（:193 的 `.items()`）、`5` → TypeError
    （:189 的 `set()`）、`[]` → **静默返回 {}**（最坏：冒充“无覆盖”）。三者在 HTTP 层
    都不是 400。修后：None 仍表示无覆盖，其它非 dict 一律 OverrideError。
    """
    for bad in (["tp_pct"], 5, [], (1, 2), "tp_pct", {1, 2}):
        with pytest.raises(OverrideError, match="type"):
            validate_overrides("short_reversal", "v50_slope", bad)


def test_none_overrides_is_still_a_no_op():
    """None 仍合法（表示“无覆盖”），不得被上面的类型守卫误伤。"""
    assert validate_overrides("short_reversal", "v50_slope", None) == {}


def test_non_dict_overrides_still_validates_engine_and_preset_first():
    """引擎/预设非法时先抛 KeyError，类型守卫不掩盖它。"""
    with pytest.raises(KeyError, match="unknown engine"):
        validate_overrides("bogus", "bogus", ["tp_pct"])
    with pytest.raises(KeyError, match="unknown preset"):
        validate_overrides("short_reversal", "no_such_preset", 5)


# --- 语义: declaration 判定对照全局 DECLARATION_KEYS，而非该 preset 的子集 ---


def test_declaration_rejection_does_not_depend_on_preset_membership(monkeypatch):
    """键在 DECLARATION_KEYS 里、但该 preset 未声明时，仍须报 declaration 而非 unknown。

    用户改的是 §2/§3/§4/§5 契约字段，拒绝理由与它是否出现在这个 preset 里无关。
    现状：全部 101 个 preset 都声明了全部 10 个契约键，故需用 monkeypatch 剥掉
    `max_positions` 才能触发这条分支（旧写法会把它降级成 `unknown`）。
    """
    import web.params as params_mod
    from web.catalog import all_presets

    real = all_presets()
    stripped = {
        eng: {
            name: {k: v for k, v in p.items() if k != "max_positions"}
            for name, p in ps.items()
        }
        for eng, ps in real.items()
    }
    monkeypatch.setattr(params_mod, "all_presets", lambda: stripped)

    with pytest.raises(OverrideError, match="declaration"):
        validate_overrides("short_reversal", "v50_slope", {"max_positions": 5})
    # 同一预设里**已声明**的契约键依旧报 declaration（现有行为不得被破坏）
    with pytest.raises(OverrideError, match="declaration"):
        validate_overrides("short_reversal", "v50_slope", {"position_fraction": 0.5})


#: 一个**真实存在**的 chase_up 预设：它的 sl_pct/tp_pct 在 PARAM_METADATA 里没有 range，
#: 正是"非有限数能溜过去"的那一类。
CHASE_PRESET = "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16"


def test_non_finite_numbers_are_rejected_even_without_a_range():
    """`NaN` / `±Inf` 必须拦下，**不能只靠 range 检查**。

    实测（2026-10-19）：`PARAM_METADATA` 里**大多数**数值键没有 `range`
    （chase_up 的 `sl_pct`/`tp_pct`/`atr_*`、cycle 的 `threshold`、
    short_reversal 的 `pct_chg_low` …），于是 `inf`/`NaN` 一路通过
    `isinstance(value, float)` 进引擎。只有恰好带 range 的键才被间接拦下
    （靠 `not (lo <= nan <= hi)` 为真）。

    后果不只是"引擎收到怪值"：账本与 `result.json` 都是 `json.dumps(..., default=str)`，
    非有限数会被写成 `Infinity` / `NaN` 字面量 —— **那不是合法 JSON**，
    浏览器 `JSON.parse` 读不了，一次"成功"的运行会把历史/对比面板弄坏。
    """
    import math

    for bad in (float("inf"), float("-inf"), float("nan")):
        for key in ("sl_pct", "tp_pct"):          # 这两个在 chase_up 上都没有 range
            with pytest.raises(OverrideError) as e:
                validate_overrides("chase_up", CHASE_PRESET, {key: bad})
            msg = str(e.value)
            assert ("有限数" in msg or "finite" in msg), f"消息没说清原因: {msg}"

    # 反例：有限值照常放行（别把规则做成"数值一律拒"）
    got = validate_overrides("chase_up", CHASE_PRESET, {"sl_pct": 0.05})
    assert got == {"sl_pct": 0.05}
    assert math.isfinite(got["sl_pct"])


def test_a_non_finite_rejection_names_the_reason_not_the_range():
    """被拒时的消息要指向**真正的原因**，不是"超出范围"。

    `nan` 落在任何 range 检查下都会失败，但报"outside range [0.0, 1.0]"会把人
    引到错误的修复方向（去调范围，而不是发现自己发了一个 NaN）。
    """
    with pytest.raises(OverrideError) as e:
        validate_overrides("chase_up", CHASE_PRESET, {"tp_pct": float("nan")})
    assert "有限数" in str(e.value) or "finite" in str(e.value)


def test_cycle_max_hold_is_declared_in_calendar_days_because_that_is_what_it_compares():
    """`cycle_price_action` 的 `max_hold` 单位是**自然日**，另三个是**交易日**。

    实测（2026-10-19）逐引擎读出来的：

      · `short_reversal`  `held = len(self) - pos["entry_bar"]`，与 `max_hold` 比较 → **bar 数**
      · `chase_up`        `code_data[...].head(max_hold + 5)` → **行数**
      · `cycle_price_action`  `hold_days()` = `(on_date - entry_date).days`
                              （cycle_price_action/portfolio.py:292）→ **自然日**

    三个引擎对同一个 UI 字段的期望单位不同，而元数据只有一份。
    原先四处都写"交易日" —— 用户按 5 个"交易日"填，在 cycle 上实际是 5 个**自然日**
    （约 3 个交易日），**会比预期早平仓**。改的是**声明**，不是引擎行为。
    """
    from web.params import PARAM_METADATA

    assert PARAM_METADATA["cycle_price_action"]["max_hold"]["unit"] == "自然日"
    for eng in ("short_reversal", "chase_up", "uptrend_pullback"):
        assert PARAM_METADATA[eng]["max_hold"]["unit"] == "交易日", \
            f"{eng} 的上限是按 bar 数比的，不该标成自然日"
    # `atr_period` 在四个引擎里都是 bar 数 —— 别被上面那条带偏
    assert PARAM_METADATA["cycle_price_action"]["atr_period"]["unit"] == "交易日"


def test_nested_dict_keys_are_checked_against_the_engine_itself():
    """嵌套 dict 的**键**要对 —— 但只对"引擎入口唯一"的那部分。

    引擎的 `select_entries` 是仅关键字、无 `**kwargs` 的签名（实测），未知键会在
    引擎里抛 `TypeError`；runner 只把 `ValueError` 具名化，`TypeError` 会一路漏到
    HTTP 层 → **变成 500**。可这是输入错误，应该是 400。

    允许键**从引擎的签名里读**，不手抄白名单（手抄的必然随引擎漂移）。

    ⚠️ **`uptrend_pullback` 故意不校验**：它按 `entry_mode` 分派到两个不同函数，
    `regime` 又去第三个（`compute_regime`）。要正确校验就得把引擎的分派逻辑复制一份
    ——那是 §6 违规，比不校验更糟。
    """
    CHASE_PRESET = "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16"
    from web.catalog import all_presets
    from web.params import split_params

    good = dict(split_params("chase_up", CHASE_PRESET)["tunable"]["signal"])

    validate_overrides("chase_up", CHASE_PRESET, {"signal": dict(good)})

    with pytest.raises(OverrideError, match="unknown key"):
        validate_overrides("chase_up", CHASE_PRESET,
                           {"signal": {**good, "并不存在的键": 1}})
    with pytest.raises(OverrideError, match="unknown key"):
        validate_overrides("chase_up", CHASE_PRESET, {"signal": {"bogus_only": 2}})


def test_no_existing_preset_is_rejected_by_the_nested_key_check():
    """**新校验绝不能误拒平台自己的预设。**

    这条是加嵌套键校验时全量扫出来的：若按 `uptrend_pullback.select_entries`
    的签名校验，v33_long_reverse_v19/v20/v21 的 `signal`（含 `pct_chg_high`、
    `pct_chg_low`、`min_above_ma60_ratio`）与 v21 的 `regime`（`breadth_window` 等）
    **会被全部误拒** —— 因为那个引擎按 `entry_mode` 分派到 `select_entries_v33_long_mirror`，
    签名完全不同。

    于是"校验"本身成了一处新的 §7 风险：用户**改不了一个没碰过的预设**。
    这条测试把"现有预设全部能过"钉成不变式。
    """
    from web.catalog import all_presets
    from web.params import validate_overrides

    checked = 0
    for eng, presets in all_presets().items():
        for name in sorted(presets):
            for nested in ("signal", "regime"):
                v = presets[name].get(nested)
                if not isinstance(v, dict) or not v:
                    continue
                checked += 1
                validate_overrides(eng, name, {nested: dict(v)})
    assert checked >= 20, f"只检查了 {checked} 个组合 —— 扫描范围可能没覆盖到"
