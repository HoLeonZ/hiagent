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
        "d_mode": {"label": "D 模式", "type": "str", "choices": ["converge_strict", "converge", "any"]},
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
        "rsi_oversold_threshold": {"label": "RSI超卖阈值", "type": "int", "unit": "RSI值"},
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
        "cash": {"label": "初始资金", "type": "float", "unit": "元"},
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
    """把一个预设拆成 `{tunable, declarations, metadata}`。"""
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
      - type：类型与元数据不符
    """
    if not overrides:
        return {}

    out = split_params(engine, preset)
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
            continue
        want = spec.get("type")
        if want == "float" and not isinstance(value, (int, float)):
            raise OverrideError(f"type error: {key} expects float, got {type(value).__name__}")
        if want == "int" and not isinstance(value, int):
            raise OverrideError(f"type error: {key} expects int, got {type(value).__name__}")
        if want == "str" and not isinstance(value, str):
            raise OverrideError(f"type error: {key} expects str, got {type(value).__name__}")
        lo_hi = spec.get("range")
        if lo_hi and isinstance(value, (int, float)):
            lo, hi = lo_hi
            if not (lo <= float(value) <= hi):
                raise OverrideError(f"type error: {key}={value} outside range [{lo}, {hi}]")

    return dict(overrides)
