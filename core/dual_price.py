"""Dual-Price System 共享逻辑 (CLAUDE.md §3, 2026-09-22).

数据加载请走 ``dna_data.dual_price_loader.load_dual_price_panel()``
(独立 I/O 模块,避免本文件引入 duckdb/pandas 依赖)。本模块是领域层,
纯函数 + 零外部依赖。

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
        """Invariants: 高 >= 低, 低 <= 收 <= 高, 开 ∈ [低, 高]。

        close <= 0 且 open > 0: 物理不合法 (有成交的 bar 必有非零 close)。
        实证 blast path (2026-09-28 net_pnl=-99,029.75):
        partial-NaN (raw_open/high/low real, raw_close=NaN) → _safe=0.0
        → 上层 chase_up/uptrend_pullback gate (bar.open>0 AND bar.high>=bar.low)
        通过 → c=0 → phantom max_hold exit at price 0。
        close=0 + open=0 (all-NaN data gap) 不视为 phantom, 见 _safe fallback。
        """
        if self.high < self.low:
            raise ValueError(
                f"ExecutionBar 高低倒挂: high={self.high} < low={self.low}"
            )
        if self.close <= 0 and self.open > 0:
            raise ValueError(
                f"ExecutionBar close 无效 (phantom guard): "
                f"close={self.close}, open={self.open} "
                f"(partial-NaN: open/high/low 有效但 close 缺失 → _safe=0.0)"
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

    Round 30 (2026-09-28, CLAUDE.md §3): NaN-aware fallback chain.
    Previous `dict.get(key, default)` only fell through when key was MISSING.
    When key EXISTS with value None or NaN (LEFT JOIN miss leaves key
    present with NULL), the None/NaN was returned → silent 0.0 bar (when
    all raw_* NULL) or ValueError (when raw_close=NaN but raw_open>0).
    Now: ``_present(v)`` treats both missing keys and None/NaN values as
    fallthrough triggers — the documented contract "raw_* 是 ground
    truth; 缺失时回退到 adj_*" actually holds for partial-NaN rows.
    """
    if layout == LAYOUT_CHASE_UPTREND:
        # raw_* 列是 ground truth; 缺失时回退到 adj_* 列。
        o = _chain_get(row, "raw_open", "adj_open", "open")
        h = _chain_get(row, "raw_high", "adj_high", "high")
        lo = _chain_get(row, "raw_low", "adj_low", "low")
        c = _chain_get(row, "raw_close", "adj_close", "close")
        pc = _chain_get(row, "raw_prev_close", "prev_close")
    elif layout in (LAYOUT_SHORT_REVERSAL, LAYOUT_CYCLE_PRICE):
        o = row["open"]; h = row["high"]; lo = row["low"]; c = row["close"]
        pc = row.get("prev_close")
    else:
        raise ValueError(f"未知 layout: {layout!r}")

    return ExecutionBar(
        open=_safe(o), high=_safe(h), low=_safe(lo), close=_safe(c),
        prev_close=_safe(pc) if pc is not None else None,
    )


def _present(v: object) -> bool:
    """Round 30 (CLAUDE.md §3): is value present (not None, not NaN)?

    dict.get(key, default) returns the VALUE when key exists, even if value
    is None or NaN. For LEFT JOIN miss rows, raw_* keys exist but values
    are None/NaN — naive dict.get returns None/NaN, defeating the fallback
    chain contract. _present() is the NaN-aware gate.
    """
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    # NaN check: NaN is the only float that is not equal to itself
    return f == f


def _chain_get(row: Mapping[str, object], *keys: str) -> object | None:
    """Round 30 (CLAUDE.md §3): walk a key chain, return first PRESENT value.

    Differs from chained ``dict.get(k1, dict.get(k2, ...))``:
      - dict.get returns the value when key exists (even if None/NaN)
      - _chain_get treats None/NaN as "missing" and continues to next key
    """
    for k in keys:
        if k in row and _present(row[k]):
            return row[k]
    return None


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


