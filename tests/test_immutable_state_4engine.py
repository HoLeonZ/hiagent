"""§0 Immutable State — In-Place State Mutation Audit (Tick 69).

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states
   as append-only."

Per coding-style.md (immutability mandate):
  "Never mutate existing objects or collections. Create new instances.
   Python: use @dataclass(frozen=True), tuples, frozenset."

**核心发现 (FRESH 2026-09-23):**

A. **§0 Immutable State rationale**:
   - Historical data is append-only (no retroactive edits)
   - Portfolio state is append-only (no equity curve re-writing)
   - Mutating shared state leads to:
     - Order-dependent test results
     - Hidden state leaking between functions
     - Loss of audit trail (which value came from which call)

B. **Genuine §0 violation patterns (focus of Tick 69)**:
   - `self.<attr>.pop()` — removes from internal state (concerning)
   - `self.<attr>.clear()` — clears internal state (concerning)
   - `self.<attr>.update({k: v})` — replaces state entries
   - `self.<attr>.add(x)` / `.discard(x)` — set mutations

C. **NOT a §0 violation (necessary accumulation)**:
   - `self.trades.append(...)` — building output list (standard pattern)
   - `self.results.append(...)` — accumulating results
   - These are append-only output accumulation, not state mutation

D. **Why this matters**:
   - §0 Immutability: state must be derivable, not edited
   - `pop()` / `clear()` / `update()` change EXISTING state, losing
     history
   - If portfolio state is mutated in place:
     - Test isolation breaks (state leaks between tests)
     - Reproducibility broken (initial state different per run)
     - Audit trail lost

E. **Detector strategy (refined after iteration 1)**:
   - Iteration 1: flagged `.append()` → 7 false REDs (necessary accumulation)
   - Iteration 2 (current): focus on TRUE state-mutating methods only:
     `.pop()`, `.clear()`, `.update()`, `.discard()`
   - AST scan: `self.<attr>.<method>(...)` where method is in
     STATE_MUTATING_METHODS

F. **Tick 69 expected results**:
   - 4 PASS baselines: each engine's Portfolio uses fresh state OR
     append-only accumulation (no pop/clear/update on self.*)
   - 0 RED expected after iteration 2 refinement
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production hot-path files per engine
PRODUCTION_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "portfolio.py",
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    ],
}


# TRUE state-mutating methods (excluding append-only accumulation)
STATE_MUTATING_METHODS = (
    "pop",
    "clear",
    "update",
    "discard",
    "remove",
)

#: §0 (audit 2026-10-15): **瞬态控制状态** —— 承载"待办意图"的属性(挂单队列),
#: 既不是历史数据,也不是组合状态,故不受 §0 的 append-only 约束。
#: 从队列里取走一条已处理/已作废的意图恰恰是**正确**行为:§4 要求涨停封板不得成交、
#: IOC 未成交部分必须取消 —— 那在实现上就是"从挂单队列移除"。历史记录(成交列表)
#: 不受影响:作废的挂单本来就不该进入 trade log。
#:
#: 这个名单必须**极窄**。若把历史/组合状态(`positions` / `closed_trades` / `cash`)
#: 塞进来,本守卫就形同虚设 —— 故由
#: `test_transient_control_state_exemptions_stay_narrow` 钉住其规模与命名。
TRANSIENT_CONTROL_STATE = frozenset({"pending_entries"})


def _scan_self_mutation() -> dict[str, list[tuple[str, int, str, str]]]:
    """Scan production files for self.<attr>.<mutable_method>(...) calls.

    Returns dict[engine → list of (file, line, target_str, method_name)]
    """
    results: dict[str, list[tuple[str, int, str, str]]] = {}

    for engine, paths in PRODUCTION_FILES.items():
        violations: list[tuple[str, int, str, str]] = []

        for path in paths:
            if not path.exists():
                continue

            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                source_lines = source.splitlines()
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if not hasattr(node, "lineno"):
                    continue
                line = node.lineno

                if isinstance(node, ast.Call):
                    func_node = node.func
                    # Pattern: self.<attr>.<method>(...) or self.<attr>[key].<method>(...)
                    if isinstance(func_node, ast.Attribute):
                        if func_node.attr in STATE_MUTATING_METHODS:
                            # Check if receiver is self.<attr>
                            receiver = func_node.value
                            if isinstance(receiver, ast.Attribute):
                                if (
                                    isinstance(receiver.value, ast.Name)
                                    and receiver.value.id == "self"
                                ):
                                    snippet = (
                                        source_lines[line - 1].strip()
                                        if line <= len(source_lines)
                                        else ""
                                    )
                                    target_str = ast.unparse(receiver)
                                    # §0: 瞬态控制状态(挂单队列)不在 append-only
                                    # 约束的射程内 —— 见 TRANSIENT_CONTROL_STATE。
                                    if (
                                        target_str.split(".")[-1]
                                        in TRANSIENT_CONTROL_STATE
                                    ):
                                        continue
                                    violations.append(
                                        (
                                            str(path.relative_to(REPO_ROOT)),
                                            line,
                                            target_str,
                                            func_node.attr,
                                        )
                                    )

        results[engine] = violations

    return results


# ---------------------------------------------------------------------------
# PASS baselines: no self.<attr>.<mutable_method> in production hot paths
# ---------------------------------------------------------------------------


def test_chase_up_no_self_state_mutation() -> None:
    """§0 PASS baseline: chase_up Portfolio does not mutate self.* in place.

    Per CLAUDE.md §0: state must be append-only / immutable.
    Per coding-style.md: Python should use @dataclass(frozen=True),
    tuples, frozenset.

    This test REDs if Portfolio mutates self.positions / self.trades /
    self.cash via in-place method calls (.append/.extend/.update/etc).
    """
    results = _scan_self_mutation()
    chase = results["chase_up"]

    if chase:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: chase_up has "
            f"{len(chase)} self.<attr>.<mutable_method>() calls in "
            f"production hot paths.\n"
            f"Per CLAUDE.md §0: state must be append-only / immutable.\n"
            f"Per coding-style.md: use @dataclass(frozen=True) or "
            f"return new instances instead of in-place mutation.\n"
            f"Violations: {chase[:5]}"
        )


def test_uptrend_pullback_no_self_state_mutation() -> None:
    """§0 PASS baseline: uptrend_pullback Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    uptrend = results["uptrend_pullback"]

    if uptrend:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: uptrend_pullback has "
            f"{len(uptrend)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {uptrend[:5]}"
        )


