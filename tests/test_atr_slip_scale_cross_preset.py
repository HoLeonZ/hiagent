"""§4 ATR-aware slippage plumbing 跨 preset审计 (Tick 38)。

CLAUDE.md §4 Microstructure: Execution slippage (price impact between
signal trigger and fill) MUST be modeled dynamically as a function of
the asset's current ATR and the order's participation rate. Flat-rate
slippage is forbidden (e.g., 1 tick flat).

**核心发现 (FRESH 2026-09-23):**

A. **atr_slip_scale signature accepts but call site DOES NOT pass**:
   - chase_up/portfolio.py:151 — `atr_slip_scale: float = 0.0` ✓
   - chase_up/backtrader_engine.py:188-202 — DOES NOT pass ✗
   - uptrend_pullback/portfolio.py:134 — same ✓
   - uptrend_pullback/backtrader_engine.py:233-256 — same ✗
   - short_reversal/engine.py:192 — `cfg.get("atr_slip_scale", 0.0)` ✓
     (only engine with full plumbing)

B. **176th dropped preset key**: extends Tick 32/37 finding.
   Preset想开 ATR-aware slippage 必须改 simulate_portfolio 调用方,
   目前 22 chase_up presets + N uptrend presets 全部 silently 0.0 (静态/无 slippage).

C. **commission_rate + stamp_duty_rate + min_commission 也 dropped**:
   - simulate_portfolio 签名有 `commission_rate: float = 0.00025`
   - backtrader_engine call site 不传 → 用默认值 0.00025
   - 任何 preset 想用 0.0003 commission 必须显式改 engine 代码
   - §0 cost model 维度相关

D. **slippage (静态) 参数也 dropped**:
   - simulate_portfolio 签名有 `slippage: float = 0.0`
   - 同样的 plumbing gap

本文件验证:
- 4 RED (chase_up + uptrend call site 缺 atr_slip_scale/commission_rate/stamp_duty_rate/min_commission/slippage)
- 2 PASS baseline (short_reversal 完整 plumbing; cost model RED 已独立跟踪)
"""
from __future__ import annotations

import re
from pathlib import Path


# Cost + slippage params that simulate_portfolio accepts but call site may not pass
PLUMBED_PARAMS = [
    "atr_slip_scale",
    "commission_rate",
    "stamp_duty_rate",
    "min_commission",
    "slippage",
]


