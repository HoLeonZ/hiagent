"""§2 NAV Gate cycle_price_action audit (Tick 46).

CLAUDE.md §2 (verbatim):
  "All-In Sizing Policy: Every entry is sized at 100% of available cash
   for that trade slot... Margin blowout protection still applies:
   `cost > cash` must reject the trade (no leverage) and NAV-floor
   cash gates remain valid for new entries."

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[cycle-nav-gate-missing]]:**

A. **cycle_price_action has ZERO NAV gate infrastructure** (verified):
   ```bash
   $ grep -n "initial_capital" cycle_price_action/*.py
   (no output)
   ```

B. **Other 3 engines have NAV gate**:
   - chase_up/portfolio.py:64 `NAV_GATE_RATIO = 0.05`
   - chase_up/portfolio.py:143 `initial_capital: float = 1_000_000.0` param
   - chase_up/portfolio.py:338-339 nav gate check:
     ```python
     if nav_now < initial_capital * NAV_GATE_RATIO:
         # reject new entry
     ```
   - uptrend_pullback/portfolio.py:48 NAV_GATE_RATIO + same param + check
   - short_reversal/replay_strategy_v3.py:64 nav_gate_ratio=0.05 (different name, same logic)

C. **cycle_price_action/portfolio.py:73-82 `__init__` signature**:
   ```python
   def __init__(
       self,
       cash: float,
       atr_slip_scale: float = 0.0,
   ) -> None:
       self.cash = float(cash)
       self.atr_slip_scale = atr_slip_scale
   ```
   - NO `initial_capital` param
   - NO NAV_GATE_RATIO constant
   - NO nav_gate check in try_enter

D. **Why this matters**:
   - Cycle can keep opening new positions even after catastrophic drawdown
   - chase_up + uptrend_pullback stop opening new positions when NAV
     drops below 5% of initial capital (catastrophic loss protection)
   - Cycle continues trading through blowup → over-trading losses
   - Inconsistent risk management across engine portfolio

E. **Numeric impact**:
   - Cycle has no test coverage (no backtest output yet, fail-fast blocks)
   - Once cycle produces output, results will diverge from
     chase_up/uptrend under identical market scenarios
   - Specifically in catastrophic drawdown regimes, cycle will show
     worse (more negative) Sharpe because it keeps entering

本文件验证:
- 3 RED: cycle lacks initial_capital param, lacks NAV_GATE_RATIO constant,
  lacks nav gate check in try_enter
- 2 PASS baseline: other 3 engines fully integrated (chase/uptrend/short)
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# RED: cycle_price_action lacks §2 NAV gate infrastructure
# ---------------------------------------------------------------------------


def test_cycle_portfolio_lacks_initial_capital_param() -> None:
    """§2 RED: cycle_price_action/portfolio.py __init__ lacks initial_capital.

    chase_up/portfolio.py:143 has `initial_capital: float = 1_000_000.0`
    in `__init__`. cycle/portfolio.py:73-82 has only `cash` + `atr_slip_scale`.

    Without initial_capital, NAV gate calculation has no anchor (gate ratio
    needs a baseline to compare current NAV against).
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    if "initial_capital" in src:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py __init__ "
        "lacks `initial_capital` parameter. CLAUDE.md §2 NAV gate "
        "requires initial_capital to compute gate threshold "
        "(nav_now < initial_capital × NAV_GATE_RATIO).\n"
        "Compare chase_up/portfolio.py:143:\n"
        "  initial_capital: float = 1_000_000.0,\n"
        "GREEN fix: add `initial_capital: float = 1_000_000.0` to "
        "cycle_price_action/portfolio.py:73-82 __init__ signature."
    )


