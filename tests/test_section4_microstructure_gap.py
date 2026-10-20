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

import ast
import inspect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

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


def test_cycle_preset_intraday_declared_has_engine_effect() -> None:
    """§4: cycle preset 的 `intraday_tiebreak` 声明必须**真的有效果**。

    2026-10-19 (§13.28): 原实现查的是 `run_backtest` 的**签名**
    (`"intraday_tiebreak" in inspect.signature(cycle_run).parameters`) ——
    而 `run_backtest` 本来就不需要这个参数: 它从 **preset dict** 走。
    接线**已经存在**: `backtest.py:110` 的白名单 `_accepted` 含它 ⇒ 转发到
    `CyclePriceActionStrategy` → `Portfolio.__init__` → 出场路径**强制校验**。
    ⇒ **这条红灯是"代码修好了、测试没跟上"**, 不是真 gap。
    (与同文件 `test_all_engines_route_volume_cap_through_core` 同一根因:
     **查形式, 不查性质**。)

    改为断言**效果**:
      1. `Portfolio` 必须**记住**传入的值 (不是忽略);
      2. 非 `sl_first` 的值必须在出场路径 **fail-fast** (这就是"engine effect");
      3. 策略必须声明该参数 (否则 preset 的值无处落地);
      4. 转发白名单必须包含它 (否则 preset 的值根本到不了策略)。
    """
    from datetime import date

    from cycle_price_action.portfolio import Portfolio

    # 1 + 2: 参数被记住、且**真的有后果** —— 这就是"engine effect"
    pf = Portfolio(cash=1_000_000.0, intraday_tiebreak="tp_first")
    assert pf.intraday_tiebreak == "tp_first", "Portfolio 忽略了这个参数 (silently dropped)"
    pf.try_enter(
        "600000.SH", 10.0, date(2025, 1, 2),
        {"k_line_score": 1.0, "phase_score": 1.0, "calendar_score": 1.0},
        bar_volume=1e7,
    )
    with pytest.raises(ValueError, match="sl_first"):
        pf.try_exit_with_intraday_check(
            date(2025, 1, 3), 11.0, 11.0, 9.0, 10.5, 0.06, 0.05
        )

    # 3: 策略必须声明该参数 (preset 的值要有地方落)
    from cycle_price_action.backtrader_engine import CyclePriceActionStrategy

    assert "intraday_tiebreak" in CyclePriceActionStrategy.params._getkeys(), (
        "策略没有声明 intraday_tiebreak ⇒ preset 的值无处落地"
    )

    # 4: 转发闸门 (preset → strategy 的闸门) 必须放行它
    # 闸门有两种**都成立**的写法, 本条两种都认(它们都靠"策略确实声明了该参数",
    # 即上一条断言, 来保证该键在集合里):
    #   (a) 字面 `_accepted = {..., "intraday_tiebreak", ...}`;
    #   (b) 从 `CyclePriceActionStrategy.params._getkeys()` **派生**(不存在
    #       "加了 param 忘了同步白名单"这种漏键)。
    # 反之, 若闸门变成一份**不含该键的手工名单**, 两种写法都不成立 ⇒ 本条照红。
    src = (ROOT / "cycle_price_action" / "backtest.py").read_text(encoding="utf-8")
    gate_literal = re.search(r"_accepted\s*=\s*\{[^}]*intraday_tiebreak", src, re.S)
    gate_derived = re.search(
        r"_accepted\s*=\s*set\(\s*CyclePriceActionStrategy\.params\._getkeys\(\)",
        src,
    )
    assert gate_literal or gate_derived, (
        "转发闸门 `_accepted` 不含 intraday_tiebreak(也不是从 params 派生) "
        "⇒ preset 的声明在转发处被丢弃"
    )


def _imports_from_core_dual_price(src: str, name: str) -> bool:
    """该源码是否**确实**从 `core.dual_price` 导入了 `name` (AST, 识别别名)。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.dual_price":
            for alias in node.names:
                if alias.name == name:
                    return True
    return False


def test_all_engines_route_volume_cap_through_core() -> None:
    """§4: 量比上限必须**全部**走 `core.dual_price.volume_cap_fill` (单一来源)。

    2026-10-19 (§13.28): 原实现是**文本钉桩** —— 断言四个文件里各出现一个
    **内联公式字符串** (`int(bar_vol * max_volume_participation // 100) * 100` 等)。
    它这次变红的理由是: **三族被正确地改走规范函数了** ——
    **代码变好了, 钉桩没跟上 ⇒ 它红着, 却什么也没在守。**
    (与 §13.22(g) 修掉的那条同一族: 用"写法"代替"性质"。)

    改为断言**性质**, 且**发现式** (不写死文件列表 —— §13.22/§13.23 的教训):
      * 正面: 任何出现 `MAX_VOL_PARTICIPATION` 的族内模块, 必须导入 `volume_cap_fill`;
      * 反面: 不得再出现内联的量比取整式。
    这样"把定义删掉"或"抄一份新的内联式"都会红。
    """
    hits_ok, hits_bad = [], []
    for p in sorted(ROOT.glob("*/**/*.py")):
        if p.parts[0] in ("core", "tests") or p.name.startswith("test_"):
            continue
        src = p.read_text(encoding="utf-8")
        if "MAX_VOL_PARTICIPATION" not in src and "max_volume_participation" not in src:
            continue
        rel = str(p.relative_to(ROOT))
        # 正面判据必须查**绑定**, 不能只查"字符串出现过" ——
        # 初稿写的是 `"volume_cap_fill" in src`, 而**去掉 import 之后调用点仍在**,
        # 断言照样通过 (§6 注入 B 实测: 该写法**不咬**)。这就是 §13.19/§13.20
        # 那种"看着在守、其实恒真"的形态, 又一次。
        # 用 **AST** 而不是正则: 导入块里带括号的注释会把 `[^)]*` 提前截断
        # (第二版就是这么假的 —— 还原态也报红)。AST 对别名也一并识别。
        if _imports_from_core_dual_price(src, "volume_cap_fill"):
            hits_ok.append(rel)
        # 反面: 内联的量比取整 (`* MAX_VOL... // 100) * 100`)
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"VOL_PARTICIPATION\s*//\s*100", line) or re.search(
                r"max_volume_participation\s*//\s*100", line
            ):
                hits_bad.append(f"{rel}:{i}")

    assert not hits_bad, (
        "§4 量比上限又出现了**内联取整式** —— 必须走 core.dual_price.volume_cap_fill:\n  "
        + "\n  ".join(hits_bad)
    )
    assert len(hits_ok) >= 4, (
        f"只有 {len(hits_ok)} 个模块走规范量比上限 ({hits_ok}) —— 预期四族各一。"
        f"若某族改用了别的写法, 本条会漏掉它。"
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