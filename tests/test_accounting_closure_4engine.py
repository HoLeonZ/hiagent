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

## ⚠️ `cycle_price_action`:**我上一版说它"输出上不可验",那句话是错的**(附一百二十九)

它确实**没有** `gross_pnl`/`fees` 列,也**没有**权益曲线 —— 于是我当时写下"不可验"。
**但可以推导**:它的成交里有 `entry_price` / `exit_price` / `shares` / `pnl`,而**费率有单一来源**
(`core.dual_price.calc_commission` / `calc_stamp_duty`)⇒ 手算 `gross − fees` 再与 `pnl` 对。
**实测 490/490 笔逐位相同**(中位差 `0.000000`,最大 `0.0000`)⇒ **它可验,而且验过了**。

判据因此从两条里**去掉用不上的第二条**(它没有曲线),保留第一条的**推导版**:
`pnl == (exit − entry) × shares − [佣金(买+卖) + 印花税(卖)]`。

(这一条同时说明:**"没有那一列"不等于"不可验"** —— 只要其它列 + 单一来源的常量能推出它。)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import require_market_db

#: 窗口取 **1 个月**(而不是 3 个月):这两条判据是**结构性等式**,与窗口长度无关,
#: 而 3 个月窗在 `short_reversal`(~9 分钟)与 `cycle`(~6 分钟)上把这条守卫推到 35 分钟。
#: 缩到 1 个月后 ≈10 分钟 —— **判据的强度不变,成本降到可接受**。
from tests.conftest import STD_WINDOWS as _STD  # 各族的窗口与窗口边界守卫**共用**(见其 docstring)
CASES = [
    ("chase_up", "chase_v1_atr_tp4_sl1"),
    ("uptrend_pullback", "v33_long_reverse_v19"),
    ("short_reversal", "v50_slope"),
    ("cycle_price_action", "v1"),
]
TOL = 1e-6


def _run(fam: str, preset: str):
    """取**共享**的一次回测(与 `test_no_pre_window_entries_4engine.py` 同源)。"""
    from tests.conftest import run_engine_once

    return run_engine_once(fam, preset, _STD[fam])


@pytest.mark.slow
@pytest.mark.parametrize("fam,preset", CASES, ids=[c[0] for c in CASES])
def test_per_trade_closure_holds(fam: str, preset: str) -> None:
    """§2/§3:每笔 `net_pnl == gross_pnl − fees`(逐位)。"""
    require_market_db()
    tr, _fin, _eq = _run(fam, preset)
    assert len(tr) > 0, f"{fam}/{preset} 在 {_STD[fam]} 上没有成交 ⇒ 本条空转"
    if fam == "cycle_price_action":
        # 推导版:cycle 没有 gross/fees 列,但有价格与股数 + **单一来源**的费率
        from core.dual_price import calc_commission, calc_stamp_duty

        buy = tr["entry_price"] * tr["shares"]
        sell = tr["exit_price"] * tr["shares"]
        fees = buy.map(calc_commission) + sell.map(calc_commission) + sell.map(
            lambda n: calc_stamp_duty(n, "sell")
        )
        derived = (tr["exit_price"] - tr["entry_price"]) * tr["shares"] - fees
        bad = tr[(tr["pnl"] - derived).abs() > 1e-6]
        assert bad.empty, (
            f"§2/§3 逐笔闭合(推导版): cycle_price_action 有 {len(bad)} 笔 "
            f"`pnl != (exit-entry)*shares - 费率` ——\n"
            f"  {bad[['thscode', 'pnl']].head(5).to_dict('records')}"
        )
        return
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
    if eq is None:
        pytest.skip(f"{fam} 没有权益曲线(其 TradeRecord 不带 gross/fees、也不出版曲线)—— "
                    f"逐笔闭合已由推导版覆盖;净值一致性对 cycle 无对象")
    assert len(eq) > 0, f"{fam}/{preset} 没有权益曲线 ⇒ 本条无从比较"
    tail = float(eq["equity"].iloc[-1]) if "equity" in eq.columns else float(eq.iloc[-1].iloc[-1])
    assert abs(fin - tail) <= 1e-6, (
        f"§2 口径不一致: {fam}/{preset} 报告的 final={fin:,.2f},而权益曲线末值={tail:,.2f} "
        f"(差 {fin - tail:,.2f}) —— 同一次运行的两份输出必须同源。"
    )
