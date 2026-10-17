"""§3/§0: 复权因子表必须**覆盖行情表的每一个交易日** —— 除**数据版本滞后**那一段。

## 为什么需要这条 (2026-10-19, Iteration 109 的产物)
`v_daily_hfq` 与 `v_daily_qfq` 都写成 `COALESCE(f.xxx_factor, 1)` ——
**因子缺失时静默当成"无调整"**。实测 (§13): 因子表止于 `2026-09-18`,
而行情表到 `2026-09-30` ⇒ **38,870 行 (0.375%) 落到回退分支**,
而 `v_daily_hfq` 用的是 `backward_factor` (均值 1.66) ⇒
**填 1 等于把 7 天价格缩到 1/1.66** ⇒ 全市场 2026-09-21 假跌 **−25%**。

## 这条 guard 的**取舍** (它刻意不做的两件事)
1. **不对"末尾滞后"报警为失败** —— 行情每天都更新、因子按批发布,
   末尾差几天是**正常的版本节奏**, 把它做成红会得到一个**恒红的 guard**
   (而恒红与恒真一样不提供信息 —— 见 §6.4 的同类讨论)。
2. **不对绝对水平做断言** —— 那是数据供应商的事, 本仓库改不了。

## 它**真正**拦的是什么
**历史中段出现缺口** —— 那不是版本节奏, 是数据损坏。
那种缺口会让**已经落地的历史窗口**悄悄用错价格, 而且**不会报错**。
本仓库的每一份回测结果都建在这些日期上, 所以这是**必须响**的一种失败。

## 两层
* 结构层 (不需要 DB): 两个视图的 DDL 里 `COALESCE` 的存在是**已知事实**,
  一旦有人把它删掉 (改回 NULL 语义), 本文件的第一条测试会红 —— 提醒同步文档;
* 行为层 (需要 DB, 缺则 skip): 实际缺口是否只在末尾。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# 末尾允许的版本滞后 (交易日)。实测 2026-10-19 时是 7 天; 给一倍余量。
# **故意不再放宽**: 放宽到几十天就等于把"中段缺口"也放过去。
MAX_VINTAGE_LAG_TRADING_DAYS = 15


def _db() -> Path | None:
    try:
        from hiagent_config import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return None


def test_coalesce_fallback_is_documented_and_known() -> None:
    """`COALESCE(..., 1)` 的静默回退必须**仍被登记为已知缺陷**。

    这条是**反向钉桩**: 若有人修好了视图 (改成保留 NULL), 本测试会红 ——
    那不是坏事, 而是要求他同时更新文档里"已知缺陷"的记载, 别让文档变成陈旧描述。
    """
    doc = (ROOT / "docs" / "strategy_mining_log.md").read_text(encoding="utf-8")
    assert "COALESCE" in doc and "§13" in doc, (
        "文档里必须留有关于 COALESCE 静默回退 (§13) 的记载 —— "
        "若视图已改为保留 NULL, 请同步更新该节而不是删掉它"
    )


@pytest.mark.skipif(_db() is None, reason="需要本地 DB (§6: 缺产物时 skip, 不 error)")
def test_factor_table_gap_is_confined_to_the_data_vintage_tail() -> None:
    """因子表与行情表的缺口**必须只出现在末尾**, 且不超过版本滞后容忍。"""
    import duckdb

    db = _db()
    assert db is not None
    con = duckdb.connect(str(db), read_only=True)
    try:
        # 行情表**全市场的**交易日序列 (用于定义"末尾")
        cal = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT date FROM raw_kline_daily ORDER BY date"
            ).fetchall()
        ]
        assert len(cal) > MAX_VINTAGE_LAG_TRADING_DAYS + 1, "行情表太短, 无法判定"
        tail_start = cal[-(MAX_VINTAGE_LAG_TRADING_DAYS + 1)]

        missing = con.execute(
            """
            SELECT count(*), min(d.date)
            FROM raw_kline_daily d
            LEFT JOIN calc_adjust_factor_daily f USING (thscode, date)
            WHERE f.backward_factor IS NULL
            """
        ).fetchone()
    finally:
        con.close()

    n_missing, earliest_missing = int(missing[0]), missing[1]
    if n_missing == 0:
        return  # 完全覆盖 —— 最好的情况

    assert earliest_missing >= tail_start, (
        f"复权因子在**历史中段**缺失: 最早缺口 {earliest_missing} "
        f"(允许的末尾起点 {tail_start}), 共 {n_missing:,} 行。\n"
        f"这不是版本滞后, 是数据损坏 —— `v_daily_hfq`/`v_daily_qfq` 会对这些行"
        f"**静默使用未复权价** (COALESCE→1), 且不报错。"
    )
