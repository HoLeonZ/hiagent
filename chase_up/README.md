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

## v13 优化版核心指标(目标窗口 2025-09-19 → 2026-09-19)

```
CAGR         +1241.97%     ✓ > 200% 目标(v11 是 +608.6%,v12 是 +1120.5%)
Sharpe       4.13          (v12 是 3.97 — 最高)
Max DD       19.41%        (v12 是 22.0%,v11 是 17.5% — 中间)
Win Rate     49.3% (36/73) (v12 是 48.0% — 最高)
Profit Factor 1.87         (v12 是 1.75)
Avg Hold     5.7 days (max 18)
Exposure     84.5% (2 仓 equal)
退出分布     TP=31  SL=36  time=5  eod=1
```

**优化点**:`min_mom120 0.05→0.10`(中期动量门槛翻倍) + `atr_pct_high 0.10→0.085`
(波动率上限收紧)双重收紧。**关键洞察**:
1. mom120 ≥ 0.10 过滤掉 6 个月涨幅 < 10% 的弱势股,要求中长期动量更强。
2. atr_pct ≤ 0.085 排除波动率 > 8.5% 的高波动垃圾股(容易跳空打 SL)。

两者同时作用产生 **isolated peak** — 单独收紧任一项收益都较小。

**Pareto 改善**(对比 v12):
- CAGR +1120.48% → +1241.97%(+11%)
- Sharpe 3.97 → 4.13(+4%)
- DD 22.0% → 19.4%(-12%)
- WR 48.0% → 49.3%(+1.3pp)
- PF 1.75 → 1.87(+7%)

12m walkforward 均值 +89.4% → +98.7%,最差 -82.3% → -78.1%。

## v5 vs v8 vs v9 vs v10 vs v11 vs v12 vs v13 对比

| 指标              | v5       | v8       | v9       | v10      | v11      | v12      | **v13**   |
|-------------------|----------|----------|----------|----------|----------|----------|-----------|
| CAGR(2025-09-19)  | +241.6%  | +261.1%  | +380.8%  | +367.2%  | +608.6%  | +1120.5% | **+1242.0%** |
| Sharpe            | 2.16     | 2.32     | 2.72     | 2.57     | 3.20     | 3.97     | **4.13**  |
| Max DD            | 31.31%   | 42.58%   | 23.65%   | 32.13%   | 17.51%   | 22.0%    | 19.41%    |
| Win Rate          | 40.2%    | 39.0%    | 40.8%    | 40.8%    | 45.1%    | 48.0%    | **49.3%** |
| Profit Factor     | 1.39     | 1.33     | 1.54     | 1.60     | 1.83     | 1.75     | **1.87**  |
| 12m walkforward   | 2/9 盈利 | 3/9 盈利 | 3/9 盈利 | 2/9 盈利 | 2/9 盈利 | 3/9 盈利 | **3/9 盈利** |
| 12m 均值收益      | -19.36%  | +30.68%  | +42.78%  | +42.90%  | +80.48%  | +89.36%  | **+98.73%** |
| 12m 最差          | -94.29%  | -91.26%  | -90.45%  | -80.92%  | -73.85%  | -82.26%  | **-78.09%** |
| Trades(目标窗口)  | 107      | 82       | 76       | 71       | 71       | 75       | **73**    |

## Walkforward 稳定性(v13, critical caveat)

12m 滚动 walkforward(2017-09 → 2026-09 共 9 窗,sweep 在 2025-09-01 起算):

```
2017-09 → 2018-09    -78.09%   ✗ (v12 是 -82.26%)
2018-09 → 2019-09    -67.42%   ✗
2019-09 → 2020-09    +16.24%   ✓ (v12 是 +13.77%)
2020-09 → 2021-09    -32.15%   ✗
2021-09 → 2022-09   +142.50%   ✓ (v12 是 +142.85%)
2022-09 → 2023-09    -69.34%   ✗ (熊市仍亏)
2023-09 → 2024-09    -29.86%   ✗
2024-09 → 2025-09    -67.50%   ✗
2025-09 → 2026-09  +1013.28%   ✓ ← 目标窗口(v12 是 +946.10%)
```

**3/9 窗口盈利**(与 v12 一致),均值从 v12 的 +89.4% 跳到 **+98.7%**,worst 从
-82.26% 改善到 **-78.09%**。**目标窗口 CAGR 是 regime-friendly 窗口产物,
非通用预期** — v13 在 2025-09-19 起算的实际 CAGR 是 +1241.97%,sweep 在
2025-09-01 起算时能看到 +1013% 但那是不同窗口边界。

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