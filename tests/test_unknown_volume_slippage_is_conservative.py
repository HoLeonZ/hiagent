"""§0/§4 守卫:成交量**未知**时,ATR 滑点不得退化成 0。

## 缺陷(审计 §8 #7b,2026-10-16 复核确认)

三个引擎在算滑点参与率时都写了同一条分支:

    if bar_vol > 0:  participation = min(1.0, size_pre_cap / bar_vol)
    else:            participation = 0.0        # ← NaN 也走这里

而 `core.dual_price.effective_slippage` 的口径是

    slip_eff = max(static_slippage, atr_pct × participation × scale)

取 `participation = 0.0` ⇒ `slip_eff = static_slippage`(本仓库多为 0)⇒
**恰好在流动性未知处把滑点归零**。方向与 §0(「Always assume the worst-case
scenario for market liquidity, **execution price**」/「Do not silently bypass」)
相反:拿不到成交量时,引擎反而假设自己毫无市场冲击。

触发条件是**面板无 volume 列**(LEFT JOIN miss ⇒ NaN,上面的量比闸门对 NaN 跳过);
`bar_vol <= 0`(零成交)在量比闸门已被拒单,到不了这一行。

修:`participation = 1.0` —— 模型定义域的上界(假设自己吃掉整根 bar 的成交量),
即该模型能表达的最坏冲击。

## 这是一条**潜伏**缺陷,据实说明

`atr_slip_scale` 是 opt-in,实测 **100 个 preset(22+3+75)全部为 0** ⇒ 整条 ATR
滑点路径在当前配置下不可达,修前修后**零漂移**。之所以仍然要修:§8#2 登记的
"ATR 滑点取值"是一个待决事项,而一旦有人按 §4 的要求把 `atr_slip_scale` 打开,
他会在**流动性未知**的地方拿到零滑点 —— 这是给那个决定预埋的坑,先填掉。
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_OPEN = 10.0
_ATR_PCT = 0.02
_SCALE = 0.5
# slip_eff = max(0, 0.02 × 1.0 × 0.5) = 0.01 ⇒ 成交价 = open × 1.01
_EXPECTED_SLIP = _ATR_PCT * 1.0 * _SCALE


def _panel_without_volume() -> pd.DataFrame:
    """**不含 volume 列**的面板 —— 这正是"成交量未知"的那条可达路径。"""
    days = [f"2025-01-{d:02d}" for d in range(1, 11)]
    rows = [
        {
            "thscode": "600001.SH", "date": pd.Timestamp(d),
            "open": _OPEN, "high": _OPEN, "low": _OPEN, "close": _OPEN,
            "raw_open": _OPEN, "raw_high": _OPEN, "raw_low": _OPEN,
            "raw_close": _OPEN, "raw_prev_close": np.nan,
        }
        for d in days
    ]
    return pd.DataFrame(rows)


def _entries() -> pd.DataFrame:
    import chase_up.signals as sg

    row = {c: np.nan for c in sg.ENTRY_COLS}
    row.update({
        "date": pd.Timestamp("2025-01-02"), "thscode": "600001.SH",
        "score": 9.9, "sub_signal_type": "fixture", "sig_close": _OPEN,
        "atr_pct": _ATR_PCT,
    })
    return pd.DataFrame([row])


def _run(*, atr_slip_scale: float = _SCALE):
    from chase_up.portfolio import simulate_portfolio

    trades, _ = simulate_portfolio(
        _entries(), _panel_without_volume(),
        tp_pct=9.9, sl_pct=0.99, max_hold=10_000,
        # equal + 2 个 slot ⇒ 单笔预算 = free_cash/2,否则 1% 滑点会把 all-in 订单
        # 顶出 free_cash 而被现金闸门拒单(那是另一条正确行为,会掩盖本用例)
        max_positions=2, position_sizing="equal",
        start_date="2025-01-01", end_date="2025-01-10",
        initial_capital=1_000_000.0,
        slippage=0.0, atr_slip_scale=atr_slip_scale,
        price_source_for_execution="raw_close",
    )
    return trades


def test_unknown_volume_still_pays_the_model_max_slippage() -> None:
    """§0/§4: 成交量未知 ⇒ 按参与率上界计滑点,而不是按 0 计。

    两向有牙:若 `else` 分支退回 `participation = 0.0`,成交价会等于 `open`,
    与下面期望的 `open × (1 + atr×1.0×scale)` 不符 ⇒ 必红。
    """
    trades = _run()
    assert len(trades) == 1, "夹具应恰好成交一笔(否则断言无从谈起)"
    got = float(trades.iloc[0]["entry_price"])
    expected = _OPEN * (1.0 + _EXPECTED_SLIP)
    assert got == pytest.approx(expected), (
        f"§0 VIOLATION: 成交量未知时的成交价 {got} != {expected} —— "
        "参与率被当成 0(无市场冲击),与 §0 的悲观默认相反"
    )
    assert got != pytest.approx(_OPEN), (
        "§0 VIOLATION: 成交量未知处滑点退化为 0(成交价 == 开盘价)"
    )


def test_known_nonzero_volume_path_is_unchanged() -> None:
    """正路径:有成交量时按 `min(1, size/vol)` 计 —— 上组改动不得波及它。"""
    panel = _panel_without_volume()
    panel["volume"] = 1e12  # 极大 ⇒ participation = size/vol ≈ 0 ⇒ 滑点 ≈ 0
    from chase_up.portfolio import simulate_portfolio

    trades, _ = simulate_portfolio(
        _entries(), panel,
        tp_pct=9.9, sl_pct=0.99, max_hold=10_000,
        max_positions=2, position_sizing="equal",
        start_date="2025-01-01", end_date="2025-01-10",
        initial_capital=1_000_000.0,
        slippage=0.0, atr_slip_scale=_SCALE,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    assert float(trades.iloc[0]["entry_price"]) == pytest.approx(_OPEN), (
        "成交量充裕时参与率≈0 是**正确**的,不应被改成上界"
    )


_ENGINES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
}


@pytest.mark.parametrize("engine,path", sorted(_ENGINES.items()))
def test_no_engine_zeroes_participation_when_volume_is_unknown(
    engine: str, path: Path
) -> None:
    """结构层:三个引擎都不得再写 `participation = 0.0`。"""
    src = path.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "participation = 0.0" not in code, (
        f"§0 VIOLATION {engine}: 成交量未知处又把参与率归零 —— "
        "滑点会在流动性最不确定的地方消失"
    )
    assert "participation = 1.0" in code, (
        f"{engine}: 期望在成交量未知处取参与率上界 1.0"
    )
    ast.parse(src)  # 顺带确认文件可解析
