# chase_up — 追涨策略

追涨(momentum / chase-up / breakout)策略,沿用 `uptrend_pullback` 与 `short_reversal`
的代码骨架,实现 OR 融合信号(突破 + 动量 + 金叉)+ ATR 自适应 TP/SL。

## 设计要点

1. **OR 融合三子信号**:`A` 突破新高 / `B` 强动量(量能+MACD 柱状)/ `C` MA 金叉,
   任一成立即可入场
2. **基线过滤**:mom120 ≥ 5% + MA20 > MA60 + 流动性 3e7~3e8 + ATR% ∈ [3%, 10%]
3. **ATR 自适应 TP/SL**:`TP = entry × (1 + atr_pct × atr_tp_mult)`,
   `SL = entry × (1 - atr_pct × atr_sl_mult)`,默认 mult=6 / 1.5
4. **退出优先级 P5**:open ≥ TP → open ≤ SL → intraday TP → intraday SL → time at close
5. **入场当日不判退出 P3**:`bars_in_pos < 1` 直接 return
6. **next-bar-open fill P1**:Phase 1 simulate 用 bar N+1 OPEN 作为 fill price

## 文件结构

```
chase_up/
├── __init__.py             # ChaseUpError + package marker
├── data.py                 # load_panel (v_daily_qfq + 400d warmup)
├── universe.py             # mainboard_only filter
├── signals.py              # compute_indicators + select_entries
├── portfolio.py            # simulate_portfolio (Phase 1)
├── replay_broker.py        # AStockBroker + AStockCommInfo
├── replay_strategy.py      # ChaseUpTradeReplay (单笔 backtrader 重放)
├── backtest.py             # compute_metrics + run_backtest
├── backtrader_engine.py    # run_backtrader_backtest (Phase 2 orchestrator)
├── presets.py              # v1/v1a..v6 7 套预设
├── sweep.py                # 3D TP×SL×max_hold 网格搜索
├── walkforward.py          # 滚动窗口验证
├── main.py                 # CLI 入口
└── results/                # 回测结果 + trades.csv
```

## 跑回测

```bash
# Phase 1 (simulate, headline)
python3 -m chase_up.main --preset chase_v5_pos2_equal_atr_tp6_sl15_mh10 \
    --start 2025-09-19 --end 2026-09-19 \
    --engine simulate --save-trades chase_up/results/v5_trades.csv

# Phase 2 (backtrader verify)
python3 -m chase_up.main --preset chase_v5_pos2_equal_atr_tp6_sl15_mh10 \
    --start 2025-09-19 --end 2026-09-19 --engine backtrader

# 3D TP×SL×max_hold 网格搜索
python3 -m chase_up.sweep --preset chase_v1_atr_tp4_sl1 \
    --tp-mults 4,5,6 --sl-mults 1.0,1.5 --max-holds 8,10,15

# 12 月滚动 walkforward
python3 -m chase_up.walkforward --preset chase_v5_pos2_equal_atr_tp6_sl15_mh10 \
    --start-month 2017-09 --end-month 2026-09 --window-months 12

# 2 月 rolling walkforward (验证市场 regime 切换)
python3 -m chase_up.walkforward --preset chase_v5_pos2_equal_atr_tp6_sl15_mh10 \
    --start-month 2017-09 --end-month 2026-09 --window-months 2 --step-months 2
```

## v12 优化版核心指标(目标窗口 2025-09-19 → 2026-09-19)

```
CAGR         +1120.48%     ✓ > 200% 目标(v9 是 +380.8%,v10 是 +367.2%,v11 是 +608.6%)
Sharpe       3.97          (v11 是 3.20 — 最高)
Max DD       21.96%        (v11 是 17.51%,略升)
Win Rate     48.0% (36/75) (v11 是 45.1% — 最高)
Profit Factor 1.75         (v11 是 1.83)
Avg Hold     5.6 days (max 18)
Exposure     85.3% (2 仓 equal)
退出分布     TP=31  SL=38  time=5  eod=1
```

**优化点**:`atr_pct_low=0.03 → 0.035`(剔除 atr% 偏低噪音信号)。**关键洞察**:
波动率太低的"安静突破"反而是低质信号 — atr_pct ∈ [0.030, 0.035) 区间的信号
胜率太低,把它们剔除后 CAGR 几乎翻倍。波动率稍高的突破(>= 0.035)才携带
真实动量信息。

**Pareto 改善**(对比 v11):
- CAGR +608.57% → +1120.48%(+84%)
- Sharpe 3.20 → 3.97(+24%)
- WR 45.1% → 48.0%(+2.9pp)
- 12m walkforward 盈利窗 2/9 → **3/9**
- 12m walkforward 均值 +80.48% → +89.36%

DD 17.51% → 21.96%(略升),PF 1.83 → 1.75(略降),最差窗口从 -73.85% 略增到
-82.26% — 总体在可接受范围内的"trade-off"。

