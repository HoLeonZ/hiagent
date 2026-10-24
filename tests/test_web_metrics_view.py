"""跨引擎 metrics 归一：缺键补 None（**不是 0**），且处理 trades 同名不同型。"""
from __future__ import annotations

import pytest

from web.metrics_view import (
    CANONICAL_KEYS,
    METRIC_KINDS,
    METRIC_LABELS,
    canonical_metrics,
    period_returns,
)

# 形状实测自 Task 2 评审：三个引擎的真实 metrics
SHORT = {"trades": [{"a": 1}], "trades_count": 74, "final_capital": 1.5e6,
         "total_yield": 0.5, "cagr": 2.19, "sharpe": 5.48, "max_dd": 0.09,
         "win_rate": 0.31, "avg_hold_days": 2.7}
CHASE = {"trades": 18, "win_rate": 0.4, "final_equity": 1.2e6, "total_return": 0.2,
         "cagr": 0.8, "sharpe": 2.1, "max_dd": 0.3, "avg_hold_days": 3.1}
CYCLE = {"n_trades": 10, "total_pnl": 12345.0, "cagr": None, "sharpe": None,
         "max_dd": None, "win_rate": 0.6, "avg_hold_days": 1.9}


def test_same_keys_for_every_engine():
    """归一后三个引擎必须是**同一组键**——否则 Task 7 的指标表会每引擎一列集错位。"""
    for m in (SHORT, CHASE, CYCLE):
        assert tuple(canonical_metrics(m)) == CANONICAL_KEYS


def test_short_reversal_maps_its_own_names():
    got = canonical_metrics(SHORT)
    assert got["trades_count"] == 74 and got["final_capital"] == 1.5e6
    assert got["total_return"] == 0.5            # total_yield → total_return


def test_chase_up_maps_equity_names_and_reads_trades_as_a_COUNT():
    got = canonical_metrics(CHASE)
    assert got["final_capital"] == 1.2e6         # final_equity → final_capital
    assert got["trades_count"] == 18             # 此引擎的 `trades` 是 int 计数


def test_a_list_valued_trades_key_is_not_mistaken_for_a_count():
    """short_reversal 的 `trades` 是 list[dict]；**不能**当计数。"""
    assert canonical_metrics({"trades": [{"a": 1}, {"b": 2}]})["trades_count"] is None


def test_a_missing_metric_is_None_not_zero():
    """§0：缺键补 None，绝不补 0。

    cycle 的 cagr/sharpe/max_dd 恒为 None——补成 0.0 会让用户读成"年化 0"，
    而真相是"这个引擎不产出 cagr"。
    """
    got = canonical_metrics(CYCLE)
    assert got["cagr"] is None and got["sharpe"] is None and got["max_dd"] is None
    assert got["trades_count"] == 10 and got["total_pnl"] == 12345.0


def test_a_money_amount_never_lands_in_a_percentage_column():
    """**单位不许跨列错配。**

    `cycle_price_action` 的 `total_pnl` 是 `sum(t.pnl)` —— **绝对金额**；
    而 `total_yield` / `total_return` 是**比例**（0.5 = 50%）。
    把金额映进"收益率"列，指标表上就会是 cycle 显示 `12345.0`、隔壁显示 `0.5`
    ——**读者会以为 cycle 赚了百万倍**。

    这与本模块存在的理由（"每引擎一列集错位"）是同一件事，
    只是从"键错位"换成了"值域错位"（CLAUDE.md §5 点名的单位/口径错配）。
    判别力：把 `"total_pnl"` 加回 `_METRIC_SOURCES["total_return"]`，这条立刻变红。
    """
    got = canonical_metrics(CYCLE)
    assert got["total_return"] is None, "cycle 不产出组合收益率，必须补 None 而不是塞进金额"
    assert got["total_pnl"] == 12345.0, "金额要有自己的键，不能被丢掉"
    assert METRIC_KINDS["total_return"] == "pct"
    assert METRIC_KINDS["total_pnl"] == "money"


