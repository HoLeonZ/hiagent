"""§2 Capital Determinism 的 equity 曲线不变量 (单一来源)。

背景: chase_up 与 uptrend_pullback 的 Phase-2 (backtrader 重放) 都这样构造
equity 曲线 —— 拿 Phase-1 的曲线,再整体加一个**累计常数**
`equity_delta = Σ (net_pnl_bt − net_pnl_p1)`:

    chase_up  : 按每笔 exit_date 前向填充累计 delta
    uptrend   : 整体平移到每一行 (含 row 0)

两种加法都不是有效的权益重建: delta 是按 Phase-1 的**逐笔固定规模**算出的
绝对金额,而 Phase-1 曲线本身是**复利**的 (all-in 逐笔重算规模),两者量纲不匹配。
当 Σ delta 的绝对值超过曲线当前权益时, 得到的"权益"会变成负数。

实测 (chase_up, preset=chase_v1_atr_tp4_sl1, 2022-10-03..2024-09-30):
  Phase 1 simulate : final_equity =  604,221   exposure =  0.263
  Phase 2 backtrader: final_equity = -423,402   exposure = -0.963
同 76 笔成交、同一窗口。负权益、负敞口在物理上不可能 (§2
「Capital is physical and finite」)。

本模块不去裁决 Phase-2 该用哪种口径重建 (那是口径选择, 登记不擅自改),
只做 §0 Fail-Fast 该做的那一半: **不允许把物理上不可能的曲线当作结果发布**。
"""

from __future__ import annotations

import pandas as pd


class EquityCurveViolationError(ValueError):
    """Phase-2 equity 曲线违反 §2 资金物理不变量。"""


def assert_equity_curve_is_physical(
    equity_df: pd.DataFrame,
    *,
    engine: str,
    preset: str,
) -> None:
    """拒绝发布现金为负 / 权益非正的 equity 曲线 (§2 + §0 Fail-Fast)。

    只检查"物理上不可能"的那两条:
      * cash   < 0  —— 无保证金账户不得透支 (§2 Margin Gatekeeper / 三池隔离)
      * equity <= 0 —— 权益归零即破产; 负权益是记账错误, 不是亏损
    不做任何"正常范围"的启发式判断 —— 大回撤本身不是错误。
    """
    if equity_df is None or len(equity_df) == 0:
        return
    if "cash" in equity_df.columns:
        worst_cash = float(equity_df["cash"].min())
        if worst_cash < 0.0:
            raise EquityCurveViolationError(
                f"{engine} preset={preset}: equity 曲线出现负现金 "
                f"(min cash = {worst_cash:,.2f})。§2: 无保证金账户不得透支。"
                f"这通常意味着 Phase-2 的累计 equity_delta 与 Phase-1 复利曲线"
                f"量纲不匹配 —— 曲线不是有效的权益重建, 不得当作结果发布。"
            )
    if "equity" in equity_df.columns:
        worst_equity = float(equity_df["equity"].min())
        if worst_equity <= 0.0:
            raise EquityCurveViolationError(
                f"{engine} preset={preset}: equity 曲线出现非正权益 "
                f"(min equity = {worst_equity:,.2f})。§2: 资本是物理且有限的, "
                f"负权益是记账错误而不是亏损。拒绝发布该曲线。"
            )
