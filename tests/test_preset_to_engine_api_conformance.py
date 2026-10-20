"""§0/§6 Preset-to-engine API conformance audit (meta-audit).

CLAUDE.md §0 Pessimistic Default: preset declarations must be ENFORCED.
If preset declares `intraday_tiebreak='sl_first'` and engine never reads
that key, the preset's promise is silently dropped — a Pessimistic Default
violation (worst-case = silent).

This test audits: for every leaf key in every preset dict, does the engine
module reference that key (or an equivalent alias) somewhere in its code?

Method:
  1. Load all preset dicts per engine
  2. For each leaf key (excluding nested config like `signal: {...}`):
     - search the engine module source for the key as a string literal
     - if NOT found → engine silently drops this preset claim → GAP
  3. PASS baseline: every declared key is referenced in engine code

Engine-to-source mapping:
  - chase_up → chase_up/portfolio.py + chase_up/backtrader_engine.py
  - uptrend_pullback → uptrend_pullback/portfolio.py + uptrend_pullback/backtrader_engine.py
  - short_reversal → short_reversal/engine.py + short_reversal/replay_strategy_v3.py
  - cycle_price_action → cycle_price_action/portfolio.py + cycle_price_action/backtest.py

FRESH 2026-09-23 audit tick: this catches the meta-pattern that allowed
cycle_price_action's `intraday_tiebreak` to be silently dropped (Tick 30/31).
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


# Engine source files to search per engine
ENGINE_SOURCES = {
    "chase_up": [
        "chase_up/portfolio.py",
        "chase_up/backtrader_engine.py",
        "chase_up/main.py",
    ],
    "uptrend_pullback": [
        "uptrend_pullback/portfolio.py",
        "uptrend_pullback/backtrader_engine.py",
        "uptrend_pullback/main.py",
    ],
    "short_reversal": [
        "short_reversal/engine.py",
        "short_reversal/replay_strategy_v3.py",
        "short_reversal/portfolio.py",
    ],
    "cycle_price_action": [
        "cycle_price_action/portfolio.py",
        "cycle_price_action/backtest.py",
        "cycle_price_action/backtrader_engine.py",
    ],
}


# Nested config blocks that we don't audit as leaves (they're structured
# config dicts passed as a single kwarg).
# `regime` 与 `signal` 同构: 都是在调用点被 `**p["regime"]` / `**p["signal"]` 展开,
# 其子键由被调方(compute_regime / select_entries_*)消费, 而不是作为字面量出现在
# 引擎源码里 —— 要求它们成为字面量是误报 (见 v33_long_reverse_v21 的 regime)。
#
# §0 (附八十八): 这份名单**不再手写**,改为**推导** —— "在至少一个 preset 里是 dict 的
# 顶层键"。手写的那版有 5 项,其中 **3 项是错的**:
#   · `universe` —— 在 101 个 preset 里都是**字符串**(不是嵌套字典),却被当成嵌套豁免
#     ⇒ 它在**任何**引擎里都**从未被审计过**;
#   · `periods` —— 是**元组**,同上;
#   · `weights` —— **任何 preset 里都不存在**,是死项。
# 后果是这条守卫**在它本该覆盖的那一类上瞎了**:`cycle_price_action` 的 `universe`
# 与 `periods` 声明了却从未被读取,而豁免名单正好把它们挡在审计之外。
# (手写名单 ≠ 实际集合 —— 本会话第四次同一个形态。)
NESTED_KEYS = {"signal", "regime"}   #: 见 test_nested_keys_are_actually_nested


def _derived_nested_keys() -> set[str]:
    """在 ≥1 个 preset 里取值是 dict 的**顶层**键 —— 即"嵌套配置块"的实际集合。"""
    out: set[str] = set()
    for engine_name, mod_path, attr in _REGISTRY_SPECS:
        mod = importlib.import_module(mod_path)
        reg = getattr(mod, attr)
        presets = _as_preset_mapping(reg, attr)
        for cfg in presets.values():
            for k, v in cfg.items():
                if isinstance(v, dict):
                    out.add(k)
    return out


def _as_preset_mapping(reg: Any, attr: str) -> dict[str, Any]:
    """`PRESETS` 是 name→cfg 的注册表;`PRESET_V1` 是**单个** cfg ⇒ 包一层。"""
    if isinstance(reg, dict) and any(isinstance(v, dict) for v in reg.values()):
        return dict(reg)
    return {attr: reg}


#: (引擎名, presets 模块, 属性名) —— 三处共用,免得多份名单再各自漂移。
_REGISTRY_SPECS = (
    ("chase_up", "chase_up.presets", "PRESETS"),
    ("uptrend_pullback", "uptrend_pullback.presets", "PRESETS"),
    ("short_reversal", "short_reversal.presets", "PRESETS"),
    ("cycle_price_action", "cycle_price_action.presets", "PRESET_V1"),
)


# 声明型键 (declaration-only)。这几个键由 §2/§3/§5 政策钉死为固定值, 运行时引擎
# 没有可分支的语义 —— 它们的消费方是 sweep / DSR 记账, 不是回测引擎:
#   MAX_POSITION_PCT        §2 All-In 政策常量, 恒 1.0; 真正的运行时输入是
#                           position_sizing + position_fraction (两者都已消费)。
#   price_source_for_signal §3 强制 signals 用 adj_close, 无可选值。
#   n_comparisons           §5 DSR/Bonferroni 多个比较数, 属 sweep 层元数据。
# 把它们也要求成引擎源码里的字面量, 只会诱导写出迎合 grep 的假"消费"代码。
# 刻意保持极窄: 任何「引擎本该读却读不到」的键必须继续 RED —— 例如
# cycle_price_action 的 weight_calendar/weight_cycle/weight_kline、
# short_reversal 的 ensemble_weight/position_sizing/price_source_for_execution。
DECLARATION_ONLY_KEYS = frozenset({
    "MAX_POSITION_PCT",
    "price_source_for_signal",
    "n_comparisons",
})


#: **登记在案的债**(不是豁免):这些键**本该被引擎读取**却读不到。
#: 与 `DECLARATION_ONLY_KEYS` **刻意分开** —— 那一桶是"按设计没有运行时语义"
#: (如 §2 政策常量),这一桶是"有语义、但接线没做"。合并会让人读不出哪些是缺口。
#: 每一项写清「现在是什么样」+「接上需要做什么」;**接上之后必须删掉本项**
#: (`test_unconsumed_declared_keys_registry_is_not_stale` 会红)。
UNCONSUMED_DECLARED_KEYS: dict[tuple[str, str], str] = {
    ("cycle_price_action", "periods"): (
        "PRESET_V1['periods'] 与 cycle.py::DEFAULT_PERIODS **逐位相同**(都是 (3,5,8,13,21)),"
        "而引擎只读后者 ⇒ 改 preset 不会有任何效果。"
        "接上要把 periods 穿进 signals.phase_score —— 那会改变信号计算,属研究改动,故登记未做。"
    ),
    ("cycle_price_action", "universe"): (
        "PRESET_V1['universe']='mainboard_only' 与 load_universe_data 里**写死的** "
        "is_main_board 过滤一致,但引擎从不读这个键 ⇒ 改成别的值不会有任何效果、也不报错。"
        "接上要给 load_universe_data 加 universe 参数并处理不支持的取值 —— 属加功能,故登记未做。"
    ),
}


def _collect_leaf_keys(preset: dict[str, Any]) -> set[str]:
    """Return the set of leaf keys (excluding nested config blocks)."""
    leaves: set[str] = set()
    for k, v in preset.items():
        if k in NESTED_KEYS:
            continue
        if isinstance(v, dict):
            # Also flatten nested signal dict keys
            leaves.update(v.keys())
        else:
            leaves.add(k)
    return leaves


def _load_engine_source(engine: str) -> str:
    """Concatenate all engine source files for one engine into a single string."""
    chunks: list[str] = []
    for path in ENGINE_SOURCES[engine]:
        try:
            chunks.append(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
    return "\n".join(chunks)


def _audit_preset_to_engine(
    engine_name: str,
    presets_module_path: str,
    presets_attr: str,
) -> list[tuple[str, str, str]]:
    """For all presets in an engine, find leaf keys NOT referenced in engine source.

    Returns: list of (engine_name, preset_name, dropped_key) tuples.
    """
    mod = importlib.import_module(presets_module_path)
    if presets_attr == "PRESETS":
        presets_dict = mod.PRESETS
    else:
        # cycle uses PRESET_V1 (singleton)
        preset_singleton = getattr(mod, presets_attr)
        presets_dict = {presets_attr: preset_singleton} if isinstance(preset_singleton, dict) else {}
    return _audit_presets_dict(engine_name, presets_dict)


def _audit_presets_dict(
    engine_name: str,
    presets_dict: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """同一审计,但直接接收 preset dict —— 让灵敏度用例能扫描**人造** preset。"""
    engine_src = _load_engine_source(engine_name)
    dropped: list[tuple[str, str, str]] = []

    for preset_name, preset_cfg in presets_dict.items():
        if not isinstance(preset_cfg, dict):
            continue
        leaf_keys = _collect_leaf_keys(preset_cfg)
        for key in sorted(leaf_keys):
            if key in DECLARATION_ONLY_KEYS:
                continue
            # Search for the key as a string literal in engine source.
            # Two patterns:
            #   1. dict access: preset['key'] or preset["key"]
            #   2. kwargs: key= (kwarg in function signature)
            #   3. attribute: .key
            patterns = [
                f"preset['{key}']",
                f'preset["{key}"]',
                f'["{key}"]',
                f"['{key}']",
                f".{key}",
                f"{key}=",
                f"cfg['{key}']",
                f'cfg["{key}"]',
                f'p["{key}"]',
                f"p['{key}']",
                f"self.{key}",
                # 2026-10-15: `.get("key")` 此前是**盲区** —— 于是短反转的
                # `cfg.get("ensemble_weight", 1.0/n)` 被误报为"从未被读"。
                # 误报比漏报更毒:它会诱导人去"修"一个根本没坏的地方。
                f'.get("{key}"',
                f".get('{key}'",
                # dict 字面量/转发:{"key": ...} 也是真实引用。
                f'"{key}":',
                f"'{key}':",
            ]
            if not any(p in engine_src for p in patterns):
                dropped.append((engine_name, preset_name, key))
    return dropped


def test_chase_up_presets_all_reach_engine() -> None:
    """§0/§6: every chase_up preset leaf key must be referenced in engine code."""
    dropped = _audit_preset_to_engine(
        "chase_up",
        "chase_up.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: chase_up has preset keys declared but NEVER "
        "referenced in engine source. Engine silently drops these "
        "preset claims (Pessimistic Default violation):\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total dropped keys)"
    )


def test_uptrend_pullback_presets_all_reach_engine() -> None:
    """§0/§6: every uptrend_pullback preset leaf key must reach engine."""
    dropped = _audit_preset_to_engine(
        "uptrend_pullback",
        "uptrend_pullback.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: uptrend_pullback has preset keys declared but "
        "NEVER referenced in engine source:\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total)"
    )


def test_short_reversal_presets_all_reach_engine() -> None:
    """§0/§6: every short_reversal preset leaf key must reach engine."""
    dropped = _audit_preset_to_engine(
        "short_reversal",
        "short_reversal.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: short_reversal has preset keys declared but "
        "NEVER referenced in engine source:\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total)"
    )


def test_cycle_price_action_presets_all_reach_engine() -> None:
    """§0/§6: every cycle_price_action preset leaf key must reach engine.

    Known gap (Tick 30/31): `intraday_tiebreak` declared in PRESET_V1
    but never referenced in cycle/portfolio.py or backtest.py.
    """
    dropped = _audit_preset_to_engine(
        "cycle_price_action",
        "cycle_price_action.presets",
        "PRESET_V1",
    )
    unexpected = [t for t in dropped if (t[0], t[2]) not in UNCONSUMED_DECLARED_KEYS]
    assert not unexpected, (
        "GAP CAPTURED: cycle_price_action has preset keys declared but "
        "NEVER referenced in engine source, **且未登记**:\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in unexpected)
        + "\n接上它,或登记到 UNCONSUMED_DECLARED_KEYS 并写清「接上要做什么」。"
    )
    # 登记过的仍然是**债**,不是"已解决" —— 在用例名与这份 registry 上都写明。
    # 若哪天接线做完了,`test_unconsumed_declared_keys_registry_is_not_stale` 会要求删条目。


def test_audit_detects_a_planted_dropped_key() -> None:
    """§6 灵敏度: 审计方法必须能抓到**确实没有任何消费者**的键。

    原用例钉的是 Tick 30/31 的 `intraday_tiebreak` 缺口。该缺口已闭合(见下一条),
    若继续钉一个已修复的历史缺口,本用例会永久 RED 且不再表达任何东西 —— 它会从
    「方法坏了」退化成「噪音」。改为钉**方法本身**:人造一个必然无人消费的键。

    (同形: silent-except 扫描器把「历史站点在名单里」换成「能抓到栽进去的桩」。)
    """
    planted = {
        "_planted_key_that_no_engine_reads_xyzzy": 1,
        "position_fraction": 1.0,   # 真实键: 应当**不**被报(证明不误报)
    }
    dropped = _audit_presets_dict("cycle_price_action", {"planted": planted})
    dropped_keys = {k for _, _, k in dropped}
    assert dropped_keys == {"_planted_key_that_no_engine_reads_xyzzy"}, (
        "AUDIT METHOD BROKEN: 审计既未抓到栽进去的键,或把真实消费的键误报了。"
        f"实际 dropped={sorted(dropped_keys)}"
    )


def test_scanner_sees_dict_get_reads() -> None:
    """§6 灵敏度: `.get("key")` 是**读取**,不是丢弃。

    2026-10-15 前扫描器只认 `["key"]` / `key=` / `.key`,于是
    `cfg.get("ensemble_weight", 1.0/n)` 被误报为"从未被读"。误报比漏报更毒:
    它会诱导人去"修"一个根本没坏的地方(short_reversal 的 3 个集成 preset 就
    因此被误判)。
    """
    dropped = _audit_presets_dict(
        "short_reversal", {"planted": {"ensemble_weight": 0.5}}
    )
    assert not dropped, (
        "`cfg.get(\"ensemble_weight\", ...)` 是真实消费,不应被报为 dropped —— "
        f"实际 {dropped}"
    )


def test_historical_intraday_tiebreak_gap_is_closed() -> None:
    """Tick 30/31 的 `intraday_tiebreak` 静默丢弃缺口**已闭合**。

    该键现由 Control Plane 经 `core.dual_price`/preset→strategy 管线注入
    (backtest.py 白名单 + CyclePriceActionStrategy.params + Portfolio.__init__)。
    记下来,是因为"缺口关闭"与"缺口从未存在"是两件不同的事 —— 后者不需要修。
    """
    dropped = _audit_preset_to_engine(
        "cycle_price_action",
        "cycle_price_action.presets",
        "PRESET_V1",
    )
    dropped_keys = {k for _, _, k in dropped}
    assert "intraday_tiebreak" not in dropped_keys, (
        "Tick 30/31 的 intraday_tiebreak 缺口重新出现了 —— 声明又一次无人消费。"
    )

# ---------------------------------------------------------------------------
# §0 (附八十八): 名单是**推导**出来的,不是手抄的
# ---------------------------------------------------------------------------
def _unexpectedly_not_nested(nested: set[str]) -> list[str]:
    """`nested` 里**不是**"在 ≥1 个 preset 里取值为 dict 的顶层键"的那些。"""
    return sorted(nested - _derived_nested_keys())


def test_nested_keys_are_actually_nested() -> None:
    """豁免名单的每一项都必须**真的是**嵌套配置块。

    手写的那版有 5 项,其中 3 项是错的(`universe` 是字符串、`periods` 是元组、
    `weights` 根本不存在)⇒ 这三个键在**任何**引擎里都从未被审计过,而
    `cycle_price_action` 的 `universe`/`periods` 声明了却读不到,正好被它们挡住。
    **手写名单 ≠ 实际集合** —— 本会话第四次同一个形态。
    """
    bad = _unexpectedly_not_nested(NESTED_KEYS)
    assert not bad, (
        "§0: NESTED_KEYS 里这几项**不是**嵌套配置块(在没有任何 preset 里取值为 dict)"
        f"⇒ 它们被永久豁免审计:{bad}。"
        "若是有意豁免,请登记到 DECLARATION_ONLY_KEYS / UNCONSUMED_DECLARED_KEYS 并写明原因。"
    )


def test_the_nested_rule_has_teeth() -> None:
    """**牙齿**:把 `universe`/`periods` 塞回去必须被认出来,`signal`/`regime` 不得误报。"""
    assert _unexpectedly_not_nested({"signal", "regime"}) == []
    assert _unexpectedly_not_nested({"signal", "universe", "periods", "weights"}) == [
        "periods", "universe", "weights",
    ]


def test_unconsumed_declared_keys_registry_is_not_stale() -> None:
    """登记表必须**跟着现实走**:接线做完了却不同步删条目 → 失败。

    (与 `test_research_scripts_reference_live_presets.py` 的
     `test_registered_debt_is_still_debt` 同型:登记表只应当变短。)
    """
    actual = {
        (engine, key)
        for engine, _p, key in _audit_preset_to_engine(
            "cycle_price_action", "cycle_price_action.presets", "PRESET_V1"
        )
    }
    stale = sorted(k for k in UNCONSUMED_DECLARED_KEYS if k not in actual)
    assert not stale, (
        "以下登记项**已不再是缺口**(键已被引擎读取,或键已被删除)—— "
        f"请从 UNCONSUMED_DECLARED_KEYS 删除:{stale}"
    )
