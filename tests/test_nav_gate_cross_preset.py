"""§2 NAV Gate 跨 preset plumbing 审计 (Tick 37)。

CLAUDE.md §2 Capital Determinism: NAV-floor cash gate 是 fail-safe
机制, 防止多仓策略在反复 gap-down 击穿 SL 后继续 all-in 累积亏损
直到穿仓 0。

audit_tick = 37
ledger_version = 2026-09-23 增量 (§2)

**核心发现 (FRESH 2026-09-23):**

A. **3 engines 用 module-level 常量, NOT preset-plumbed**:
   - chase_up/portfolio.py:64 `NAV_GATE_RATIO = 0.05`
   - uptrend_pullback/portfolio.py:48 `NAV_GATE_RATIO = 0.05`
   - short_reversal/replay_strategy_v3.py:73 `min_cash_ratio=0.05`
     (engine.py:189 通过 `cfg.get("min_cash_ratio", 0.05)` 从 preset
     读, 但 replay_strategy_v3 默认仍是 hardcoded 0.05)
   - cycle_price_action: 没有 NAV Gate (per [[cycle-nav-gate-missing]])

B. **simulate_portfolio 签名不接受 nav_gate_ratio**:
   - chase_up/portfolio.py:133 simulate_portfolio(...) 无 nav_gate_ratio 参数
   - uptrend_pullback/portfolio.py:117 simulate_portfolio(...) 同样无
   - backtrader_engine.py:188-202 (chase) / :233-256 (uptrend) call site
     都不传 nav_gate_ratio

C. **Presets 不声明 nav_gate_ratio**:
   - chase_up/presets.py 无 nav_gate_ratio / min_cash_ratio key
   - uptrend_pullback/presets.py 同样无
   - 所有 preset 共享同一个 0.05 hardcoded 值

D. **chapter §0/§6 Meta-audit 175th dropped key**:
   - Tick 32 发现 174 个 preset keys 被静默丢弃
   - NAV_GATE_RATIO 是第 175 个 — preset 想开 0.10 / 0.03 都无效,
     永远 0.05

本文件验证:
- 5 RED (plumbing 缺失)
- 2 PASS baseline (short_reversal 接受 preset, cycle 缺全 NAV gate)
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Module-level constant detection
# ---------------------------------------------------------------------------


def _scan_for_module_constant(file: Path, const_name: str) -> int | None:
    """Return line number if module-level `NAME = <number>` found."""
    text = file.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^{re.escape(const_name)}\s*=\s*([\d.]+)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m:
        return text[: m.start()].count("\n") + 1
    return None


def test_chase_up_nav_gate_ratio_is_hardcoded_constant() -> None:
    """§2 RED: chase_up NAV_GATE_RATIO 是 module-level 常量.

    chase_up/portfolio.py:64 定义 `NAV_GATE_RATIO = 0.05` 在 module
    顶部. 所有 preset 共享这一个值, 即使 preset 想用 0.03 (更激进)
    或 0.10 (更保守) 都无效.
    """
    portfolio = Path("chase_up/portfolio.py")
    line = _scan_for_module_constant(portfolio, "NAV_GATE_RATIO")
    if line is None:
        return  # 如果已重构, PASS
    raise AssertionError(
        f"GAP CAPTURED: chase_up/portfolio.py:{line} defines "
        "NAV_GATE_RATIO as module-level constant. Preset cannot "
        "override. §2 violation — same gate applies to all 22 presets "
        "regardless of declared risk appetite. GREEN fix: add "
        "nav_gate_ratio parameter to simulate_portfolio() and pass "
        "from preset (default 0.05 for back-compat)."
    )


def test_uptrend_pullback_nav_gate_ratio_is_hardcoded_constant() -> None:
    """§2 RED: uptrend_pullback NAV_GATE_RATIO 是 module-level 常量."""
    portfolio = Path("uptrend_pullback/portfolio.py")
    line = _scan_for_module_constant(portfolio, "NAV_GATE_RATIO")
    if line is None:
        return
    raise AssertionError(
        f"GAP CAPTURED: uptrend_pullback/portfolio.py:{line} defines "
        "NAV_GATE_RATIO as module-level constant. Same as chase_up — "
        "preset cannot override."
    )


def test_short_reversal_replay_strategy_min_cash_hardcoded() -> None:
    """§2 RED: short_reversal/replay_strategy_v3.py:73 hardcoded 0.05.

    engine.py:189 does `cfg.get("min_cash_ratio", 0.05)` so the preset
    value CAN be passed — but replay_strategy_v3.py:73 default param
    is hardcoded 0.05. If a preset omits min_cash_ratio, the engine
    silently uses 0.05 instead of any preset-declared value.
    """
    replay = Path("short_reversal/replay_strategy_v3.py")
    text = replay.read_text(encoding="utf-8")
    if "min_cash_ratio=0.05" not in text:
        return
    line_no = text[: text.index("min_cash_ratio=0.05")].count("\n") + 1
    raise AssertionError(
        f"GAP CAPTURED: short_reversal/replay_strategy_v3.py:{line_no} "
        "uses hardcoded `min_cash_ratio=0.05` as default param. "
        "engine.py:189 does `cfg.get('min_cash_ratio', 0.05)` but if "
        "preset declares 0.10 it WILL be passed — but if preset omits "
        "the key, silently falls back to 0.05. Forward-defense: should "
        "raise on missing preset key, not silently default."
    )


def test_simulate_portfolio_accepts_nav_gate_ratio_param() -> None:
    """§2 RED: chase_up + uptrend simulate_portfolio 签名缺 nav_gate_ratio.

    Currently both signatures are preset-blind to NAV gate threshold.
    Adding `nav_gate_ratio: float = 0.05` would be back-compat.
    """
    violations: list[tuple[str, str]] = []

    for engine, path in [
        ("chase_up", "chase_up/portfolio.py"),
        ("uptrend_pullback", "uptrend_pullback/portfolio.py"),
    ]:
        p = Path(path)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if "def simulate_portfolio(" not in text:
            continue

        # Find the def line and inspect signature until first `:` at depth 0
        start = text.index("def simulate_portfolio(")
        # Skip to next top-level `:` (signature end)
        sig_end = text.find(":\n", start)
        if sig_end == -1:
            continue
        sig = text[start:sig_end]

        # Look for any param named nav_gate_ratio (case-insensitive)
        if not re.search(r"\bnav_gate_ratio\b", sig, re.IGNORECASE):
            # Also accept min_cash_ratio as alternative naming
            if not re.search(r"\bmin_cash_ratio\b", sig, re.IGNORECASE):
                violations.append((engine, path))

    assert not violations, (
        "GAP CAPTURED: simulate_portfolio() signature does NOT accept "
        "nav_gate_ratio (or min_cash_ratio). Preset NAV gate threshold "
        "is unreachable. Add nav_gate_ratio: float = 0.05 for "
        "back-compat:\n"
        + "\n".join(f"  - {e}: {p}" for e, p in violations)
    )


def test_backtrader_engine_call_site_passes_nav_gate_ratio() -> None:
    """§2 RED: backtrader_engine.py call site 不传 nav_gate_ratio.

    chase_up/backtrader_engine.py:188-202 and
    uptrend_pullback/backtrader_engine.py:233-256 — even if
    simulate_portfolio accepts nav_gate_ratio, call site must also
    plumb it from preset. Currently neither does.
    """
    violations: list[tuple[str, str]] = []

    for engine, path in [
        ("chase_up", "chase_up/backtrader_engine.py"),
        ("uptrend_pullback", "uptrend_pullback/backtrader_engine.py"),
    ]:
        p = Path(path)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        # Find simulate_portfolio(...) call and ensure nav_gate_ratio is passed
        if "simulate_portfolio(" not in text:
            continue

        # Find each call and check if nav_gate_ratio appears within ~500 chars
        for m in re.finditer(r"simulate_portfolio\(", text):
            start = m.start()
            # Slice up to ~500 chars after call to capture kwargs
            window = text[start:start + 800]
            # Find balanced close
            depth = 0
            end = start
            for j in range(start, len(text)):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            call = text[start:end]
            if not re.search(r"\bnav_gate_ratio\b", call):
                if not re.search(r"\bmin_cash_ratio\b", call):
                    violations.append((engine, path))
                    break

    assert not violations, (
        "GAP CAPTURED: backtrader_engine.py call site does NOT pass "
        "nav_gate_ratio to simulate_portfolio. Even if signature is "
        "updated, the call site must plumb from preset:\n"
        + "\n".join(f"  - {e}: {p}" for e, p in violations)
    )


# ---------------------------------------------------------------------------
# PASS baselines
# ---------------------------------------------------------------------------


def test_short_reversal_engine_accepts_min_cash_ratio_from_preset() -> None:
    """§2 PASS baseline: short_reversal/engine.py:189 passes cfg value.

    `cfg.get("min_cash_ratio", 0.05)` means preset-declared values
    flow to replay_strategy_v3.min_cash_ratio. The 0.05 default is
    fine for presets that don't declare the key.

    However replay_strategy_v3.py:73 still hardcodes 0.05 as the
    param default, which silently masks missing-preset-key cases
    (see test_short_reversal_replay_strategy_min_cash_hardcoded).
    """
    engine_path = Path("short_reversal/engine.py")
    if not engine_path.exists():
        return
    text = engine_path.read_text(encoding="utf-8")
    assert "min_cash_ratio" in text and "cfg.get" in text, (
        "Regression: short_reversal/engine.py no longer plumbs "
        "min_cash_ratio from preset."
    )


def test_cycle_price_action_lacks_nav_gate_documented() -> None:
    """§2 PASS baseline: cycle_price_action has NO NAV gate (documented gap).

    Per [[cycle-nav-gate-missing]], cycle is the only engine without
    §2 NAV gate. This is a known forward-defense item, not a regression.
    """
    portfolio = Path("cycle_price_action/portfolio.py")
    if not portfolio.exists():
        return
    text = portfolio.read_text(encoding="utf-8")
    has_nav_gate = bool(
        re.search(r"\bNAV_GATE\b|\bnav_gate_ratio\b|\bmin_cash_ratio\b", text)
    )
    # Document the gap (this is currently expected per memory note)
    assert not has_nav_gate, (
        "cycle_price_action unexpectedly has NAV gate — update "
        "[[cycle-nav-gate-missing]] memory note."
    )