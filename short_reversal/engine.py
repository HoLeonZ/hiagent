"""v3 事件驱动 backtest 编排（唯一对外入口）。

run_backtest_v3() 跑一个 preset，返回 metrics dict。

Universe 走 load_universe_asof：剔除 asof_date 之后才上市的票，
严格消除 survivorship bias（DuckDB 无历史成分表，能做的最小代理）。

§6 architecture (Tick 40, 2026-09-28): panel loading lives in Control Plane
helper `short_reversal._panel_loader`. The `_load_panel` thin wrapper here
exists only to preserve the import surface for `lookahead_trade_trace.py`
and tests that monkeypatch the function name (e.g.
tests/test_short_reversal_v8_plumbing.py:79, :112). It does NOT open duckdb
itself.
"""
from __future__ import annotations

import math
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from short_reversal._panel_loader import (
    PANEL_FORWARD_BUFFER_DAYS,
    load_panel_for_backtest,
)
from short_reversal.feed_bt import build_per_stock_feeds
from short_reversal.presets import PRESETS, get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

# §2 single-source (2026-10-14 审计修正): 规范费率从 core.dual_price 导入。
# 此前为模块级重复定义, 且注释谎称"已从 core.dual_price 导入" (实际无 import)。
from core.dual_price import COMMISSION_RATE, STAMP_DUTY_RATE

INITIAL_CAPITAL = 1_000_000.0
# MARGIN_RATE (融券年化费率) 无 canonical 源, 保留本地定义。
MARGIN_RATE = 0.086
DAYS_PER_YEAR = 365

# Re-export for back-compat: tests/golden baselines reference this constant.
PANEL_FORWARD_BUFFER_DAYS = PANEL_FORWARD_BUFFER_DAYS


def _load_panel(db_path: Path, start: str, end: str, universe: list[str]) -> pd.DataFrame:
    """Thin wrapper delegating to Control Plane panel loader (CLAUDE.md §6).

    The actual DuckDB I/O is owned by
    `short_reversal._panel_loader.load_panel_for_backtest`. This wrapper
    exists only to preserve the import surface for callers that
    `from short_reversal.engine import _load_panel` (notably
    short_reversal.lookahead_trade_trace and tests that monkeypatch
    the function name).
    """
    return load_panel_for_backtest(db_path, start, end, universe)


def _metrics_from_holder(holder: dict, start: str, end: str, cfg: dict) -> dict:
    """从 result_holder + 区间算出最终 metrics dict。"""
    final_capital = float(holder["cash"])
    trades = holder["trades"]
    trades_count = len(trades)

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / DAYS_PER_YEAR,
        1.0 / DAYS_PER_YEAR,
    )
    total_yield = final_capital / INITIAL_CAPITAL - 1
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1 if final_capital > 0 else -1.0

    wins = sum(1 for t in trades if t["net"] > 0)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    avg_pnl = float(np.mean([t["net"] for t in trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in trades])) if trades_count > 0 else 0.0

    # 简单 Sharpe: 日 PnL 序列 → 年化
    sharpe = _approx_sharpe(trades)

    # exit reason 计数
    tp_count = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in trades if t["exit_reason"] == "time")

    # §5 日净值口径: 逐 bar 净值序列由 Phase3V3Strategy 在 next() 第 5 步写入
    # result_holder["equity_curve"] (replay_strategy_v3.py 的 recorder), stop()
    # 用 update() 合并保留。原实现把它丢掉了, main.py 读 m.get("equity_curve")
    # 恒为 None → equity_curve.csv 从未产出, 没有日净值就没有日频 Sharpe, 也就没有
    # 可信的 DSR。纯透传: 不排序、不改 date 类型 (记录器存的是 datetime.date),
    # 也不在这里新建第二个记录器。
    # 直接索引 holder["equity_curve"] 而不是 .get("equity_curve", []): 该键由策略
    # next() 的 setdefault 建立, 跑过一根 bar 就一定在; 没跑过则由 F-01 守卫在上游
    # 拦下。写成 .get(..., []) 会把"记录器停止了记录"降级成"一条空曲线", 而空曲线在
    # _weighted_equity_curve 里会被当成"该腿每根 bar 都还没跑", 静默编造平坦贡献。
    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "trades": trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": min(1.0, max(0.0, float(holder["max_dd"]))),
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
        "equity_curve": holder["equity_curve"],
    }