def test_every_canonical_key_declares_a_kind_and_a_label():
    """**双向**元数据测试（与 §8 的参数元数据同一条纪律）。

    前端不再用 `toFixed(4)` 一把梭——它按 `METRIC_KINDS` 渲染。
    于是"加了一个规范键却忘了声明它的类型/标签"会**静默**退化成
    "这一格格式不对"或"显示成英文键名"。这条让它在测试里就红。

    反方向也查：不得存在指向**不存在**键的元数据（改名后会留下幽灵）。
    """
    assert set(METRIC_KINDS) == set(CANONICAL_KEYS), \
        f"类型声明与规范键不一致：{set(METRIC_KINDS) ^ set(CANONICAL_KEYS)}"
    assert set(METRIC_LABELS) == set(CANONICAL_KEYS), \
        f"中文标签与规范键不一致：{set(METRIC_LABELS) ^ set(CANONICAL_KEYS)}"
    assert set(METRIC_KINDS.values()) <= {"pct", "money", "ratio", "count", "days"}


def test_a_real_zero_is_preserved_as_zero_not_None():
    """反过来也要对：**真的 0** 必须留成 0，不能被误判为"缺失"。"""
    got = canonical_metrics({"cagr": 0.0, "trades_count": 0})
    assert got["cagr"] == 0.0 and got["trades_count"] == 0


def test_a_non_finite_metric_becomes_None_not_a_NaN_on_the_wire():
    """`NaN` / `±Inf` 一律变成 `None`（Global Constraints：API 边界不得输出非有限数）。

    **这不是洁癖，是 500**：Starlette 的 `JSONResponse.render` 用
    `json.dumps(..., allow_nan=False)`，任一非有限数都会让端点抛 `ValueError`。
    用户看到的是"服务器错误"，不是结果页。

    真相不是"这个数是 0"，而是"这个数没有意义"——所以与缺键同规则补 `None`（§0）。
    实测的产出方：`chase_up/backtest.py` 的 `profit_factor` 在**无亏损时无条件**是
    `float("inf")`（`chase_up/backtest.py:64` 与有成交分支的 else）。今天它没炸，
    只是因为 `_METRIC_SOURCES` 的白名单**恰好没收录这个键**——那是运气，不是设计。
    """
    got = canonical_metrics({"cagr": float("nan"), "sharpe": float("inf"),
                             "max_dd": float("-inf"), "win_rate": 0.5})
    assert got["cagr"] is None and got["sharpe"] is None and got["max_dd"] is None
    assert got["win_rate"] == 0.5          # 有限值不受影响


def test_no_non_finite_value_survives_the_real_encoder():
    """**用真实编码器当裁判**，而不是只断言我们自己写的 `None`。

    只断言 `got["cagr"] is None` 是"与实现同源"的检查——它证明不了 payload 里
    不会出现非有限数（换个键、换个没走 `canonical_metrics` 的路径就漏了）。
    这条把 Starlette 拉进来：喂进去的东西只要含非有限数，它就抛。
    """
    import pytest
    from starlette.responses import JSONResponse

    payload = canonical_metrics({
        "cagr": float("nan"), "sharpe": float("inf"), "final_capital": 1e6,
        "win_rate": float("nan"), "avg_hold_days": float("-inf"),
    })
    JSONResponse(payload).render(payload)          # 含任何非有限数就抛 ValueError

    # 判别力自检：**证明这个裁判真的会抛**，否则上面那句在"测试永远绿"的意义上毫无价值
    with pytest.raises(ValueError):
        JSONResponse({"x": float("nan")}).render({"x": float("nan")})


def test_non_finite_is_not_confused_with_a_real_zero():
    """`None`（无意义）与 `0.0`（真的零）必须是三态里清楚的两态，不能混。"""
    got = canonical_metrics({"cagr": 0.0, "sharpe": float("nan")})
    assert got["cagr"] == 0.0 and got["cagr"] is not None
    assert got["sharpe"] is None


