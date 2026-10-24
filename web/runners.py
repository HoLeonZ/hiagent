"""四引擎 → 统一接口。

单一职责：吸收四个引擎的签名差异，对外只暴露一个 `run()`。
不接触 HTTP、不接触前端、不写盘（写盘由 jobs 负责）。

## 下游契约（Task 6/7 必读）

**短窗语义不对称**：只有 `short_reversal` 在窗口/数据覆盖不足时**抛错**，
且本模块把它转成具名的 `WindowTooShortError` / `EngineInputError`（可映射 400）：
  - `short_reversal`：窗口太短 → `WindowTooShortError`；空 universe / 数据覆盖不足 →
    `EngineInputError`。
  - `chase_up` / `uptrend_pullback`：短窗**不抛异常**，静默返回 **0 笔**（空结果）。
  - `cycle_price_action`：短窗或停牌缺口会抛 **`RuntimeError`**（引擎自身缺陷，非本模块
    转换范围），HTTP 层对它没有 400 映射。
即：四个引擎对"我没跑出东西"的表达方式并不一致，调用方**不能**假设"0 笔"或"抛错"
可互换。本模块只统一**成功**返回的形状，不统一失败的语义。

**metrics schema 未统一**：四个引擎共有的键只有 `trades_count`（由本模块补，
`short_reversal` 是原生的）。同名不同型：`metrics["trades"]` 在 `short_reversal` 是
`list[dict]`、在 `chase_up`/`uptrend_pullback` 是 `int`。价值键分叉
（`final_capital`/`total_yield` vs `final_equity`/`total_return`）；`cycle` 的
`cagr`/`sharpe`/`max_dd` 恒为 `None`。规范 metrics 映射需在 Task 6/7 补。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from web.catalog import all_presets
from web.params import validate_overrides

#: preview 模式默认回看的自然日数。
#:
#: **这个数是算出来的，不是拍的。** 引擎侧的硬约束是 `short_reversal` 的
#: `min_bars=200`（101 个预设里 75 个用它），而面板跨度是 `窗口 + 180 前置 + 60 后置`。
#:
#: ⚠️ **关键：那 60 天"后置"只有在 `end` 比库内最后一个交易日早 ≥60 天时才有数据。**
#: 而 UI 默认 `end` 就是今天 —— 后置窗口是**空的**。
#: 这一点原先被算错了：
#:
#:   旧注释写"90 天预览的面板约 330 天 ≈ 225 个交易日，高于 min_bars=200"，
#:   它是按"后置有数据"算的。**按 UI 默认路径实测**（2026-10-19）：
#:
#:   | 窗口 | 面板实际覆盖 | 交易日数 | min_bars=200 |
#:   |---|---|---|---|
#:   | 90 天 | 2026-01-19..2026-10-16 | **178** | ❌ 抛 WindowTooShortError |
#:   | 120 天 | 2025-12-20..2026-10-16 | 196 | ❌ |
#:   | 150 天 | 2025-11-20..2026-10-16 | 218 | ✅ |
#:   | **200 天** | 2025-10-01..2026-10-16 | **248** | ✅（留 ~24% 余量） |
#:
#: 即：**旧的 90 天在 UI 默认路径上必然失败** —— preview 对 75/101 个预设跑不起来。
#: 取 200 是为了留出余量，而不是卡在边界上：测试用的是 `>= 1.1 × min_bars`，
#: 而"恰好等于 min_bars"这种擦边（旧测试正是 200 == 200）下次照样会漏。
PREVIEW_DAYS: int = 200

#: 引擎侧最严的 min_bars —— `short_reversal/engine.py:364` 的默认值。
#: 放在这里是为了让"preview 窗口够不够"这件事有一个**可断言的依据**，
#: 而不是靠注释里的一段算术。
STRICTEST_MIN_BARS: int = 200


class WindowTooShortError(ValueError):
    """窗口（含面板缓冲）不足以满足引擎的 min_bars。消息里必须含 min_bars。"""


class EngineInputError(ValueError):
    """引擎在**输入层面**拒绝本次运行（空 universe / 数据覆盖 / 参数硬约束等）。

    与 `WindowTooShortError` 同源：都是"这次请求的输入不对"，调用方应映射成 400，
    而不是 500。**任何**来自引擎的 `ValueError` 都必须在此具名化——裸 `ValueError`
    漏到 HTTP 层会变成 500，用户看不到真实原因。

    实测触发点（short_reversal/engine.py:426）：空 universe 守卫抛的 `ValueError`
    消息里**不含** `min_bars`（消息是 `preset {...} resolved an EMPTY universe ...`），
    故只靠子串判据会漏成裸 `ValueError`。
    """


@dataclass(frozen=True)
class RunResult:
    """一次回测的统一结果。

    `metrics` 是引擎自报的指标 dict（**schema 未跨引擎统一**，见模块 docstring）；
    `trades` 统一为 `list[dict]`，但**列集不统一**——`short_reversal` / `chase_up` /
    `uptrend_pullback` 是 `core/trade_schema.py` 的 14 列，`cycle_price_action` 的
    `TradeRecord` 只有 11 个字段（无 `exit_reason`/`gross_pnl`/`net_pnl`/`net_return`/
    `atr_pct`/`sub_signal_type`）。适配器只做容器归一，不做列级对齐。
    """

    engine: str
    preset: str
    start: str
    end: str
    metrics: dict[str, Any]
    trades: list[dict[str, Any]]


def effective_window(mode: str, start: str, end: str) -> tuple[str, str]:
    """按 mode 算出实际要跑的窗口。

    preview 只缩窗口、**不缩票池**——因为只有两个引擎支持注入受限面板
    （chase_up / uptrend_pullback 收 panel_ind），另两个要改生产入口。
    缩窗口让四个引擎走同一条代码路径（见设计文档 §7.1）。
    """
    if mode != "preview":
        return start, end
    end_d = dt.date.fromisoformat(end)
    start_d = max(dt.date.fromisoformat(start), end_d - dt.timedelta(days=PREVIEW_DAYS))
    return start_d.isoformat(), end_d.isoformat()


def _as_equity_curve(equity: Any) -> list[dict[str, Any]]:
    """把引擎的 equity 帧转成平台的曲线形状 `[{date, equity}, …]`。

    ⚠️ **只有 short_reversal 自带净值曲线**（`run_backtest_v3` 的 metrics 里就有
    `equity_curve`）。而 chase_up / uptrend_pullback 的引擎**其实已经算出了这条曲线** ——
    `chase_up/backtrader_engine.py` 返回 `{"metrics":…, "trades":…, "equity": equity_df}`
    （`equity_df` 的列是 `date/cash/holdings/equity`，见 `chase_up/portfolio.py`），
    **只是适配器把它丢掉了**。

    丢掉的后果不是"少一张图"：没有曲线时平台的结果页**头部收益曲线、每日收益、
    每日持仓全都没有**，指标表也退化成引擎口径（`window_metrics` 退回 `engine_scoped`）。

    `cycle_price_action` **真的没有**组合级净值曲线（它的账户按票独立，v1 做不出来）——
    那个引擎保持引擎口径，指标表会**标注**出来，不假装一致。
    """
    if equity is None:
        return []
    try:
        import pandas as pd

        if not isinstance(equity, pd.DataFrame) or equity.empty:
            return []
        if not {"date", "equity"} <= set(equity.columns):
            return []
        out = []
        for _, r in equity.iterrows():
            out.append({"date": str(r["date"])[:10], "equity": float(r["equity"])})
        return out
    except (TypeError, ValueError, KeyError):
        return []


def _as_trades(payload: Any) -> list[dict[str, Any]]:
    """把引擎返回的交易统一成 14 列规范的 list[dict]。

    四个引擎的 trades 形态各不相同，逐个吸收：
      - chase_up / uptrend_pullback：`res["trades"]` 是 pandas DataFrame → to_dict(records)
      - short_reversal：list[dict]（`t2 = dict(t)` 逐笔重建）
      - cycle_price_action：list[cycle_price_action.metrics.TradeRecord]（**frozen dataclass**）
        —— dataclass 实例**不可迭代**，`dict(t)` 会抛 `TypeError: 'TradeRecord' object
        is not iterable`，必须走 `dataclasses.asdict`。原 brief 的 `dict(t)` 只在
        cycle 恰好 0 笔时侥幸不报错（空列表短路），一旦有成交即崩。
    """
    if payload is None:
        return []
    if isinstance(payload, pd.DataFrame):
        return payload.to_dict(orient="records")
    out: list[dict[str, Any]] = []
    for t in payload:
        row = asdict(t) if (is_dataclass(t) and not isinstance(t, type)) else dict(t)
        out.append(_canonical_field_names(row))
    return out


#: 引擎自己的字段名 → 14 列规范名。**只做等价改名，不造值。**
#:
#: `cycle_price_action` 的 `TradeRecord` 用的是 `shares` / `pnl`，而平台与
#: `core.trade_schema.TRADE_COLS` 认的是 `size` / `net_pnl`。不改名的后果不是"少两列"：
#: `window_metrics` 用 `net_pnl` 算胜率与总盈亏，取不到就 `or 0.0`，
#: 于是**一次真赚钱的运行在结果页上显示"胜率 0.00% / 总盈亏 0.00"**（实测 2026-10-24，
#: cycle PRESET_V1 10 笔成交）—— 丢失被渲染成了零，正是 §0 明令禁止的。
#:
#: `pnl = net_out - gross_in`（`cycle_price_action/portfolio.py`），即**扣费后**的净盈亏，
#: 所以映射到 `net_pnl` 是等价的，不是猜测。
_FIELD_RENAMES: dict[str, str] = {"shares": "size", "pnl": "net_pnl"}


def _canonical_field_names(row: dict[str, Any]) -> dict[str, Any]:
    """把引擎自己的字段名换成规范名。**目标已存在时不覆盖**（规范名优先）。"""
    for src, dst in _FIELD_RENAMES.items():
        if src in row and dst not in row:
            row[dst] = row.pop(src)
    return row


def _run_short_reversal(preset: str, start: str, end: str, db: Path, params: dict) -> RunResult:
    from short_reversal.engine import run_backtest_v3

    # ⚠️ 必须传 `params`（dict）而不是 `preset`（名字）——传名字会让平台侧的覆盖被静默丢弃
    # （见 Step 3.0）。引擎默认 min_bars=200（与 CLI 一致）；窗口太短时引擎抛 F-01。
    try:
        m = run_backtest_v3(params, start, end, db)
    except ValueError as exc:
        if "min_bars" in str(exc):
            raise WindowTooShortError(str(exc)) from exc
        # 其余引擎 ValueError（空 universe / 数据覆盖 / 参数硬约束）一律具名化：
        # 绝不以裸 ValueError 漏到 HTTP 层——那会变成 500，而这些都是**输入**问题 → 400。
        # （实测触发点：空 universe 守卫的消息不含 min_bars，旧写法会漏。）
        raise EngineInputError(str(exc)) from exc
    return RunResult("short_reversal", preset, start, end, m, _as_trades(m.get("trades")))


def _run_chase_up(preset: str, start: str, end: str, db: Path, params: dict) -> RunResult:
    from chase_up.backtest import run_backtest

    # chase_up / uptrend_pullback 的 `run_backtest` 返回的是包装 dict
    #   `{"metrics": <指标>, "trades": <DataFrame>, "equity": <DataFrame>}`，
    # **不是**指标本身（与 short_reversal 直接返回指标 dict 不同）。
    # 若把整个包装当 metrics，RunResult.metrics 会塞进两个 DataFrame 且没有
    # `trades_count`——形状不统一，正是本适配器要消灭的差异。
    res = run_backtest(params, start, end, db)
    metrics = dict(res.get("metrics") or {})
    trades = _as_trades(res.get("trades"))
    metrics.setdefault("trades_count", len(trades))
    # 引擎**已经把净值曲线算出来了**（在返回值的 `equity` 里），接回来 ——
    # 否则结果页的收益曲线、每日收益、每日持仓全都没有。
    curve = _as_equity_curve(res.get("equity"))
    if curve:
        metrics["equity_curve"] = curve
    return RunResult("chase_up", preset, start, end, metrics, trades)


def _run_uptrend_pullback(preset: str, start: str, end: str, db: Path, params: dict) -> RunResult:
    from uptrend_pullback.backtest import run_backtest

    # 见 `_run_chase_up`：同样是 `{"metrics", "trades", "equity"}` 包装 dict。
    res = run_backtest(params, start, end, db)
    metrics = dict(res.get("metrics") or {})
    trades = _as_trades(res.get("trades"))
    metrics.setdefault("trades_count", len(trades))
    # 同 chase_up：引擎已算出曲线，接回来（见 `_as_equity_curve` 的说明）。
    curve = _as_equity_curve(res.get("equity"))
    if curve:
        metrics["equity_curve"] = curve
    return RunResult("uptrend_pullback", preset, start, end, metrics, trades)


def _run_cycle_price_action(preset: str, start: str, end: str, db: Path, params: dict) -> RunResult:
    """cycle 收 date 对象、返回 dataclass、且没有 PRESETS——差异最多，逐个吸收。"""
    from cycle_price_action.backtest import run_backtest

    res = run_backtest(db, dt.date.fromisoformat(start), dt.date.fromisoformat(end),
                       preset=params)
    metrics = dict(getattr(res, "metrics", {}) or {})
    trades = _as_trades(getattr(res, "trades", None))
    metrics.setdefault("trades_count", len(trades))
    return RunResult("cycle_price_action", preset, start, end, metrics, trades)


_RUNNERS = {
    "short_reversal": _run_short_reversal,
    "chase_up": _run_chase_up,
    "uptrend_pullback": _run_uptrend_pullback,
    "cycle_price_action": _run_cycle_price_action,
}


def run(
    engine: str,
    preset: str,
    start: str,
    end: str,
    *,
    overrides: dict[str, Any] | None = None,
    mode: str = "full",
) -> RunResult:
    """跑一次回测，返回统一形状。"""
    from hiagent_config import get_db_path

    if engine not in _RUNNERS:
        raise KeyError(f"unknown engine: {engine}")

    presets = all_presets()
    if preset not in presets.get(engine, {}):
        raise KeyError(f"unknown preset: {preset} for engine {engine}")

    clean = validate_overrides(engine, preset, overrides or {})
    params = dict(presets[engine][preset])
    params.update(clean)

    # 注入真名（评审焦点 2）：short_reversal 引擎把 `cfg["_name"]` 当作 metrics["preset"]
    # 与 ensemble 汇总标签；平台走 **dict** 通路，不注入就会落成 `"<dict>"`（实测）。
    # 这里在 `validate_overrides` **之后**、调引擎**之前**注入，故：
    #   - 不触碰校验（`_name` 从不出现在 overrides 里）；
    #   - 完全不改变字符串调用路径（平台永远走 dict 路径）；
    #   - 另三个引擎用 `p.get(...)` / `_accepted` 白名单取参，多出的 `_name` 被忽略。
    params["_name"] = preset

    eff_start, eff_end = effective_window(mode, start, end)
    return _RUNNERS[engine](preset, eff_start, eff_end, get_db_path(), params)