def _approx_sharpe(trades: list[dict]) -> float:
    """无日 PnL 序列 → 用每笔 net 估算 sharpe（粗略，仅供排序）。"""
    if not trades:
        return 0.0
    arr = np.array([t["net"] for t in trades])
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    if std < 1e-9:
        return 0.0
    # 假设 ~250 笔/年，按交易频率缩放
    return float(mean / std * math.sqrt(min(len(arr), 250)))


def _weighted_equity_curve(
    curves: list[list[dict]], weights: list[float]
) -> list[dict]:
    """按腿加权合成 ensemble 的日净值曲线 (CLAUDE.md §1/§2)。

    口径必须与 `_run_ensemble` 的 `final_capital = Σ w_i · final_capital_i`
    一致: `equity_ens(d) = Σ w_i · equity_i(d)`。各腿都跑在**同一条主时钟**
    (同一 panel / 同一 calendar) 上, 所以按 `date` 对齐即可; 换了别的合成方式,
    曲线末端就会与该函数自己报的 final_capital 对不上。

    `cash` 与 `holdings_value` 用**同样的权重**逐日合成 —— 只合成 equity 而让
    这两个字段缺省会破坏记录器自身的恒等式
    `equity == cash + holdings_value` (逐项线性组合 ⇒ 恒等式仍然成立), 而这是
    唯一与「当日是否持仓」无关的结构性断言。

    §2 三池 (`free_cash` / `locked_margin` / `settling_funds`) 同样按权重合成:
    ensemble 行必须与单腿行 **schema 完全一致**。少了这三个键, main.py 的
    cash_walk.csv 在 ensemble 路径上又会静默回落到硬编码的 0.0 —— 也就是
    tests/test_short_reversal_daily_equity.py::test_rows_carry_the_three_cash_pools
    记录的那个缺陷, 只是换到了另一条路径上。池的加权和恰等于 `cash` 的加权和
    (每腿都有 free + locked + settling = total), 所以对账关系仍然成立。
    腿行缺键时直接 KeyError 而不是补默认值 —— 见下方 else 分支的注释。

    §1 缺失值语义: 某腿在某日缺行 (该腿 panel 没有该交易日) 时, 该腿当日按
    **前值**参与加权 —— 只向前填充, 绝不向后填充 (`bfill` 是 §1 明令禁止的)。
    某腿首行之前的日期, 该腿尚未产生任何成交, 按 `w_i · INITIAL_CAPITAL` 计:
    那是它当时的真实状态 (现金未动、无持仓), 不含任何未来信息。

    `drawdown` 不做腿间加权 —— 各腿的峰值不同, 加权平均没有意义。它由合成后的
    净值的 running peak 算出, 即该组合自身的当日回撤 (与单腿记录器同一定义)。
    """
    legs = [
        sorted(
            [row for row in curve if row.get("date") is not None],
            key=lambda row: row["date"],
        )
        for curve in curves
    ]
    # 空曲线绝不是合法状态, 必须显式抛错 —— 这是「该腿没有可用行」的真正拦截点。
    # 直接索引只堵住「键不存在」这一个入口; 「键在但列表为空」是第二个入口, 少了这道
    # 闸, 该腿会在下面每一天都落进 row is None 分支, 凭空合成 w_i · INITIAL_CAPITAL
    # —— 一条 keys 齐全、首行 1M、对账也成立的**假曲线**, 而同 dict 的 final_capital
    # 却是按真实腿算的。生产中真正能走到的触发点是「该腿所有行的 date 都是 None」:
    # 记录器的 append 是无条件的且写在 try 之外, 所以 next() 只要跑过就一定有行; 而
    # 日期提取 (replay_strategy_v3.py:557-562) 捕获过宽, 会把 date 存成 None, 于是被
    # 上面的过滤器清空。所以这道闸必须在**过滤器之后** —— 挪到前面, 全 None 的腿在
    # 过滤前非空、会绕过闸门, 过滤后却变空, 正好回到上面那条假曲线。
    for i, leg in enumerate(legs):
        if not leg:
            raise ValueError(
                f"leg {i} produced an empty equity curve: no row survived with a "
                f"date (the recorder appends one row per bar unconditionally, so "
                f"this means every row of that leg had date=None and was filtered "
                f"out). Aggregating it would fabricate a flat "
                f"w_i * INITIAL_CAPITAL contribution."
            )
    dates = sorted({row["date"] for leg in legs for row in leg})
    if not dates:
        return []

    n_legs = len(legs)
    cursor = [0] * n_legs
    latest: list[dict | None] = [None] * n_legs
    peak = 0.0
    out: list[dict] = []

    for day in dates:
        cash = 0.0
        free_cash = 0.0
        locked_margin = 0.0
        settling_funds = 0.0
        holdings_value = 0.0
        equity = 0.0
        for i in range(n_legs):
            leg = legs[i]
            # 只向前推进游标: 取该腿上 date <= day 的最后一行 (ffill)。
            while cursor[i] < len(leg) and leg[cursor[i]]["date"] <= day:
                latest[i] = leg[cursor[i]]
                cursor[i] += 1
            row = latest[i]
            if row is None:
                # 该腿当日尚无记录 → 尚未交易的初始资金 (不是未来信息)。
                # 未动用的现金全在 free 池, 另两池为 0。
                leg_cash = INITIAL_CAPITAL
                leg_holdings = 0.0
                leg_equity = INITIAL_CAPITAL
                leg_locked = 0.0
                leg_settling = 0.0
                leg_free = INITIAL_CAPITAL
            else:
                # 直接索引, 不用 .get(...) 兜底: 腿行一旦缺键就 KeyError (fail-fast,
                # 与 check_conditions 里 params["X"] 同一套推理)。兜底正是本任务要
                # 消灭的那个缺陷 —— main.py 的 row.get("locked_margin", 0.0) 让缺失
                # 的池字段静默变成硬编码 0.0, 产出的 CSV 看起来完全正常。而且兜底会
                # 让本函数自己凑出全部字段, 使 ensemble 那侧的池对账断言变成恒真 ——
                # 断言就再也测不到任何东西。
                leg_cash = float(row["cash"])
                leg_holdings = float(row["holdings_value"])
                leg_equity = float(row["equity"])
                leg_locked = float(row["locked_margin"])
                leg_settling = float(row["settling_funds"])
                leg_free = float(row["free_cash"])
            w = weights[i]
            cash += w * leg_cash
            free_cash += w * leg_free
            locked_margin += w * leg_locked
            settling_funds += w * leg_settling
            holdings_value += w * leg_holdings
            equity += w * leg_equity

        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        out.append({
            "date": day,
            "cash": cash,
            "free_cash": free_cash,
            "locked_margin": locked_margin,
            "settling_funds": settling_funds,
            "holdings_value": holdings_value,
            "equity": equity,
            "drawdown": drawdown,
        })
    return out