def test_profit_factor_is_mapped_when_present_and_None_when_absent():
    """盈亏比：对标聚宽「收益概览」的同名项。

    实测四引擎：`chase_up` / `uptrend_pullback` 已产出该键；
    `short_reversal` / `cycle_price_action` **没有** → 补 `None`（§0：缺键不补 0）。
    补成 0 会让人读成"每亏 1 块只赚 0 块"，而真相是"这个引擎不产出盈亏比"。
    """
    assert canonical_metrics({"profit_factor": 2.5})["profit_factor"] == 2.5
    assert canonical_metrics({"cagr": 0.1})["profit_factor"] is None


def test_an_infinite_profit_factor_becomes_None_not_Infinity():
    """**实测的真实路径**：`chase_up/backtest.py:64` 在**无亏损时无条件**给
    `float("inf")`（空成交分支同样给 inf）。

    一个 `inf` 会让端点 500（`allow_nan=False`），也会让 `export/metrics.json`
    写出非法 JSON。`_finite_or_none` 把它变成 `None` —— 语义也对：
    "没有任何亏损"不是"盈亏比无穷大"这个可比较的数，而是"这个比值没有意义"。
    """
    assert canonical_metrics({"profit_factor": float("inf")})["profit_factor"] is None
    assert canonical_metrics({"profit_factor": float("-inf")})["profit_factor"] is None


def test_avg_hold_days_label_admits_the_unit_varies_by_engine():
    """`avg_hold_days` 这一列在不同引擎下**不是同一个单位**，标签必须说出来。

    实测：`short_reversal` 的 `hold_days = len(self) - pos["entry_bar"]` → **交易日**；
    `chase_up` 记的是 `(exit_date - entry_ts).days`（backtrader_engine.py:294）、
    `cycle_price_action` 的 `hold_days()` 同 → **自然日**。

    本模块的整个存在理由是"让四个引擎的指标可比"（避免"每引擎一列集错位"），
    而这一列**恰好不可比**。不做换算：日历↔交易日需要交易日历，而且那会成为
    引擎语义的第二份实现（§6）。**如实标注口径，比给一个看起来可比的数强。**
    """
    from web.metrics_view import METRIC_LABELS

    label = METRIC_LABELS["avg_hold_days"]
    assert "口径" in label, f"标签必须提示口径随引擎而变，现在是 {label!r}"
    assert METRIC_LABELS["trades_count"] == "交易笔数", "别把无关的标签也改了"


def test_the_risk_metrics_joinquant_shows_are_computed_from_the_window_curve():
    """**日胜率 / 年化波动率 / Calmar** —— 聚宽风险指标里的那几项，平台自己算。

    全部来自**窗口切片的曲线**（平台已有的东西），不碰引擎、不引第二份实现。
    `Alpha`/`Beta` **明确不做**：基准是等权多头篮子而策略是空头，回归会产出
    方向相反的 "alpha"，比没有更坏。
    """
    import math

    from web.metrics_view import window_metrics

    class _R:
        start, end = "2025-01-01", "2025-01-04"

        def __init__(self, curve, trades):
            self.metrics = {"equity_curve": curve}
            self.trades = trades

    # 手工构造：日收益 +10%、−10%、+9.09%
    curve = [{"date": "2025-01-01", "equity": 100.0},
             {"date": "2025-01-02", "equity": 110.0},
             {"date": "2025-01-03", "equity": 99.0},
             {"date": "2025-01-04", "equity": 108.0}]
    m = window_metrics(_R(curve, []))

    rets = [0.10, -0.10, 108.0 / 99.0 - 1.0]
    mu = sum(rets) / 3
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / 2)     # 样本标准差

    assert abs(m["daily_win_rate"] - 2 / 3) < 1e-12, "日胜率 = 正收益天数占比"
    assert abs(m["volatility"] - sd * math.sqrt(243.0)) < 1e-9, \
        "年化波动率 = 日收益标准差 × √243（与夏普同一条年化约定）"
    assert abs(m["sharpe"] - (mu / sd) * math.sqrt(243.0)) < 1e-9
    assert abs(m["calmar"] - m["cagr"] / m["max_dd"]) < 1e-9, "Calmar = 年化收益 / 最大回撤"
    # 回撤：峰值 110 → 谷 99 = 10%
    assert abs(m["max_dd"] - 0.10) < 1e-9


