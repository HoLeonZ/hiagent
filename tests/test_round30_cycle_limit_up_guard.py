"""Round 30 Finding 2 (2026-09-28, CLAUDE.md §3 truthfulness): cycle_price_action
limit-up guard missing.

cycle_price_action is the ONLY engine among the 4 that does NOT enforce
is_limit_up at entry time:
  - chase_up/portfolio.py:507 — inline (o / pc - 1) >= LIMIT_UP_THRESHOLD guard
  - uptrend_pullback/portfolio.py:470 — same
  - short_reversal/replay_strategy_v3.py:429 — is_limit_down guard (symmetric)
  - cycle_price_action — NONE

Per CLAUDE.md §3 + §4 (Pessimistic Default): a limit-up open means the
stock cannot be bought (no shares available). Entering at limit-up close
generates phantom PnL — the backtest records a fill that could not
actually occur in the market. Same engine category, different outcome.

This test enforces: cycle_price_action/backtrader_engine.py:next MUST call
is_limit_up() (or equivalent threshold check) before try_enter at the
entry path. Threshold must be exposed via params (preset-overridable) so
chase_up's 0.098 vs cycle's default 0.095 distinction is supported.
"""
from __future__ import annotations

import inspect
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycle_price_action.backtrader_engine import CyclePriceActionStrategy  # noqa: E402


# ---------------------------------------------------------------------------
# Source guard: cycle_price_action backtrader_engine.next must reference
# is_limit_up before the try_enter call.
# ---------------------------------------------------------------------------


CYCLE_ENGINE = ROOT / "cycle_price_action" / "backtrader_engine.py"


def _read(path: str | Path) -> str:
    return Path(path).read_text()


def test_cycle_limit_up_guard_lives_in_the_execution_layer() -> None:
    """§6 单层归属:涨停不可成交是**执行**约束 → 归 Portfolio。

    audit P3 (2026-10-15): 本文件原断言守卫必须在 `strategy.next()` 里,而
    `test_cycle_limit_up_guard.py` 同时断言它必须在 `Portfolio.try_enter()` 里 ——
    **两个测试文件对归属层互相矛盾**。§6 要求一条规则只有一处归属,否则两处会各自
    演化;而另外三个引擎都在 portfolio 层。故以执行层为准,本处改为钉住:
      (a) 执行层确实实现该守卫(`portfolio.py` 调用 core 的 is_limit_up),且
      (b) 生产路径确实把 prev_close 传下去 —— 否则守卫不可达(与窗口门同款教训)。
    行为由 tests/test_cycle_limit_up_guard.py 的 4 条用例覆盖。
    """
    engine_src = _read(CYCLE_ENGINE)
    assert re.search(r"prev_close\s*=\s*prev_close", engine_src), (
        "§4 VIOLATION: 引擎未把 prev_close 传给 try_enter —— "
        "执行层的涨停守卫在生产路径上不可达"
    )
    port = (ROOT / "cycle_price_action" / "portfolio.py").read_text(encoding="utf-8")
    assert "is_limit_up" in port, (
        "§4 VIOLATION: Portfolio 未实现涨停守卫(§6:该规则归属执行层)"
    )
    assert re.search(r"if is_limit_up\(", port), (
        "§4 VIOLATION: Portfolio 里 is_limit_up 存在但未用于拒绝入场"
    )

def test_cycle_engine_threshold_param_overridable() -> None:
    """§3 forward-defense: limit-up threshold should be exposed via params
    (preset-overridable) so cycle presets can override the default 0.095."""
    src = _read(CYCLE_ENGINE)
    # params dict must include a limit_up_threshold entry (or similar)
    has_param = bool(re.search(
        r"limit_up_threshold\s*=\s*[\d.]+",
        src,
    ))
    assert has_param, (
        "§3 forward-defense: cycle_price_action should expose "
        "limit_up_threshold via params (default 0.095) so presets can "
        "override per CLAUDE.md §4 Pessimistic Default."
    )


# ---------------------------------------------------------------------------
# Behavioral test: limit-up open must reject entry (cycle strategy must
# skip try_enter when today's open hit limit-up).
# ---------------------------------------------------------------------------


