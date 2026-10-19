# ══════════════════════════════════════════════════════════════════════════
# web/metrics_view.py —— 把四个引擎各不相同的 metrics 归一到一组规范键
#
# 为什么需要（Task 2 评审实测）：四个引擎的 metrics **schema 并不统一**——
#   short_reversal    : final_capital / total_yield / trades_count(原生) / trades = list[dict]
#   chase_up, uptrend : final_equity / total_return / trades = **int（计数）**
#   cycle_price_action: total_pnl / n_trades / cagr,s harpe,max_dd **恒为 None**
# 唯一四引擎共有的键是 trades_count，且 short_reversal 是原生的、另三个由适配器补。
# 直接按引擎原始键渲染指标表，会"每引擎一列集"错位——下游 Task 7 正需要这一层。
#
# **一条硬规则：缺键一律补 `None`，绝不补 `0`。**
# 0 是"真的零"，None 是"没有这个数"。把缺失的 cagr 渲染成 0.0 会让用户读成
# "这个策略年化 0"，而真相是"这个引擎不产出 cagr"。这正是 §0 禁止的静默降级。
#
# **第二条同族规则：非有限数（NaN/±Inf）也补 `None`。**
# 它不是 0，也不是"缺键"——它是"这个数没有意义"（0 笔成交时的均值、无亏损时的
# profit_factor）。留在 payload 里会让端点 500（`allow_nan=False`），见 Global Constraints。
# ══════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import math
from typing import Any

#: 规范键 → 依优先级尝试的原始键（先命中先用）
_METRIC_SOURCES: dict[str, tuple[str, ...]] = {
    "trades_count":  ("trades_count", "n_trades"),
    "final_capital": ("final_capital", "final_equity"),
    # ⚠️ `total_pnl` **不在**这里。它是 `cycle_price_action` 的
    # `sum(t.pnl)` —— **绝对金额**，而另三引擎的 `total_yield` / `total_return`
    # 是**比例**（0.5 = 50%）。把金额映进"收益率"这一列，会让指标表上
    # cycle 显示 `total_return 12345.0` 而隔壁显示 `0.5`，
    # **读者会以为 cycle 赚了百万倍** —— 这正是本模块要修的"每引擎一列集错位"，
    # 只是从"键错位"换成了"值域错位"（CLAUDE.md §5 点名的单位/口径错配）。
    # 它有自己的键（下方 `total_pnl`），标注成金额。
    "total_return":  ("total_yield", "total_return"),
    "cagr":          ("cagr",),
    "sharpe":        ("sharpe",),
    "max_dd":        ("max_dd",),
    "win_rate":      ("win_rate",),
    # 盈亏比：对标聚宽「收益概览」里的同名项。
    # 实测四引擎：`chase_up` / `uptrend_pullback` 已产出；`short_reversal` / `cycle`
    # **没有**这个键 → 按 §0 规则补 `None`（不是 0，也不是 1）。
    # ⚠️ `chase_up/backtest.py:64` 在**无亏损时无条件**返回 `float("inf")`
    #（空成交分支同样给 inf）—— 由 `_finite_or_none` 接住变成 `None`，
    # 否则一个 `inf` 就让指标端点 500（见 Global Constraints「API 边界不得输出非有限数」）。
    "profit_factor": ("profit_factor",),
    # 绝对盈亏（**金额**，不是比例）。四引擎初始资金统一 1e6（平台不暴露该参数），
    # 故跨引擎可比。前端必须按金额渲染（千分位、两位小数），不能按百分比。
    "total_pnl":     ("total_pnl",),
    "avg_hold_days": ("avg_hold_days",),
}

#: 每个规范键的渲染类型：`"pct"` / `"money"` / `"ratio"` / `"count"` / `"days"`。
#: **这张表存在的理由**：前端原先用 `v.toFixed(4)` 一把梭，于是
#: `trades_count` 会渲染成 `74.0000`（一个计数带四位小数）、
#: `final_capital` 会渲染成 `1500000.0000`。**单位是数据的一部分**，
#: 不能只靠键名猜——把渲染类型显式声明出来，加错键时前端会拿到未知类型而不是默默格式化错。
METRIC_KINDS: dict[str, str] = {
    "trades_count":  "count",
    "final_capital": "money",
    "total_return":  "pct",
    "cagr":          "pct",
    "sharpe":        "ratio",
    "max_dd":        "pct",
    "win_rate":      "pct",
    "profit_factor": "ratio",
    "total_pnl":     "money",
    "avg_hold_days": "days",
}

#: 中文标签（对标聚宽的「收益概览」列名）。
METRIC_LABELS: dict[str, str] = {
    "trades_count":  "交易笔数",
    "final_capital": "期末资金",
    "total_return":  "总收益率",
    "cagr":          "年化收益",
    "sharpe":        "夏普比率",
    "max_dd":        "最大回撤",
    "win_rate":      "胜率",
    "profit_factor": "盈亏比",
    "total_pnl":     "总盈亏",
    # ⚠️ **这一列的口径随引擎而变，标签必须说出来。**
    # 实测：short_reversal 的 `hold_days = len(self) - pos["entry_bar"]` → **交易日**；
    # chase_up 记的是 `(exit_date - entry_ts).days`（backtrader_engine.py:294）、
    # cycle_price_action 的 `hold_days()` 同 → **自然日**。
    # 本模块的整个存在理由是"让四个引擎的指标可比"，而这一列**恰好不可比**。
    # **不做换算**：日历↔交易日需要交易日历，而且那会成为引擎语义的第二份实现（§6）。
    # 如实标注口径，比给一个看起来可比的数强。
    "avg_hold_days": "平均持仓（天，口径随引擎）",
}

#: 规范键的顺序（前端指标表按它渲染）
CANONICAL_KEYS: tuple[str, ...] = tuple(_METRIC_SOURCES)


def _finite_or_none(v: Any) -> Any:
    """非有限数（`NaN` / `±Inf`）→ `None`；其余原样返回。

    为什么在**值这一层**就要处理，而不是只靠出口的响应类兜底：
    出口的网是"最后一道"，它保证 500 不会发生；但这一层决定**语义**——
    "这个数没有意义"必须表示成 `null`，而不是让一个 `Infinity` 一路飘到 CSV /
    metrics.json（`export_metrics` 用 `default=str`，非有限数会被静默写成
    **字符串 `"Infinity"`**，那是既非法 JSON 又骗人的产物）。

    实测的产出方：`chase_up/backtest.py` 的 `profit_factor` 在无亏损时**无条件**为
    `float("inf")`。它今天没炸只是因为白名单恰好没收录该键——把规则写在这里，
    就不必依赖那种巧合。
    """
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def canonical_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """把一个引擎的 metrics 映到规范键；缺的补 `None`（**不是 0**）。"""
    out: dict[str, Any] = {}
    for key, sources in _METRIC_SOURCES.items():
        val = None
        for s in sources:
            if metrics.get(s) is not None:
                val = metrics[s]
                break
        if key == "trades_count" and val is None:
            # `trades` 在 chase_up/uptrend 里是**计数**（int），在 short_reversal 里是 list。
            # 只有 int 形态才是计数；list 是明细，不是个数——**这个同名不同型正是 Task 2 评审抓到的坑。**
            t = metrics.get("trades")
            if isinstance(t, int) and not isinstance(t, bool):
                val = t
        out[key] = _finite_or_none(val)
    return out
