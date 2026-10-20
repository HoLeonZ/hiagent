"""TradeRecord dataclass + aggregate metrics for cycle_price_action backtests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TradeRecord:
    thscode: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    hold_days: int
    k_line_score: float
    phase_score: float
    calendar_score: float


def compute_metrics(
    trades: list[TradeRecord],
    *,
    cash_per_account: float,
    n_accounts: int,
) -> dict:
    """Aggregate trade-level metrics.

    ⚠️ **口径警告:这不是组合 P&L**(§2, audit 2026-10-15)

    本引擎按**每只股票一个独立账户**运行 —— `backtest.run_backtest` 对 universe 里
    每个代码各建一个 cerebro 并各自 `setcash(cash)`,再把所有账户的成交并成一张表。
    因此:

      - 这些数字描述的是**横截面信号研究**,不是一条资金曲线;
      - `total_pnl` 是 **N 个账户盈亏的合计**,其"本金"是 `n_accounts ×
        每账户资金`(接近市值量级)。**它不能**与 chase_up / uptrend_pullback /
        short_reversal 的单账户(一个 100 万组合)结果直接比较 —— 量级差
        n_accounts 倍;
      - `cagr` / `sharpe` / `max_dd` 因此**无法定义**,一律返回 `None`
        —— 诚实的"算不出",而不是拿横截面合计冒充组合指标。

    实测(2026-04-01..2026-05-01):492 笔成交分布在 **472** 只股票上,
    `total_pnl=-776,948`;其分母是 472 个各 100 万的账户,不是 100 万。

    为让这个口径**随产物一起走**(而不是只活在这段 docstring 里,读者看不到),
    返回值必带 `account_model` / `capital_per_account` / `n_accounts` /
    `notional_capital` 四个字段 —— 拿到 `total_pnl` 时旁边就有它的分母。

    两个参数是**必填**:让"忘记标注"直接失败,而不是产出一个含义不明的合计。
    """
    model = {
        "account_model": "per_stock_independent",
        "capital_per_account": float(cash_per_account),
        "n_accounts": int(n_accounts),
        "notional_capital": float(cash_per_account) * int(n_accounts),
    }
    n = len(trades)
    if n == 0:
        return dict(
            n_trades=0, n_wins=0, n_stocks=0,
            total_pnl=0.0, avg_hold_days=0.0,
            win_rate=0.0, cagr=None, sharpe=None, max_dd=None,
            **model,
        )

    n_wins = sum(1 for t in trades if t.pnl > 0)
    total_pnl = sum(t.pnl for t in trades)
    avg_hold = sum(t.hold_days for t in trades) / n
    return dict(
        n_trades=n,
        n_wins=n_wins,
        n_stocks=len({t.thscode for t in trades}),
        total_pnl=total_pnl,
        avg_hold_days=avg_hold,
        win_rate=n_wins / n,
        cagr=None,        # see docstring
        sharpe=None,
        max_dd=None,
        **model,
    )