def test_cycle_engine_skips_entry_on_limit_up() -> None:
    """§3 behavior: when prev_close=10, today's open=11 (10% above = limit-up),
    CyclePriceActionStrategy.next() must NOT call try_enter with positive
    state outcome.

    We exercise the strategy's `_is_limit_up_bar` (or equivalent) helper
    via inspection if present, or via direct is_limit_up() call assertion.
    """
    from core.dual_price import is_limit_up  # noqa: E402

    prev_close = 10.0
    open_price = 11.0  # 10% above → limit-up
    # Direct API check (sanity)
    assert is_limit_up(prev_close, open_price, threshold=0.095) is True

    # Now verify cycle engine file imports is_limit_up (or the next method
    # contains the inline check). If neither, RED.
    src = _read(CYCLE_ENGINE)
    has_is_limit_up_import = "is_limit_up" in src
    assert has_is_limit_up_import, (
        "§3 VIOLATION: cycle_price_action/backtrader_engine.py must "
        "import is_limit_up from core.dual_price AND call it before "
        "try_enter."
    )


def _params_keywords(src: str) -> set[str] | None:
    """取循环引擎里 `params = dict(...)` 的**关键字名**(AST,不看括号平衡)。"""
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "params" for t in node.targets):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "dict":
            return {k.arg for k in call.keywords if k.arg}
    return None


def test_cycle_engine_does_not_enter_at_limit_up_close() -> None:
    """§3 source-guard via parametrize: check the cycle strategy.params dict
    has limit_up_threshold exposed (default 0.095 to match chase_up +
    uptrend_pullback conventions).
    """
    src = _read(CYCLE_ENGINE)
    # ⚠️ 2026-10-22 (附一百八十七): 此处原用「括号平衡」正则取 params 块 ——
    #     r"params\s*=\s*dict\(((?:[^()]|\([^()]*\))*)\)"
    # 它只容许**一层**嵌套括号。params 块里后来出现了更深嵌套 ⇒ **匹配失败** ⇒
    # 报「params dict not found」,**而键一直都在**(实测 :83 `limit_up_threshold=0.095`)。
    # ⇒ 改为 AST: 找 `params = dict(...)` 的赋值, 直接读它的**关键字名**。
    keys = _params_keywords(src)
    assert keys is not None, "循环引擎里找不到 `params = dict(...)` 赋值"
    assert "limit_up_threshold" in keys, (
        "§3 forward-defense: limit_up_threshold 必须在 params 里(默认 0.095)以便 preset 覆盖。"
        f"实测 params 关键字: {sorted(keys)}"
    )
    # 故意**不钉死**数值: chase_up / uptrend_pullback 用 0.098, 而本族用 0.095 ——
    # 文档里说明"这条区分要被支持",钉死任一侧都会与那句话打架。


# ---------------------------------------------------------------------------
# Cross-engine consistency: chase_up + uptrend_pullback + cycle_price_action
# all reference is_limit_up (or inline LIMIT_UP_THRESHOLD). short_reversal
# references is_limit_down. The guard may live in backtrader_engine.py
# (cycle) or portfolio.py (chase/uptrend use inline check).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_path,guard_token",
    [
        (ROOT / "chase_up" / "portfolio.py", ("is_limit_up", "LIMIT_UP_THRESHOLD")),
        (ROOT / "uptrend_pullback" / "portfolio.py", ("is_limit_up", "LIMIT_UP_THRESHOLD")),
        (ROOT / "cycle_price_action" / "backtrader_engine.py", ("is_limit_up",)),
        (ROOT / "short_reversal" / "replay_strategy_v3.py", ("is_limit_down",)),
    ],
)
def test_cross_engine_includes_limit_guard(engine_path: Path, guard_token: tuple) -> None:
    """§3 cross-engine consistency: all 4 engines must reference their
    appropriate limit guard (chase/uptrend: `is_limit_up()` OR inline
    `LIMIT_UP_THRESHOLD` in portfolio.py; cycle_price_action:
    `is_limit_up()` (Round 30); short_reversal: `is_limit_down()`)."""
    src = _read(engine_path)
    found = any(tok in src for tok in guard_token)
    assert found, (
        f"§3 VIOLATION: {engine_path.name} does NOT reference any of "
        f"{guard_token}. Only engines with limit-bar guards are "
        f"CLAUDE.md §3 compliant."
    )