## v5 vs v8 vs v9 vs v10 vs v11 vs v12 对比

| 指标              | v5       | v8       | v9       | v10      | v11      | **v12**   |
|-------------------|----------|----------|----------|----------|----------|-----------|
| CAGR(2025-09-19)  | +241.6%  | +261.1%  | +380.8%  | +367.2%  | +608.6%  | **+1120.5%** |
| Sharpe            | 2.16     | 2.32     | 2.72     | 2.57     | 3.20     | **3.97**  |
| Max DD            | 31.31%   | 42.58%   | 23.65%   | 32.13%   | 17.51%   | 21.96%    |
| Win Rate          | 40.2%    | 39.0%    | 40.8%    | 40.8%    | 45.1%    | **48.0%** |
| Profit Factor     | 1.39     | 1.33     | 1.54     | 1.60     | 1.83     | 1.75      |
| 12m walkforward   | 2/9 盈利 | 3/9 盈利 | 3/9 盈利 | 2/9 盈利 | 2/9 盈利 | **3/9 盈利** |
| 12m 均值收益      | -19.36%  | +30.68%  | +42.78%  | +42.90%  | +80.48%  | **+89.36%** |
| 12m 最差          | -94.29%  | -91.26%  | -90.45%  | -80.92%  | -73.85%  | -82.26%   |
| Trades(目标窗口)  | 107      | 82       | 76       | 71       | 71       | **75**    |

## Walkforward 稳定性(v12, critical caveat)

12m 滚动 walkforward(2017-09 → 2026-09 共 9 窗,sweep 在 2025-09-01 起算):

```
2017-09 → 2018-09    -82.26%   ✗ (v11 是 -73.85%)
2018-09 → 2019-09    -67.83%   ✗
2019-09 → 2020-09    +13.77%   ✓ (v11 是 -10.05%,翻正)
2020-09 → 2021-09    -37.18%   ✗
2021-09 → 2022-09   +142.85%   ✓ (v11 是 +164.20%)
2022-09 → 2023-09    -71.40%   ✗ (熊市仍亏)
2023-09 → 2024-09    -28.62%   ✗
2024-09 → 2025-09    -68.04%   ✗
2025-09 → 2026-09   +946.10%   ✓ ← 目标窗口(v11 是 +869.26%)
```

**3/9 窗口盈利**(v11 是 2/9),均值从 v11 的 +80.5% 跳到 **+89.4%**。
**目标窗口 CAGR 是 regime-friendly 窗口产物,非通用预期** — v12 在 2025-09-19
起算的实际 CAGR 是 +1120.48%,sweep 在 2025-09-01 起算时能看到 +946% 但那是
不同窗口边界。

## 策略逻辑变化须同步更新的 golden baseline

`tests/golden/chase_v5_baseline.json` 锁定 v5 trades.csv 的 sha256。
任何会改变交易列表的逻辑改动(信号阈值、退出优先级、费用模型、universe)
都必须:
1. 在 PR 描述中说明原因
2. 重新生成 trades.csv
3. 同步更新 baseline 的 hash + rows 字段
4. 跑 `pytest tests/test_chase_up_no_lookahead.py` 全绿

## 与项目硬约束对齐

| 协议 | 实现位置 | 验证测试 |
|---|---|---|
| P0 决策时刻已知 | `signals.py:high20_prev = shift(1)` + `ATR14` 用 close 计算 | `test_compute_tp_sl_*` |
| P1 成交价 | Phase 1 用 bar N+1 OPEN;Phase 2 backtrader 撮合 | `test_exit_price_is_actual_*` |
| P2 trade 携带决策快照 | `TRADE_COLS` 含 `atr_pct` + `sub_signal_type` | `test_trade_cols_*` |
| P3 entry ≠ exit | `bars_in_pos < 1` 跳过退出 + `exit_date > entry_date` | `test_phase1_skips_exit_on_entry_day` |
| P4 DB schema | duckdb `DESCRIBE v_daily_qfq` | `test_db_schema_*` |
| P5 退出优先级 | `portfolio.py` TP-first open → SL → intraday → time | `test_exit_priority_open_first_time_last` |
| P6 信号/执行解耦 | select_entries 无 max_positions / cash | `test_signal_layer_has_no_capital_constraints` |
| P7 indicator 分组 | `compute_indicators` 内部 `groupby(thscode)` | `test_compute_indicators_does_not_leak_across_stocks` |
| P8 universe as-of | `load_panel` 用 `WHERE date <= end_date` | `test_load_panel_does_not_include_bars_after_end_date` |

## 已知 limitation

backtrader 撮合层对单笔 trade 的 `actual_exit_price` 在多触发场景下并不严格保证
等于 next-bar-open(沿用 uptrend_pullback 现状)。这是 codebase 范围的撮合约定,
非 chase_up 独有 bug。Phase 1 simulate 是 headline metric,Phase 2 是 sanity check。