def _find_call_window(text: str, func_name: str) -> str | None:
    """Find balanced parens window after func_name call. Return None if not found."""
    start = text.find(f"{func_name}(")
    if start == -1:
        return None
    depth = 0
    end = start
    for j in range(text.find("(", start), len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    return text[start:end]


def test_chase_up_call_site_passes_atr_slip_scale() -> None:
    """§4 RED: chase_up/backtrader_engine.py call site 不传 atr_slip_scale.

    simulate_portfolio signature (chase_up/portfolio.py:151) accepts
    `atr_slip_scale: float = 0.0` but backtrader_engine.py:188-202
    does NOT plumb this from preset. Result: all 22 chase_up presets
    silently use 0.0 (no ATR-aware slippage).
    """
    call_window = _find_call_window(
        Path("chase_up/backtrader_engine.py").read_text(encoding="utf-8"),
        "simulate_portfolio",
    )
    if call_window is None:
        return

    if "atr_slip_scale" not in call_window:
        raise AssertionError(
            "GAP CAPTURED: chase_up/backtrader_engine.py does NOT pass "
            "atr_slip_scale to simulate_portfolio(). Signature accepts "
            "it (chase_up/portfolio.py:151) but call site silently "
            "uses default 0.0. §4 violation — preset cannot enable "
            "ATR-aware slippage. 176th dropped preset key. "
            "GREEN fix: add `atr_slip_scale=p.get('atr_slip_scale', 0.0)` "
            "to the call site."
        )


def test_uptrend_pullback_call_site_passes_atr_slip_scale() -> None:
    """§4 RED: uptrend_pullback/backtrader_engine.py call site 不传 atr_slip_scale."""
    call_window = _find_call_window(
        Path("uptrend_pullback/backtrader_engine.py").read_text(encoding="utf-8"),
        "simulate_portfolio",
    )
    if call_window is None:
        return

    if "atr_slip_scale" not in call_window:
        raise AssertionError(
            "GAP CAPTURED: uptrend_pullback/backtrader_engine.py does "
            "NOT pass atr_slip_scale to simulate_portfolio(). Same "
            "176th dropped preset key pattern as chase_up."
        )


def test_chase_up_call_site_passes_cost_model_params() -> None:
    """§0 RED: chase_up/backtrader_engine.py 不传 commission_rate/stamp_duty_rate/min_commission.

    Cost model is canonical (¥5 floor + 0.00025 commission + 0.0005 stamp
    post-Aug 2023) per CLAUDE.md §0/§3. But presets declaring different
    rates cannot reach simulate_portfolio.
    """
    text = Path("chase_up/backtrader_engine.py").read_text(encoding="utf-8")
    call_window = _find_call_window(text, "simulate_portfolio")
    if call_window is None:
        return

    missing = []
    for param in ["commission_rate", "stamp_duty_rate", "min_commission"]:
        if param not in call_window:
            missing.append(param)

    if missing:
        raise AssertionError(
            f"GAP CAPTURED: chase_up/backtrader_engine.py call site "
            f"missing {missing}. Presets cannot override cost model "
            f"defaults. §0/§3 coupling — even after GREEN cost model "
            f"fix, presets still can't tune commission/stamp/floor "
            f"without engine code change. GREEN fix: add to call "
            f"site:\n"
            f"  commission_rate=p.get('commission_rate', 0.00025),\n"
            f"  stamp_duty_rate=p.get('stamp_duty_rate', 0.0005),\n"
            f"  min_commission=p.get('min_commission', 5.0),"
        )


def test_uptrend_pullback_call_site_passes_cost_model_params() -> None:
    """§0 RED: uptrend_pullback/backtrader_engine.py 不传 cost model 参数."""
    text = Path("uptrend_pullback/backtrader_engine.py").read_text(encoding="utf-8")
    call_window = _find_call_window(text, "simulate_portfolio")
    if call_window is None:
        return

    missing = []
    for param in ["commission_rate", "stamp_duty_rate", "min_commission"]:
        if param not in call_window:
            missing.append(param)

    if missing:
        raise AssertionError(
            f"GAP CAPTURED: uptrend_pullback/backtrader_engine.py call "
            f"site missing {missing}. Same 176th dropped key pattern "
            f"as chase_up. Cost model plumbing gap."
        )


# ---------------------------------------------------------------------------
# PASS baselines
# ---------------------------------------------------------------------------


def test_short_reversal_atr_slip_full_plumbing() -> None:
    """§4 PASS baseline: short_reversal has full atr_slip_scale plumbing.

    short_reversal/engine.py:192 — `atr_slip_scale=cfg.get("atr_slip_scale", 0.0)`
    plumbs preset value all the way to replay_strategy_v3.atr_slip_scale
    parameter. Presets that declare non-zero atr_slip_scale get actual
    ATR-aware slippage.

    This is the gold standard that chase_up + uptrend_pullback should match.
    """
    engine = Path("short_reversal/engine.py")
    if not engine.exists():
        return
    text = engine.read_text(encoding="utf-8")

    assert "atr_slip_scale" in text and "cfg.get" in text, (
        "Regression: short_reversal/engine.py no longer plumbs "
        "atr_slip_scale from preset"
    )


def test_simulate_portfolio_signature_pins_atr_slip_scale() -> None:
    """§4 PASS baseline: simulate_portfolio signature accepts atr_slip_scale.

    chase_up/portfolio.py:151 + uptrend_pullback/portfolio.py:134 both
    declare `atr_slip_scale: float = 0.0` in signature. So adding the
    call site param is a non-breaking change (default preserves back-compat).
    """
    violations: list[str] = []

    for engine, path in [
        ("chase_up", "chase_up/portfolio.py"),
        ("uptrend_pullback", "uptrend_pullback/portfolio.py"),
    ]:
        text = Path(path).read_text(encoding="utf-8")
        if "def simulate_portfolio(" not in text:
            continue
        # Extract signature
        start = text.index("def simulate_portfolio(")
        sig_end = text.find(":\n", start)
        sig = text[start:sig_end]
        if "atr_slip_scale" not in sig:
            violations.append(f"{engine}: {path}")

    assert not violations, (
        "Regression: simulate_portfolio signature no longer accepts "
        "atr_slip_scale:\n" + "\n".join(f"  - {v}" for v in violations)
    )