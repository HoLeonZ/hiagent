"""Dual-Price System 共享逻辑 (CLAUDE.md §3, 2026-09-22).

本模块是领域层:纯函数 + **零外部依赖**(故不引入 duckdb/pandas)。

**勘误(2026-10-17)**:此处原写「数据加载请走
``dna_data.dual_price_loader.load_dual_price_panel()``」—— 那是一条**没人遵守的规定**:
生产代码里**没有任何引擎**走它(只有 tests 引用)。实际情况是:

- 四个引擎各有自己的面板加载器(`chase_up/data.py`、`uptrend_pullback/data.py`、
  `short_reversal/_panel_loader.py`、`cycle_price_action/data_feed.py`),
  外加扫描器的 `load_panel_for_signal`;
- `dna_data/` 那套 loader + resolver(`signal_close` / `execution_close` /
  `execution_open`)是**迁移目标**,不是现状 —— 其 resolver 的 docstring 也如实写着
  「legacy panel / 允许逐个策略增量迁移」。

这个「共享层存在但无人接线」的状态**有代价**,今天刚吃过一次:附四十七 ——
扫描器的加载器漏了 `adj_*`,`adj_close != close` 的行占 **94%**,而它本该是
「只改一处」就能避免的事。**修一处 ≠ 修一族;一个共享层只有被接线才算数。**

接线本身是结果敏感的重构(各引擎 loader 还带 warmup 缓冲、公司行为事件列、universe
切片等各自的东西),故**登记待评估**,而不是在审计里顺手改。

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

import bisect
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


class SlippagePolicyUndeclared(ValueError):
    """preset 未显式声明滑点标定值(§4, audit P1-B2)。"""


def resolve_atr_slip_scale(preset: dict, preset_name: str = "<preset>") -> float:
    """§4 滑点标定值必须由 preset **显式声明**;缺声明 → fail-fast。

    为什么不允许静默默认(审计 P1-B2, 2026-10-15):
    `p.get("atr_slip_scale", 0.0)` 让"没有声明"与"声明为 0"完全无法区分,于是
    §4 强制的 ATR×参与率滑点在**全部 100 个出厂 preset** 上都不生效,而这一点在
    任何地方都看不出来 —— 没有报错、没有日志、没有断言。审计实测四引擎的成交价
    恒等于 bar 开盘价,"已实现但不可达"。

    现在:缺声明直接抛错。厂商 preset 一律显式写下 `SLIP_NONE_ACKNOWLEDGED`
    (= 0.0,即"已知缺口"的确认值),使缺口**被枚举、可审计**,而不是靠沉默存在。
    把标定值改成真实数值会改变成交价,属研究决策(§5 迭代计数),不在此替用户决定。
    """
    if "atr_slip_scale" not in preset:
        raise SlippagePolicyUndeclared(
            f"§4: preset {preset_name!r} 未显式声明滑点标定值 `atr_slip_scale`。"
            "滑点策略必须单源且显式声明 —— 请写入 `SLIP_NONE_ACKNOWLEDGED`"
            "(=0.0,确认已知缺口)或真实标定值。静默默认已移除。"
        )
    try:
        return float(preset["atr_slip_scale"])
    except (TypeError, ValueError) as exc:
        raise SlippagePolicyUndeclared(
            f"§4: preset {preset_name!r} 的 atr_slip_scale={preset['atr_slip_scale']!r} "
            "无法解析为 float"
        ) from exc

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
# §4 (audit P2-11, 2026-10-15): 融券年化费率。此前只在
# short_reversal/engine.py 本地定义为 MARGIN_RATE,而 presets.py 的
# BORROW_ASSUMPTION.borrow_cost_rate 又独立写了同一个数值 —— 两处同值
# 不同源,正是会静默漂移的形态。§4 要求做空策略显式声明借券模型,
# 该数值必须是同一个源。
BORROW_RATE_ANNUAL: float = 0.086   # 年化 8.6%(做空融券费)


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


def _is_missing(v: object) -> bool:
    """NaN / None 判定(零依赖;`v != v` 对任何浮点类型都成立)。"""
    return v is None or v != v


def mark_price(
    pi: dict,
    day,
    price_source_for_execution: str,
) -> float:
    """§1/§3 盯市价 —— `day` 当日或之前**最后一个可用收盘价**(raw-first)。

    §1 Suspension semantics (audit HIGH, 2026-10-16): 停牌产生的是**缺 bar**,
    既不是 0 价、也不是入场价。§1 原文:「positions in suspended names are
    marked at the **last `raw_close`** and MUST NOT generate fills until
    trading resumes」。

    此前签名是 `(pi, j, fallback, price_source_for_execution)`,两个 DataFrame
    引擎(chase_up / uptrend_pullback)在 `j is None`(当日无 bar)时返回
    `fallback` = `pos["entry_price"]` —— 于是**停牌期间持仓按入场价盯市**:

      - 停牌期内该仓位的浮盈浮亏**全部消失**(净值曲线被凭空拉平),复牌当日
        再一次性跳回 —— 一段真实的行情在权益曲线上被抹掉又还回来;
      - NAV 闸门(§2)用这个假净值判断是否已击穿,停牌股会让闸门看不见亏损;
      - 窗口末日强平(下方 `t == last_t`)会按 `entry_price` **造出一笔现实中
        不可能成交的"≈0 盈亏"交易**,并把 §1 明令禁止的 fill 写进成交列表。

    实测暴露面(黄金窗口 2025-09-19→2026-09-19,3159 只票 / 242 个交易日):
    299 只票有缺口、共 1348 个 (股票, 日) 缺口事件,其中 **10 只在窗口末日
    仍无 bar** —— 只要窗口末持有其中之一,就会产生上述假成交。

    现在盯市价不再有"调用方给的成本价"这一路输入:缺 bar 时**向前回退**到
    最后一个真实收盘价(这正是 §1 的要求),故该函数只依赖股票自身的 bar 序列。

    §3:`raw_close` = 原始域,`close` = 复权域;raw 列缺失(LEFT JOIN miss →
    NaN)时回退该行复权价(baseline parity)。整段无可用价 → fail-fast。
    本模块保持零外部依赖,故用 `bisect` 而非 numpy。
    """
    dates = pi["dates"]
    k = bisect.bisect_right(dates, day) - 1
    for idx in range(k, -1, -1):
        if price_source_for_execution == PRICE_SOURCE_RAW and "raw_close" in pi:
            raw_px = pi["raw_close"][idx]
            if not _is_missing(raw_px):
                return float(raw_px)
        adj_px = pi["close"][idx]
        if not _is_missing(adj_px):
            return float(adj_px)
    raise ValueError(
        f"§1: {day} 及之前没有任何可用收盘价,无法盯市 —— "
        "该股票在此窗口内没有任何 bar。持仓必然存在至少一根 bar,"
        "因此这是调用方的 bug,不是可静默回退的情形。"
    )


def portfolio_nav(
    free_cash: float,
    settling_funds: float,
    holdings_value: float,
) -> float:
    """Canonical NAV = Free_Cash + Settling_Funds + Σ 持仓市值.

    §2 (audit P0-1, 2026-10-15) — 唯一净值口径。

    `locked_margin` 保存的是持仓的**成本基础**,而 `holdings_value` 是同一
    持仓的**市值**。把两者相加会把仓位计两次:持仓期间权益虚增约一个入场
    成本,平仓后该虚增自动消失 —— 因此这个错误**只在持仓期间出现**,
    在"平仓后对账"式的测试下极易漏检,四个引擎都曾这样写。

    入场费在 reserve_for_entry 时即离开现金池(且 release_margin 不回补
    free_cash),所以净值里不含 locked_margin 才是正确口径。

    等价写法 `total_cash + Σ未实现盈亏` 在持仓期间会高估 Σ入场费,不作为
    规范口径;需要单源 NAV 时一律调用本函数。
    """
    return free_cash + settling_funds + holdings_value


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
    "BORROW_RATE_ANNUAL",
    "calc_commission",
    "calc_stamp_duty",
    # audit P0-1 (2026-10-15): canonical NAV single-source
    "portfolio_nav",
    # audit P0-1b (2026-10-15): canonical raw-first mark price
    "mark_price",
    # audit P1-B (2026-10-15): canonical slippage policy single-source
    "effective_slippage",
    "resolve_atr_slip_scale",
    "SlippagePolicyUndeclared",
]
