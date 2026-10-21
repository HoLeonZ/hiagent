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
    # ↓ 下面三项**引擎不产出**，是平台从**窗口切片的曲线**自己算的
    # （对标聚宽「收益概览/风险指标」里的日胜率、年化波动率、Calmar）。
    # 它们的来源元组是**空的** —— 引擎侧永远取不到，`canonical_metrics` 会给 `None`，
    # 由 `window_metrics` 填上真正的值。**不要**给它们编一个引擎键名去凑。
    "daily_win_rate": (),
    "volatility": (),
    "calmar": (),
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
    "daily_win_rate": "pct",
    "volatility": "pct",
    "calmar": "ratio",
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
    "daily_win_rate": "日胜率",
    "volatility": "年化波动率",
    "calmar": "Calmar比率",
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


# ══════════════════════════════════════════════════════════════════════════
# 窗口口径：结果页要显示的**全部**指标，都按**请求窗口**算。
#
# 为什么（2026-10-21 实测）：引擎的记录器覆盖的是**带缓冲的面板**
# （`[start-180d, end+60d]`，引擎不设 fromdate/todate），于是
#   · 引擎会在**窗口之前**交易（实测：请求 2026-03-30..2026-10-16，45 笔里 3 笔入场早于起点）；
#   · 引擎的 `cagr` 分母用**窗口**年数、分子却含**窗口前**的盈亏
#     （`short_reversal/engine.py:65-70`：`cagr = (final_capital/INITIAL_CAPITAL)**(1/years)-1`）。
#
# 平台**已经**把净值曲线切到了 `[start, end]`（设计文档明文要求"策略曲线必须切到"），
# 而曲线的两个端点**必然**给出窗口收益 —— 所以**窗口口径是设计自己选的**。
# 但指标表没跟着切，于是**同一个结果页自己跟自己不一致**：
#   指标表 total_return = 114.24%（引擎口径） vs 曲线栏 strategy_return = 115.03%（窗口口径）
# —— 聚宽那边「收益概览」与「收益曲线」是同一套数。
#
# 这里把该口径**应用完整**：指标表与曲线同源，都来自窗口切片后的曲线与成交。
# **不冻结一半** —— 只改 total_return 而留着面板口径的 cagr，用户拿显示的
# total_return 反推 cagr 会得到另一个数，比不修更坏。
#
# ⚠️ **平台口径与引擎口径会分叉**，这是有意的：引擎那份仍混着面板盈亏，
# 全仓库的报告与门禁都吃它。**那是一个独立且未修的引擎缺陷**，本模块不掩盖它，
# 也不假装两边一致。
# ══════════════════════════════════════════════════════════════════════════


def window_slice(curve: list[dict], start: str, end: str) -> list[dict]:
    """把净值曲线切到 `[start, end]` —— **窗口切片的唯一判据**。

    `/equity` 与指标表都走这里：两处各写一遍筛选条件，就是"各自漂移"的起点。
    """
    return [r for r in curve
            if r.get("date") is not None and start <= str(r["date"])[:10] <= end]


def window_trades(trades: list[dict], start: str, end: str) -> list[dict]:
    """只保留**在窗口内入场**的成交 —— **成交窗口切片的唯一判据**。

    为什么必须是唯一判据：三处要用它，且**必须完全一致** ——
      · 指标表的 `trades_count`；
      · 交易明细**列出的行**；
      · `GET /trades/{i}/chart` 的**下标 `i`**（它建立在同一份列表上，
        列表不同则点第 i 行会取到另一笔）。
    实测踩过：指标表按窗口报了 42，而交易表列的是 45 行 ——
    **页面又自己跟自己矛盾了**（那正是上一轮刚修掉的那类）。
    """
    return [t for t in trades if start <= str(t.get("entry_date", ""))[:10] <= end]


def _days_between(a: str, b: str) -> int:
    import datetime as dt

    return (dt.date.fromisoformat(str(b)[:10]) - dt.date.fromisoformat(str(a)[:10])).days