def _run_ensemble(
    cfg: dict,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int,
    signal_log: list | None = None,
    universe_as_of: str | None = None,
) -> dict:
    """v63 ensemble: 跑 N 个子策略, 资金等分, 汇总 metrics。

    假设: 各子策略完全独立 (不同 universe / 不同条件), 资金均分
    (每份 = INITIAL_CAPITAL / N)。汇总方法:
      - final_capital = sum(sub_i.final_capital / N) over all i
      - max_dd = max(sub_i.max_dd) over all i  (worst-case DD, 保守口径)
      - trades = concat(sub_i.trades), 按时间排序

    验证: 4×6mo WFV (2024-2025) + 2026-H2 holdout, OOS 表现一致优于
    v50_slope (mean Calmar +10.9%, holdout +5.4%)。
    """
    sub_names = cfg["ensemble_substrategies"]
    n = len(sub_names)
    if n < 2:
        raise ValueError(f"ensemble needs ≥2 sub-strategies, got {n}")
    weight = cfg.get("ensemble_weight", 1.0 / n)
    weights = [weight] * n  # 等权; 未来可加自定义权重

    sub_results = []
    for name in sub_names:
        sub_cfg = dict(get_preset(name))
        sub_cfg["_name"] = name
        # 递归调用 run_backtest_v3 (会跳过 ensemble check, 走标准路径)
        sub_results.append(
            run_backtest_v3(
                name, start, end, db_path, min_bars,
                signal_log=signal_log, universe_as_of=universe_as_of,
            )
        )

    # 汇总 PnL: 等权 final_capital
    final_capital = sum(r["final_capital"] * w for r, w in zip(sub_results, weights))
    total_yield = final_capital / INITIAL_CAPITAL - 1
    # 保守 max_dd: 任一子策略的最大 DD (实际投资组合 DD ≤ 线性叠加上界)
    max_dd = max(r["max_dd"] for r in sub_results)

    # 合并 trades (按时间排序, 标 sub-strategy 来源)
    all_trades = []
    for r, name in zip(sub_results, sub_names):
        for t in r["trades"]:
            t2 = dict(t)
            t2["ensemble_sub"] = name
            all_trades.append(t2)
    all_trades.sort(key=lambda t: t.get("entry_time", ""))

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / DAYS_PER_YEAR,
        1.0 / DAYS_PER_YEAR,
    )
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1

    wins = sum(1 for t in all_trades if t["net"] > 0)
    trades_count = len(all_trades)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    avg_pnl = float(np.mean([t["net"] for t in all_trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in all_trades])) if trades_count > 0 else 0.0
    sharpe = _approx_sharpe(all_trades)
    tp_count = sum(1 for t in all_trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in all_trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in all_trades if t["exit_reason"] == "time")

    # §5 日净值口径: run_backtest_v3 对 ensemble 提前 return, 走不到
    # _metrics_from_holder, 所以 ensemble 必须自己合成净值曲线 —— 否则三个候选
    # ensemble 全都没有 equity_curve (Task 8 的对比 + 日频 Sharpe 直接卡死)。
    # 合成口径与上面的 final_capital 完全一致 (Σ w_i · x_i)。
    # 直接索引 r["equity_curve"], 与上面两行 r["trades"] 同一形式: 某腿没产出曲线
    # 就是那条腿的路径坏了, 必须 KeyError 炸出来。用 .get(...) or [] 兜底的话, 该腿
    # 会在每一天都退化成 row is None 分支的 INITIAL_CAPITAL —— 合成出一条**水平假
    # 曲线**, 而 keys/首行 1M/对账全都依然"正常", 同时同一个 dict 的 final_capital
    # 却是按真实腿算的。那是 fail-fast 的反面: 平坦的线正好掩盖了坏掉的路径。
    equity_curve = _weighted_equity_curve(
        [r["equity_curve"] for r in sub_results], weights
    )

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "trades": all_trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": min(1.0, max(0.0, float(max_dd))),
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
        "ensemble_subs": sub_names,
        "equity_curve": equity_curve,
    }


