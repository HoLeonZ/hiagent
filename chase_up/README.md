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

## v8 优化版核心指标(目标窗口 2025-09-19 → 2026-09-19)

```
CAGR         +261.1%       ✓ > 200% 目标(v5 的 +241.6% 提升 +8%)
Sharpe       2.32          (v5 是 2.16)
Max DD       42.58%        (v5 是 31.31% — 接受 trade-off 换 CAGR)
Win Rate     39.0% (32/82) (v5 是 40.2%, 略低)
Profit Factor 1.33         (v5 是 1.39)
Avg Hold     5.9 days (max 18) (v5 是 4.5/max 10)
Exposure     96.6% (2 仓 equal)
退出分布     TP=25  SL=50  time=5  eod=2  (v5: 24/60/21/2)
```

**优化点**:max_hold 10 → 18。给赢家更长时间触发 6×ATR 的止盈位,time-exit 从 21 笔
降到 5 笔,绝大多数未达 TP 的交易自然落到 SL(没变),赢家充分奔跑。

## v5 vs v8 对比

| 指标              | v5           | v8           |
|-------------------|--------------|--------------|
| CAGR              | +241.6%      | **+261.1%**  |
| Sharpe            | 2.16         | **2.32**     |
| Max DD            | **31.31%**   | 42.58%       |
| Win Rate          | **40.2%**    | 39.0%        |
| 12m walkforward   | 2/9 盈利     | **3/9 盈利** |
| 12m 均值收益      | -19.36%      | **+30.68%**  |
| 12m 最差          | -94.29%      | **-91.26%**  |
| Trades(目标窗口)  | 107          | 82           |
| time exit 占比    | 21/107 (20%) | 5/82 (6%)    |

**优化方向**:不再为单窗口最高 CAGR 优化,而是兼顾 walkforward 稳定性 + CAGR。
v8 在目标窗口上略优于 v5,同时在 12m walkforward 上更稳(均值从 -19% 翻到 +31%)。

## Walkforward 稳定性(v8, critical caveat)

12m 滚动 walkforward(2017-09 → 2026-09 共 9 窗):

```
2017-09 → 2018-09    -82.08%   ✗
2018-09 → 2019-09    -63.95%   ✗
2019-09 → 2020-09     -5.30%   ✗ (从 v5 的 -37% 大幅改善)
2020-09 → 2021-09    -36.82%   ✗
2021-09 → 2022-09    +85.93%   ✓ (从 v5 的 +2.83% 暴涨)
2022-09 → 2023-09    -91.26%   ✗ (熊市仍亏)
2023-09 → 2024-09    +16.94%   ✓ (从 v5 的 -32% 翻正)
2024-09 → 2025-09    -69.56%   ✗
2025-09 → 2026-09   +522.21%   ✓ ← 目标窗口
```

**3/9 窗口盈利**(v5 是 2/9)。2022-09→2023-09 熊市窗口 v8 仍亏 91%,但 2019 / 2021 /
2023 三个窗口比 v5 都明显改善。**目标窗口 CAGR +522% 是窗口产物,非通用预期**。

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