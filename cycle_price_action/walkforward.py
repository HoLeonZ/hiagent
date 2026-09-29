"""Walk-forward validation window generator for cycle_price_action.

2026-09-23 迁移: 重新导出 core.walkforward 共用 API, 4-engine 共享同一份代码。
原实现保留作 fallback (deprecation 路径), 强制外部 import 走 core。

CLAUDE.md §5 合规：re-export dna_stats.deflated 让 cycle sweep 脚本
(cycle_price_action.sweep_thresholds / main.run) 共享同一份 DSR/Bonferroni
工具, 不重复实现。
"""
from __future__ import annotations

# 4-engine 共用 WFV 窗口生成 (CLAUDE.md §5)
from core.walkforward import (  # noqa: F401
    WalkForwardWindow,
    walkforward_windows,
)
from dna_stats.deflated import (  # noqa: F401
    deflated_sharpe_ratio,
    bonferroni_correct,
)