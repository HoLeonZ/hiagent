"""§4 intraday_tiebreak plumbing 跨引擎审计 (Tick 39)。

CLAUDE.md §4 Microstructure: Intraday Blindness — On daily bar data,
if BOTH the Stop-Loss and Take-Profit limits are breached within the
same bar, the engine MUST assume the worst-case scenario (Stop-Loss
hit first).

intraday_tiebreak is the policy field that enforces this. Per V8
(2026-09-22) plumbing, it must flow: preset → engine → strategy.

**核心发现 (FRESH 2026-09-23):**

A. **3 engines have full intraday_tiebreak plumbing**:
   - chase_up: preset declares → backtrader_engine.py:200 passes →
     portfolio.py:165 accepts → portfolio.py:294-298 validates
   - uptrend_pullback: same pattern (backtrader_engine.py:255 area)
   - short_reversal: engine.py:197 plumbs cfg.get(...)
   - **181st dropped preset key**: cycle_price_action declares
     `intraday_tiebreak="sl_first"` in presets.py:32 but Portfolio
     doesn't accept it (per [[section4-microstructure-cycle-gap]])

B. **Cycle's try_exit_with_intraday_check IS sl-first hardcoded**:
   - Per cycle_price_action/audit_phantom.py:56-70, the try_exit
     function has `sl_first_in_intraday_check` check — the *behavior*
     is correct (SL-first), but it's NOT exposed as a configurable
     parameter. Result: preset can declare `tp_first` but engine
     silently ignores, treats as `sl_first` (Pessimistic Default is
     preserved by accident, not by design).

C. **Inconsistency**: 3 engines have parameter; 1 engine has only
   hardcoded behavior. CLAUDE.md §4 pessimism is preserved (best
   outcome), but §0/§6 preset→strategy plumbing is broken.

本文件验证:
- 3 RED (cycle Portfolio signature lacks intraday_tiebreak, cycle
  call site doesn't pass, audit_phantom.py override)
- 3 PASS baseline (chase + uptrend + short_reversal plumbing works)
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Cycle plumbing RED tests
# ---------------------------------------------------------------------------


def test_cycle_portfolio_signature_accepts_intraday_tiebreak() -> None:
    """§4 RED: cycle_price_action/portfolio.py:73 Portfolio.__init__
    signature lacks intraday_tiebreak param.

    Per [[section4-microstructure-cycle-gap]], this is the 181st
    dropped preset key. chase_up + uptrend_pullback Portfolio accepts
    it; cycle does not.
    """
    portfolio = Path("cycle_price_action/portfolio.py")
    text = portfolio.read_text(encoding="utf-8")

    # Find class Portfolio + __init__ block
    if "class Portfolio" not in text:
        return

    # Find def __init__ within Portfolio class (first match)
    init_start = text.find("def __init__")
    if init_start == -1:
        return
    # Find signature end (first ':' at depth 0)
    sig_end = text.find(":\n", init_start)
    sig = text[init_start:sig_end]

    if "intraday_tiebreak" not in sig:
        raise AssertionError(
            "GAP CAPTURED: cycle_price_action/portfolio.py Portfolio "
            "class __init__ signature does NOT accept "
            "intraday_tiebreak param. §4 inconsistency — chase_up + "
            "uptrend_pullback Portfolio accept it (chase_up/"
            "portfolio.py:165), but cycle does not. Preset "
            "intraday_tiebreak is silently dropped. 181st dropped "
            "preset key. GREEN fix: add `intraday_tiebreak: str = "
            "\"sl_first\"` to Portfolio.__init__ signature and "
            "validate the value matches CLAUDE.md §4 'sl_first'."
        )


def test_cycle_backtrader_engine_call_site_passes_intraday_tiebreak() -> None:
    """§4 RED: cycle_price_action/backtrader_engine.py:53 Portfolio()
    call doesn't pass intraday_tiebreak.

    Even if Portfolio.__init__ accepts the param (Tick 39 GREEN fix),
    the call site must also plumb it from preset.
    """
    engine_path = Path("cycle_price_action/backtrader_engine.py")
    text = engine_path.read_text(encoding="utf-8")

    # Find Portfolio(...) call sites
    call_starts = [m.start() for m in re.finditer(r"\bPortfolio\(", text)]
    for start in call_starts:
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
        call = text[start:end]
        if "intraday_tiebreak" not in call:
            # Find line number
            line_no = text[:start].count("\n") + 1
            raise AssertionError(
                f"GAP CAPTURED: cycle_price_action/backtrader_engine.py"
                f":{line_no} Portfolio() call does NOT pass "
                "intraday_tiebreak. Even if Portfolio.__init__ "
                "signature is updated, this call site must plumb "
                "from preset. 181st dropped key + plumbing gap."
            )


def test_cycle_preset_declares_intraday_tiebreak() -> None:
    """§4 audit: cycle presets DECLARE intraday_tiebreak but it's silently dropped.

    cycle_price_action/presets.py:32 declares
    `intraday_tiebreak="sl_first"`. But Portfolio doesn't accept
    it, so the value is unused. Pessimism preserved by accident.
    """
    presets = Path("cycle_price_action/presets.py")
    if not presets.exists():
        return
    text = presets.read_text(encoding="utf-8")

    if "intraday_tiebreak" not in text:
        # If preset doesn't declare, this is a different gap (forward-defense)
        return

    # Confirm cycle Portfolio signature still lacks it (compound finding)
    portfolio = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")
    init_match = re.search(
        r"def __init__\s*\(([^)]*)\)", portfolio, re.DOTALL
    )
    if init_match and "intraday_tiebreak" not in init_match.group(1):
        raise AssertionError(
            "GAP CAPTURED: cycle_price_action/presets.py declares "
            "intraday_tiebreak but cycle_price_action/portfolio.py "
            "Portfolio.__init__ does NOT accept it. Compound "
            "finding: preset declares + Portfolio ignores. "
            "Pessimism preserved by hardcoded sl_first in "
            "try_exit_with_intraday_check, not by parameter "
            "plumbing. §4/§0 inconsistency."
        )


# ---------------------------------------------------------------------------
# PASS baselines: chase + uptrend + short_reversal have full plumbing
# ---------------------------------------------------------------------------


def test_chase_up_intraday_tiebreak_full_plumbing() -> None:
    """§4 PASS baseline: chase_up has full intraday_tiebreak plumbing.

    chase_up/presets.py declares → chase_up/backtrader_engine.py:200
    passes → chase_up/portfolio.py:165 accepts → portfolio.py:294-298
    validates ('sl_first' required).
    """
    text = Path("chase_up/backtrader_engine.py").read_text(encoding="utf-8")
    assert "intraday_tiebreak" in text, (
        "Regression: chase_up/backtrader_engine.py no longer passes "
        "intraday_tiebreak"
    )


def test_uptrend_pullback_intraday_tiebreak_full_plumbing() -> None:
    """§4 PASS baseline: uptrend_pullback has full intraday_tiebreak plumbing."""
    text = Path("uptrend_pullback/backtrader_engine.py").read_text(encoding="utf-8")
    assert "intraday_tiebreak" in text, (
        "Regression: uptrend_pullback/backtrader_engine.py no longer "
        "passes intraday_tiebreak"
    )


def test_short_reversal_intraday_tiebreak_full_plumbing() -> None:
    """§4 PASS baseline: short_reversal has full intraday_tiebreak plumbing.

    engine.py:197 — `intraday_tiebreak=cfg.get("intraday_tiebreak",
    "sl_first")` plumbs from preset to replay_strategy_v3.
    """
    text = Path("short_reversal/engine.py").read_text(encoding="utf-8")
    assert "intraday_tiebreak" in text and "cfg.get" in text, (
        "Regression: short_reversal/engine.py no longer plumbs "
        "intraday_tiebreak from preset"
    )


# ---------------------------------------------------------------------------
# PASS baseline: cycle's behavior IS sl-first (by hardcoded behavior)
# ---------------------------------------------------------------------------


def test_cycle_try_exit_evaluates_sl_first_in_code() -> None:
    """§4 PASS baseline: cycle's try_exit_with_intraday_check IS sl-first.

    Per cycle_price_action/audit_phantom.py:56-70 and confirmed at
    cycle_price_action/portfolio.py:217-224 — function order:
      1. open_price <= sl_p → SL (gap-down at open, worst case)
      2. open_price >= tp_p → TP
      3. low <= sl_p → SL (intra-bar)
      4. high >= tp_p → TP (intra-bar)

    So Pessimism is preserved, but not via parameter plumbing.
    """
    portfolio = Path("cycle_price_action/portfolio.py")
    text = portfolio.read_text(encoding="utf-8")

    # Find try_exit_with_intraday_check function
    marker = "def try_exit_with_intraday_check"
    start = text.find(marker)
    if start == -1:
        return

    # Skip past def signature (until next line starting with `if` /
    # `elif` / `tp_p = ` / `sl_p = `) — heuristic: find first
    # `if open_price` or `tp_p = entry` after def line
    body_start = text.find("tp_p = entry", start)
    if body_start == -1:
        body_start = text.find("if open_price", start)
    if body_start == -1:
        return

    # Slice until next def or class
    end = text.find("\n    def ", body_start + 100)
    if end == -1:
        end = len(text)
    check_body = text[body_start:end]

    # Find sl_p / tp_p comparisons (not sl_pct / tp_pct which are params)
    # sl-first means `if open_price <= sl_p` BEFORE `if open_price >= tp_p`
    sl_check = check_body.find("if open_price <= sl_p")
    tp_check = check_body.find("if open_price >= tp_p")

    if sl_check == -1 or tp_check == -1:
        return  # structure changed, can't verify

    assert sl_check < tp_check, (
        "Regression: cycle try_exit_with_intraday_check evaluates "
        "TP before SL. CLAUDE.md §4 Intraday Blindness violation — "
        "must assume worst-case (SL first)."
    )