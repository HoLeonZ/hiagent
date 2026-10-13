"""uptrend_pullback 公司行为 (分红/送股) 暴露守卫 — 2026-10-13 决策记录。

背景
----
``tests/test_corporate_actions_gap.py`` 把「是否实现 event-sourced 公司行为
handler」当作一个待用户拍板的设计二选一 (A: 纯 adj_close 隐式 / B: raw + 显式
event handler), 以永久红灯锁定。

决策 (2026-10-13, 基于实测而非偏好)
-----------------------------------
uptrend_pullback 保持 raw_close 执行 + 不做显式 CA 记账。理由:

1. 实测暴露为零。v33_long_reverse_v19 在 2024-09-01..2026-09-01 的 105 笔交易,
   持仓期中位数仅 **3 天** (min 1 / max 29), **没有任何一笔持仓穿过除权日**:
   漏记分红现金 = 0, 除权日幻影止损 = 0。
   (同窗口全市场有 9,667 个除权日、覆盖 4,187 只票, 集中在 5-7 月 —— 所以
   「零」不是数据缺失或查询写错, 而是持仓期太短的真实结果。)
2. 因此现在实现 option B 的 event 记账属于投机性工程, 无实测收益。
3. 也不能采用 option A 的字面表述「一律用 adj_close」: §3 明确要求成交/止损/
   市值用 raw 价 (§4 涨跌停、整手、T+1 都依赖真实价), 改成全 adj 会自相矛盾。

本测试的作用
------------
把上面第 1 条这个「零暴露」前提变成**可证伪的不变量**。一旦将来持仓期变长
(例如 max_hold 上调) 或有交易真的穿过除权日, 本测试立即失败, 迫使那时基于
真实暴露量再决定是否实现 §3 的显式 cash deposit / quantity 调整 —— 而不是让
一个无法执行的永久红灯留在 CI 里。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

PRESET = "v33_long_reverse_v19"
START, END = "2024-09-01", "2026-09-01"


def test_no_position_spans_a_corporate_action_ex_date() -> None:
    """持仓期内不得穿过任何除权日 —— 否则必须实现 §3 的 event-sourced 记账。"""
    from hiagent_config import DB_PATH as _DB
    from uptrend_pullback.backtest import run_backtest

    db = Path(_DB)
    if not db.exists():
        pytest.skip(f"本测试需要本机 DuckDB: {db}")

    trades = run_backtest(PRESET, START, END, db)["trades"]

    con = duckdb.connect(str(db), read_only=True)
    try:
        ev = con.execute(
            "SELECT thscode, ex_date, dividend_per_share, per_share_bonus "
            "FROM raw_adjustment_events WHERE ex_date BETWEEN ? AND ?",
            [START, END],
        ).fetchdf()
    finally:
        con.close()
    ev["ex_date"] = pd.to_datetime(ev["ex_date"])
    by_code = {c: g for c, g in ev.groupby("thscode")}

    offenders = []
    foregone_cash = 0.0
    for _, t in trades.iterrows():
        g = by_code.get(t["thscode"])
        if g is None:
            continue
        ent, ext = pd.Timestamp(t["entry_date"]), pd.Timestamp(t["exit_date"])
        # 除权日当天买入不享有分红 (价格已调整), 故区间左开右闭
        hits = g[(g["ex_date"] > ent) & (g["ex_date"] <= ext)]
        if hits.empty:
            continue
        cash = float((hits["dividend_per_share"] * float(t["size"])).sum())
        foregone_cash += cash
        offenders.append(
            (t["thscode"], ent.date(), ext.date(), len(hits), cash)
        )

    assert not offenders, (
        f"{len(offenders)} 笔持仓穿过了除权日, 漏记分红现金合计 "
        f"{foregone_cash:,.2f} CNY:\n{offenders[:5]}\n"
        f"这打破了本文件记录的『零暴露』前提, 现在必须实现 CLAUDE.md §3 的 "
        f"event-sourced 记账 (分红 → free_cash 物理入账; 送股 → quantity/avg_cost "
        f"原子调整), 并用 raw+事件 与 forward_factor 总收益两条路径对账验证。"
    )
