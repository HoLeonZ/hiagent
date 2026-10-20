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
from short_reversal.presets import ENSEMBLE_SPLIT, PRESETS, get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

# §2 single-source (2026-10-14 审计修正): 规范费率从 core.dual_price 导入。
# 此前为模块级重复定义, 且注释谎称"已从 core.dual_price 导入" (实际无 import)。
from core.dual_price import (
    resolve_atr_slip_scale,
    BORROW_RATE_ANNUAL,
    COMMISSION_RATE,
    STAMP_DUTY_RATE,
)
from core.preset_contract import (  # §0/§2/§3 (audit 2026-10-15)
    ALL_IN,
    EXECUTION_PRICE_SOURCE,
    resolve_execution_price_source,
    resolve_max_positions,
    resolve_nav_gate_ratio,
    resolve_position_fraction,
    resolve_position_sizing,
    resolve_volume_participation,
)
from core.trade_schema import annualized_years  # §2 年化单源 (audit 2026-10-15)
from core.walkforward import window_trading_days  # §5 窗口交易日数单源 (附八十一)

INITIAL_CAPITAL = 1_000_000.0
# §4 (audit P2-11, 2026-10-15): 融券年化费率改为 core 单源并再导出
# (scan_signals / lookahead_trade_trace 从本模块引用 MARGIN_RATE)。
# 此前注释写"无 canonical 源,保留本地定义",而 presets.py 的
# BORROW_ASSUMPTION.borrow_cost_rate 又独立写了同一个 0.086 —— 同值不同源。
MARGIN_RATE = BORROW_RATE_ANNUAL

#: 年化常数(交易日/年), 用于 `_equity_sharpe`(姊妹口径的日权益 Sharpe)。
#: **本文件不重写它** —— 它不是本模块的常数: §2 单源, 见 `core.trade_schema`,
#: 且 `tests/test_annualization_basis.py` 明令短侧不得自定该值。
#: 由规范助手反推而不是手打 243 —— 手打就是"同值不同源", 即下一次漂移的起点。
ANN_TRADING_DAYS = int(round(1.0 / annualized_years(1)))

# §13.89: 口径**自披露**的单一来源 (与 metrics 里报出的 `metrics_basis` 同源)。
# ⚠️ 取值按**合并后**的引擎状态填写, 不是任一分支各自的期望值:
#   * `trading_days` = core.trade_schema 的规范常数(A 股交易日/年), 由上面反推;
#   * `cagr`/`total_yield` 的年数分母 = **窗口内**交易日数 (单源
#     `core.walkforward.window_trading_days`), 与 chase_up / uptrend / cycle 同口径 ——
#     **不再**取"实测期"(那条口径是本分支的, 与 DSR 的 T 单源冲突);
#   * `win_rate` / `sharpe` 走**含 ¥5 最低佣金下限**的规范化字段
#     (`net_pnl` / `net_return`), 不用纯费率的旧兼容字段 `net`;
#   * 实测期(start/end)仍随产物发布, 见 metrics 的 `evaluated_*`;
#     姊妹口径的 Sharpe 见 `sharpe_equity_basis`。
#: 未统一项(§5/§6, 登记不擅改): `cycle_price_action` 仍用 252 ⇒ 两族的日权益
#: Sharpe 相差 √(252/ANN_TRADING_DAYS) ≈ 1.8%。只影响标度, 不影响排序。
METRICS_BASIS = {
    "trading_days": ANN_TRADING_DAYS,
    "sharpe": "per_trade_ratio_approx",  # 与 metrics 的 `sharpe_kind` 同词
    "cagr_denominator": "window_trading_days",
    "win_rate_field": "net_pnl",
    "max_dd": "nav_mtm",  # ensemble 路径例外: 见 _run_ensemble 的 max(sub_i)
}

# Re-export for back-compat: tests/golden baselines reference this constant.
PANEL_FORWARD_BUFFER_DAYS = PANEL_FORWARD_BUFFER_DAYS


def _benchmark_block(panel, total_return: float) -> dict:
    """§5:基准收益 + 相对超额。见 core/benchmark.py 的选择理由。

    基准**算不出时**(窗口内没有可构成买入持有的标的)发布 `None`,不是 0.0 ——
    否则 `excess_return` 会等于总收益,读起来像"基准没动",与真实的 0% 不可区分
    (与 `profit_factor` 的 None 口径一致)。
    """
    from core.benchmark import BENCHMARK_KIND_EQUAL_WEIGHT, equal_weight_basket_return

    bench, n_members = equal_weight_basket_return(panel)
    return {
        # 数字必须带着它的含义一起发布(与 sharpe_kind / n_daily_returns 同一原则):
        # "超额 +3%"在没说明基准是什么之前,不是一个可引用的结论。
        "benchmark_kind": BENCHMARK_KIND_EQUAL_WEIGHT,
        "benchmark_return": bench,
        "benchmark_members": n_members,
        "excess_return": None if bench is None else total_return - bench,
    }


