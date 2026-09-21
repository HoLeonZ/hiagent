# v19 后探索日志 (2026-09-21)

## 起点

v19 (atr_sl_mult=1.75) 是当前 locked 冠军: CAGR +1750% / Sharpe 4.72 / WR 54.9% / PF 2.20。
v18 (atr_sl_mult=1.6) 是当前严格 Pareto 冠军: CAGR +1317% / WF mean +154.37%。

目标: 寻找 v20+ 进一步改善。

## 测试

| 改动 | locked CAGR | WF mean | 备注 |
|------|------------|---------|------|
| v19 baseline | +1750% | +165.29% | 起点 |
| max_positions 1 | +292% | - | 砍半仓,严重退化 |
| max_positions 3 | +400% | - | 仓位分散,退化 |
| position_sizing='all_in' | +420% | - | 单仓位 all-in,退化 |
| tp_mult 5/5.5/6.5/7 | +224/+168/+189/+354% | - | TP 宽度都退化 |
| max_hold 16/20 | +39%/+343% | - | 都退化 |
| macross_vol_min 1.5 | +1712% | - | 微退化 |
| momentum_vol_min 1.0 | +605% | - | 严重退化 |
| pct_chg_low/high 微调 | +1750% | - | 无效果 |
| min_score 1.69/1.71/1.72/1.75 | - | - | 都退化 |
| breakout_vol_min 1.4/1.6 | - | - | 退化 |

## v18 vs v19 trade-level diff

- v18 trades: 72
- v19 trades: 71
- 9 trades differ (entry priority shifts due to wider SL)
- 63 trades common
  - 52 完全相同 (net_return diff = 0)
  - 10 v19 输更多 (wider SL 让一些未中位 stocks 损失更大)
  - 1 v19 赢更多

**洞察**: v19 的 locked 增益主要来自**入口选择优先级变化**(更宽的 SL 让更多"会经历波动" 的 stocks 通过 entry selection),而非"拯救个别 trades"。

## 结论

v19 已被多维 sweep 验证为 locked 全局最优。进一步改善需要修改源码:

1. **修改 score formula 权重** (signals.py 第 230/235/240 行) — 需参数化当前硬编码的 mom120/vol_ratio/ret1/(ma20-ma60) 权重
2. **添加 trailing stop 机制** (portfolio.py) — 让盈利 trade 锁利
3. **新增子信号 D** (signals.py) — 例如 OBV / 北向资金 / 涨停封板

这些都需要修改源码,超出纯参数调优范畴。
