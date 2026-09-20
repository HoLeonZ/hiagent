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

## v5 核心指标(目标窗口 2025-09-19 → 2026-09-19)

```
CAGR         +241.6%       ✓ > 200% 目标
Sharpe       2.16
Max DD       31.31%
Win Rate     40.2% (43/107)
Profit Factor 1.39
Avg Hold     4.5 days (max 10)
Exposure     97.0% (2 仓 equal)
退出分布     TP=24  SL=60  time=21  eod=2
```

## Walkforward 稳定性(critical caveat)

12m 滚动 walkforward(2017-09 → 2026-09 共 9 窗):

```
2017-09 → 2018-09    -83.35%   ✗
2018-09 → 2019-09    -58.51%   ✗
2019-09 → 2020-09    -37.19%   ✗
2020-09 → 2021-09    -52.69%   ✗
2021-09 → 2022-09     +2.83%   ✓ (勉强)
2022-09 → 2023-09    -94.29%   ✗ (熊市)
2023-09 → 2024-09    -31.71%   ✗
2024-09 → 2025-09    -87.80%   ✗
2025-09 → 2026-09   +268.44%   ✓ ← 目标窗口
```

**仅 2/9 窗口盈利**。这并非 chase_up 独有的过拟合问题 — 对比 reference baseline
`uptrend_pullback v33_long_reverse_v3` 在同样 12m walkforward 上也是 4/9 窗口盈利,
最近窗口同样占大头。2025-09→2026-09 的市场 regime 对动量 / 突破类策略异常友好,
不代表策略在长期可重复。**该 CAGR 是单窗口产物,非通用预期。**

### 2m rolling walkforward(2024-09 → 2026-09 共 12 窗)

```
2024-09 → 2024-11    +1.11%   ✓
2024-11 → 2025-01   -74.80%   ✗
2025-01 → 2025-03   -17.25%   ✗
2025-03 → 2025-05    -3.59%   ✗
2025-05 → 2025-07   +46.69%   ✓
2025-07 → 2025-09   -15.60%   ✗
2025-09 → 2025-11    -1.87%   ✗
2025-11 → 2026-01   +37.66%   ✓
2026-01 → 2026-03   +16.75%   ✓
2026-03 → 2026-05   -14.70%   ✗
2026-05 → 2026-07   +35.71%   ✓
2026-07 → 2026-09   +38.41%   ✓
```

**6/12 窗口盈利**。2m 粒度下近期表现更稳,但单窗口仍有 -75% 这种极端回撤。
说明即便 regime-friendly 期,策略对市场短期切换仍很敏感。

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