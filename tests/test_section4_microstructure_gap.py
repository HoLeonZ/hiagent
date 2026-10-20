"""§4 Microstructure & Liquidity cross-engine audit RED tests.

CLAUDE.md §4 mandates:
  - Volume Participation Limit: Max_Fill_Qty = MIN(Order_Qty, Bar_Volume × 0.10)
  - Slippage as function of ATR (Execution Only) — NOT flat-rate
  - Exit Thresholds (TP/SL): documented in preset compliance header
  - Intraday Blindness: on daily bar data, if BOTH SL+TP breached in same bar,
    MUST assume worst-case (SL-first)

§4 Audit matrix (FRESH 2026-09-23):

| Engine | Volume cap | ATR-slip opt-in | SL-first intraday |
|---|---|---|---|
| chase_up | ✓ portfolio.py:406 | ✓ portfolio.py:151 | ✓ portfolio.py (validated) |
| uptrend_pullback | ✓ portfolio.py:395 | ✓ portfolio.py | ✓ portfolio.py:282 |
| short_reversal | ✓ replay_strategy_v3.py:257 | ✓ engine.py:192 | ✓ declared in preset, used in code |
| cycle_price_action | ✓ portfolio.py:137 | ✓ portfolio.py:79 | ⚠️ hardcoded, no param |

VIOLATIONS:
A. **cycle_price_action intraday_tiebreak is hardcoded** — no `intraday_tiebreak`
   parameter on Portfolio.__init__. Preset declares `"intraday_tiebreak": "sl_first"`
   but engine doesn't take it as input. Future preset change to e.g.
   "tp_first" would silently NOT take effect.

B. **chase_up/uptrend_pullback has volume cap LOW-BAR BYPASS** (already pinned
   in [[volume-cap-low-bar-bypass]] from Tick 25).

C. **cycle_price_action portfolio.LAYOUT_CYCLE_PRICE differs from
   chase/uptrend LAYOUT_CHASE_UPTREND** — cross-engine price layout divergence.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


def test_cycle_intraday_tiebreak_is_parameter() -> None:
    """§4 RED: cycle_price_action Portfolio must accept intraday_tiebreak
    parameter (matches chase/uptrend convention).

    chase_up/portfolio.py:149 `intraday_tiebreak: str = "sl_first"`
    uptrend_pullback/portfolio.py:149 same
    cycle_price_action/portfolio.py:73-82 `__init__` has NO `intraday_tiebreak`

    §4 mandates SL-first. The behavior is correctly hardcoded in
    `try_exit_with_intraday_check`. But the API is inconsistent:
    - chase/uptrend expose it as param
    - cycle does not
    Future preset tuning cannot reach cycle's behavior.
    """
    from cycle_price_action.portfolio import Portfolio

    sig = inspect.signature(Portfolio.__init__)
    assert "intraday_tiebreak" in sig.parameters, (
        "GAP CAPTURED: cycle_price_action.Portfolio.__init__ missing "
        "`intraday_tiebreak` parameter. §4 API inconsistency with "
        "chase_up / uptrend_pullback. Preset cannot tune this engine's "
        "intraday behavior. GREEN fix: add `intraday_tiebreak: str = "
        "'sl_first'` param and thread through try_exit_with_intraday_check."
    )


def test_cycle_intraday_declaration_reaches_the_execution_layer() -> None:
    """§4: cycle preset 声明的 `intraday_tiebreak='sl_first'` 必须有**引擎效果**。

    原版判据是「`run_backtest` 的**函数签名**里没有 `intraday_tiebreak`」——这个判据
    本身就是错的:该键经 preset 白名单 → strategy params → Portfolio 三层流动
    (见 `backtest.py` 的 `_accepted`),不必是 `run_backtest` 的形参。于是 Round 15
    修好接线之后,这条用例仍在报旧结论 —— **判据选错,修复也会被报成缺口**。

    现在的判据是「声明真的到执行层,而且会被强制」:Portfolio 拒绝任何非
    'sl_first' 的值(§4 强制 SL-first 悲观口径 —— 同 bar 双触及时假设先止损),
    故该声明是一条**可被违反、违反即失败**的契约,而不是装饰。
    """
    from cycle_price_action.backtrader_engine import CyclePriceActionStrategy
    from cycle_price_action.portfolio import Portfolio

    # (a) 三层接线都在:preset 白名单 → strategy params → Portfolio 形参
    backtest_src = Path("cycle_price_action/backtest.py").read_text(encoding="utf-8")
    assert "intraday_tiebreak" in backtest_src, (
        "§4 VIOLATION: cycle 的 preset 白名单不再放行 intraday_tiebreak"
    )
    assert hasattr(CyclePriceActionStrategy.params, "intraday_tiebreak"), (
        "§4 VIOLATION: CyclePriceActionStrategy.params 缺 intraday_tiebreak"
    )
    assert "intraday_tiebreak" in inspect.signature(Portfolio.__init__).parameters, (
        "§4 VIOLATION: Portfolio 不接受 intraday_tiebreak(声明到不了执行层)"
    )

    # (b) 声明被**强制**:非 sl_first → 出场判定 fail-fast(而不是静默按 sl_first 跑完)。
    #     校验点就在出场决策里 —— 正是"同 bar 双触发时假设先止损"这条悲观口径的入口。
    from datetime import date

    pf = Portfolio(cash=100_000.0, intraday_tiebreak="tp_first")
    assert pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.0})
    with pytest.raises(ValueError, match="intraday_tiebreak"):
        pf.try_exit_with_intraday_check(
            exit_date=date(2024, 6, 4),
            open_price=10.0, high=11.0, low=9.0, close=10.0,
            tp_pct=0.06, sl_pct=0.05,
        )


#: §4 成交量上限的四条接线点 —— 必须全部经**规范助手**,而不是各写一份字面公式。
VOLUME_CAP_SITES = (
    "chase_up/portfolio.py",
    "uptrend_pullback/portfolio.py",
    "short_reversal/replay_strategy_v3.py",
    "cycle_price_action/portfolio.py",
)


def test_all_engines_route_the_volume_cap_through_the_canonical_helper() -> None:
    """§4: 四个引擎的成交量上限必须走**同一个**规范助手 `volume_cap_fill`。

    原版钉的是四条**字面公式**(其中三条自带 round-to-0 缺陷)。chase_up /
    uptrend_pullback 改用规范助手之后,它反而报「回归,§4 审计必须重跑」——
    **把修复当成破坏**。钉住缺陷的字面量,是在为缺陷投保。

    规范助手的关键性质:薄量 bar 上至少返回 1 lot 而非 0。旧公式取整到 0 时
    `max_fill > 0` 守卫被跳过,下单**完全不受约束**(liquidity illusion)。
    """
    for rel in VOLUME_CAP_SITES:
        src = Path(rel).read_text(encoding="utf-8")
        assert "volume_cap_fill" in src, (
            f"§4 VIOLATION: {rel} 未使用规范 volume_cap_fill —— "
            "自行实现的 `int(bar_vol * pct // 100) * 100` 在 `bar_vol × pct < 100` "
            "时取整到 0,守卫随之被跳过,薄量 bar 上产生无上限的幻影成交。"
        )


def test_all_engines_atr_slip_scale_opt_in() -> None:
    """§4 baseline: all 4 engines have `atr_slip_scale` opt-in param
    (default 0.0 = static slip, scale>0 = ATR-aware slip).
    """
    engines_with_atr_slip = {
        "chase_up/portfolio.py": "atr_slip_scale: float = 0.0",
        "uptrend_pullback/portfolio.py": "atr_slip_scale: float = 0.0",
        "cycle_price_action/portfolio.py": "atr_slip_scale: float = 0.0",
        # audit P1-B2 (2026-10-15): 该引擎的滑点标定值不再走 `cfg.get(..., 0.0)`
        # 静默默认,而是经 core.dual_price.resolve_atr_slip_scale 解析 ——
        # **缺声明 fail-fast**,仍来自 cfg(opt-in 语义不变,且更强:未声明会被
        # 拦下而不是悄悄变成 0)。故断言改为新的取值路径。
        "short_reversal/engine.py": "resolve_atr_slip_scale(cfg",
        "short_reversal/replay_strategy_v3.py": "atr_slip_scale=0.0",
    }
    for path, pattern in engines_with_atr_slip.items():
        src = Path(path).read_text(encoding="utf-8")
        assert pattern in src, (
            f"Regression: {path} no longer has `{pattern}`. §4 ATR-aware "
            f"slippage opt-in removed."
        )


def test_short_reversal_uses_sl_first_in_code() -> None:
    """§4 baseline: short_reversal engine uses sl_first logic in code.

    Pin that when `o >= tp_p` AND `o <= sl_p` happen in same bar, sl
    wins. Already implemented in `replay_strategy_v3.py:170-180`.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")

    # Pin: short_reversal evaluates SL first (worst-case)
    has_sl_first_logic = (
        "sl_first" in src or
        "o <= sl_p" in src or
        "if low <= self.sl_price" in src
    )
    assert has_sl_first_logic, (
        "Regression: short_reversal no longer evaluates SL-first in "
        "intraday logic. §4 Intraday Blindness violation."
    )