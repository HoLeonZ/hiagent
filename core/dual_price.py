"""Dual-Price System 共享逻辑 (CLAUDE.md §3, 2026-09-22).

Background
==========
CLAUDE.md §3 铁律:
  - 信号/指标 (MACD, MA, ATR, Volatility, ...) → MUST use adjusted_close
  - 限价单触发 / SL / 物理 cash mark-to-market (含 entry fill) → MUST use raw_close

历史回归 (V3a, 2026-09-22):
  chase_up + uptrend_pullback 此前静默回退到 adj_open 作 entry fill,
  触发 29/75 v3 phantom TP — 物理 raw_high 从未触达 TP 阈值却声称成交。

本次引入本模块 = 把 §3 行为集中到一处, 让 4 个 engine 共用同一份代码:

  +------------------+-----------+-----------+-----------+-----------+
  | engine           | entry     | SL/TP     | 信号/指标 | 数据布局  |
  +==================+===========+===========+===========+===========+
  | chase_up         | raw_open  | raw_*     | adj_*     | Layout A  |
  | uptrend_pullback | raw_open  | raw_*     | adj_*     | Layout A  |
  | short_reversal   | open (=r) | h/l (=r)  | adj_*     | Layout B  |
  | cycle_price_act  | close(=r) | h/l (=r)  | (raw 单价)| Layout C  |
  +------------------+-----------+-----------+-----------+-----------+

  Layout A: panel 同时有 raw_open/high/low/close/prev_close + adj_open/...
  Layout B: panel 有 open/high/low/close (=raw), LEFT JOIN hfq 提供 adj_*
  Layout C: panel 只有 open/high/low/close (=raw) — 单价格系统

API 表面
========
1. ExecutionBar          — 规范化执行 bar (raw entry/exit price domain)
2. extract_execution_bar — 从 panel row 提取 ExecutionBar (Layout-agnostic)
3. is_limit_up           — 涨停开盘检测 (entry-time no-buy filter)
4. atr_slippage          — ATR-aware execution slippage
5. price_source_contract — 类型常量 (Layout A/B/C), 编译期防混用

TDD: tests/test_dual_price.py 是本模块的契约锁。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# ---------------------------------------------------------------- constants

# 涨停阈值: open >= prev_close × (1 + LIMIT_UP_THRESHOLD) 视为无法买入。
# A 股主板 10% 涨停, 此处 9.5% 留 0.5% 容差应对尾盘瞬间异常。
LIMIT_UP_THRESHOLD: float = 0.095


# ---------------------------------------------------------- Layout contract

LAYOUT_CHASE_UPTREND = "layout_a_raw_adj"  # raw_* + adj_* 双列并存
LAYOUT_SHORT_REVERSAL = "layout_b_raw_only_hfq_join"  # open(=raw) + LEFT JOIN adj_*
LAYOUT_CYCLE_PRICE = "layout_c_raw_only"  # 仅 open/high/low/close (=raw)


# ----------------------------------------------------------- data structures

@dataclass(frozen=True)
class ExecutionBar:
    """执行域 (raw) 单根 bar — 所有 4 个 engine 共用。

    open / high / low / close: 物理成交价 (raw close 域, 含除权除息调整后)。
    prev_close: 上一交易日收盘 (raw, 用于 LIMIT_UP 检测)。
    ATR-aware slippage 通过 atr_slippage() 函数外加。
    """
    open: float
    high: float
    low: float
    close: float
    prev_close: float | None = None  # None = 缺失, LIMIT_UP 检测跳过

    def __post_init__(self) -> None:
        """Invariants: 高 >= 低, 低 <= 收 <= 高, 开 ∈ [低, 高]。"""
        if self.high < self.low:
            raise ValueError(
                f"ExecutionBar 高低倒挂: high={self.high} < low={self.low}"
            )


# ----------------------------------------------------------- extractors

def extract_execution_bar(
    row: Mapping[str, float],
    layout: str = LAYOUT_CHASE_UPTREND,
) -> ExecutionBar:
    """从单根 panel row 抽取 ExecutionBar, 按 layout 适配列名。

    Layout A (chase_up, uptrend_pullback): raw_open / raw_high / raw_low /
        raw_close / raw_prev_close 列。
    Layout B (short_reversal): open / high / low / close (=raw), LEFT JOIN
        提供 adj_* (不需要) — 取默认列即可。
    Layout C (cycle_price_action): 同 B 但没 LEFT JOIN — 完全 raw。

    Returns:
        ExecutionBar with NaN → 0.0 fallback (避免下游 numpy 报错)。

    Raises:
        KeyError: 缺核心列 (open / high / low / close / raw_open for A)。
    """
    if layout == LAYOUT_CHASE_UPTREND:
        # raw_* 列是 ground truth; 缺失时回退到 adj_* 列。
        o = row.get("raw_open", row.get("adj_open", row.get("open")))
        h = row.get("raw_high", row.get("adj_high", row.get("high")))
        lo = row.get("raw_low", row.get("adj_low", row.get("low")))
        c = row.get("raw_close", row.get("adj_close", row.get("close")))
        pc = row.get("raw_prev_close", row.get("prev_close"))
    elif layout in (LAYOUT_SHORT_REVERSAL, LAYOUT_CYCLE_PRICE):
        o = row["open"]; h = row["high"]; lo = row["low"]; c = row["close"]
        pc = row.get("prev_close")
    else:
        raise ValueError(f"未知 layout: {layout!r}")

    return ExecutionBar(
        open=_safe(o), high=_safe(h), low=_safe(lo), close=_safe(c),
        prev_close=_safe(pc) if pc is not None else None,
    )


def is_limit_up(
    prev_close: float | None,
    open_price: float,
    threshold: float = LIMIT_UP_THRESHOLD,
) -> bool:
    """判断是否涨停开盘 (open 已不可买入)。

    CLAUDE.md §3 LIMIT_UP noise filter: 涨停开盘视为无法买入。
    prev_close 缺失 (data gap) → 返回 False, 允许 entry (best-effort)。

    threshold 默认 0.095 (主板 10% 涨停的容差)。chase_up 设为 0.098 是历史
    preset override (略宽松, 容许盘中瞬间跳价); 通过参数传入而非硬编码。
    """
    if prev_close is None or prev_close <= 0:
        return False
    return (open_price / prev_close - 1.0) >= threshold


def atr_slippage(
    atr_pct: float,
    participation: float,
    scale: float = 1.0,
) -> float:
    """ATR-aware execution slippage (CLAUDE.md §4 铁律).

    公式: slippage = max(0, atr_pct × participation × scale)
    - atr_pct: 当根 bar 的 ATR / close (无量纲)
    - participation: 实际下单量 / Bar_Volume ∈ [0, 1]
    - scale: 策略级参数, 默认 1.0; V33 baseline parity 时 = 0 → 无 slippage。

    用于 chase_up (long): entry_price = raw_open × (1 + slip)
    用于 short_reversal (short): entry_price = raw_open × (1 + slip)
        (做空方向 slip 上调 sell price = 收到更少 sale proceeds = 悲观)
    """
    if atr_pct <= 0 or participation <= 0 or scale <= 0:
        return 0.0
    return atr_pct * participation * scale


# ----------------------------------------------------------- internals

def _safe(v: float | None) -> float:
    """None / NaN → 0.0, 避免下游 numpy 报错。"""
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0  # NaN check


# ----------------------------------------------------------- price-source contract

# 用于 strategy / portfolio 显式声明 price_source_for_execution。
# 集中常量而非散落字符串, 防止 typo bug。
PRICE_SOURCE_RAW = "raw_close"
PRICE_SOURCE_ADJ = "adj_close"


def validate_price_source(value: str) -> None:
    """校验 price_source_for_execution 取值合法。集中校验防 typo。"""
    if value not in (PRICE_SOURCE_RAW, PRICE_SOURCE_ADJ):
        raise ValueError(
            f"price_source_for_execution 必须是 {PRICE_SOURCE_RAW!r} 或 "
            f"{PRICE_SOURCE_ADJ!r}, 实得 {value!r}"
        )


__all__ = [
    "LIMIT_UP_THRESHOLD",
    "LAYOUT_CHASE_UPTREND",
    "LAYOUT_SHORT_REVERSAL",
    "LAYOUT_CYCLE_PRICE",
    "ExecutionBar",
    "extract_execution_bar",
    "is_limit_up",
    "atr_slippage",
    "PRICE_SOURCE_RAW",
    "PRICE_SOURCE_ADJ",
    "validate_price_source",
]
