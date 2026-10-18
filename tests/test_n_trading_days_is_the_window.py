"""附八十一 —— `n_trading_days` 必须是**窗口内**的交易日数,不是整张面板的日期数。

## 缺陷(实测)

`short_reversal/engine.py` 此前传 `n_trading_days=int(panel["date"].nunique())`,
注释写的是「年化用**窗口内**的交易日数」。而面板含暖机缓冲、**两端都外扩**
(实测 2 个月窗口:面板范围 2025-09-02..2026-06-30):

| 窗口 | 窗口内交易日 | `panel["date"].nunique()` |
|---|---|---|
| 2026-03-01..05-01 | **43** | **197** |
| 2026-07-01..09-01 | **45** | **181** |

它同时喂给 **CAGR 的年化分母**(⇒ 短窗口 CAGR 被压低 ~4.6 倍)与 **DSR 的 `n_returns`**
(⇒ T 被高估 ⇒ 偏乐观)。逐窗实测(同一批窗口,`v50_slope`):

    窗口1: 总收益 +11.73%  → CAGR 14.66%(分母 197)  vs  87.12%(分母 43)
    窗口3: 总收益 +45.32%  → CAGR 65.16%(分母 181)  vs 652.45%(分母 45)

## 这条守卫为什么要带**非空转前提**

若哪天有人把面板的 padding 去掉,`panel.nunique()` 与"窗口内交易日"就会**相等**,
于是"断言两者一致"的用例会**恒真**(测不出任何东西)。故先断言"面板确实比窗口长"。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from tests.conftest import require_market_db  # noqa: E402

_WINDOW = ("2026-06-01", "2026-07-01")   # 1 个月窗口:跑得快,且 padding 必然显著


@pytest.mark.slow  # 真跑一次回测(约 1–3 分钟)
def test_n_trading_days_is_the_window_not_the_panel() -> None:
    require_market_db()
    from hiagent_config import get_db_path
    from short_reversal.engine import _load_panel, run_backtest_v3
    from short_reversal.universe import load_universe_asof

    start, end = _WINDOW
    db = Path(get_db_path())

    # 面板(带暖机缓冲)与"窗口内"的交易日数
    uni = load_universe_asof("mainboard_only", start, db)
    panel = _load_panel(db, start, end, uni)
    panel_days = int(panel["date"].nunique())
    con = duckdb.connect(str(db), read_only=True)
    try:
        win_days = int(con.execute(
            "SELECT count(DISTINCT date) FROM v_daily WHERE date BETWEEN ? AND ?",
            [start, end],
        ).fetchone()[0])
    finally:
        con.close()

    # **非空转前提**:面板必须确实比窗口长,否则下面的断言恒真、测不出东西
    assert panel_days > win_days, (
        f"面板没有比窗口长({panel_days} vs {win_days})—— 本用例失去判别力,请改夹具"
    )

    m = run_backtest_v3("v50_slope", start, end, db)
    assert m["n_trading_days"] == win_days, (
        f"§2/§5 VIOLATION: n_trading_days={m['n_trading_days']},而窗口内实际是 {win_days}"
        f"(面板长度是 {panel_days})—— 年化分母与 DSR 的 T 都会因此偏。"
    )
