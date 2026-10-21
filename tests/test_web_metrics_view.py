"""跨引擎 metrics 归一：缺键补 None（**不是 0**），且处理 trades 同名不同型。"""
from __future__ import annotations

from web.metrics_view import (
    CANONICAL_KEYS,
    METRIC_KINDS,
    METRIC_LABELS,
    canonical_metrics,
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
