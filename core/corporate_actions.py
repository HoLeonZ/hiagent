"""事件化公司行为 — 共享领域层(CLAUDE.md §3, audit P2-10, 2026-10-15)。

CLAUDE.md §3 逐字要求:
  - "Cash dividends must explicitly trigger a physical cash deposit into
     `Free_Cash`."
  - "Stock splits must trigger an atomic multiplier adjustment to
     `Position_Quantity` and `Average_Cost`."

为什么必须有:四个引擎的执行域是**原始价**,除权日 raw 价向下跳空。没有事件源时
那个缺口被当成真实盈亏 —— 多头系统性少计分红,空头把缺口记成利润。

本模块是**纯函数 + 零外部依赖**(与 `core.dual_price` 同约定),四个引擎共用同一份
实现。事件的读取(DB I/O)在各引擎的 data 层完成,并把列注入 panel —— 这样
portfolio / broker 层保持无 DB(§6 分层)。

口径说明
--------
  分红: `cash_delta = size × dividend_per_share`,对**多头为正**。
        空头由调用方取负 —— 做空者需要**付出**分红(§4 借券模型的应有之义),
        本函数不替调用方决定方向,以免把符号错误藏进共享代码里。
  送股/拆股: `size × (1 + bonus_ratio)`,并按 `ep × size_old / size_new` 重定成本价,
        **总成本基不变**(无现金流)。这保证 `entry_price × size` 不变,从而与各
        引擎 `_close` 里 `release_margin(ep*size + entry_fee)` 的口径兼容。
  配股(`rights_ratio > 0`): **不建模** —— §3 未规定其语义,且全库窗口内仅 1 例。
        显式产出 warning,由调用方落日志;绝不静默。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorporateActionOutcome:
    """一次公司行为作用在单个持仓上的结果(不可变)。"""

    size: int
    entry_price: float
    cash_delta: float
    warnings: tuple[str, ...] = ()


def apply_corporate_action(
    *,
    size: int,
    entry_price: float,
    dividend_per_share: float = 0.0,
    bonus_ratio: float = 0.0,
    rights_ratio: float = 0.0,
) -> CorporateActionOutcome:
    """对单个持仓应用除权日事件。纯函数:不修改入参,不读全局状态。

    幂等性:对同一 (size, entry_price, 事件) 反复调用得到相同结果 —— 调用方
    负责"每根 bar 只应用一次"(事件列按 (thscode, ex_date) 聚合,天然一次)。
    """
    warnings: list[str] = []
    out_size = int(size)
    out_ep = float(entry_price)

    # ---- 送股 / 拆股:先调数量,再据数量算分红(与除权日的经济实质一致) ----
    if bonus_ratio and bonus_ratio > 0:
        new_size = max(1, int(round(out_size * (1.0 + float(bonus_ratio)))))
        if new_size != out_size:
            total_cost = out_ep * out_size
            out_size = new_size
            out_ep = total_cost / new_size

    # ---- 现金分红 ----
    cash_delta = 0.0
    if dividend_per_share and dividend_per_share > 0:
        cash_delta = out_size * float(dividend_per_share)

    # ---- 配股:不建模,显式告警 ----
    if rights_ratio and rights_ratio > 0:
        warnings.append(
            f"配股未建模 (rights_ratio={float(rights_ratio):.4f});§3 未规定配股语义,"
            "显式跳过而非静默处理"
        )

    return CorporateActionOutcome(
        size=out_size,
        entry_price=out_ep,
        cash_delta=cash_delta,
        warnings=tuple(warnings),
    )


__all__ = ["CorporateActionOutcome", "apply_corporate_action"]
