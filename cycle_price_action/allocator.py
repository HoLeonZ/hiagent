"""cycle_price_action 的跨股容量层 (纯函数, 零 I/O)。

**为什么需要它**: `backtest.run_backtest` 对每只票各起一个 cerebro 并
`setcash(1_000_000)`, 于是 2986 只票 = 2986 个互相独立的百万账户, 各自单仓
all-in。PRESET_V1 声明 `max_positions=1`, 而引擎实际同时持有约 204 只 ——
与 CLAUDE.md §2「Single-Bullet Execution … capacity is bounded by the
preset's max_positions; signals beyond capacity at time T MUST BE IMMEDIATELY
DISCARDED」相反。后果是 `compute_metrics` 只能给出逐笔 PnL, 没有组合权益曲线,
`cagr` / `sharpe` / `max_dd` 全是 null。

本模块把那批逐笔成交重新放回**一个**资金账户里, 按 `max_positions` 定容,
让 cycle 第一次有可比较的策略级收益。

**明确声明的假设** (都写在这里, 不藏):
  1. 每笔的收益率 `r = pnl / (entry_price × shares)` 直接取自该股自身的
     all-in 回测结果。all-in 下单笔收益率与账户规模无关, 唯一例外是
     §4 的成交量上限 (`max_volume_participation`) 和 100 股整手 —— 两者都
     让收益率带上轻微的资金规模依赖。容量层在扩大资金的场景下会**乐观**
     一点, 因为它复用的是 100 万名义额下算出的 r。
  2. 槽位释放条件取 `exit_date < entry_date` (**严格小于**)。CLAUDE.md §2
     Settlement Isolation: 不得假设 T 日卖出的资金在 T 日即可用于买入。
  3. 满仓时到达的信号**直接丢弃**, 不排队到 T+1 (§2 明文)。
  4. 排序依据 = 三维融合分 (与 entry_signal 同一组权重), 平分按 thscode
     字典序 —— 完全确定性, 与输入顺序无关。

**已登记的已知问题 (2026-10-16, 不改默认)**: 融合分**不是**单调预测器, 而
"取最高分"这条当前默认规则实测**劣于随机** (IS2 cap=1: -13.11% vs 随机
-23.94%… 见下 W2: -24.37% vs -16.35%, 两个窗口一致)。反向规则 (取最低分)
在两个窗口都更好, 但 9 条规则 × 2 窗口属典型多重比较, 且反向规则在
cap=3 上优势消失 —— 没有 holdout 确认, 故**不改默认**。任何改动必须先在一个
未参与该轮搜索的窗口上验证 (§5)。详见 /tmp 工作日志 Iteration 5。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from cycle_price_action.metrics import TradeRecord

TRADING_DAYS_PER_YEAR = 252

# §13.89: 口径**自披露**的单一来源 (与 metrics 里报出的 `metrics_basis` 同源)。
METRICS_BASIS = {
    "trading_days": TRADING_DAYS_PER_YEAR,
    "sharpe": "equity",
    "cagr_denominator": "evaluated_days",
    "win_rate_field": "pnl",
}


@dataclass(frozen=True)
class AllocationResult:
    trading_days: tuple[date, ...]
    equity: tuple[float, ...]
    taken: tuple[TradeRecord, ...]
    n_signals: int
    n_rejected_capacity: int
    exposure: float          # 持仓交易日占比
    initial_capital: float
    final_equity: float


def _fused(t: TradeRecord, weights: tuple[float, float, float]) -> float:
    wk, wc, wcal = weights
    return wk * t.k_line_score + wc * t.phase_score + wcal * t.calendar_score


def _trade_return(t: TradeRecord) -> float:
    notional = t.entry_price * t.shares
    if notional <= 0:
        raise ValueError(
            f"{t.thscode} {t.entry_date}: 名义额非正 ({notional}) —— 无法折算收益率"
        )
    return t.pnl / notional


def allocate(
    trades: Sequence[TradeRecord],
    *,
    trading_days: Sequence[date],
    initial_capital: float,
    max_positions: int,
    weights: tuple[float, float, float] = (1.0, 0.7, 0.5),
) -> AllocationResult:
    """把逐笔成交放回单一账户, 按 max_positions 定容, 返回逐日权益曲线。"""
    if max_positions < 1:
        raise ValueError(f"max_positions must be >= 1, got {max_positions}")
    days = tuple(sorted(set(trading_days)))
    if not days:
        raise ValueError("trading_days 为空 —— 无法构造权益曲线")

    # 确定性排序: 入场日 → 融合分降序 → thscode
    ordered = sorted(
        trades,
        key=lambda t: (t.entry_date, -_fused(t, weights), t.thscode),
    )

    slots: list[date] = []          # 每个占用槽位的释放日
    taken: list[TradeRecord] = []
    n_rejected = 0
    r_by_day: dict[date, float] = {}
    for t in ordered:
        # 槽位释放: 卖出日必须**严格早于**新入场日 (§2 结算隔离)
        slots = [d for d in slots if not (d < t.entry_date)]
        if len(slots) >= max_positions:
            n_rejected += 1
            continue
        slots.append(t.exit_date)
        taken.append(t)
        r_by_day[t.exit_date] = r_by_day.get(t.exit_date, 1.0) * (
            1.0 + _trade_return(t)
        )

    equity: list[float] = []
    level = initial_capital
    held_days = 0
    for d in days:
        level *= r_by_day.get(d, 1.0)
        equity.append(level)
        if any(t.entry_date <= d < t.exit_date for t in taken):
            held_days += 1

    return AllocationResult(
        trading_days=days,
        equity=tuple(equity),
        taken=tuple(taken),
        n_signals=len(trades),
        n_rejected_capacity=n_rejected,
        exposure=held_days / len(days),
        initial_capital=initial_capital,
        final_equity=equity[-1],
    )


def portfolio_metrics(res: AllocationResult) -> dict:
    """组合级指标。权益曲线按日给出, 退出日之外保持不变。

    注意: 这是**已实现权益**曲线 (不盯市), 因此回撤只在退出点更新 ——
    真实回撤不会比它小, 但日内浮亏不计入。这一点必须随数字一起说。
    """
    eq = res.equity
    n = len(eq)
    if n == 0 or res.initial_capital <= 0:
        raise ValueError("空权益曲线")

    total_return = eq[-1] / res.initial_capital - 1.0
    years = n / TRADING_DAYS_PER_YEAR
    cagr = (eq[-1] / res.initial_capital) ** (1.0 / years) - 1.0 if years > 0 else None

    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - v / peak)

    rets = [
        eq[i] / eq[i - 1] - 1.0 for i in range(1, n) if eq[i - 1] > 0
    ]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = (
        sum((x - mean_r) ** 2 for x in rets) / (len(rets) - 1)
        if len(rets) > 1
        else 0.0
    )
    sd = var ** 0.5
    sharpe = (
        mean_r / sd * (TRADING_DAYS_PER_YEAR ** 0.5) if sd > 0 else None
    )

    return {
        "n_trades": len(res.taken),
        "n_signals": res.n_signals,
        "n_rejected_capacity": res.n_rejected_capacity,
        "rejection_rate": (
            res.n_rejected_capacity / res.n_signals if res.n_signals else 0.0
        ),
        "total_return": total_return,
        "final_equity": res.final_equity,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "exposure": res.exposure,
        "win_rate": (
            sum(1 for t in res.taken if t.pnl > 0) / len(res.taken)
            if res.taken
            else 0.0
        ),
        # §13.89: 口径自披露 —— 此前本族**一个口径字段都没有**。
        "metrics_basis": dict(METRICS_BASIS),
    }