def strategy_kwargs(cfg: dict, name: str, *, holder: dict, start: str, end: str) -> dict:
    """构造 `Phase3V3Strategy` 的**全部**参数(§6 单源)。

    生产入口(`engine.run_backtest_v3`)与实时扫描工具(`scan_signals._scan_preset`)
    必须用**同一份**构造逻辑 —— 否则后者会以默认值评估 opt-in 开关,给出与回测
    不一致的信号集。2026-10-16 实测:`scan_signals` 只传了参数子集,连 §2 的
    `nav_gate_ratio`(必须由声明解析后注入)都没传 ⇒ **直接崩溃**;而即便补上那一个,
    它的 F/G/H/I/J/K 等开关仍全部走默认值 ⇒ 信号集偏多(与快速扫描器同一类错)。

    新增策略参数时**只改这里** —— 两个构造点会同时跟上(附三十八)。
    """
    return dict(
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"],
        # v58 (2026-10-13): 多仓并行。max_positions > 1 时每笔 sizing 改为
        # free_cash / max_positions, 维持 all-in 总仓位。默认 1 保 v50 兼容。
        # §2 (audit 2026-10-17): 声明必须到达引擎。本引擎**没有物理容量上限**
        # (按 free_cash/N 分散、容量闸门逐 bar 约束),故 capacity=None ——
        # 只强制"必须声明",不编一个假的上界。
        max_positions=resolve_max_positions(cfg, name),
        # §2 (audit 2026-10-15): 经规范契约解析(缺声明/越界 fail-fast),不再
        # `cfg.get(..., 1.0)` —— 那样「没声明」与「声明为 1.0」不可区分。
        position_fraction=resolve_position_fraction(cfg, name),
        # §2 (audit 2026-10-15): 单腿路径只可能是 all_in(集成路径已在上面分流)。
        position_sizing=resolve_position_sizing(cfg, name, allowed=frozenset({ALL_IN})),
        # §3 (audit 2026-10-15): 上面已解析(碰库之前),此处只注入。
        # §3: 在 helper 内部解析(原先是调用方的局部变量) —— 声明不合法即 fail-fast,
        # 且这一处是**唯一**的价源解析点,扫描工具与回测因此不可能取到不同的域。
        price_source_for_execution=resolve_execution_price_source(
            cfg, name, supported=frozenset({EXECUTION_PRICE_SOURCE}),
        ),
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
                # 2026-10-17 (本分支 §4): 此前**硬编码** MARGIN_RATE, preset 的 `margin_rate`
        # 键从未被读取 —— 属"声明了却无人读取"那一类(与 §4 的借券成本声明同型)。
        # 接通后可由 preset 覆盖; 出厂 preset 均未设该键 ⇒ **零漂移**。
        margin_rate=cfg.get("margin_rate", MARGIN_RATE),
        commission_rate=COMMISSION_RATE,
        stamp_duty_rate=STAMP_DUTY_RATE,
        initial_capital=INITIAL_CAPITAL,
        lot_size=100,
        # §2 (audit 2026-10-15): NAV 闸门比例经规范契约解析(缺声明/越界 fail-fast),
        # 不再 `cfg.get("min_cash_ratio", 0.05)` —— 那样「没声明」与「声明为 0.05」
        # 不可区分,而此处此前 75/75 个 preset 都不声明。
        nav_gate_ratio=resolve_nav_gate_ratio(cfg, name),
        # V5' (2026-09-22, CLAUDE.md §4): ATR-aware slippage is opt-in via preset。
        # 默认 0.0 = baseline parity (无 slippage), preset 可上调启用真实市场摩擦。
        atr_slip_scale=resolve_atr_slip_scale(cfg, name),
        # V8 (2026-09-22, CLAUDE.md §4): max_volume_participation 与 intraday_tiebreak
        # 从 preset 显式 plumb 到 strategy (而非依赖模块常量/默认值)。
        # 当前 preset 默认 0.10 / 'sl_first', 完整覆盖 11/11 preset。
        max_volume_participation=resolve_volume_participation(cfg, name),
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
        # L / M / ST 条件 (2026-10-17, 本分支 §1/§4; opt-in, 出厂 preset 均未声明
        # ⇒ 默认值下零漂移)。此前它们只存在于 `run_backtest_v3` 的内联构造里,
        # 而 `scan_signals` 走的是本函数 ⇒ 扫描器会以**默认值**评估这些开关,
        # 给出与回测不一致的信号集(§6 单源的理由见本函数 docstring)。
        require_close_below_vwap=cfg.get("require_close_below_vwap", False),
        close_vwap_buffer=cfg.get("close_vwap_buffer", 0.0),
        signal_gap_max=cfg.get("signal_gap_max", None),
        require_shortable_st_filter=cfg.get("require_shortable_st_filter", False),
        st_lookback_bars=cfg.get("st_lookback_bars", 60),
        # v81 (2026-10-14, §3): 信号价格域 ('raw' 默认兼容 / 'adj' §3 合规)。
        signal_price_domain=cfg.get("signal_price_domain", "adj"),
        # §1 (audit, 2026-10-15): 窗口上下界显式下发到策略。
        # 面板向两端扩 buffer 且 feed 不设 fromdate/todate,此前入场不受任何
        # 窗口约束 —— 「无窗口前入场」只是指标暖机 NaN gate 的偶然结果。
        # 生产入口必须传真实窗口;策略侧对 None 会打 warn 而非静默放行。
        window_start=start,
        window_end=end,
        result_holder=holder,
    )


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