def window_metrics(result: Any) -> dict[str, Any]:
    """该次运行**按请求窗口**算出来的规范指标（键与 `CANONICAL_KEYS` 一致）。

    数据全部来自平台**已经拥有**的东西：窗口切片后的净值曲线，与窗口内入场的成交。
    没有第二份实现，也不碰引擎。
    """
    import math

    start, end = result.start, result.end
    curve = window_slice(result.metrics.get("equity_curve") or [], start, end)
    trades = window_trades(result.trades or [], start, end)

    out: dict[str, Any] = {k: None for k in CANONICAL_KEYS}

    # ---- 成交派生（只用**窗口内入场**的）----
    n = len(trades)
    out["trades_count"] = n
    if n:
        net = [float(t.get("net_pnl") or 0.0) for t in trades]
        out["win_rate"] = sum(1 for x in net if x > 0) / n
        holds = [float(t["hold_days"]) for t in trades if t.get("hold_days") is not None]
        if holds:
            out["avg_hold_days"] = sum(holds) / len(holds)
        out["total_pnl"] = sum(net)
        gains = sum(x for x in net if x > 0)
        losses = -sum(x for x in net if x < 0)
        # 盈亏比：**没有亏损就没有这个比值** —— 不是无穷大（§0：缺失补 None 不补 0）
        out["profit_factor"] = (gains / losses) if losses > 0 else None

    # ---- 曲线派生（与 `/equity` 同一段窗口切片）----
    if len(curve) >= 2:
        e0 = float(curve[0]["equity"])
        e1 = float(curve[-1]["equity"])
        if e0 > 0:
            out["final_capital"] = e1
            out["total_return"] = e1 / e0 - 1
            days = max(_days_between(curve[0]["date"], curve[-1]["date"]), 1)
            out["cagr"] = (e1 / e0) ** (365.0 / days) - 1
        peak, dd = -math.inf, 0.0
        for r in curve:
            eq = float(r["equity"])
            peak = max(peak, eq)
            if peak > 0:
                dd = max(dd, (peak - eq) / peak)
        out["max_dd"] = dd
        rets = []
        for a, b in zip(curve, curve[1:]):
            pa = float(a["equity"])
            if pa > 0:
                rets.append(float(b["equity"]) / pa - 1.0)
        if len(rets) >= 2:
            mu = sum(rets) / len(rets)
            var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
            sd = math.sqrt(var)
            out["sharpe"] = (mu / sd) * math.sqrt(243.0) if sd > 0 else None
            # 年化波动率：日收益标准差 × √243（与上面的夏普同一条年化约定）
            out["volatility"] = sd * math.sqrt(243.0)
            # 日胜率：**日**收益为正的天数占比（与"胜率"按笔不同，别混）
            out["daily_win_rate"] = sum(1 for r in rets if r > 0) / len(rets)
        # Calmar = 年化收益 / 最大回撤。回撤为 0 时**没有意义** → None（不是 inf）
        if out["cagr"] is not None and out["max_dd"]:
            out["calmar"] = out["cagr"] / out["max_dd"]

    if len(curve) < 2:
        # ⚠️ **这个引擎不产出净值曲线** —— 四个引擎里**只有 short_reversal 有**
        # （实测：chase_up / uptrend_pullback / cycle_price_action 的 metrics 里
        # 「equity_curve」出现 0 次）。此时曲线派生的键**退回引擎自报的值**。
        #
        # 它们**不是窗口口径**（引擎按它自己的面板算），但那是**唯一可得**的数。
        # 让它们留 `None` 会让这三个引擎的结果页有 **8/13 格是"—"**
        #（期末资金/总收益率/年化/夏普/最大回撤/年化波动率/日胜率/Calmar）——
        # 那是把一个"口径不够理想"的问题，换成一个"整张表空了"的问题。
        #
        # 退回的那几个键在此**明确标注来源**，别让人以为它们与 short_reversal 同口径。
        fb = canonical_metrics(result.metrics)
        for k in ("final_capital", "total_return", "cagr", "sharpe", "max_dd"):
            if out.get(k) is None:
                out[k] = fb.get(k)
        # 这个标记**不是**规范键（不在 `CANONICAL_KEYS` 里），所以指标表不会渲染它；
        # 它随 `metrics` 一起走，是为了让**消费方**知道哪几个数是引擎口径的。
        out["engine_scoped"] = ["final_capital", "total_return", "cagr", "sharpe", "max_dd"]
    return out


#: 交易明细的**中文列名**（聚宽的交易明细是中文列头）。
#:
#: 为什么需要：指标表已经有中文标签（`METRIC_LABELS`），而交易明细的表头却全是
#: `entry_date`/`exit_date`/`thscode` 这些英文键 —— **同一个页面上两套语言**。
#: 实测（2026-10-21 看真实页面）：交易明细的表头是英文的，日期还被挤成两行
#: （`2026-03-` / `09`）。
#:
#: 键名来自 `core.trade_schema.TRADE_COLS`（14 列规范）**加上**平台自己补的两列
#: （`sl_price`/`tp_price`）。`i` 是稳定下标，**不显示**。
TRADE_LABELS: dict[str, str] = {
    "entry_date": "买入日期",
    "exit_date": "卖出日期",
    "thscode": "证券代码",
    "exit_reason": "平仓原因",
    "entry_price": "买入价",
    "exit_price": "卖出价",
    "size": "数量",
    "hold_days": "持仓天数",
    "gross_pnl": "毛利",
    "fees": "费用",
    "net_pnl": "净利",
    "net_return": "净收益率",
    "atr_pct": "ATR占比",
    "sub_signal_type": "子信号类型",
    "sl_price": "止损价",
    "tp_price": "止盈价",
}

#: 平仓原因的**中文值**。引擎写的是英文码（SL/TP/time/eod），
#: 界面上直接显示英文码等于让用户去查文档。
EXIT_REASON_LABELS: dict[str, str] = {
    "SL": "止损",
    "TP": "止盈",
    "time": "到期",
    "eod": "收盘平仓",
    "take_profit": "止盈",
    "stop_loss": "止损",
}