def test_the_engine_side_mapping_leaves_the_window_only_metrics_as_none():
    """这三项**引擎不产出** → 引擎映射路径必须给 `None`，不能编一个值出来。

    它们的来源元组是**空的**；若有人给它们编一个引擎键名去凑，
    这条会红。
    """
    from web.metrics_view import canonical_metrics

    got = canonical_metrics({"cagr": 1.0, "trades_count": 3})
    for k in ("daily_win_rate", "volatility", "calmar"):
        assert k in got, f"规范键里应当有 {k}"
        assert got[k] is None, f"{k} 没有引擎来源，引擎映射路径必须给 None"


def _engine_only_result():
    """造一次**没有净值曲线**的运行 —— 三个非 short_reversal 引擎的真实形态。"""
    class _R:
        start, end = "2025-01-01", "2025-03-01"

        def __init__(self):
            # chase_up 的真实 metrics 形状：有 final_equity/total_return/cagr/…，
            # 但**没有 equity_curve**（实测：那三个引擎的源码里 `equity_curve` 出现 0 次）。
            self.metrics = {"final_equity": 1_200_000.0, "total_return": 0.2,
                            "cagr": 0.5, "sharpe": 1.5, "max_dd": 0.1, "win_rate": 0.4,
                            "trades": 3, "avg_hold_days": 2.0}
            self.trades = [{"entry_date": "2025-01-05", "net_pnl": 10.0, "hold_days": 2},
                           {"entry_date": "2025-02-05", "net_pnl": -5.0, "hold_days": 3},
                           {"entry_date": "2025-02-20", "net_pnl": 7.0, "hold_days": 1}]
    return _R()


def test_an_engine_without_an_equity_curve_still_gets_its_metrics():
    """**四个引擎里只有 short_reversal 产出净值曲线。**

    实测（2026-10-21）：`chase_up` / `uptrend_pullback` / `cycle_price_action` 的 metrics 里
    `equity_curve` 出现 **0 次**。而窗口指标是**从曲线算**的 —— 若不给回退，
    这三个引擎的结果页会有 **8/13 格是 `—`**（期末资金/总收益率/年化/夏普/最大回撤/
    年化波动率/日胜率/Calmar），把"口径不够理想"换成了"整张表空了"。

    这条测试就是为此存在的 —— **原先的窗口测试只用 short_reversal 的曲线，
    所以那个回归一路全绿通过了。**
    """
    from web.metrics_view import window_metrics

    m = window_metrics(_engine_only_result())
    # 曲线派生的键退回**引擎自报**的值（唯一可得）
    assert m["total_return"] == 0.2, "没有曲线时应当退回引擎自报的 total_return"
    assert m["final_capital"] == 1_200_000.0
    assert m["cagr"] == 0.5 and m["sharpe"] == 1.5 and m["max_dd"] == 0.1
    # 成交派生的仍然按**窗口**算（那不需要曲线）
    assert m["trades_count"] == 3 and m["win_rate"] == pytest.approx(2 / 3)
    # 明确标注哪几个数是引擎口径的 —— 消费方要能分辨
    assert set(m["engine_scoped"]) == {"final_capital", "total_return", "cagr", "sharpe", "max_dd"}
    # 它是**额外的标记**，不是规范键：指标表按 metric_meta 渲染，不会多出一格
    from web.metrics_view import CANONICAL_KEYS

    assert "engine_scoped" not in CANONICAL_KEYS


def test_a_run_with_a_curve_does_not_get_the_engine_scoped_marker():
    """有曲线时它就是窗口口径，不该带"引擎口径"的标记 —— 免得标记变成噪声。"""
    from web.metrics_view import window_metrics

    class _R:
        start, end = "2025-01-01", "2025-01-03"

        def __init__(self):
            self.metrics = {"equity_curve": [
                {"date": "2025-01-01", "equity": 100.0},
                {"date": "2025-01-03", "equity": 110.0}]}
            self.trades = []

    m = window_metrics(_R())
    assert "engine_scoped" not in m
    assert abs(m["total_return"] - 0.1) < 1e-12


