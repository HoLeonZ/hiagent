r"""§2/§3 守卫:**四族的账务闭合** —— 此前**只有 `chase_up` 有判据**(附一百二十八)。

## 缺口

仓库里三个 closure 文件都是 **chase_up-only**:`test_per_trade_math_closure.py`
(`test_chase_up_per_trade_*`)、`test_gross_pnl_per_row_closure.py`(`test_chase_up_per_row_*`)、
以及 `test_nav_cash_ledger_invariants.py` 的端到端那条(注释明写"端到端:chase_up …")。
⇒ **同一批性质,另外三族没有输出侧判据** —— 正是本册反复记的"族内不对称"。

## 判据(两条,都是**逐位等式**,不留容差口子)

1. **逐笔闭合**:`net_pnl == gross_pnl − fees`(每笔);
2. **净值 ↔ 权益曲线一致**:`final == equity_curve` 末值。

## 实测读数(建成时,窗口 2026-02-02..2026-04-30)

| 族 | 成交 | 逐笔闭合违反 | final 与曲线末值之差 |
|---|---|---|---|
| `chase_up` | 9 | **0** | **0.00** |
| `uptrend_pullback` | 14 | **0** | **0.00** |
| `short_reversal` | 12 | **0** | **0.00** |

**顺带量掉的一条"疑似违反"**:`short_reversal` 的 `末值 − 初值 − Σnet_pnl = −8,338.72`。
**它不是缺陷**:该组**末笔 exit = 2026-05-06 > 窗口止 2026-04-30** ⇒ 期末**仍有持仓**,
而 `final_capital` 取的是**窗口末的净值**(含浮盈)—— `engine.py:228` 明写"必须用净值,不是总现金"。
chase/uptrend 那两组的末笔 exit 恰为窗口止日 ⇒ 全部平仓 ⇒ 差额 0.00。

## `cycle_price_action` 为什么不在本文件里(如实记)

它的 `TradeRecord` **只有 `pnl`**,**没有 `gross_pnl`/`fees`**;`BacktestResult` 也**没有权益曲线**
(只有 `trades` + `metrics`)。⇒ **输出侧无法验**逐笔闭合与净值一致 ——
**不是"已验证通过",是"在输出上不可验"**。要覆盖它得先让 cycle 的成交记录暴露成本分解
(那是 schema 变更,属**结果变更类**决定,不由本批做)。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import require_market_db

WINDOW = ("2026-02-02", "2026-04-30")
CASES = [
    ("chase_up", "chase_v1_atr_tp4_sl1"),
    ("uptrend_pullback", "v33_long_reverse_v19"),
    ("short_reversal", "v50_slope"),
]
TOL = 1e-6


def _run(fam: str, preset: str):
    from hiagent_config import get_db_path

    db = Path(str(get_db_path()))
    start, end = WINDOW
    if fam == "chase_up":
        from chase_up.backtest import run_backtest

        r = run_backtest(preset, start, end, db)
        return pd.DataFrame(r["trades"]), float(r["metrics"]["final_equity"]), pd.DataFrame(r["equity"])
    if fam == "uptrend_pullback":
        from uptrend_pullback.backtest import run_backtest

        r = run_backtest(preset, start, end, db)
        return pd.DataFrame(r["trades"]), float(r["metrics"]["final_equity"]), pd.DataFrame(r["equity"])
    from short_reversal.engine import run_backtest_v3

    r = run_backtest_v3(preset, start, end, db)
    return pd.DataFrame(r["trades"]), float(r["final_capital"]), pd.DataFrame(r["equity_curve"])


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset", CASES, ids=[c[0] for c in CASES])
def test_per_trade_closure_holds(fam: str, preset: str) -> None:
    """§2/§3:每笔 `net_pnl == gross_pnl − fees`(逐位)。"""
    require_market_db()
    tr, _fin, _eq = _run(fam, preset)
    assert len(tr) > 0, f"{fam}/{preset} 在 {WINDOW} 上没有成交 ⇒ 本条空转"
    bad = tr[(tr["net_pnl"] - (tr["gross_pnl"] - tr["fees"])).abs() > TOL]
    assert bad.empty, (
        f"§2/§3 逐笔闭合: {fam}/{preset} 有 {len(bad)} 笔 `net_pnl != gross_pnl - fees` ——\n"
        f"  {bad[['thscode', 'gross_pnl', 'fees', 'net_pnl']].head(5).to_dict('records')}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset", CASES, ids=[c[0] for c in CASES])
def test_final_equity_equals_the_equity_curve_tail(fam: str, preset: str) -> None:
    """§2:报告口径必须与权益曲线**同源** —— `final` == 曲线末值(逐位)。

    (这条钉的是"同一次运行的两份输出要一致":`final_capital` 取净值还是总现金、取哪一天,
     都会在这里露出来。`short_reversal/engine.py:228` 那段注释记的正是它修过一次的错。)
    """
    require_market_db()
    _tr, fin, eq = _run(fam, preset)
    assert len(eq) > 0, f"{fam}/{preset} 没有权益曲线 ⇒ 本条无从比较"
    tail = float(eq["equity"].iloc[-1]) if "equity" in eq.columns else float(eq.iloc[-1].iloc[-1])
    assert abs(fin - tail) <= 1e-6, (
        f"§2 口径不一致: {fam}/{preset} 报告的 final={fin:,.2f},而权益曲线末值={tail:,.2f} "
        f"(差 {fin - tail:,.2f}) —— 同一次运行的两份输出必须同源。"
    )