def _evaluated_days(
    equity_curve: list[dict] | None,
    trades: list[dict],
) -> tuple[object | None, object | None, int, str]:
    """**实测期**的首末日与交易日数 —— 诊断披露, **不是** CAGR 的年数分母。

    §6/§0 (2026-10-17, 第 8 处, 本分支): 本引擎的实测期**可以显著偏离请求窗**。
    实测 (v58_mp_2, 请求 `2018-01-01..2020-12-31`): 权益曲线实际只有
    `2019-02-18..2021-03-01`(495 个交易日 = 1.964 年), 而按请求窗取 3.000 年
    (膨胀 1.527x) ⇒ 同一份累计收益 (−58.06%) 被摊到更长的窗口上, CAGR 由
    **−35.75%** 变成 **−25.15%**, **低估亏损 10.60pp**。偏差方向是**美化**,
    与 §0「Pessimistic Default」相反, 与 §4 跳空成交口径同族 —— 都在亏损腿上
    把结果往好处挪。起点侧为什么晚 1.13 年**仍未解**(四个假设已被实验否证),
    但**不需要解开**: 实测期是引擎自己吐出的可观测事实, 不是推断。

    ⚠️ **合并后的口径 (2026-10-20)**: 上面那个缺陷的**修法**取 main 的单源 ——
    年化分母是**窗口内交易日数**(`core.walkforward.window_trading_days`, 与
    chase_up / uptrend / cycle 以及 DSR 的 T 同源), **不是**本函数量出来的实测
    行数(本分支原取实测期, 那会让本族成为唯一的少数派, 且与 T 的口径打架)。
    故本函数的产物以 `evaluated_start` / `evaluated_end` /
    `evaluated_period_source` **随产物发布**: "实测期 ≠ 请求窗"这件事保持可见,
    它现在是一条**披露**而不是分母。两者不一致时以 `n_trading_days` 为准。

    回退顺序: 权益曲线 → 逐笔成交日 → (None, None, 0, "none")。
    """
    rows = [r.get("date") for r in (equity_curve or []) if r.get("date")]
    if rows:
        return min(rows), max(rows), len(rows), "equity_curve"
    days: list[object] = []
    for t in trades:
        for k in ("entry_time", "entry_date", "exit_time", "exit_date"):
            v = t.get(k)
            if v:
                days.append(v)
    if days:
        # 无权益曲线时, 交易日数只能由成交日的**不同日期数**下界估计。
        # 入场与出场都要收 —— 只看出场会把首笔建仓日之前的区间丢掉。
        return min(days), max(days), len(set(days)), "trades"
    return None, None, 0, "none"


def _equity_sharpe(equity_curve: list[dict] | None) -> float | None:
    """**姊妹引擎口径**的 Sharpe: 日权益收益的 mean/std × sqrt(年化常数)。

    公式结构与 `chase_up/backtest.py`、`uptrend_pullback/backtest.py`、
    `cycle_price_action/allocator.py` 相同 (日收益, ddof=1)。
    年化常数取 `ANN_TRADING_DAYS` —— 与 `cagr` 同一个常数(单源), 于是本值与
    chase_up / uptrend 直接可比; cycle 仍写 252, 差 sqrt(252/243) ≈ 1.8%,
    只影响标度不影响排序(登记为未统一项)。
    """
    eq = [r.get("equity") for r in (equity_curve or [])]
    eq = [float(v) for v in eq if v is not None]
    if len(eq) < 3:
        return None
    arr = np.asarray(eq, dtype=float)
    if np.any(arr[:-1] == 0):
        return None
    rets = np.diff(arr) / arr[:-1]
    std = float(np.std(rets, ddof=1))
    if std < 1e-12:
        return None
    return float(np.mean(rets) / std * math.sqrt(ANN_TRADING_DAYS))


