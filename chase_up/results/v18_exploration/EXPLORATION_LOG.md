# v18 探索日志 (2026-09-21)

## 起点

v17 锁定窗口 +1285.01% / Sharpe 4.18 / DD 18.07% / WR 49.3% / PF 1.93,
walkforward 均值 +116.94% / worst -79.08% / 3/9 盈利。

目标:寻找更多 Pareto 改善 (locked 不变 + WF 均值提升)。

## 失败尝试 (全部回归)

| 改动 | locked trades | CAGR | Sharpe | WF mean | 备注 |
|------|--------------|------|--------|---------|------|
| v17 baseline | 73 | +1285% | 4.18 | +116.94% | 起点 |
| breakout_vol_min 1.5→2.0 | 80 | +157% | 1.73 | - | 严重回归 |
| breakout_vol_min 1.5→1.7 | 75 | +685% | 3.33 | - | 仍回归 |
| min_score 1.7→1.75 | 74 | +1325% | 4.23 | +91.89% | locked 微改善, WF 显著回归 |
| atr_sl_mult 1.5→1.7 | 73 | +1516% | 4.49 | +97.46% | locked 改善, WF 回归 |
| atr_tp_mult 6.0→7.0 | 63 | +259% | 2.13 | - | TP 太远,损失大盈利 |
| min_amount 3e7→5e7 | 66 | +584% | 3.25 | - | 砍小盘,意外破坏 locked |
| atr_pct_low 0.035→0.040 | 80 | +817% | 3.50 | - | 边界过滤,shifted 队列 |
| max_hold 18→15 | 72 | +315% | 2.42 | - | 长持仓本来是盈利(winners) |

## 关键发现

1. **长持仓(h>=8) 是策略的金块**:
   - 148 trades, WR 64.2%, avg +11.37%, 总净利 +16.8M
   - 减 max_hold 切掉了这条利润腿

2. **day-1 SL 主导负窗口损失**:
   - walkforward 中 297/788 (37.7%) 是 day-1 SL,平均亏 -10.7%
   - locked 也有 17 个 day-1 SL,但其中部分最终算赢

3. **A-only 信号是负窗口主因**:
   - walkforward 中 A-only (387) WR 25.8% avg -0.21%
   - 而 A-only 输家 mom120 median 0.775,A-only 赢家 1.176 (差异显著)
   - 但 locked 也有 32 个 A-only 交易,mom120 分布类似,提高门槛会破坏 locked

4. **几乎所有参数调整都破坏 locked**:
   - 调整 vol_min / min_amount / atr_pct_low / breakout_vol_min
   - 即使是"温和"改动 (±0.001, ±0.05, ±0.5e7) 也会替换同日 entry 队列中的某些股票
   - 因为 max_positions=2,即使保留 71 trades,如果某日的 top-2 排名变了,就会替换
   - 73 trades 的整体指标因此漂移

5. **PF > CAGR 关系**:
   - 2025-09→2026-09 locked 是一个异常好的牛市期
   - 该窗口自身 WF +1013% (接近 locked 的 +1285%)
   - 其他 8 个窗口中只有 1 个真正正(2021-09 +326%)
   - 想在 locked 上加更多约束而不破坏它是反 desired

## 结论

**v17 是该信号框架的最优 Pareto 点**。
进一步改善需要:
1. 新增信号组件 (例如行业轮动 / 市场 regime filter / 涨跌停 / 北向资金)
2. 或者使用 SH index / 板块指数作为额外过滤
3. 或者重新设计 SL/TP 退出机制 (例如动态 trailing stop)

## 已锁定不动的文件

- v17 golden baseline: tests/golden/chase_v17_baseline.json
- trades.csv SHA256: f733347dacd72c6682ebfc58897c2bb9cd2094c1891291c91b005920aac1df6a

下次循环可继续探索的方向:
- [ ] 添加 regime filter: 当 SH index 跌破 MA60 时降仓或禁用
- [ ] 改用 volatility-targeted position sizing
- [ ] 增加 sector concentration limit
- [ ] 添加"连续 2 日 close > MA20"动量确认
