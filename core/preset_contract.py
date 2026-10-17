"""§2/§3/§4 preset 声明契约 —— 声明必须**到达引擎**,不能只是装饰。

审计 (2026-10-15) 的元发现:100+ 个出厂 preset 里有一批键**声明了却没有任何
消费者**。`test_preset_to_engine_api_conformance.py` 逐个把它们点出来,本次修复
就是让每一个都真正生效。三类形态:

  1. **装饰性声明** —— `cycle_price_action` 的 `weight_kline/cycle/calendar`
     在 `signals.fuse_scores` 里被**同值硬编码为默认参数**(1.0/0.7/0.5)。
     预设与代码看起来一致,于是没人发现改预设其实什么都不会发生。
  2. **结构性替代** —— `short_reversal` 用 `"ensemble_substrategies" in cfg`
     决定走集成路径,而预设声明的 `position_sizing='ensemble_split'` 从未被读。
     声明与真正起作用的开关是**两个**东西,前者纯装饰。
  3. **无处可去的声明** —— `chase_up` 声明 `position_fraction` 但引擎只用
     `position_sizing`;`cycle_price_action` 声明 `max_positions`/
     `max_volume_participation`/`price_source_for_execution` 而从不读取。

本模块把「读声明」这件事收敛成**单源**(与 `core.dual_price.resolve_atr_slip_scale`
同约定、同 fail-fast 纪律):缺声明 → 抛错,值越界 → 抛错。引擎不得再用
`p.get(key, <看起来合理的默认值>)` —— 那正是让缺口靠沉默存在的写法。

⚠️ 与 §4 滑点一样,这些键的**出厂值全部是常量**,故接通它们不改变任何历史成交。
若将来有人改了预设值,行为应当随之改变 —— 那时它是真的生效了,而不是被忽略。
"""
from __future__ import annotations

from typing import Any, Mapping

#: §2 声明的取值域。`all_in` 是项目政策(chase_up/uptrend/cycle);`equal`/`kelly`
#: 仅 chase_up 实现;`ensemble_split` 仅 short_reversal 的集成路径实现。
ALL_IN = "all_in"

#: §2 政策:position_fraction 恒 1.0(全仓,不预留现金缓冲,尾部风险由 TP/SL 承担)。
ALL_IN_FRACTION = 1.0

#: §3 政策:执行域恒为原始价(raw_close)。指标域才用 adj_close。
EXECUTION_PRICE_SOURCE = "raw_close"


class PresetDeclarationMissing(ValueError):
    """preset 缺少一条引擎需要的声明 —— §0 Pessimistic Default(最坏情形=沉默)。"""


def _declared(preset: Mapping[str, Any], key: str, preset_name: str) -> Any:
    if key not in preset:
        raise PresetDeclarationMissing(
            f"§0/§6: preset {preset_name!r} 未声明 {key!r} —— 引擎需要它,"
            "而「没有声明」与「声明为合法值」必须可区分。"
        )
    return preset[key]


def resolve_position_fraction(preset: Mapping[str, Any], preset_name: str) -> float:
    """§2 仓位比例声明。取值域 (0, 1];越界即契约违规。"""
    raw = _declared(preset, "position_fraction", preset_name)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 的 position_fraction={raw!r} 不是数字"
        ) from exc
    if not (0.0 < value <= 1.0):
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 的 position_fraction={value} 越界 (0, 1]。"
            "预留给现金缓冲违反 §2 All-In 政策 —— 尾部风险由 TP/SL 承担,"
            "不是靠在开仓时扣一块钱。"
        )
    return value


def resolve_position_sizing(
    preset: Mapping[str, Any], preset_name: str, *, allowed: frozenset[str],
) -> str:
    """§2 sizing 模式声明。`allowed` 由引擎给出自己**真正实现**的模式集合。"""
    raw = _declared(preset, "position_sizing", preset_name)
    if raw not in allowed:
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 声明 position_sizing={raw!r},但该引擎只实现 "
            f"{sorted(allowed)}。声明一个引擎不实现的分支,等于承诺被静默丢弃。"
        )
    return str(raw)


