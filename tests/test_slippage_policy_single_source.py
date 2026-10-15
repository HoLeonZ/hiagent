"""§4 滑点策略单源守卫（审计 P1-B，2026-10-15）。

CLAUDE.md §4: 执行滑点必须建模为 ATR × 参与率 的函数,禁用 flat rate。

审计发现:四个引擎**各自内联重算**了同一行
`atr_pct × participation × atr_slip_scale`,而 `core.dual_price.atr_slippage()`
虽已存在却**从未被任何引擎调用** —— §4 条款"已实现但不可达",§6 单源形同虚设。
其中 `short_reversal` 还漏了与 static 滑点取 max 的分支(与另外三引擎不一致)。

本文件锁定:
  1. 唯一口径 `effective_slippage = max(static, atr × participation × scale)`
     及其退化情形。
  2. 四个引擎都必须经该函数取滑点。
  3. 引擎源码里不得再出现内联的 `participation × atr_slip_scale` 乘积
     （即公式的副本）。这条是"单源"的可执行定义 —— 仅靠约定挡不住下一次复制。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.dual_price import atr_slippage, effective_slippage

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_SOURCES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "replay_broker.py",
}


# ---------------------------------------------------------------------------
# 1) 唯一口径
# ---------------------------------------------------------------------------


def test_effective_slippage_is_max_of_static_and_atr_component() -> None:
    atr_pct, participation, scale = 0.03, 0.2, 1.0
    atr_component = atr_pct * participation * scale  # 0.006
    assert effective_slippage(0.0, atr_pct, participation, scale) == pytest.approx(atr_component)
    # static 更大时取 static
    assert effective_slippage(0.01, atr_pct, participation, scale) == pytest.approx(0.01)
    # static 更小时取 atr 分量
    assert effective_slippage(0.001, atr_pct, participation, scale) == pytest.approx(atr_component)


def test_effective_slippage_degenerate_cases_match_old_inline_behaviour() -> None:
    """scale=0(出厂配置)/ 参与率 0 / atr 非正 → 0,与旧内联逻辑一致。"""
    assert effective_slippage(0.0, 0.03, 0.2, 0.0) == 0.0
    assert effective_slippage(0.0, 0.03, 0.0, 1.0) == 0.0
    assert effective_slippage(0.0, 0.0, 0.2, 1.0) == 0.0
    assert effective_slippage(0.0, -0.01, 0.2, 1.0) == 0.0
    # 有 static 时,退化情形仍应保留 static
    assert effective_slippage(0.002, 0.0, 0.2, 1.0) == pytest.approx(0.002)


def test_atr_component_helper_unchanged() -> None:
    """atr_slippage 仍是 ATR 分量本身(不含 static),供 effective_slippage 组合。"""
    assert atr_slippage(0.03, 0.2, 1.0) == pytest.approx(0.006)
    assert atr_slippage(0.03, 0.2, 0.0) == 0.0


# ---------------------------------------------------------------------------
# 2) 四引擎必须经单源
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine,path", sorted(ENGINE_SOURCES.items()))
def test_engine_routes_slippage_through_core(engine: str, path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "effective_slippage(" in src, (
        f"§4/§6: {engine} 未经过 core.dual_price.effective_slippage 取滑点 —— "
        "滑点策略必须单源"
    )


@pytest.mark.parametrize("engine,path", sorted(ENGINE_SOURCES.items()))
def test_engine_has_no_inline_slippage_formula_copy(engine: str, path: Path) -> None:
    """公式本体不得在引擎里再出现一份副本。

    旧内联形式为 `<atr> * participation * <scale>`。允许的写法只有经
    `effective_slippage(...)` 取值。
    """
    src = path.read_text(encoding="utf-8")
    # 去掉注释行,避免把说明文字里的公式当成副本
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    pattern = re.compile(
        r"\*\s*participation\s*\*\s*(?:self\.(?:p\.)?)?atr_slip_scale"
    )
    m = pattern.search(code)
    assert m is None, (
        f"§6: {engine} 源码里仍有内联的滑点公式副本 "
        f"({code[max(0, m.start()-40):m.end()+20]!r}) —— 应改为调用 "
        "core.dual_price.effective_slippage"
    )