def test_cycle_portfolio_lacks_nav_gate_ratio_constant() -> None:
    """§2 RED: cycle_price_action/portfolio.py lacks NAV_GATE_RATIO constant.

    chase_up/portfolio.py:64 + uptrend_pullback/portfolio.py:48 define
    `NAV_GATE_RATIO = 0.05`. cycle has no equivalent.

    Without the ratio, even if initial_capital is added, no gate threshold
    can be computed.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    if "NAV_GATE_RATIO" in src or "nav_gate_ratio" in src:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py lacks "
        "`NAV_GATE_RATIO` constant. CLAUDE.md §2 mandates 5% NAV floor "
        "gate for new entries.\n"
        "Compare chase_up/portfolio.py:64:\n"
        "  NAV_GATE_RATIO = 0.05\n"
        "GREEN fix: add `NAV_GATE_RATIO = 0.05` to module-level constants "
        "in cycle_price_action/portfolio.py."
    )


def test_cycle_try_enter_lacks_nav_gate_check() -> None:
    """§2 RED: cycle_price_action try_enter() lacks nav_gate check.

    chase_up/portfolio.py:338-339:
      if nav_now < initial_capital * NAV_GATE_RATIO:
          # reject new entry

    cycle try_enter() at line 106 has:
      - Line 118: `if price <= 0: return None` (NaN check)
      - Line 136: volume cap
      - **NO nav gate check**

    Cycle keeps opening new positions through catastrophic drawdowns.
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")

    # Extract try_enter body
    func_start = src.find("def try_enter(")
    if func_start == -1:
        return  # structure changed

    body_start = src.find(":\n", func_start) + 2
    body_end = len(src)
    for m in re.finditer(r"\n    def ", src[body_start:]):
        candidate = body_start + m.start() + 1
        if candidate < body_end:
            body_end = candidate
            break
    body = src[body_start:body_end]

    has_nav_gate = (
        "nav_gate" in body or
        "NAV_GATE" in body or
        ("initial_capital" in body and "cash +=" in body)  # implicit
    )

    if has_nav_gate:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/portfolio.py try_enter() "
        "lacks NAV gate check. CLAUDE.md §2 NAV floor mandate: when "
        "nav_now < initial_capital × NAV_GATE_RATIO, reject new entries.\n"
        "Per [[cycle-nav-gate-missing]], this is the ONLY engine without "
        "the gate — chase_up + uptrend_pullback + short_reversal all "
        "integrated.\n"
        "GREEN fix: add at start of try_enter() (after price > 0 check):\n"
        "  if hasattr(self, 'initial_capital') and hasattr(self, 'NAV_GATE_RATIO'):\n"
        "      nav_now = self.cash + (self._pos.mark_to_market if self._pos else 0)\n"
        "      if nav_now < self.initial_capital * self.NAV_GATE_RATIO:\n"
        "          return None  # reject catastrophic drawdown entries"
    )


# ---------------------------------------------------------------------------
# PASS baselines: other 3 engines have NAV gate
# ---------------------------------------------------------------------------


def test_chase_up_nav_gate_fully_integrated() -> None:
    """§2 PASS baseline: chase_up/portfolio.py FULLY integrated NAV gate.

    Round 14 (2026-09-28, CLAUDE.md §2): NAV gate 从 module-level 常量
    NAV_GATE_RATIO 改为 simulate_portfolio 参数 nav_gate_ratio (默认 0.05)。
    Pin 改为检查参数化 API 完整性。
    """
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")

    assert "nav_gate_ratio" in src, (
        "Regression: chase_up/portfolio.py lost nav_gate_ratio parameter"
    )
    assert "initial_capital" in src, (
        "Regression: chase_up/portfolio.py lost initial_capital param"
    )
    assert "nav_now < initial_capital * nav_gate_ratio" in src or \
           "nav < initial_capital * nav_gate_ratio" in src, (
        "Regression: chase_up/portfolio.py lost nav gate check"
    )