def _metrics_from_holder(
    holder: dict, start: str, end: str, cfg: dict, *, n_trading_days: int,
) -> dict:
    """从 result_holder + 区间算出最终 metrics dict。

    §2 单源 (audit 2026-10-15): 年化用 **交易日数**,与 chase_up /
    uptrend_pullback 同口径。此前这里用**日历日跨度** `/365`,而两引擎用
    `交易日/243` —— 同一窗口同一收益会得到不同的 CAGR,且**两边都看起来合理**:

    | 窗口 | 交易日/日历日 | 交易日口径 | 日历日口径 |
    |---|---|---|---|
    | 2026-04-01→05-01 | 23/30  | 173.7% | 218.9% |
    | 2026-05 之前的 2025 全年 | 261/364 | 9.28% | 10.03% |

    `n_trading_days` 是**必填**参数:让"用错口径"在调用点就失败,而不是悄悄
    按日历日年化出一个与别的引擎不可比的数字。
    """
    # §2 (audit 2026-10-15): final_capital 必须用**净值**,不是总现金。
    # `total_cash` 只含成本基础 + 已实现盈亏 → **期末未平仓的浮盈被抹掉**;
    # 而 equity_curve 的每行 `equity` 用的是 nav(含浮盈)—— 同一次回测于是
    # 给出两个互相打架的"期末权益"。stop() 会写 final_nav;缺它即 fail-fast
    # (合成夹具若只给 cash,就会拿到一个与曲线末行不一致的数)。
    if "final_nav" not in holder:
        raise KeyError(
            "§2: result_holder 缺 final_nav —— final_capital 必须取净值(含期末浮盈),"
            "不能用 total_cash。生产路径由 Phase3V3Strategy.stop() 写入;"
            "单元夹具请显式提供 final_nav。"
        )
    final_capital = float(holder["final_nav"])
    trades = holder["trades"]
    trades_count = len(trades)

    years = annualized_years(n_trading_days)

    # §6/§0 (2026-10-20 合并): 上面的 `n_trading_days` 就是 `cagr` 的年数分母 ——
    # **窗口内**交易日数, 单源 `core.walkforward.window_trading_days`, 与 chase_up /
    # uptrend / cycle 以及 DSR 的 T 同口径。实测期只作**披露**发布, 让"实测期 ≠
    # 请求窗"保持可见(本分支 2026-10-17 实测: 请求 3.000 年、实测 1.964 年 ⇒ 同一个
    # −58.06% 的 CAGR 在两种分母下差 10.6pp)。两者不一致时以 `n_trading_days` 为准。
    ev_start, ev_end, ev_days, ev_source = _evaluated_days(
        holder.get("equity_curve"), trades,
    )
    ev_years = annualized_years(ev_days) if ev_days > 0 else None

    total_yield = final_capital / INITIAL_CAPITAL - 1
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1 if final_capital > 0 else -1.0

    # §4/§0 (2026-10-17): 胜数必须按**规范化字段** `net_pnl` 判, 不能用旧兼容字段 `net`。
    # `net` 是**纯费率**公式 (`gross_pct - total_fee_ratio`), **不含 ¥5 最低佣金下限** ——
    # 小额单 (notional < ¥20,000) 的下限约 ¥2.50-5.00/腿不进 `net`, 于是真亏的单
    # 可能被记成胜。实测 (cap50/W2): 844 笔里有 3 笔两字段符号相反, 报告 win_rate
    # 因此高 0.4pp。`net_pnl` / `net_return` 走的是含下限的 cash walk, 是权威口径。
    wins = sum(1 for t in trades if t["net_pnl"] > 0)

    # §0 (2026-10-17): `avg_pnl` 是**无权**平均 —— 一笔 ¥300 的残仓与一笔 ¥100 万的
    # 仓位同等计入。实测 (v50_slope/W2): 63 笔残仓只占**名义额的 0.052%**, 却把
    # avg_pnl 从 -0.226% 拉到 -0.972% (t 从 -0.43 拉到 -2.39) —— **它会改变结论**。
    # 保留 avg_pnl 的既有定义 (它已发布), 但**同时给出按名义额加权的版本**与
    # 残仓占比, 让失真无法再隐形。
    _notional = [(t["entry_price"] * t["size"]) for t in trades]
    _tot_n = sum(_notional)
    _w = [(n / _tot_n) for n in _notional] if _tot_n > 0 else []
    avg_pnl_w = float(sum(w * t["net_return"] for w, t in zip(_w, trades)))
    # 残仓判据: 名义额 < 初始资金的 5% —— 这些是量能上限/现金闸门裁出来的残余仓位
    _MICRO = INITIAL_CAPITAL * 0.05
    _micro = [n for n in _notional if n < _MICRO]
    micro_count = len(_micro)
    micro_notional_share = (sum(_micro) / _tot_n) if _tot_n > 0 else 0.0
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    # 同上: 用含下限的 `net_return` (逐笔收益率), 而非 rate-only 的 `net`。
    avg_pnl = float(np.mean([t["net_return"] for t in trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in trades])) if trades_count > 0 else 0.0

    # 简单 Sharpe: 日 PnL 序列 → 年化
    sharpe = _approx_sharpe(trades)

    # exit reason 计数
    # §13.118 (2026-10-19): 出场原因**必须穷尽** —— 本族有**第四个** reason
    # `nav_gate_eod` (NAV 闸门强制平仓, 见 replay_strategy_v3 的 `_close` 调用点),
    # 而此处只数 TP/SL/time ⇒ `tp+sl+time` **可能少于** `trades`。
    # (另两族 chase/uptrend 有 `eod_count` 覆盖它们的第四个 reason `"eod"` ⇒ 只有本族缺。)
    # ⚠️ 方向: `nav_gate_eod` 是打在 NAV 下限上的**强制平仓**, 基本是亏损腿;
    #    不数它 ⇒ 读 `sl_count/trades` 的人会**低估止损占比**。
    # **加键是加法 ⇒ 对已有键零漂移。**
    tp_count = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in trades if t["exit_reason"] == "time")
    nav_gate_count = sum(1 for t in trades if t["exit_reason"] == "nav_gate_eod")

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        # §6/§7 (audit 2026-10-16): 逐 bar 权益曲线**带进 metrics**。
        # 此前它只活在 `result_holder["equity_curve"]` 里,而 main.py 读的是
        # `m.get("equity_curve")` —— 该键根本不存在 ⇒ `eq_rows` 恒为 None ⇒
        # equity_curve.csv / cash_walk.csv 的 writer **永远不执行**(静默空转),
        # 尽管策略每个 bar 都在往那个列表里写。典型的"已实现但不可达"。
                # 注: 返回的是 holder 里那**同一个** list 对象(未拷贝) —— `holder` 在
        # `run_backtest_v3` 里是局部变量、回测结束后即弃, 不存在共享可变状态的风险;
        # 两条既有的**结构守卫**(按源码文本判定)都钉在这一处, 这个写法同时满足它们。
        "equity_curve": holder.get("equity_curve", []),
        # §2 (audit 2026-10-15): 年化口径随产物发布 —— 拿到 cagr 时旁边就有它
        # 的年数分母(交易日数),而不是让读者猜是交易日还是日历日。
        # ⚠️ 这也是 `cagr` 的**唯一**分母(`cagr = (nav/初始)^(1/annualized_years(n_trading_days))`)。
        "n_trading_days": int(n_trading_days),
        # §6/§0 (2026-10-17, 第 8 处; 2026-10-20 合并): `start`/`end` 是**请求窗**,
        # 不是实测期 —— 实测期可以偏离请求窗数月到数年 (见 `_evaluated_days` 的实测记录),
        # 故"这段曲线覆盖了哪段历史"必须读下面三个字段。
        # 但它们**不是** `cagr` 的分母(那是上面的 `n_trading_days`); 两条口径不一致时
        # 以 `n_trading_days` 为准 —— 发布它们是让那个偏离保持可见, 而不是掩盖它。
        "evaluated_start": str(ev_start) if ev_start is not None else None,
        "evaluated_end": str(ev_end) if ev_end is not None else None,
        "evaluated_years": None if ev_years is None else float(ev_years),
        "evaluated_period_source": ev_source,
        "trades": trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "sharpe_kind": "per_trade_ratio_approx",  # §2 (audit 2026-10-15): 逐笔 net_return 的 mean/std × √(min(n,250)) —— **交易级比率**,不是日收益 Sharpe,仅供本引擎内排序
        # §5/§6 (2026-10-17, 第 9 处): 报告的 `sharpe` 是**逐笔口径**
        # (mean/std of `net_return` × sqrt(min(n,250))), 而三个姊妹引擎是**日权益口径**
        # (mean/std of 日收益 × sqrt(年化常数))。**两者是不同的统计量, 不可跨族比较** ——
        # 逐笔口径不含空仓日 (实测本样本 28.95% 的日子权益不变) 也不含持仓重叠。
        #
        # 本字段给出姊妹口径的值, 让不可比性无法再隐形。
        # **不覆盖 `sharpe`**: 逐笔 Sharpe 是合法且已发布的统计量 (per-trade IR),
        # 换掉它属**结果变更 / 口径选择** —— 按长期授权「登记, 不擅自改」。
        # 实测 (v58_mp_2 / 2018-01-01..2020-12-31): 逐笔 −1.761 vs 日权益 −1.440,
        # 差 0.32 (相对 22%)。注意方向**不系统**: 与本案前 8 处缺陷不同, 它不固定美化
        # —— 空仓日占比越高, 日权益口径被稀释越多。它的问题不是偏差, 是**换了一把尺子**。
        "sharpe_equity_basis": _equity_sharpe(holder.get("equity_curve")),
        # §13.89: 与三个姊妹族**同名同形**的口径自披露 (本族此前只有 sharpe 那一个字段)。
        "metrics_basis": dict(METRICS_BASIS),
        "max_dd": min(1.0, max(0.0, float(holder["max_dd"]))),
        # 注: `equity_curve` 已在本 dict 上方发布(那是 §2/§3 Tick 51 的修复)。
        # 此处**不再重复该键** —— 同一个 dict 字面量里写两次, 会让"哪个是权威"
        # 变成行序问题, 而两个分支各自都修过这一处。
        "avg_pnl": avg_pnl,
        # 无权 vs 按名义额加权 —— 两者差异即"残仓污染"的量度 (§0)
        "avg_pnl_notional_weighted": avg_pnl_w,
        "micro_trade_count": micro_count,
        "micro_trade_notional_share": micro_notional_share,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
        "nav_gate_count": nav_gate_count,
    }


