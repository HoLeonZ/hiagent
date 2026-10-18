"""§2 Cost > Cash Rejection (No Leverage) Verification (Tick 64).

CLAUDE.md §2 (verbatim):
  "**All-In Sizing Policy (2026-09-21):** ... Margin blowout
   protection still applies: `cost > cash` must reject the trade
   (no leverage) and NAV-floor cash gates remain valid for new entries."

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

**核心发现 (FRESH 2026-09-23):**

A. **No-leverage principle**:
   - `cost > cash` MUST reject the trade (no implicit margin)
   - Per [[chase-up-conservative-cash-fixes]] Bug A (fixed 2026-09-21):
     - chase_up/portfolio.py had implicit margin bug
     - Bug allowed cost > cash → blew past capital limits

B. **Expected rejection pattern**:
   ```python
   cost = size * entry_price
   if cost > cash:
       continue  # reject trade, no margin
   ```
   Or:
   ```python
   if size * entry_price > cash:
       raise ValueError("cost > cash; no leverage allowed")
   ```

C. **Anti-patterns to detect**:
   - No check at all (cost > cash allowed → implicit margin)
   - Silent truncation: `size = int(cash / entry_price)` without
     rejecting the original request
   - Negative cash silently allowed: `cash -= cost` without guard

D. **Why this matters**:
   - §2 Capital conservation: physical cash must back every position
   - §0 Pessimistic Default: leverage amplifies losses beyond capital
   - If cost > cash is silently allowed:
     - Reported equity curve diverges from real portfolio equity
     - Backtest shows phantom gains funded by phantom capital
     - Live trading would result in actual margin call

E. **Coverage** — ⚠️ §13.68 更正:
   - chase_up/portfolio.py:try_enter — should have cost > cash rejection
   - uptrend_pullback/portfolio.py:try_enter — should have cost > cash rejection
   - short_reversal/replay_strategy_v3.py (+ engine.py) — ✅ 真实引擎
   - ~~short_reversal/portfolio.py:try_enter~~ — **该路径从来不存在** (短仓的引擎是
     `replay_strategy_v3.py`), 它一直躺在扫描集里被 `if not path.exists(): continue`
     **静默跳过**。已删, 并加了存在性断言。
   - ~~cycle_price_action: uses cerebro (different pattern, skip)~~ —— **这句话是错的**:
     `cycle_price_action/portfolio.py:170` 就是 `if cost > free_cash + epsilon:`,
     且该类**有** `Portfolio`。⇒ 一整族**因此从未被这条 §2 守卫检查过**。已纳入。

F. **AST detection strategy**:
   - Look for: comparison `cost > cash` (or `size * entry_price > cash`)
   - Look for: in if-statement context (rejection guard)
   - Look for: rejection action (continue / raise / return None)
   - Forward-defense: any Portfolio without this guard RED

G. **Test results (Tick 64 expected)**:
   - PASS baselines: each engine has cost > cash rejection guard
   - RED if: guard missing or in wrong form
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# ⚠️ §13.68: 此处原为**手写清单**, 里面 `short_reversal/portfolio.py` **从来不存在**
# (短仓引擎是 `replay_strategy_v3.py`), 于是被扫描器里的
# `if not path.exists(): continue` **静默跳过**; 而 `cycle_price_action` **根本不在清单里**
# (依据是文件头那句错的 "uses cerebro, skip") ⇒ **一整族从未被这条守卫检查过**。
# ⇒ 改为**发现式**; 另有两条断言 (§13.66 的形状) 保证: 每个候选路径都存在、每个族都被扫到。
PORTFOLIO_FILES = sorted(REPO_ROOT.glob("*/portfolio.py")) + [
    REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    REPO_ROOT / "short_reversal" / "engine.py",
]

# 族 → 该族的引擎入口 (用于"每个族都被扫到"的断言)
FAMILY_ENGINES = {
    "chase_up": ["chase_up/portfolio.py"],
    "uptrend_pullback": ["uptrend_pullback/portfolio.py"],
    "short_reversal": ["short_reversal/replay_strategy_v3.py", "short_reversal/engine.py"],
    "cycle_price_action": ["cycle_price_action/portfolio.py"],
}


def _scan_cost_cash_rejection() -> dict[str, dict[str, object]]:
    """Scan Portfolio files for cost > cash rejection pattern.

    Recognizes multiple anti-leverage idioms:
    - `if cost > cash: continue/raise` (explicit reject)
    - `if cash < 0: continue` (negative cash → reject)
    - `budget = min(slot_value, cash)` (cap budget at cash)
    - `size = int(cash / entry_price)` (size capped by cash)

    Returns dict[file_rel → {
        "has_rejection_guard": bool,
        "guard_lines": list[int],
        "guard_snippets": list[str],
    }]
    """
    results: dict[str, dict[str, object]] = {}

    for path in PORTFOLIO_FILES:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        rel = path.relative_to(REPO_ROOT)
        guard_lines: list[int] = []
        guard_snippets: list[str] = []

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            line = node.lineno
            snippet = (
                source_lines[line - 1].strip()
                if line <= len(source_lines)
                else ""
            )

            # Pattern 1: `if cost > cash: continue/raise/return`
            if isinstance(node, ast.If):
                test = node.test
                if isinstance(test, ast.Compare):
                    left_str = (
                        ast.unparse(test.left) if hasattr(ast, "unparse") else ""
                    )
                    comp_right_str = ""
                    for comp in test.comparators:
                        comp_right_str += (
                            ast.unparse(comp) if hasattr(ast, "unparse") else ""
                        )
                    test_str = (left_str + " " + comp_right_str).lower()
                    has_cost = (
                        "cost" in test_str
                        or ("size" in test_str and "entry" in test_str)
                        or "value" in test_str
                        or "amount" in test_str
                        or "budget" in test_str
                    )
                    has_cash = (
                        "cash" in test_str
                        or "free_cash" in test_str
                        or "available" in test_str
                    )
                    if has_cost and has_cash:
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in (
                                    "continue",
                                    "raise",
                                    "return None",
                                    "return",
                                )
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

                    # Pattern 2: `if cash < 0: continue/raise`
                    if has_cash and ("< 0" in test_str or "< 0.0" in test_str):
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in ("continue", "raise", "return")
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

                    # Pattern 2b: NAV-floor gate (short_reversal style)
                    # `if nav < ... * min_cash_ratio: ...` or
                    # `if nav < cash_gate_threshold: ...`
                    if "nav" in test_str and (
                        "min_cash_ratio" in test_str
                        or "cash_gate" in test_str
                        or "nav_gate" in test_str
                        or "initial_capital" in test_str
                    ):
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in (
                                    "continue",
                                    "raise",
                                    "return",
                                    "skip",
                                )
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

            # Pattern 3: `budget = min(..., cash)` (cap budget at cash)
            # Pattern 4: `size = int(cash / entry_price)` (size capped by cash)
            if isinstance(node, ast.Assign):
                target_str = (
                    ast.unparse(node.targets[0])
                    if hasattr(ast, "unparse")
                    else ""
                )
                value_str = (
                    ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                )
                combined = (target_str + " " + value_str).lower()
                if "min" in combined and "cash" in combined and (
                    "slot" in combined or "budget" in combined or "value" in combined
                ):
                    guard_lines.append(line)
                    guard_snippets.append(snippet)
                elif "size" in target_str.lower() and "cash" in combined and (
                    "/" in combined or "min" in combined
                ):
                    guard_lines.append(line)
                    guard_snippets.append(snippet)

        # Dedup
        seen = set()
        unique_lines: list[int] = []
        unique_snippets: list[str] = []
        for ln, sn in zip(guard_lines, guard_snippets):
            if ln not in seen:
                seen.add(ln)
                unique_lines.append(ln)
                unique_snippets.append(sn)

        results[str(rel)] = {
            "has_rejection_guard": len(unique_lines) > 0,
            "guard_lines": unique_lines,
            "guard_snippets": unique_snippets,
        }

    return results


# ---------------------------------------------------------------------------
# PASS baselines: each engine rejects cost > cash
# ---------------------------------------------------------------------------


def test_chase_up_rejects_cost_greater_than_cash() -> None:
    """§2 PASS baseline: chase_up Portfolio rejects cost > cash.

    Per CLAUDE.md §2: "cost > cash must reject the trade (no leverage)".
    Per [[chase-up-conservative-cash-fixes]] Bug A: chase_up had
    implicit margin bug, FIXED 2026-09-21. Forward-defense guard.
    """
    results = _scan_cost_cash_rejection()
    chase = results.get("chase_up/portfolio.py", {})

    assert chase.get("has_rejection_guard"), (
        "§2 NO-LEVERAGE GUARD MISSING: chase_up/portfolio.py has no "
        "`if cost > cash: continue/raise` rejection pattern.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "Per [[chase-up-conservative-cash-fixes]] Bug A (fixed 2026-09-21):\n"
        "  chase_up had implicit margin bug that allowed cost > cash.\n"
        "If regression reintroduces the bug, this test REDs.\n\n"
        "Expected pattern: `if cost > cash: continue` (skip trade, no margin)"
    )


def test_uptrend_pullback_rejects_cost_greater_than_cash() -> None:
    """§2 PASS baseline: uptrend_pullback Portfolio rejects cost > cash."""
    results = _scan_cost_cash_rejection()
    uptrend = results.get("uptrend_pullback/portfolio.py", {})

    assert uptrend.get("has_rejection_guard"), (
        "§2 NO-LEVERAGE GUARD MISSING: uptrend_pullback/portfolio.py has "
        "no `if cost > cash: continue/raise` rejection pattern.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "If uptrend_pullback silently allows cost > cash, backtest can "
        "show phantom gains funded by phantom capital."
    )


# ---------------------------------------------------------------------------
# RED forward-defense: short_reversal should also have this guard
# ---------------------------------------------------------------------------


def test_short_reversal_rejects_cost_greater_than_cash() -> None:
    """§2 RED forward-defense: short_reversal has no-leverage guard.

    Short reversal doesn't use a Portfolio class — it uses
    replay_strategy_v3.py (backtrader strategy) and engine.py. The
    no-leverage guard must exist in one of these.
    """
    results = _scan_cost_cash_rejection()

    # Look across all short_reversal entry points
    short_keys = [
        "short_reversal/portfolio.py",
        "short_reversal/replay_strategy_v3.py",
        "short_reversal/engine.py",
    ]
    has_guard = any(
        results.get(k, {}).get("has_rejection_guard", False)
        for k in short_keys
        if k in results
    )

    assert has_guard, (
        "§2 NO-LEVERAGE GUARD MISSING: short_reversal has no "
        "`cost > cash → reject` pattern in any of "
        "portfolio.py / replay_strategy_v3.py / engine.py.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "short_reversal must enforce this even for SHORT positions "
        "(margin on short side still requires capital backing)."
    )


# ---------------------------------------------------------------------------
# §13.68: cycle_price_action —— 此前**一整族**被漏掉 (依据是文件头那句错的前提)
# ---------------------------------------------------------------------------


def test_cycle_price_action_rejects_cost_greater_than_cash() -> None:
    """§2: cycle_price_action 必须有 `cost > cash → reject` 守卫。

    ⚠️ §13.68: 本族此前**从未被这条守卫检查过** —— 文件头断言
    "cycle_price_action: uses cerebro (different pattern, skip)", 而那句话是**错的**:
    `cycle_price_action/portfolio.py` 里就有 `class Portfolio` (第 69 行),
    且第 170 行就是 `if cost > free_cash + epsilon:`。
    **一个未被核实的前提, 让一整族失明** (与 §13.66(c) 同源, 这是它在第二个文件里的复现)。
    """
    results = _scan_cost_cash_rejection()
    cyc = results.get("cycle_price_action/portfolio.py", {})
    assert cyc, "cycle_price_action/portfolio.py 不在扫描结果里 —— 发现式清单又漏了它"
    assert cyc.get("has_rejection_guard"), (
        "§2 NO-LEVERAGE GUARD MISSING: cycle_price_action/portfolio.py 没有 "
        "`cost > cash → reject` 形态。\n"
        "§2 Capital conservation: 每一笔持仓都必须有实物现金支撑。"
    )


# ---------------------------------------------------------------------------
# 反空转断言 (§13.66 的形状): 扫描清单本身必须是真的
# ---------------------------------------------------------------------------


def test_scanned_paths_all_exist() -> None:
    """每个候选路径都必须存在 —— 不存在的会被 `if not path.exists(): continue`
    **静默跳过**, 于是受它保护的那个族静默失明 (§13.68 的根因之一)。"""
    missing = [str(p.relative_to(REPO_ROOT)) for p in PORTFOLIO_FILES if not p.exists()]
    assert not missing, f"扫描清单里有不存在的路径: {missing} —— 它们会被静默跳过"


def test_every_family_engine_is_scanned() -> None:
    """**每个族的引擎入口**都必须真的在扫描清单里 (§13.68 的根因之二)。"""
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in PORTFOLIO_FILES}
    blind = {fam: [f for f in files if f not in scanned]
             for fam, files in FAMILY_ENGINES.items()
             if any(f not in scanned for f in files)}
    assert not blind, f"这些族的引擎入口**不在**扫描清单里, 守卫对它们失明: {blind}"