def is_limit_down(
    prev_close: float | None,
    open_price: float,
    threshold: float = 0.095,
) -> bool:
    """Symmetric to ``is_limit_up``: detect limit-down (跌停) for short entries.

    short_reversal makes the SYMMETRIC check: a stock that just hit
    limit-down cannot be sold short (the short side would not be able
    to close by buying back — buyer pool is gone).

    Threshold convention matches ``is_limit_up``: positive value 0.095
    means "trip if drop >= 9.5%". Caller passes positive threshold;
    function compares (open/prev - 1) <= -threshold.

    prev_close missing → False (allow entry, best-effort).
    """
    if prev_close is None or prev_close <= 0:
        return False
    return (open_price / prev_close - 1.0) <= -threshold


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

    ⚠️⚠️ **2026-10-19 (§13.120): 此处原文写「用于 chase_up (long) / 用于 short_reversal (short)」
    —— 两句都**不成立**, 出于一个精确扫描 (`tools/scan_unused_core_imports.py`)。**
    * `chase_up/portfolio.py` / `uptrend_pullback/portfolio.py` **根本不 import 本函数**
      —— 它们把同一公式**内联重写**了 (见 §13.95);
    * `short_reversal/replay_strategy_v3.py` **import 了它 (别名 `dual_atr_slippage`) 却从不调用**
      (§13.95)。⇒ **本函数在写下这句话时, 全仓零个真实消费者。**
    ⇒ 真正两条腿都用的是 `effective_slippage` (§13.95 新增, 它负责"与静态值取较大者")。
    **本函数今天仍无消费者** —— 保留是因为它是 ATR 项的**唯一公式来源**,
    但**不要按这段话去找它的调用者。**

    **符号 (多头 / 空头必须相反 —— 这是 §4/§0 的铁律)**:
    * **买入腿** (任何族的多头 entry): `entry_price = raw_open × (1 + slip)` —— 更贵 = 悲观 ✓
    * **卖出腿** (空头 entry, 或多头出场): `price = raw_open × (1 − slip)` —— 更低 = 悲观 ✓
    ⚠️ 本函数**只管 ATR 项的大小**, 不管符号; 符号由**调用方**按腿的方向决定。
    (2026-10-19 §13.120 更正: 这句话我上一版改写时**删掉过**, 而
     `tests/test_slippage_sign_long_short_antisymmetry.py` 正是断言它在这里 ——
     **又一次"改注释踩响一条文本钉桩"**, 与 §13.64 同形。)

    ⚠️ 2026-10-17 修正: 此处原文写 `short: × (1 + slip)` 并注为"悲观",
    是**自相矛盾**的 —— 上调卖出价是收到**更多**。short 的 entry 是卖出,
    取负号才悲观。该分支当时因 `atr_slip_scale=0` 全部 preset 而不可达,
    故修正无结果漂移; 详见 short_reversal/replay_strategy_v3.py 的对应注释。
    """
    if atr_pct <= 0 or participation <= 0 or scale <= 0:
        return 0.0
    return atr_pct * participation * scale

def effective_slippage(
    static_slip: float = 0.0,
    atr_pct: float | None = None,
    participation: float = 0.0,
    scale: float = 0.0,
) -> float:
    """一笔成交的**有效**冲击系数 —— **entry 与 exit 都必须走这里** (§4, §13.95)。

    规则: ``eff = max(static_slip, atr_pct × participation × scale)``

    ## 为什么需要它 (§13.95)
    §4 把执行滑点定义为「signal trigger 与 fill 之间的 price impact」——
    这是**每一笔 execution** 的性质, **买入腿与卖出腿同样成立**。
    但在 §13.95 之前, 这条规则在四个引擎里**各写了一遍, 且全部只作用于买入腿**
    ⇒ 卖出腿零冲击 = **单一方向的乐观** (§0 Pessimistic Default)。
    把「取较大者」收成唯一一处, 是为了让「两条腿用同一个模型」**可被断言**。

    ## 与 `atr_slippage` 的分工
    `atr_slippage` 只算 ATR 那一项; 本函数负责「与静态值**取较大者**」。
    静态 `slippage` 是历史遗留的 flat 项: §4 禁止把它当**唯一**模型,
    但作为下限保留 (取 max 而不是相加 —— 相加会把历史 flat 值叠加进去)。

    ## ⚠️ NaN / None 语义 (这一条是照抄内联式最容易写错的地方)
    `atr_pct` 为 ``None`` / NaN / ≤0 ⇒ 退回 `static_slip`, **不参与 max**。
    旧的内联写法靠 ``not np.isnan(...)`` 显式跳过; 若改写成裸 ``max()``,
    NaN 虽然因 ``NaN > x`` 恒假而"碰巧"取到 x, 语义已经坏了 ——
    且 `atr_pct <= 0` 对 NaN 也是 False, 会**静默传播**。故此处显式判 。
    """
    if atr_pct is None or participation <= 0 or scale <= 0:
        return float(static_slip)
    atr = float(atr_pct)
    if atr != atr or atr <= 0:  # NaN 或非正 ⇒ 该腿退回静态值
        return float(static_slip)
    return max(float(static_slip), atr * float(participation) * float(scale))


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


def volume_cap_fill(bar_vol: float, max_pct: float, lot_size: int) -> int:
    """§4 Volume Participation Limit (CLAUDE.md).

    Computes max fill quantity for a single order such that
    `Max_Fill_Qty = MIN(Order_Qty, Bar_Volume × max_pct)`, then rounds
    DOWN to the nearest `lot_size` (A股 100-share lots).

    Returns 0 only when there is nothing to participate in (bar_vol ≤ 0,
    max_pct ≤ 0, or lot_size ≤ 0). Otherwise returns at least 1 lot —
    this is the GREEN fix for the round-to-0 silent bypass
    ([[volume-cap-low-bar-bypass]]): when raw cap rounds to zero but
    bar has volume, return 1 lot rather than 0. This causes the caller
    to either fill 1 lot or reject the order (caller decides).

    Parameters
    ----------
    bar_vol : float
        Bar volume in shares. Negative → no fill.
    max_pct : float
        Maximum participation rate ∈ (0, 1]. 0 → no fill.
    lot_size : int
        A-share lot size (typically 100).

    Returns
    -------
    int
        Rounded-down fill quantity in shares. 0 iff no participation.
    """
    if bar_vol <= 0 or max_pct <= 0 or lot_size <= 0:
        return 0
    raw = bar_vol * max_pct
    # Floor to integer lots: at least 1 lot when raw is non-zero but
    # smaller than lot_size (was the round-to-0 bug).
    if raw < lot_size:
        return int(lot_size)
    return int(raw // lot_size) * int(lot_size)


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


# ----------------------------------------------------------- cost model constants
# CLAUDE.md §0 (Pessimistic Default) + §3 (Data Integrity): canonical cost
# rates for A-share backtests. POST-Aug2023 market structure (current).
#
# Single source of truth (Round 9, 2026-09-28). Previously each engine
# maintained its own copy → drift observed:
#   - short_reversal engine.py:24  COMMISSION_RATE = 0.0006 (2.4x off)
#   - cycle_price_action portfolio.py:62 STAMP_TAX_SELL = 0.001 (2x off)
# All 4 engines now import canonical constants from this module.

COMMISSION_RATE: float = 0.00025  # 万 2.5 (commission on both buy + sell)
STAMP_DUTY_RATE: float = 0.0005   # 万 5 (sell-side only, post-Aug2023)
MIN_COMMISSION: float = 5.0       # ¥5 floor per fill
STAMP_DUTY_SIDE: str = "sell"     # stamp duty applies only on sell side


def calc_commission(
    notional: float,
    min_commission: float = MIN_COMMISSION,
) -> float:
    """Canonical commission = max(min_commission, notional × COMMISSION_RATE).

    Both buy and sell sides pay commission (A-share market convention).
    """
    return max(min_commission, notional * COMMISSION_RATE)


def calc_stamp_duty(notional: float, side: str) -> float:
    """Canonical stamp duty = notional × STAMP_DUTY_RATE if side == SELL.

    Buy side pays zero (A-share market convention).
    """
    return notional * STAMP_DUTY_RATE if side == STAMP_DUTY_SIDE else 0.0


__all__ = [
    "LIMIT_UP_THRESHOLD",
    "LAYOUT_CHASE_UPTREND",
    "LAYOUT_SHORT_REVERSAL",
    "LAYOUT_CYCLE_PRICE",
    "ExecutionBar",
    "extract_execution_bar",
    "is_limit_up",
    "atr_slippage",
    "effective_slippage",
    "PRICE_SOURCE_RAW",
    "PRICE_SOURCE_ADJ",
    "validate_price_source",
    # Round 9 (2026-09-28): cost model canonical single-source
    "COMMISSION_RATE",
    "STAMP_DUTY_RATE",
    "MIN_COMMISSION",
    "STAMP_DUTY_SIDE",
    "calc_commission",
    "calc_stamp_duty",
]