def test_uptrend_pullback_nav_gate_fully_integrated() -> None:
    """§2 PASS baseline: uptrend_pullback/portfolio.py FULLY integrated.

    Round 14 (2026-09-28, CLAUDE.md §2): NAV gate 从 module-level 常量
    NAV_GATE_RATIO 改为 simulate_portfolio 参数 nav_gate_ratio (默认 0.05)。
    """
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")

    assert "nav_gate_ratio" in src, (
        "Regression: uptrend_pullback/portfolio.py lost nav_gate_ratio parameter"
    )
    assert "initial_capital" in src, (
        "Regression: uptrend_pullback/portfolio.py lost initial_capital"
    )


# ---------------------------------------------------------------------------
# Round 10 (2026-09-28, CLAUDE.md §2): GREEN verification suite for cycle
# NAV gate fix — closes [[cycle-nav-gate-missing]] / [[nav-gate-cycle-price-action-audit-2026-09-23]].
# ---------------------------------------------------------------------------


def test_cycle_has_nav_gate_ratio_constant() -> None:
    """Round 10 GREEN: cycle_price_action Portfolio.NAV_GATE_RATIO == 0.05。

    Mirrors chase_up/portfolio.py:64 + uptrend_pullback/portfolio.py:48.
    """
    from cycle_price_action.portfolio import Portfolio

    assert hasattr(Portfolio, "NAV_GATE_RATIO"), (
        "cycle_price_action Portfolio missing NAV_GATE_RATIO class constant"
    )
    assert Portfolio.NAV_GATE_RATIO == 0.05, (
        f"NAV_GATE_RATIO must be 0.05 (CLAUDE.md §2 NAV-floor mandate), "
        f"got {Portfolio.NAV_GATE_RATIO}"
    )


def test_cycle_portfolio_takes_initial_capital() -> None:
    """Round 10 GREEN: Portfolio.__init__ 接受 initial_capital 参数 (默认 1M)。

    Mirrors chase_up + uptrend_pullback + short_reversal initial_capital=1_000_000.0
    默认值, 防止预设未声明时回退到隐式 0 或 NaN。
    """
    import inspect

    from cycle_price_action.portfolio import Portfolio

    sig = inspect.signature(Portfolio.__init__)
    assert "initial_capital" in sig.parameters, (
        "Portfolio.__init__ 缺 initial_capital 参数 — NAV gate 无 baseline"
    )
    param = sig.parameters["initial_capital"]
    assert param.default == 1_000_000.0, (
        f"initial_capital 默认应为 1_000_000.0 (与其他 3 个 engine 一致), "
        f"got default={param.default}"
    )


def test_cycle_try_enter_skips_when_nav_below_threshold() -> None:
    """Round 10 GREEN: 当 cash < initial_capital × NAV_GATE_RATIO, try_enter 返回 None。

    Setup: initial_capital=1_000_000, cash=0 (在 catastrophic blowup 后),
    NAV gate threshold = 1_000_000 × 0.05 = 50_000. cash=0 < 50_000 →
    try_enter 必须 return None (拒绝新开仓)。

    Mirrors chase_up/portfolio.py:314-323 NAV-floor 守卫逻辑。
    """
    from cycle_price_action.portfolio import Portfolio

    pf = Portfolio(cash=0.0, initial_capital=1_000_000.0)
    assert pf.initial_capital == 1_000_000.0
    assert pf.cash == 0.0

    # NAV gate threshold = 1_000_000 × 0.05 = 50_000
    # cash=0 << 50_000 → 拒绝 entry
    state = pf.try_enter(
        thscode="600000.SH",
        price=10.0,
        entry_date=__import__("datetime").date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
    )
    assert state is None, (
        "try_enter 在 NAV 跌穿 gate threshold 后仍返回 PositionState — "
        "NAV gate 未生效 (CLAUDE.md §2 violation)"
    )
    # cash 未被扣除 — 没有成交发生
    assert pf.cash == 0.0, (
        f"cash 应保持 0.0 (无成交), got {pf.cash}"
    )


