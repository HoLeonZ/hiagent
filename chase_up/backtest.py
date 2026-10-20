"""回测编排 + 绩效指标 (沿用 uptrend_pullback/backtest.py 口径)。"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from chase_up.data import load_panel
from chase_up.portfolio import simulate_portfolio
from chase_up.presets import MAX_HOLD_LIMIT, get_preset
from chase_up.signals import compute_indicators, select_entries
# §2 Canonical Cost Model: 成本常量只在 core/ 定义一次, 引擎必须**导入**而非重写。
# ⚠️ 合并注意: 本行**必须**保持"单行 import + COMMISSION_RATE"这一形态 ——
# tests/test_cost_constants_bound_to_core.py 的正向绑定判据是
# `from core\.dual_price import .*COMMISSION_RATE` 的单行正则, 而下面
# core.dual_price 的括号式多行 import 匹配不到它。
from core.dual_price import COMMISSION_RATE, MIN_COMMISSION, STAMP_DUTY_RATE
from chase_up.universe import load_universe

from core.dual_price import (  # §2 单源 (audit P2-11, 2026-10-15)
    resolve_atr_slip_scale,
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
)
from core.trade_schema import TRADING_DAYS_PER_YEAR  # §2 单源 (audit 2026-10-15)
# §2 单源 (audit 2026-10-17): 契约键一律经 core.preset_contract 解析(缺声明即
# fail-fast),不再用 `p.get(key, <看起来合理的默认值>)` —— 那正是 preset_contract
# docstring 明令禁止的「让缺口靠沉默存在」。
from core.preset_contract import (
    ALL_IN,
    resolve_nav_gate_ratio,
    resolve_position_sizing,
    resolve_volume_participation,
)

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 1_000_000.0
#: 年化口径单源 —— 见 core.trade_schema.TRADING_DAYS_PER_YEAR 的说明
#: (日历日 vs 交易日会让同一窗口的 CAGR 差 8%~26%)。此处保留旧名以兼容调用方。
TRADING_DAYS = TRADING_DAYS_PER_YEAR

# §13.89: 口径**自披露**的单一来源 —— 与 metrics 里报出的 `metrics_basis` 同源,
# 也与 §13.13 的对照表同源 (§13.87 钉住的那张表)。
METRICS_BASIS = {
    "trading_days": TRADING_DAYS,
    "sharpe": "equity",
    "cagr_denominator": "evaluated_days",
    "win_rate_field": "net",
    "max_dd": "nav_mtm",
}


def compute_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    *,
    initial_capital: float = INITIAL_CAPITAL,
    max_hold: int = MAX_HOLD_LIMIT,
) -> dict:
    """由净值曲线与逐笔交易计算绩效指标。"""
    if equity_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_equity": initial_capital,
            "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "max_dd": 0.0,
            "avg_hold_days": 0.0, "max_hold_days": 0, "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": 0.0, "exposure": 0.0,
            "metrics_basis": dict(METRICS_BASIS),
        }

    eq = equity_df["equity"].to_numpy(dtype=float)
    final_equity = float(eq[-1])
    total_return = final_equity / initial_capital - 1.0

    n_days = len(eq)
    years = max(n_days / TRADING_DAYS, 1e-9)
    cagr = (final_equity / initial_capital) ** (1 / years) - 1 if final_equity > 0 else -1.0

    rets = np.diff(eq) / eq[:-1] if n_days > 1 else np.array([0.0])
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (float(np.mean(rets)) / std * math.sqrt(TRADING_DAYS)) if std > 0 else 0.0

    peak = np.maximum.accumulate(eq)
    max_dd = float(np.max((peak - eq) / peak)) if len(eq) else 0.0
    exposure = float((equity_df["holdings"] / equity_df["equity"]).mean())

    if trades_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_equity": final_equity,
        # §5 (audit 2026-10-16): 观察数**随产物发布**。DSR 的 `n_returns` 参数是
        # "Sharpe 用了多少个收益观测"(T = len(eq) - 1,因为 rets = diff(eq)),
        # 而此前各 sweep 只能把这个数**硬编码**(多处写 252),窗口实际只有
        # 242~243 个交易日 ⇒ T 被高估约 4%,标准误被低估约 2%,DSR 系统性偏乐观。
        # 与 short_reversal 的 `n_trading_days` 是**两个量**:那个是"窗口有多少个
        # 交易日"(用于年化),这个是"有多少个收益观测"(用于标准误),差一个观测。
        "n_daily_returns": int(max(len(eq) - 1, 0)),
            "total_return": total_return, "cagr": cagr, "sharpe": sharpe,
            # §2 (audit 2026-10-15): sharpe 的定义随产物发布 —— 与 short_reversal
            # 的 `sharpe` 不是同一个量(那个是逐笔比率的近似)。
            "sharpe_kind": "daily_returns_annualized",
            "max_dd": max_dd, "avg_hold_days": 0.0, "max_hold_days": 0,
            "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": None, "exposure": exposure,
        }

    net = trades_df["net_pnl"].to_numpy(dtype=float)
    wins = net[net > 0]
    losses = net[net < 0]
    # §0/§7 (audit 2026-10-15): 无亏损笔数时 `profit_factor` **无定义**(分母 0),
    # 返回 None 而不是 `float("inf")` —— Python 的 `json.dumps(inf)` 会写出
    # `Infinity`,那不是 RFC 8259 的合法值:除 Python 自己的宽松 `json.loads`
    # (正因它能读回来,这个缺陷一直没被发现)之外,JS / Go / Rust / jq 一律拒绝。
    # 于是 `results/backtest.json` 在"全胜窗口"下是**非法 JSON**。None 既合法,
    # 也与本仓库既有的"算不出就 None"口径一致(max_dd=None / cagr=None / beta=None)。
    profit_factor = (
        float(wins.sum() / abs(losses.sum()))
        if losses.size and losses.sum() != 0
        else None
    )

    return {
        "trades": int(len(trades_df)),
        # §13.89: 口径自披露 —— 让"各族同名指标定义不同"这件事**从产出里可读**,
        # 而不是只写在注释里 (全仓此前只有 short_reversal 报 `sharpe_equity_basis`)。
        "metrics_basis": dict(METRICS_BASIS),
        "win_rate": float((net > 0).mean()),
        "final_equity": final_equity,
        # §5 (audit 2026-10-16): 观察数**随产物发布**。DSR 的 `n_returns` 参数是
        # "Sharpe 用了多少个收益观测"(T = len(eq) - 1,因为 rets = diff(eq)),
        # 而此前各 sweep 只能把这个数**硬编码**(多处写 252),窗口实际只有
        # 242~243 个交易日 ⇒ T 被高估约 4%,标准误被低估约 2%,DSR 系统性偏乐观。
        # 与 short_reversal 的 `n_trading_days` 是**两个量**:那个是"窗口有多少个
        # 交易日"(用于年化),这个是"有多少个收益观测"(用于标准误),差一个观测。
        "n_daily_returns": int(max(len(eq) - 1, 0)),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "sharpe_kind": "daily_returns_annualized",  # §2 (audit 2026-10-15): 日收益序列的 Sharpe(mean/std × √243)。与 short_reversal 的 `sharpe` **不是**同一个量
        "max_dd": max_dd,
        "avg_hold_days": float(trades_df["hold_days"].mean()),
        "max_hold_days": int(trades_df["hold_days"].max()),
        "overrun_count": int((trades_df["hold_days"] > max_hold).sum()),
        "tp_count": int((trades_df["exit_reason"] == "TP").sum()),
        "sl_count": int((trades_df["exit_reason"] == "SL").sum()),
        "time_count": int((trades_df["exit_reason"] == "time").sum()),
        "eod_count": int((trades_df["exit_reason"] == "eod").sum()),
        "avg_net_return": float(trades_df["net_return"].mean()),
        "profit_factor": profit_factor,
        "exposure": exposure,
    }


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


def run_backtest(
    preset: str | dict,
    start: str,
    end: str,
    db_path: Path,
    *,
    panel_ind: pd.DataFrame | None = None,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """端到端回测 (Phase 1: pandas 自循环)。"""
    p = get_preset(preset) if isinstance(preset, str) else preset
    if p["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(f"max_hold={p['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

    if panel_ind is None:
        universe = set(load_universe(p["universe"], db_path, asof_date=start))
        panel = load_panel(db_path, start, end, universe=universe)
        panel_ind = compute_indicators(panel)

    sig_kwargs = dict(p["signal"])
    entries = select_entries(
        panel_ind,
        start_date=start, end_date=end,
        **sig_kwargs,
    )

    trades_df, equity_df = simulate_portfolio(
        entries, panel_ind,
        tp_pct=p["tp_pct"], sl_pct=p["sl_pct"],
        max_hold=p["max_hold"], max_positions=p["max_positions"],
        start_date=start, end_date=end,
        initial_capital=initial_capital,
        atr_tp_mult=p.get("atr_tp_mult"),
        atr_sl_mult=p.get("atr_sl_mult"),
        position_sizing=resolve_position_sizing(
            p, p.get("_name", "chase_up"), allowed=frozenset({ALL_IN})
        ),
        kelly_fraction=p.get("kelly_fraction"),
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
        price_source_for_execution=p.get("price_source_for_execution", "raw_close"),
        # V8 (2026-09-22, CLAUDE.md §4): preset→strategy explicit plumbing。
        intraday_tiebreak=p.get("intraday_tiebreak", "sl_first"),
        max_volume_participation=resolve_volume_participation(
            p, p.get("_name", "chase_up")
        ),
        # R5 (2026-10-09, CLAUDE.md §2): NAV-floor cash gate, 与 backtrader_engine.py:223 保持一致。
        # portfolio.py:175-189 文档化 Round 14 (2026-09-28) 引入,默认 0.05。
        nav_gate_ratio=resolve_nav_gate_ratio(p, p.get("_name", "chase_up")),
        # R6 (2026-10-09, CLAUDE.md §0/§4): cost model plumbing, 与 backtrader_engine.py:212-216 保持一致。
        # Round 15 (2026-09-28) 在 portfolio.py:247-254 引入 ATR-aware slippage 与成本参数。
        # 当前 0/22 preset 声明这些 key, 函数默认 0.00025/0.0005/5.0/0.0/0.0 与 backtrader_engine.py p.get 默认完全一致 (R5 nav_gate_ratio 同模式)。
        # 显式 plumb 防止未来 preset override 时两引擎 drift。
        # 2026-10-19 (§2): 以下三个默认值**原先写死为字面量** ⇒ 违反
        # "constants are defined exactly once (in core/) … redefining fee constants
        # inside an engine is a fail-fast violation"。取值与规范值逐字节相同,
        # 改为绑定 ⇒ **零结果漂移**; 而以后 core 改值时这里会跟着走, 不再静默分叉。
        commission_rate=p.get("commission_rate", COMMISSION_RATE),
        stamp_duty_rate=p.get("stamp_duty_rate", STAMP_DUTY_RATE),
        min_commission=p.get("min_commission", MIN_COMMISSION),
        slippage=p.get("slippage", 0.0),
        atr_slip_scale=resolve_atr_slip_scale(p, p.get("_name", "chase_up")),
    )

    metrics = compute_metrics(
        trades_df, equity_df, initial_capital=initial_capital, max_hold=p["max_hold"]
    )
    metrics.update({"start": start, "end": end, "signals": int(len(entries))})

    # §5 Attribution Mandate(此前**全库无实现**,2026-10-16 补齐):
    # 「Headline returns MUST be reported alongside benchmark-relative excess
    # return (index or style basket)」—— 否则"纯 style beta"会被当成 alpha 呈现。
    # 基准 = 本窗口 PIT 宇宙的等权买入持有;选择理由与价格域见 core/benchmark.py。
    metrics.update(_benchmark_block(panel_ind, float(metrics["total_return"])))
    if isinstance(preset, str):
        metrics["preset"] = preset
    return {"metrics": metrics, "trades": trades_df, "equity": equity_df}