def resolve_max_positions(
    preset: Mapping[str, Any], preset_name: str, *, capacity: int | None = None,
) -> int:
    """§2 持仓上限声明。

    `capacity` = 该引擎的**物理**上限(单仓引擎恒 1);

    **`capacity=None` = 该引擎没有物理上限**(支持任意 N,按 `free_cash / N` 分散,
    容量闸门逐 bar 约束)—— 此时仍强制"**必须声明**",但不做上界检查。

    2026-10-17:`capacity` 原为**必填**。但 chase_up / uptrend_pullback /
    short_reversal 的引擎都支持任意 N(只有 cycle 的单仓是物理恒 1)⇒
    给它们编一个"物理上限"是**假事实**,而"声明必须到达引擎"这一条(契约的本意)
    仍然应当强制。故加 `None` 这一档,而不是让它们继续用 `p.get(key, 默认值)`
    —— 那正是本模块 docstring 明令禁止的写法。
    """
    raw = _declared(preset, "max_positions", preset_name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 的 max_positions={raw!r} 不是整数"
        )
    if raw < 1:
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 声明 max_positions={raw} < 1"
        )
    if capacity is not None and raw > capacity:
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 声明 max_positions={raw},"
            f"但该引擎的物理容量是 {capacity}。声明超出容量 = 静默忽略。"
        )
    return raw


def resolve_volume_participation(
    preset: Mapping[str, Any], preset_name: str,
) -> float:
    """§4 成交量参与率上限声明。取值域 (0, 1] —— 占单根 bar 成交量的比例。"""
    raw = _declared(preset, "max_volume_participation", preset_name)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PresetDeclarationMissing(
            f"§4: preset {preset_name!r} 的 max_volume_participation={raw!r} 不是数字"
        ) from exc
    if not (0.0 < value <= 1.0):
        raise PresetDeclarationMissing(
            f"§4: preset {preset_name!r} 的 max_volume_participation={value} 越界 (0, 1]"
        )
    return value


def resolve_nav_gate_ratio(
    preset: Mapping[str, Any], preset_name: str,
) -> float:
    """§2 NAV 闸门比例声明(NAV 跌破 `初始资金 × ratio` 时拒绝新开仓)。

    此前 short_reversal 的 75 个 preset 一律不声明它,引擎却写
    `cfg.get("min_cash_ratio", 0.05)` —— 「没声明」与「声明为 0.05」不可区分,
    缺口靠沉默存在。与 §4 滑点同型。

    取值域 (0, 1):ratio ≥ 1 会让闸门在初始资金处就锁死(永远无法开仓);
    ratio ≤ 0 则闸门失效。两者都是静默的语义灾难,故在此 fail-fast。
    """
    raw = _declared(preset, "nav_gate_ratio", preset_name)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 的 nav_gate_ratio={raw!r} 不是数字"
        ) from exc
    if not (0.0 < value < 1.0):
        raise PresetDeclarationMissing(
            f"§2: preset {preset_name!r} 的 nav_gate_ratio={value} 越界 (0, 1) —— "
            "≥1 会在初始资金处锁死开仓,≤0 则闸门形同虚设。"
        )
    return value


def resolve_execution_price_source(
    preset: Mapping[str, Any], preset_name: str, *, supported: frozenset[str],
) -> str:
    """§3 执行价源声明。`supported` 由引擎给出自己**真正实现**的价源集合。"""
    raw = _declared(preset, "price_source_for_execution", preset_name)
    if raw not in supported:
        raise PresetDeclarationMissing(
            f"§3: preset {preset_name!r} 声明 price_source_for_execution={raw!r},"
            f"但该引擎只实现 {sorted(supported)}。声明一个不存在的执行域,"
            "等于让「原始价成交」这句承诺无人兑现。"
        )
    return str(raw)


__all__ = [
    "ALL_IN",
    "ALL_IN_FRACTION",
    "EXECUTION_PRICE_SOURCE",
    "PresetDeclarationMissing",
    "resolve_execution_price_source",
    "resolve_max_positions",
    "resolve_nav_gate_ratio",
    "resolve_position_fraction",
    "resolve_position_sizing",
    "resolve_volume_participation",
]
