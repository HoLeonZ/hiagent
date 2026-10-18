"""可调参数与声明字段的拆分，以及 overrides 校验。

单一职责：参数层的规则。不接触回测、DB、HTTP。
"""
from __future__ import annotations

from typing import Any

from web.catalog import DECLARATION_KEYS, all_presets


class OverrideError(ValueError):
    """非法的参数覆盖。消息里必须含 declaration / unknown / type 之一。"""


#: 每个引擎的可调参数元数据。**手写，因此会和预设一起腐烂**——
#: 由 tests/test_web_params.py 的双向测试钉住（缺元数据 / 幽灵键都会变红）。
#:
#: 覆盖范围 = 各引擎 `all_presets()` 里**实际出现**的可调键的并集
#: （short_reversal 38 / chase_up 7 / uptrend_pullback 5 / cycle_price_action 11）。
#: 隔壁 preset 的键集并不一致（例如 v63_ensemble 没有 sl_pct/tp_pct，改为
#: ensemble_substrategies/ensemble_weight），因此这里登记的是并集，不是任一预设。
#: 类型/单位取自各引擎策略源码的参数声明与调用点（short_reversal:
#: replay_strategy_v3.py:160-320 + conditions.py:69-97；chase_up: presets.py:6-7；
#: cycle: presets.py），不臆造范围：除少数有明确物理上下界的键外不写 range，
#: 由 validate_overrides 的 range 检查在缺省时跳过。
PARAM_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "short_reversal": {
        "tp_pct": {"label": "止盈", "type": "float", "unit": "比例", "range": [0.0, 1.0],
                   "help": "相对入场价的止盈幅度（§4 相对百分比）"},
        "sl_pct": {"label": "止损", "type": "float", "unit": "比例", "range": [0.0, 1.0],
                   "help": "相对入场价的止损幅度（§4 相对百分比）"},
        "max_hold": {"label": "最长持有", "type": "int", "unit": "交易日",
                     "range": [1, 60], "help": "超时退出"},
        "pct_chg_low": {"label": "涨幅下界", "type": "float", "unit": "比例"},
        "pct_chg_high": {"label": "涨幅上界", "type": "float", "unit": "比例"},
        "below_ratio_60": {"label": "低于MA60占比", "type": "float", "unit": "比例"},
        "close_ma60_buffer": {"label": "MA60缓冲", "type": "float", "unit": "比例"},
        "d_mode": {"label": "D 模式", "type": "str",
                   # choices 必须覆盖引擎的三条实际分支（conditions.py:240-249）：
                   #   'converge_strict' → dif<0 & dea<0 & |bar| < |prev_bar|*0.5
                   #   'd_only'          → 仅 dif<0
                   #   其它（含默认 'strict'，即 v50_slope 所用的值）→
                   #                      dif<0 & dea<0 & |bar| < |prev_bar|
                   # 旧 choices 列了引擎并不区分的 'converge'/'any'，却漏掉了
                   # 引擎默认与预设实值 'strict' —— 会让严格 choices 校验误拒合法值。
                   "choices": ["strict", "converge_strict", "d_only"]},
        # --- A/B/E 条件（conditions.py:205-229）---
        "a_condition": {"label": "A 条件模式", "type": "str",
                        "choices": ["default", "cascade_price"]},
        "up_streak_low": {"label": "连阳天数下界", "type": "int", "unit": "交易日"},
        "up_streak_high": {"label": "连阳天数上界", "type": "int", "unit": "交易日"},
        "liq_low": {"label": "流动性下界", "type": "float", "unit": "元",
                    "help": "60 日均成交额下界"},
        "liq_high": {"label": "流动性上界", "type": "float", "unit": "元",
                     "help": "60 日均成交额上界"},
        # --- F 条件：MA20 斜率（replay_strategy_v3.py:214-221）---
        "require_ma20_slope_neg": {"label": "启用MA20负斜率过滤", "type": "bool"},
        "ma20_slope_period": {"label": "MA20斜率回看窗口", "type": "int", "unit": "交易日"},
        "ma20_slope_threshold": {"label": "MA20斜率阈值", "type": "float", "unit": "比例/日"},
        # --- G 条件：弱势股过滤（replay_strategy_v3.py:222-232）---
        "require_weak_1m": {"label": "启用1月弱势过滤", "type": "bool"},
        "require_weak_3m": {"label": "启用3月弱势过滤", "type": "bool"},
        "require_weak_6m": {"label": "启用6月弱势过滤", "type": "bool"},
        "weak_1m_threshold": {"label": "1月累计回报阈值", "type": "float", "unit": "比例"},
        "weak_3m_threshold": {"label": "3月累计回报阈值", "type": "float", "unit": "比例"},
        "weak_6m_threshold": {"label": "6月累计回报阈值", "type": "float", "unit": "比例"},
        # --- H 条件：成交额萎缩（replay_strategy_v3.py:233-242）---
        "require_amount_dryup": {"label": "启用成交额萎缩过滤", "type": "bool"},
        "amount_dryup_threshold": {"label": "成交额萎缩阈值", "type": "float", "unit": "比例",
                                   "help": "5日/20日均成交额比率上界"},
        # --- I 条件：RSI 超卖（replay_strategy_v3.py:243-251）---
        "require_rsi_oversold": {"label": "启用RSI超卖过滤", "type": "bool"},
        "rsi_oversold_threshold": {"label": "RSI超卖阈值", "type": "float", "unit": "RSI值",
                                   "help": "RSI(14) 低于此值算超卖；引擎按数值比较，允许小数"},
        # --- J 条件：止损冷却（replay_strategy_v3.py:252-258）---
        "sl_cooldown_days": {"label": "止损后冷却期", "type": "int", "unit": "交易日"},
        # --- K 条件：日内反转（replay_strategy_v3.py:259-269）---
        "require_intraday_reversal": {"label": "启用日内反转过滤", "type": "bool"},
        "intraday_reversal_threshold": {"label": "日内反转阈值", "type": "float", "unit": "比例",
                                        "help": "close 在当日区间中的相对位置下界"},
        "intraday_reversal_require_close_above_open": {"label": "日内反转要求收阳", "type": "bool"},
        # --- 浮动止损（replay_strategy_v3.py:277-286）---
        "trailing_stop_pct": {"label": "移动止损幅度", "type": "float", "unit": "比例"},
        "trailing_activation_pct": {"label": "移动止损激活阈值", "type": "float", "unit": "比例"},
        # --- 市场宽度 regime（replay_strategy_v3.py:287-296）---
        "require_market_breadth_bear": {"label": "启用市场宽度熊市过滤", "type": "bool"},
        "market_breadth_max": {"label": "市场宽度上界", "type": "float", "unit": "比例",
                               "help": "universe 中 close>MA20 的比例上界，超过则不入场"},
        # --- 并发填充选择（replay_strategy_v3.py:297-301）---
        "entry_selection": {"label": "入场选择", "type": "str",
                            "choices": ["first", "steepest_slope"]},
        # --- 信号价格域（replay_strategy_v3.py:302-311）---
        "signal_price_domain": {"label": "信号价格域", "type": "str",
                                "choices": ["adj", "raw"]},
        # --- ensemble（engine.py:274-294）---
        "ensemble_substrategies": {"label": "集成子策略", "type": "list"},
        "ensemble_weight": {"label": "集成权重", "type": "float", "unit": "比例"},
    },
    "chase_up": {
        "tp_pct": {"label": "止盈", "type": "float", "unit": "比例"},
        "sl_pct": {"label": "止损", "type": "float", "unit": "比例"},
        "max_hold": {"label": "最长持有", "type": "int", "unit": "交易日"},
        "atr_tp_mult": {"label": "ATR止盈倍数", "type": "float",
                        "help": "止盈宽度 = ATR% × 本系数（presets.py:6-7）"},
        "atr_sl_mult": {"label": "ATR止损倍数", "type": "float",
                        "help": "止损宽度 = ATR% × 本系数（presets.py:6-7）"},
        "nav_gate_ratio": {"label": "现金闸门比率", "type": "float", "unit": "比例"},
        "signal": {"label": "入场信号参数", "type": "dict",
                   "help": "select_entries 的关键字参数（嵌套 dict）"},
    },
    "uptrend_pullback": {
        "tp_pct": {"label": "止盈", "type": "float", "unit": "比例"},
        "sl_pct": {"label": "止损", "type": "float", "unit": "比例"},
        "max_hold": {"label": "最长持有", "type": "int", "unit": "交易日"},
        "signal": {"label": "入场信号参数", "type": "dict",
                   "help": "select_entries 的关键字参数（嵌套 dict）"},
        "regime": {"label": "大盘择时参数", "type": "dict",
                   "help": "None 表示不做择时（嵌套 dict）"},
    },
    "cycle_price_action": {
        "tp_pct": {"label": "止盈", "type": "float", "unit": "比例"},
        "sl_pct": {"label": "止损", "type": "float", "unit": "比例"},
        "max_hold": {"label": "最长持有", "type": "int", "unit": "交易日"},
        "atr_period": {"label": "ATR周期", "type": "int", "unit": "交易日"},
        "atr_sl_mult": {"label": "ATR止损倍数", "type": "float"},
        "threshold": {"label": "周期评分阈值", "type": "float"},
        "min_dim": {"label": "最小维度分", "type": "float"},
        "weight_kline": {"label": "K线维度权重", "type": "float", "unit": "比例"},
        "weight_cycle": {"label": "周期维度权重", "type": "float", "unit": "比例"},
        "weight_calendar": {"label": "日历维度权重", "type": "float", "unit": "比例"},
        "periods": {"label": "周期列表", "type": "list",
                    "help": "元组，前端以列表消费（JSON 序列化时 tuple→list）"},
    },
}