def run_backtest_v3(
    preset: str,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int = 200,
    signal_log: list | None = None,
    universe_as_of: str | None = None,
) -> dict:
    """跑 v3 引擎返回 metrics dict。

    参数:
      preset: PRESETS 里的 preset name
      start / end: 回测区间 (YYYY-MM-DD)
      db_path: DuckDB 文件路径
      min_bars: 每只票最少需要的 bar 数;2-month 滚动窗口期间 panel 跨春节可能
                只有 ~197 trading days,这时可下调到 150,NaN gate 会兜底。
      signal_log: 只读诊断旁路 (§6)。非 None 时, 策略每评估一根 bar 就向该
                list 追加一条 {"preset", "thscode", "date", "passed",
                "failed_at"} 记录; None (默认) 时完全惰性, 行为逐字节不变。
                条目里的 preset 标签取自本函数的 preset 形参本身, 所以
                ensemble 逐腿调用时会自动落成腿名。
      universe_as_of: universe 的 as-of 日期 (load_universe_asof 语义: 首现日
                ≤ as-of)。None (默认) 时取 `start` —— 回测路径行为逐字节不变。
                线上信号作业必须显式传 signal_date: 它用 panel_start =
                signal_date - 400d 换取 MA60/126 日回报的预热, 若 universe 跟着
                解析在 panel_start 上, 会把 signal_date 前 400 天内上市的票
                全部静默排除 (实测 36 只 / 1.13%, 全是最近上市的那批)。
                那是面板算术的副作用, 不是策略规则 —— 策略只用 min_bars
                闸门判定暖机不足。
    """
    cfg = dict(get_preset(preset))
    cfg["_name"] = preset

    # v63 (2026-10-13): Ensemble 模式 — 跑 N 个子策略, 资金等分, 汇总 PnL。
    # OOS-validated (WFV mean +10.9%, holdout 2026-H2 +5.4%) over v50_slope.
    # 实现是 N 个独立 backtest 的 wrapper, 复用 v3 引擎, 行为等价。
    if "ensemble_substrategies" in cfg:
        return _run_ensemble(
            cfg, start, end, db_path, min_bars,
            signal_log=signal_log, universe_as_of=universe_as_of,
        )

    asof = universe_as_of if universe_as_of is not None else start
    universe = load_universe_asof(
        cfg["universe"],
        # NOT `universe_as_of or start`: `or` treats an empty string as absent
        # and silently reverts to `start` — the same silent-fallback shape that
        # Task 2 removed from check_conditions. A bogus caller value must fail
        # loudly, not quietly resolve a different universe.
        asof,
        db_path,
    )
    # §0 fail-fast (2026-10-18): 空 universe 不再静默产出 0 笔 (F-01 的近亲, R10)。
    # load_universe_asof 用「首现日 ≤ as-of」做代理, as-of 早于数据地板
    # (raw_kline_daily min(date)) 或 DB 缺该日覆盖时返回 []。空 universe →
    # panel 无行 → build_per_stock_feeds 的 `if codes and not feeds` 守卫**不触发**
    # (codes 为空) → cerebro 无 feed → next() 从不执行 → 记录器 setdefault 从不运行
    # → _metrics_from_holder 直接索引 holder["equity_curve"] 抛裸 KeyError("equity_curve")。
    # 「什么都没评估」与「市场当天没信号」在输出上必须可区分, 故这里具名抛错。
    if not universe:
        raise ValueError(
            f"preset {preset!r} resolved an EMPTY universe (mode "
            f"{cfg['universe']!r}) as-of {asof} from {db_path}: "
            f"load_universe_asof returns [] when the as-of predates the data "
            f"floor (raw_kline_daily min(date)) or the DB lacks coverage for "
            f"this date. An empty universe evaluates nothing — reporting 0 "
            f"trades here would be indistinguishable from a quiet market. This "
            f"is a window/data-coverage problem, not a signal (§0 fail-fast): "
            f"widen the [start, end] window, sync the DB, or pick an as-of with "
            f"data coverage."
        )
    panel = _load_panel(db_path, start, end, universe)
    feeds = build_per_stock_feeds(panel, universe, min_bars=min_bars)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=0.0)  # 成本由 strategy 内扣

    holder: dict = {"cash": INITIAL_CAPITAL, "trades": [], "max_dd": 0.0}

    for code, feed in feeds:
        cerebro.adddata(feed, name=code)
    cerebro.addstrategy(
        Phase3V3Strategy,
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"],
        # v58 (2026-10-13): 多仓并行。max_positions > 1 时每笔 sizing 改为
        # free_cash / max_positions, 维持 all-in 总仓位。默认 1 保 v50 兼容。
        max_positions=cfg.get("max_positions", 1),
        position_fraction=cfg.get("position_fraction", 1.0),
        pct_chg_low=cfg.get("pct_chg_low", 0.02),
        pct_chg_high=cfg.get("pct_chg_high", 0.06),
        a_condition=cfg.get("a_condition", "default"),
        up_streak_low=cfg.get("up_streak_low", 3),
        up_streak_high=cfg.get("up_streak_high", 10),
        liq_low=cfg.get("liq_low", 3e7),
        liq_high=cfg.get("liq_high", 3e8),
        below_ratio_60=cfg.get("below_ratio_60", 0.6),
        close_ma60_buffer=cfg.get("close_ma60_buffer", 0.0),
        d_mode=cfg.get("d_mode", "strict"),
        margin_rate=MARGIN_RATE,
        commission_rate=COMMISSION_RATE,
        stamp_duty_rate=STAMP_DUTY_RATE,
        initial_capital=INITIAL_CAPITAL,
        lot_size=100,
        min_cash_ratio=cfg.get("min_cash_ratio", 0.05),
        # V5' (2026-09-22, CLAUDE.md §4): ATR-aware slippage is opt-in via preset。
        # 默认 0.0 = baseline parity (无 slippage), preset 可上调启用真实市场摩擦。
        atr_slip_scale=cfg.get("atr_slip_scale", 0.0),
        # V8 (2026-09-22, CLAUDE.md §4): max_volume_participation 与 intraday_tiebreak
        # 从 preset 显式 plumb 到 strategy (而非依赖模块常量/默认值)。
        # 当前 preset 默认 0.10 / 'sl_first', 完整覆盖 11/11 preset。
        max_volume_participation=cfg.get("max_volume_participation", 0.10),
        intraday_tiebreak=cfg.get("intraday_tiebreak", "sl_first"),
        # v50 (2026-10-12): F 条件 — MA20 下降趋势斜率过滤 (opt-in)。
        require_ma20_slope_neg=cfg.get("require_ma20_slope_neg", False),
        ma20_slope_period=cfg.get("ma20_slope_period", 5),
        ma20_slope_threshold=cfg.get("ma20_slope_threshold", 0.0),
        # v51 (2026-10-12): G 条件 — 弱势股过滤 (1M/3M/6M 累计跌幅, opt-in)。
        require_weak_1m=cfg.get("require_weak_1m", False),
        weak_1m_threshold=cfg.get("weak_1m_threshold", -0.05),
        require_weak_3m=cfg.get("require_weak_3m", False),
        weak_3m_threshold=cfg.get("weak_3m_threshold", -0.10),
        require_weak_6m=cfg.get("require_weak_6m", False),
        weak_6m_threshold=cfg.get("weak_6m_threshold", -0.15),
        # v52 (2026-10-12): H 条件 — 无成交下跌过滤 (5d/20d 成交金额比率, opt-in)。
        # v51 测绝对跌幅 (cumret) 失败, 改测资金流衰减: 卖压枯竭 = 死猫跳最佳入场。
        require_amount_dryup=cfg.get("require_amount_dryup", False),
        amount_dryup_threshold=cfg.get("amount_dryup_threshold", 0.70),
        amount_dryup_short=cfg.get("amount_dryup_short", 5),
        amount_dryup_long=cfg.get("amount_dryup_long", 20),
        # v53 (2026-10-12): I 条件 — RSI(14) 超卖过滤 (opt-in)。
        # v52 (H 资金流 dry-up) 失败, 用户选 B 方向: 测价格动量超卖。
        require_rsi_oversold=cfg.get("require_rsi_oversold", False),
        rsi_oversold_threshold=cfg.get("rsi_oversold_threshold", 30),
        rsi_period=cfg.get("rsi_period", 14),
        # v57 (2026-10-12): J 条件 — SL 之后冷静期 (opt-in)。
        # 若上一笔以 SL 出场, 强制 N 日全局冷却, 跳过最强信号。
        # max_positions=1 时 J 是「全局」冷却, 因为单仓策略同一时间只持 1 笔。
        sl_cooldown_days=cfg.get("sl_cooldown_days", 0),
        # v61 (2026-10-13): K 条件 — 日内反转 (intraday reversal, opt-in)。
        # 与 F (多日趋势) 正交: K 测「单日 close 在 day range 中的位置 + 收阳」。
        # 死猫跳最经典微观结构 → 多仓顺势加码,空仓博弈次日的失败回吐。
        require_intraday_reversal=cfg.get("require_intraday_reversal", False),
        intraday_reversal_threshold=cfg.get("intraday_reversal_threshold", 0.6),
        intraday_reversal_require_close_above_open=cfg.get(
            "intraday_reversal_require_close_above_open", True
        ),
        # v65 (2026-10-13): 浮动止损 (trailing stop, short-side, opt-in)。
        trailing_stop_pct=cfg.get("trailing_stop_pct", 0.0),
        trailing_activation_pct=cfg.get("trailing_activation_pct", 0.0),
        # v66 (2026-10-13): 市场宽度 regime gate (opt-in)。
        require_market_breadth_bear=cfg.get("require_market_breadth_bear", False),
        market_breadth_max=cfg.get("market_breadth_max", 0.5),
        # v68 (2026-10-13, §2): conviction-based 填充选择 (opt-in)。
        entry_selection=cfg.get("entry_selection", "first"),
        # v81 (2026-10-14, §3): 信号价格域 ('raw' 默认兼容 / 'adj' §3 合规)。
        signal_price_domain=cfg.get("signal_price_domain", "adj"),
        # 诊断旁路 (§6): 只读, None 时策略完全不触碰该属性。标签用 preset 形参
        # 本身 —— ensemble 逐腿调用 run_backtest_v3(name, ...) 时自动落成腿名。
        signal_log=signal_log,
        signal_log_tag=preset,
        result_holder=holder,
    )
    cerebro.run()
    return _metrics_from_holder(holder, start, end, cfg)