def _approx_sharpe(trades: list[dict]) -> float:
    """无日 PnL 序列 → 用每笔收益率估算 sharpe（粗略，仅供排序）。

    §0/§4 (2026-10-17): 必须用**规范化字段 `net_return`**, 不能用旧兼容字段 `net`。
    两者差别在**小额成交**上极大: `net` 是纯费率公式
    `gross_pct - (佣金率 + 印花税率 + 佣金率×xp/ep)`, **不含 ¥5 最低佣金下限、也不含
    融券费**。实测 pure-1day/W2: 名义额 ~¥100 万的成交两者几乎相等 (−0.671% vs
    −0.670%), 而被**量能上限**裁到 100~200 股 (名义额 ¥300-800) 的残仓上, `net` 报
    +1.957% 而 `net_return` 只有 +0.716% (¥10 费用占 ¥778 名义额的 1.3%)。

    由于本函数对成交做**无权平均**, 一笔 ¥300 的残仓与一笔 ¥100 万的仓位同等计入
    ⇒ 报告的 sharpe 被小残仓系统性抬高, 甚至**符号相反**
    (pure-1day/W2: 按 net **+1.19** vs 按 net_return **-0.39**)。

    ⚠️ 另一个**未修**的问题 (§5/§6, 第 9 处): 本函数是**逐笔口径** Sharpe, 而三个姊妹
    引擎是**日权益口径**。两者不可跨族比较。见 `_metrics_from_holder` 里
    `"sharpe_equity_basis"` 的说明 —— 那里给出姊妹口径的值。本函数**未改**,
    因为换口径属结果变更 (登记, 不擅自改)。
    """
    if not trades:
        return 0.0
    arr = np.array([t["net_return"] for t in trades])
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    if std < 1e-9:
        return 0.0
    # 假设 ~250 笔/年，按交易频率缩放
    return float(mean / std * math.sqrt(min(len(arr), 250)))