def split_params(engine: str, preset: str) -> dict[str, Any]:
    """把一个预设拆成 `{tunable, declarations, metadata}`。

    **返回值是调用方私有**：底层来自 `all_presets()` 的深拷贝，`tunable` /
    `declarations` 里的嵌套 dict/list/tuple 与引擎模块的全局 `PRESETS`
    不共享引用，可安全原地修改。
    """
    presets = all_presets()
    if engine not in presets:
        raise KeyError(f"unknown engine: {engine}")
    if preset not in presets[engine]:
        raise KeyError(f"unknown preset: {preset}")

    params = presets[engine][preset]
    declarations = {k: v for k, v in params.items() if k in DECLARATION_KEYS}
    tunable = {k: v for k, v in params.items() if k not in DECLARATION_KEYS}
    meta = PARAM_METADATA.get(engine, {})
    # 只为**实际存在**的可调键提供元数据；元数据里的幽灵键由测试抓
    return {
        "tunable": tunable,
        "declarations": declarations,
        "metadata": {k: meta[k] for k in tunable if k in meta},
    }


def validate_overrides(engine: str, preset: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """校验并清洗 overrides。

    三类拒绝：
      - declaration：声明字段受 §2/§3/§4/§5 约束，不可在 UI 修改
      - unknown：未知键（静默忽略会让用户以为改了但没改）
      - type：类型/取值范围/枚举与元数据不符（含 bool 冒充数值、可调键缺元数据）

    先调 `split_params` 校验引擎与预设合法性，**再**处理空 overrides 的短路——
    否则 `validate_overrides('bogus', 'bogus', {})` 会对一个不存在的引擎静默成功。
    """
    # 先校验 engine/preset 合法（未知引擎/预设在此抛 KeyError）。
    out = split_params(engine, preset)
    if not overrides:
        return {}

    tunable, declarations, meta = out["tunable"], out["declarations"], out["metadata"]

    bad_decl = sorted(set(overrides) & set(declarations))
    if bad_decl:
        raise OverrideError(
            f"declaration field(s) are read-only: {bad_decl} — "
            "these are CLAUDE.md §2/§3/§4/§5 contract declarations and editing them "
            "produces a preset that fails the compliance audit"
        )

    unknown = sorted(set(overrides) - set(tunable))
    if unknown:
        raise OverrideError(f"unknown parameter(s): {unknown}")

    for key, value in overrides.items():
        spec = meta.get(key)
        if not spec:
            # 可调键却没有元数据 = 元数据缺口（既漏 UI 又把校验洞打开）。
            # fail-fast，绝不 `continue` 静默放行。
            raise OverrideError(
                f"type error: no metadata for tunable key {key!r} — "
                "PARAM_METADATA is missing this key (metadata gap); refusing to "
                "skip validation"
            )
        want = spec.get("type")
        if want == "bool":
            if not isinstance(value, bool):
                raise OverrideError(
                    f"type error: {key} expects bool, got {type(value).__name__}"
                )
        elif isinstance(value, bool):
            # bool 是 int 的子类：True/False 绝不能冒充数值参数
            # （isinstance(True, (int, float)) 为真）。先判 bool 再判数值。
            raise OverrideError(
                f"type error: {key} received a bool; expected {want}"
            )
        elif want == "float" and not isinstance(value, (int, float)):
            raise OverrideError(f"type error: {key} expects float, got {type(value).__name__}")
        elif want == "int" and not isinstance(value, int):
            raise OverrideError(f"type error: {key} expects int, got {type(value).__name__}")
        elif want == "str" and not isinstance(value, str):
            raise OverrideError(f"type error: {key} expects str, got {type(value).__name__}")
        elif want == "list" and not isinstance(value, (list, tuple)):
            # 引擎里 periods 存的是 tuple（cycle PRESET_V1），而 JSON 只能表示
            # list —— 值从前端回来必然是 list。两者都是这个参数域的合法形态：
            # 只接 list 会拒掉引擎自己的 tuple（校验器拒真值），只接 tuple 又
            # 会拒掉前端回声。两边都接。
            raise OverrideError(
                f"type error: {key} expects list, got {type(value).__name__}"
            )
        elif want == "dict" and not isinstance(value, dict):
            raise OverrideError(f"type error: {key} expects dict, got {type(value).__name__}")

        lo_hi = spec.get("range")
        if lo_hi and isinstance(value, (int, float)) and not isinstance(value, bool):
            lo, hi = lo_hi
            if not (lo <= float(value) <= hi):
                raise OverrideError(f"type error: {key}={value} outside range [{lo}, {hi}]")

        choices = spec.get("choices")
        if choices is not None and value not in choices:
            raise OverrideError(
                f"type error: {key}={value!r} not one of {sorted(choices)}"
            )

    return dict(overrides)
