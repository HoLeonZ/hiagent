"""§4 滑点标定值必须「显式声明」守卫（审计 P1-B2，2026-10-15）。

背景：CLAUDE.md §4 强制滑点建模为 ATR × 参与率 的函数。审计实测四引擎的成交价
恒等于 bar 开盘价 —— 因为处处写作 `p.get("atr_slip_scale", 0.0)`：
**「没有声明」与「声明为 0」完全无法区分**,于是缺口靠沉默存在,没有报错、没有
日志、没有断言。这正是「已实现但不可达」,也是审计在 §3 `signal_price_domain`
上批评过的同一形态(修复做成可选开关、默认值仍是违规值)。

现在:缺声明 → `SlippagePolicyUndeclared` fail-fast;出厂 preset 一律显式写下
`SLIP_NONE_ACKNOWLEDGED`(= 0.0,"已知缺口"的确认值),使缺口**被枚举、可审计**。

本文件锁定:
  1. 解析器语义(缺声明抛错、值可解析、非法值抛错)。
  2. **全部出厂 preset 都已显式声明**(100 个 + cycle 的 1 个)。
  3. 引擎确实经解析器取值(而非 `p.get(..., 0.0)`)—— 用源码断言兜住新写的调用点。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.dual_price import SlippagePolicyUndeclared, resolve_atr_slip_scale

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_FILES = {
    "chase_up.backtest": REPO_ROOT / "chase_up" / "backtest.py",
    "chase_up.backtrader_engine": REPO_ROOT / "chase_up" / "backtrader_engine.py",
    "uptrend_pullback.backtest": REPO_ROOT / "uptrend_pullback" / "backtest.py",
    "uptrend_pullback.backtrader_engine": REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    "short_reversal.engine": REPO_ROOT / "short_reversal" / "engine.py",
    "cycle_price_action.backtest": REPO_ROOT / "cycle_price_action" / "backtest.py",
}


# ---------------------------------------------------------------------------
# 1) 解析器语义
# ---------------------------------------------------------------------------


def test_undeclared_slippage_fails_fast() -> None:
    with pytest.raises(SlippagePolicyUndeclared, match="atr_slip_scale"):
        resolve_atr_slip_scale({}, "no_such_declaration")


def test_declared_value_is_returned_as_float() -> None:
    assert resolve_atr_slip_scale({"atr_slip_scale": 0.0}, "p") == 0.0
    assert resolve_atr_slip_scale({"atr_slip_scale": 2}, "p") == 2.0


def test_unparseable_declaration_fails_fast() -> None:
    with pytest.raises(SlippagePolicyUndeclared):
        resolve_atr_slip_scale({"atr_slip_scale": "not-a-number"}, "p")


# ---------------------------------------------------------------------------
# 2) 全部出厂 preset 必须显式声明
# ---------------------------------------------------------------------------


def _preset_registries() -> list[tuple[str, dict]]:
    out = []
    for name, mod_name in (
        ("chase_up", "chase_up.presets"),
        ("uptrend_pullback", "uptrend_pullback.presets"),
        ("short_reversal", "short_reversal.presets"),
        ("cycle_price_action", "cycle_price_action.presets"),
    ):
        mod = __import__(mod_name, fromlist=["*"])
        reg = getattr(mod, "PRESETS", None)
        if reg:
            out.append((name, reg))
        else:
            single = getattr(mod, "PRESET_V1", None)
            if single is not None:
                out.append((name, {"PRESET_V1": single}))
    return out


def test_every_shipped_preset_declares_slippage_scale() -> None:
    total = 0
    for engine, reg in _preset_registries():
        missing = [k for k, v in reg.items() if "atr_slip_scale" not in v]
        assert not missing, (
            f"§4 VIOLATION: {engine} 的 preset 未显式声明 atr_slip_scale: "
            f"{missing[:5]}{'...' if len(missing) > 5 else ''} "
            "(共 %d 个)" % len(missing)
        )
        for k, v in reg.items():
            assert resolve_atr_slip_scale(v, f"{engine}:{k}") is not None
        total += len(reg)
    assert total >= 100, f"preset 总数异常(只找到 {total} 个)"


def test_acknowledged_value_is_documented_not_magic() -> None:
    """出厂值必须是命名常量(可审计),而不是散落的字面量 0.0。

    这条不作强制(模块未必导出常量名),但若导出则必须等于 0.0 —— 防止有人把
    「确认值」悄悄改成非零而无人注意。
    """
    for _, mod_name in (("chase_up", "chase_up.presets"),
                        ("short_reversal", "short_reversal.presets"),
                        ("cycle_price_action", "cycle_price_action.presets")):
        mod = __import__(mod_name, fromlist=["*"])
        if hasattr(mod, "SLIP_NONE_ACKNOWLEDGED"):
            assert mod.SLIP_NONE_ACKNOWLEDGED == 0.0, (
                f"{mod_name}.SLIP_NONE_ACKNOWLEDGED 被改成 "
                f"{mod.SLIP_NONE_ACKNOWLEDGED!r} —— 那是一个**研究决策**,"
                "不是可以随手改的常量"
            )


# ---------------------------------------------------------------------------
# 3) 引擎必须经解析器取值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,path", sorted(ENGINE_FILES.items()))
def test_engine_resolves_slippage_through_the_single_source(label: str, path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "resolve_atr_slip_scale(" in src, (
        f"§4 VIOLATION: {label} 未经 core.dual_price.resolve_atr_slip_scale 取滑点 —— "
        "静默默认会重新打开「未声明 vs 声明为 0 不可区分」的缺口"
    )
    assert 'atr_slip_scale", 0.0' not in src, (
        f"§4 VIOLATION: {label} 仍有 `atr_slip_scale\", 0.0` 静默默认"
    )