def _run_ensemble(
    cfg: dict,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int,
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
        sub_results.append(run_backtest_v3(name, start, end, db_path, min_bars))

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

    # §2 单源 (audit 2026-10-15): 年化必须用**交易日**,不能用日历日跨度 ——
    # 后者与 chase_up / uptrend_pullback 的口径不同,同一窗口会给出不同的 CAGR
    # (实测差 8%~26%,而两边都"看起来合理")。子策略共享同一窗口,故交易日数相同。
    n_trading_days = max((r["n_trading_days"] for r in sub_results), default=0)
    years = annualized_years(n_trading_days)

    # §6/§0 (2026-10-17, 第 8 处; 2026-10-20 合并): 与 `_metrics_from_holder` 同口径 ——
    # `cagr` 的分母是上面的 `n_trading_days`(**窗口**交易日数), 实测期只作**披露**。
    # 各子策略跑同一窗口, 取最宽的实测期(合并后的交易集覆盖的就是这个并集)。
    _sub_spans = [
        (r.get("evaluated_start"), r.get("evaluated_end"), r.get("evaluated_years"))
        for r in sub_results
        if r.get("evaluated_start") and r.get("evaluated_end")
    ]
    if _sub_spans:
        ev_start = min(s for s, _, _ in _sub_spans)
        ev_end = max(e for _, e, _ in _sub_spans)
        ev_years = max(y for _, _, y in _sub_spans)
        ev_source = "sub_equity_curves"
    else:
        ev_start, ev_end, ev_days, ev_source = _evaluated_days(None, all_trades)
        ev_years = annualized_years(ev_days) if ev_days > 0 else None
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1

    wins = sum(1 for t in all_trades if t["net_pnl"] > 0)  # 见上: 须用含下限的 net_pnl
    trades_count = len(all_trades)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    avg_pnl = float(np.mean([t["net_return"] for t in all_trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in all_trades])) if trades_count > 0 else 0.0
    sharpe = _approx_sharpe(all_trades)
    tp_count = sum(1 for t in all_trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in all_trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in all_trades if t["exit_reason"] == "time")
    nav_gate_count = sum(1 for t in all_trades if t["exit_reason"] == "nav_gate_eod")

    # §5 Attribution Mandate: 集成的基准取自子策略 —— 它们共享同一窗口与(实际
    # 上相同的)宇宙,故基准应当一致。**不一致即 fail-fast**:那说明子策略的宇宙
    # 不同,怎么合并基准是个人为决定,不该由这里悄悄取平均或取第一个。
    raw_bench = [r["benchmark_return"] for r in sub_results]
    if any(b is None for b in raw_bench) and not all(b is None for b in raw_bench):
        raise ValueError(
            f"§5: 集成子策略的基准部分为 None(无法计算): {raw_bench} —— 不允许静默取平均"
        )
    bench_values = sorted({None if b is None else round(float(b), 12) for b in raw_bench})
    if len(bench_values) != 1:
        raise ValueError(
            f"§5: 集成子策略的基准不一致 {bench_values} —— 子策略宇宙不同,"
            "基准如何合并需显式决定,不得静默取平均"
        )
    bench = bench_values[0]
    n_members = max(int(r["benchmark_members"]) for r in sub_results)

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "n_trading_days": int(n_trading_days),
        # 集成:多个子组合各自的权益曲线尚未聚合,故此处置 None。
        # **显式 None 而不是"缺键"** —— 缺键会让 main.py 的 `m.get(...)` 与
        # "字段根本没实现"不可区分(附三十三 的教训);None 可被读取方明确抱怨。
        "equity_curve": None,
        "benchmark_kind": sub_results[0]["benchmark_kind"],
        "benchmark_return": bench,
        "benchmark_members": n_members,
        "excess_return": None if bench is None else float(total_yield) - bench,
        # 实测期**披露**(诊断): `cagr` 的分母是上面的 `n_trading_days`, 不是这里 ——
        # 与 `_metrics_from_holder` 同一口径, 两者不一致时以 `n_trading_days` 为准。
        "evaluated_start": ev_start,
        "evaluated_end": ev_end,
        "evaluated_years": None if ev_years is None else float(ev_years),
        "evaluated_period_source": ev_source,
        "trades": all_trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "sharpe_kind": "per_trade_ratio_approx",  # §2 (audit 2026-10-15): 逐笔 net 的 mean/std × √(min(n,250)) —— **交易级比率**,不是日收益 Sharpe,仅供本引擎内排序
        "max_dd": min(1.0, max(0.0, float(max_dd))),
        # §5 (2026-10-17, 第 9 处): ensemble 汇总路径**不产出权益曲线** ⇒ 日权益口径
        # 无法计算。显式给 None 而不是省略键 —— 省略会让调用方以为"没这个指标",
        # 而真相是"这条路径量不出来"。同族的 `equity_curve` 也缺失, 是同一个原因。
        "sharpe_equity_basis": None,
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
        "nav_gate_count": nav_gate_count,
        "ensemble_subs": sub_names,
    }