def test_cycle_backtest_accepts_initial_capital() -> None:
    """Round 10 GREEN → §13.122 改钉**机制**: `_accepted` 必须**从 params 派生**。

    要保的性质 (Round 10 的原始意图, 未变): preset 里声明的 `initial_capital`
    不得被 `_accepted` 静默过滤掉 —— 否则 strategy 拿不到, NAV gate 锚点失效。

    ⚠️ 本断言此前钉的是 `backtest.py` 里必须出现**字面量** `"initial_capital"`
    (那是当时的**手工白名单**)。§13.98 把白名单换成
    `set(CyclePriceActionStrategy.params._getkeys()) - _INJECTED` ——
    派生之后那个字面量**合法地**消失了, 于是这条断言变成**死钉桩**
    (`.index`/`in` 永不命中 ⇒ 永不可能通过), 由 §13.122 的普查抓到。

    现在改钉**机制**而不是**某一次的字面量**:
      * `_accepted` 必须是**派生**的 ⇒ 「忘了同步白名单」这类事故在机制上消失;
      * 参数确实进了 strategy 的 params —— 由同文件的
        `test_cycle_strategy_passes_initial_capital` 覆盖 (不重复钉)。
    """
    src = Path("cycle_price_action/backtest.py").read_text(encoding="utf-8")

    assert "_accepted = set(" in src, (
        "cycle_price_action/backtest.py 的 `_accepted` 不再是**派生集合** —— "
        "退回手工白名单会让新加的 preset 键被静默丢弃 (§13.98)"
    )
    assert "CyclePriceActionStrategy.params._getkeys()" in src, (
        "`_accepted` 必须从 CyclePriceActionStrategy.params 派生, 而不是手抄一份"
    )


def test_cycle_strategy_passes_initial_capital() -> None:
    """Round 10 GREEN: CyclePriceActionStrategy.params 显式声明 initial_capital 默认值。

    保证 backtrader 调用方 backtest.py → addstrategy(... initial_capital=...)
    把预设值传递给 strategy, strategy 再传给 Portfolio (R1 NAV gate 边界)。
    Mirrors chase_up/backtrader_engine.py:188-202 同样 pattern。

    Note: backtrader MetaParams metaclass 把 `params = dict(...)` 包装成
    AutoInfoClass 对象, 运行时通过 CyclePriceActionStrategy.params 拿到
    不是 dict 实例。所以本测试用源文件静态扫描验证 preset plumbing,
    跟其他 audit test 一致 (test_atr_slip_scale_cross_preset.py 等)。
    """
    src = Path("cycle_price_action/backtrader_engine.py").read_text(encoding="utf-8")

    # Locate `params = dict(` block, scan until matching `)`
    params_start = src.find("params = dict(")
    assert params_start != -1, (
        "cycle_price_action/backtrader_engine.py 缺 `params = dict(` 块"
    )
    # Find balanced close paren (depth 1 from `(`)
    depth = 0
    end = params_start
    for i in range(params_start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    params_block = src[params_start:end]

    assert "initial_capital" in params_block, (
        "CyclePriceActionStrategy.params 块缺 `initial_capital=...` 声明 — "
        "NAV gate anchor 无法传给 Portfolio"
    )
    # 进一步验证默认值是 1_000_000.0 (与其他 3 个 engine 一致)
    import re as _re
    # Match only valid Python float literals (e.g., 1_000_000.0, 1000000.0, 1e6)
    # — strict pattern avoids `initial_capital=...)` from comment false-matches.
    m = _re.search(
        r"initial_capital\s*=\s*([\d_]+(?:\.[\d_]+)?(?:[eE][+-]?[\d_]+)?)",
        params_block,
    )
    assert m is not None, (
        "params 块声明 initial_capital 但未匹配到数值默认值"
    )
    assert m.group(1) == "1_000_000.0", (
        f"initial_capital 默认值应为 1_000_000.0, got {m.group(1)}"
    )

    # 验证 __init__ 把 initial_capital 传给 Portfolio
    assert "initial_capital=self.p.initial_capital" in src, (
        "CyclePriceActionStrategy.__init__ 未把 self.p.initial_capital "
        "传给 Portfolio(初始 NAV gate anchor 丢失)"
    )