# --- 年度/月度收益分解 --------------------------------------------------------


def _curve(pairs):
    return [{"date": d, "equity": v} for d, v in pairs]


def test_period_returns_compounds_back_to_the_total():
    """**可加性**：把每段收益复利回去，必须等于累计收益。

    这是这张表唯一的一致性判据。不成立的表比没有表更坏：用户会拿
    "分段加起来只有 40%、总收益却说 300%" 去怀疑整个回测。
    """
    import math

    c = _curve([("2024-12-30", 100.0), ("2025-01-02", 101.0), ("2025-12-31", 150.0),
                ("2026-01-02", 160.0), ("2026-06-30", 180.0)])
    rows = period_returns(c)
    assert [r["period"] for r in rows] == ["2024", "2025", "2026"]
    comp = math.prod(1 + r["return"] for r in rows if r["return"] is not None)
    assert abs(comp - 180.0 / 100.0) < 1e-12, "分段收益复利回去必须等于累计收益"
    # 中间年份的基期是**上一段的末值**，不是窗口起点
    assert abs(rows[2]["return"] - (180.0 / 150.0 - 1)) < 1e-12


def test_a_period_with_no_measurable_return_is_none_not_zero():
    """窗口起点落在某年最后一个交易日 → 首段只有一行、它就是自己的基期。

    此时收益是**测不出**（`None`），不是 0。写成 0 会被读成"那年不涨不跌"，
    而真相是"那年只覆盖了一天，什么都没有发生也什么都没法测"。
    首段的收益里还**包含**窗口第一天的涨跌（基期是窗口起点），所以更不能写 0。
    """
    rows = period_returns(_curve([("2025-12-31", 1.0), ("2026-01-05", 1.1)]))
    assert rows[0] == {"period": "2025", "from": "2025-12-31", "to": "2025-12-31",
                       "return": None}
    assert abs(rows[1]["return"] - 0.1) < 1e-12, "第二段的基期是上一段末值，收益可测"


def test_a_period_that_really_did_not_move_is_zero_not_none():
    """反向守门：**真的有多个交易日而净值没变**时，是 0.0，不是 None。

    没有这条，"一律返回 None" 也能让上一条变绿——而那样整张表都是破折号。
    """
    rows = period_returns(_curve([("2025-01-02", 1.0), ("2025-06-30", 1.0),
                                  ("2025-12-31", 1.0)]))
    assert rows[0]["return"] == 0.0


def test_period_returns_keeps_the_date_range_of_each_period():
    """每段都带**实际覆盖的区间**。年份标签本身不等于整年：首尾被窗口切过。"""
    rows = period_returns(_curve([("2025-03-04", 1.0), ("2025-12-31", 1.2),
                                  ("2026-01-02", 1.3)]))
    assert (rows[0]["from"], rows[0]["to"]) == ("2025-03-04", "2025-12-31")
    assert (rows[1]["from"], rows[1]["to"]) == ("2026-01-02", "2026-01-02")


def test_period_returns_can_split_by_month():
    rows = period_returns(_curve([("2025-01-02", 1.0), ("2025-01-31", 1.1),
                                  ("2025-02-28", 1.21)]), unit="month")
    assert [r["period"] for r in rows] == ["2025-01", "2025-02"]
    assert abs(rows[0]["return"] - 0.1) < 1e-12
    assert abs(rows[1]["return"] - 0.1) < 1e-12


def test_period_returns_refuses_an_unknown_unit():
    with pytest.raises(ValueError, match="period unit"):
        period_returns(_curve([("2025-01-02", 1.0), ("2025-12-31", 1.1)]), unit="quarter")


def test_period_returns_needs_at_least_two_points():
    assert period_returns([]) == []
    assert period_returns(_curve([("2025-01-02", 1.0)])) == []