def run_backtest_v3(
    preset: str,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int = 200,
) -> dict:
    """跑 v3 引擎返回 metrics dict。

    参数:
      preset: PRESETS 里的 preset name
      start / end: 回测区间 (YYYY-MM-DD)
      db_path: DuckDB 文件路径
      min_bars: 每只票最少需要的 bar 数;2-month 滚动窗口期间 panel 跨春节可能
                只有 ~197 trading days,这时可下调到 150,NaN gate 会兜底。
    """
    cfg = dict(get_preset(preset))
    cfg["_name"] = preset
    _name = cfg.get("_name", "short_reversal")

    # v63 (2026-10-13): Ensemble 模式 — 跑 N 个子策略, 资金等分, 汇总 PnL。
    # OOS-validated (WFV mean +10.9%, holdout 2026-H2 +5.4%) over v50_slope.
    # 实现是 N 个独立 backtest 的 wrapper, 复用 v3 引擎, 行为等价。
    #
    # §2 (audit 2026-10-15, preset→engine conformance): 此前**真正**决定走哪条
    # 路径的是结构性开关 `"ensemble_substrategies" in cfg`,而 preset 声明的
    # `position_sizing` 从未被读取 —— 声明纯装饰(75 个 preset 全中)。现在两者
    # 必须一致:'ensemble_split' ⇔ 有子策略。不一致 → fail-fast,而不是按声明
    # 以外的方式静默跑完。
    position_sizing = resolve_position_sizing(
        cfg, _name, allowed=frozenset({ALL_IN, ENSEMBLE_SPLIT}),
    )
    has_ensemble = "ensemble_substrategies" in cfg
    if has_ensemble != (position_sizing == ENSEMBLE_SPLIT):
        raise ValueError(
            f"§2: preset {_name!r} 声明 position_sizing={position_sizing!r},但 "
            f"ensemble_substrategies {'存在' if has_ensemble else '缺失'} —— "
            "声明与真正决定路径的结构性开关不一致:两者必须同时修正。"
        )
    if has_ensemble:
        return _run_ensemble(cfg, start, end, db_path, min_bars)

    # §3 (audit 2026-10-15): 执行域价源声明。本引擎的成交价/SL/TP 全部取自
    # raw 域(d.close/d.open 即 v_daily 原始价);指标域才切 adj_close。
    # 声明别的价源必须炸 —— 否则「按原始价成交」是一句无人兑现的承诺。
    # 与 position_sizing 一样在**碰数据库之前**解析:preset 契约不合法时
    # 不应先跑半个宇宙再报错。
    price_source_for_execution = resolve_execution_price_source(
        cfg, _name, supported=frozenset({EXECUTION_PRICE_SOURCE}),
    )
    # §2 (audit 2026-10-15): NAV 闸门比例由 preset 的 `nav_gate_ratio` 声明驱动。
    # 此前 75/75 个 preset 都不声明它,引擎却写 `cfg.get("min_cash_ratio", 0.05)`
    # —— 「没声明」与「声明为 0.05」不可区分。现与参数同名,一个概念一个名字。

    # §4 (2026-10-17, 本分支): 可选的做空可行性过滤 —— 疑似 ST/风险警示(±5% 封板)
    # 的票现实中不在融券名单里。默认关闭, 由 preset 的 `exclude_suspected_st` 显式开启
    # (出厂 preset 均未声明 ⇒ 零漂移)。
    universe = load_universe_asof(
        cfg["universe"], start, db_path,
        exclude_suspected_st=cfg.get("exclude_suspected_st", False),
    )
    panel = _load_panel(db_path, start, end, universe)
    feeds = build_per_stock_feeds(panel, universe, min_bars=min_bars)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=0.0)  # 成本由 strategy 内扣

    # §2 (audit 2026-10-15): `final_nav` 也在此初始化。
    # 窗口太短/全部被 warmup 门滤掉时**策略根本没跑**,`stop()` 不会被调用 ——
    # 此时空仓,净值 == 初始资金,初始化值就是**正确**答案(不是占位谎言)。
    # 真有运行时 `stop()` 会用 `_nav()` 覆盖它。
    holder: dict = {"cash": INITIAL_CAPITAL, "final_nav": INITIAL_CAPITAL,
                    "trades": [], "max_dd": 0.0}

    for code, feed in feeds:
        cerebro.adddata(feed, name=code)
    cerebro.addstrategy(
        Phase3V3Strategy,
        **strategy_kwargs(cfg, _name, holder=holder, start=start, end=end),
    )
    cerebro.run()
    # §2 单源 (audit 2026-10-15): 年化用**窗口内的交易日数**(面板去重日期),
    # 而不是日历日跨度 —— 与 chase_up / uptrend_pullback 同口径。
    # §2 单源 / §5 (附八十一): 年化与 DSR 都要**窗口内**的交易日数 ——
    # 而这里此前传的是 `panel["date"].nunique()`,即**整张面板**(含暖机缓冲,
    # 且两端都外扩;实测:2 个月窗口 43 个交易日,面板却报 197,并含窗口之后的日期)。
    # 后果:①CAGR 的年化分母大 ~4 倍 ⇒ 短窗口 CAGR 被系统性压低
    #      (而各 walk-forward 汇总正是逐窗 CAGR);②附六十 把同一个数当成 DSR 的 T
    #      ⇒ T 被高估、DSR 偏乐观。
    # 口径现收到 `core.walkforward.window_trading_days` 单源(全库 8 处同缺陷,见附八十一);
    # 窗口内一个交易日都没有时它在内部 fail-fast。
    metrics = _metrics_from_holder(
        holder, start, end, cfg,
        n_trading_days=window_trading_days(panel, start, end),
    )
    # §5 Attribution Mandate(此前全库无实现,2026-10-16 补齐)
    metrics.update(_benchmark_block(panel, float(metrics["total_yield"])))
    return metrics
