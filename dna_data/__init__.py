"""dna_data — 数据访问层。

CLAUDE.md §6 控制平面 / 策略 / 执行代理 三层分离下,本包是控制平面
的数据装载层(对外 I/O,与核心业务逻辑解耦)。

模块:
  - dual_price_loader: 从 v_daily_dual view 装载 adj_*/raw_* 双价 panel
  - dual_price_resolver: 把 preset 声明的 price_source_for_signal /
    price_source_for_execution 解析到具体列(adj_close / raw_close / close)
"""
from __future__ import annotations

from .dual_price_loader import load_dual_price_panel

__all__ = ["load_dual_price_panel"]