def test_short_reversal_no_self_state_mutation() -> None:
    """§0 PASS baseline: short_reversal Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    short = results["short_reversal"]

    if short:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: short_reversal has "
            f"{len(short)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {short[:5]}"
        )


def test_cycle_price_action_no_self_state_mutation() -> None:
    """§0 PASS baseline: cycle_price_action Portfolio no self.* mutation."""
    results = _scan_self_mutation()
    cycle = results["cycle_price_action"]

    if cycle:
        raise AssertionError(
            f"§0 IMMUTABILITY VIOLATION: cycle_price_action has "
            f"{len(cycle)} self.<attr>.<mutable_method>() calls.\n"
            f"Per CLAUDE.md §0: state must be append-only.\n"
            f"Violations: {cycle[:5]}"
        )


def test_transient_control_state_exemptions_stay_narrow() -> None:
    """§0: 豁免名单必须**极窄**,且只含队列类状态。

    这条守的是**守卫本身**。给剧本记账/组合状态开一个"反正它会 pop"的口子极其容易,
    而那一刻起 `test_*_no_self_state_mutation` 就只剩仪式感了。故:
      (a) 名单规模有上界;
      (b) 名字必须像队列(否则说明有人把历史/组合状态混了进来)。
    """
    assert len(TRANSIENT_CONTROL_STATE) <= 3, (
        f"§0 豁免名单膨胀到 {len(TRANSIENT_CONTROL_STATE)} 项:"
        f"{sorted(TRANSIENT_CONTROL_STATE)} —— 它只该装队列类瞬态状态。"
    )
    for attr in TRANSIENT_CONTROL_STATE:
        assert any(tok in attr for tok in ("pending", "queue", "buffer")), (
            f"§0: {attr!r} 不像瞬态队列状态。历史/组合状态(positions / "
            "closed_trades / cash)不得进入豁免名单 —— 那会让本文件其余断言失效。"
        )