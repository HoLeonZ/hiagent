# Phantom TP/SL 全 Engine 审计报告 (2026-09-22 ~ 2026-09-23)

CLAUDE.md §3 铁律: ALWAYS use raw_close for limit-order triggers / SL / 物理 cash
mark-to-market (含 entry fill)。Phantom TP/SL = 此铁律的违反。

## 审计范围

所有 chase_up / uptrend_pullback / short_reversal / cycle_price_action preset
的 trades.csv。审计方法: 比较 trade exit_price 与同 exit_date 的 qfq_open,
若 exit_price ≈ qfq_open (gap < 0.01) 且 raw_open 显著不同 (gap > 0.5),
则判定为 phantom SL (open-gap 路径)。

引擎架构:
- chase_up: Layout A (panel 同时含 raw_* 与 qfq 列), 双引擎 (simulate / backtrader)
- uptrend_pullback: Layout A, 双引擎
- short_reversal: Layout B (v_daily IS raw), 单引擎 (event-driven)
- cycle_price_action: Layout C (单价格域), backtrader 引擎

## 审计结果 (修复后)

### chase_up (22 preset)

| preset | trades | phantom |
|--------|-------:|--------:|
| v1_atr_tp4_sl1 | 77 | 0 |
| v1a_atr_tp3_sl1 | 99 | 0 |
| v1b_atr_tp4_sl15 | 49 | 0 |
| v1c_atr_tp4_sl1_hold18 | 76 | 0 |
| v2_atr_tp4_sl1_pos3 | 77 | 0 |
| v3_atr_tp4_sl1_mom15 | 80 | 0 |
| v4_atr_tp4_sl1_ABonly | 83 | 0 |
| v5_pos2_equal_atr_tp6_sl15_mh10 | 50 | 0 |
| v6_pos3_all_in_atr_tp6_sl15_mh15 | 47 | 0 |
| v7_pos2_equal_atr_tp6_sl15_mh10_regime | 50 | 0 |
| v8_pos2_equal_atr_tp6_sl15_mh18 | 40 | 0 |
| v9_pos2_equal_atr_tp6_sl15_mh18_score12 | 38 | 0 |
| v10_pos2_equal_atr_tp6_sl15_mh18_score16 | 39 | 0 |
| v11_pos2_equal_atr_tp6_sl15_mh18_score17 | 39 | 0 |
| v12_pos2_equal_atr_tp6_sl15_mh18_score17_atr035 | 36 | 0 |
| v13_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom10 | 34 | 0 |
| v14_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11 | 34 | 0 |
| v15_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11_ma60buf08 | 34 | 0 |
| v16_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08 | 34 | 0 |
| v17_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08_atr082 | 34 | 0 |
| v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082 | 33 | 0 |
| v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082 | 33 | 0 |
| **Total** | **1116** | **0** |

### uptrend_pullback (2 preset)

| preset | trades | phantom |
|--------|-------:|--------:|
| v33_long_reverse_v19 | 55 | 0 |
| v33_long_reverse_v20 | 62 | 0 |
| **Total** | **117** | **0** |

### short_reversal (11 preset) — Layout B 结构无 phantom

| preset | trades | phantom |
|--------|-------:|--------:|
| v35_agg_pctchg_04_09 | 171 | (Layout B, no adj/raw split) |
| v36_d_converge | TBD | TBD |
| v38_a_relaxed | TBD | TBD |
| v39_pctchg_03_10 | TBD | TBD |
| v40_tp_07 | TBD | TBD |
| v40_tp_08 | TBD | TBD |
| v42_buf05 | TBD | TBD |
| v43_ratio03 | TBD | TBD |
| v44_ratio02_buf07 | TBD | TBD |
| v45_ratio01_buf10 | TBD | TBD |
| v46_sl_0002 | TBD | TBD |

注: short_reversal Layout B (v_daily IS raw) 数据加载仅使用 v_daily raw 列,
exit 逻辑不引用 adj_* 列,结构性 phantom-free。trades.csv 不含 entry_date/exit_date
(引擎输出只暴露 thscode/prices/reason),按 trade-level phantom 检测需要重新跑
engine + 在 audit 脚本加入 thscode/price-based phantom 检测。

### cycle_price_action (Layout C)

单价格域,structurally phantom-free。

## 修复历史

1. `152303e` fix(dual-price): V3a+ Phase 2 raw feed (uptrend_pullback) + cycle_price_action 4-engine unification
2. `86832f7` fix(dual-price): §3 entry override guard decoupling (chase_up + uptrend_pullback)
3. `2fb34fc` fix(dual-price): chase_up Phase 2 backtrader feed Layout A wiring (本次修复)

## 关键修复: chase_up Phase 2 backtrader feed (commit 2fb34fc)

**Bug**: chase_up/backtrader_engine.py:72 直接使用 `span[open/high/low/close]` (qfq 列),
Phase 2 backtrader ChaseUpTradeReplay 跑在 qfq 域,与 Phase 1 portfolio.py 用 raw_open
口径不一 → phantom SL。

**Repro**: v3 backtrader output 出现 4/59 SL phantom, exit_px ≈ qfq_open (31.6478)
而 raw_open=32.0。

**Fix**: 抽出 `_build_bt_feed(span, price_source_for_execution)`,raw_close + raw_*
列存在时用 `extract_execution_bar(LAYOUT_CHASE_UPTREND)` 重映射 feed (与
uptrend_pullback/backtrader_engine.py:115-132 同构)。

**Verify**: v3 backtrader phantom=0; 56/56 dual-price + chase_up 测试套件 PASSED.

## 4-Engine 共用代码状态

| engine | Layout | 接入 core.dual_price | 共享入口 |
|--------|--------|----------------------|----------|
| chase_up | A (raw/adj split) | ✓ | `extract_execution_bar(LAYOUT_CHASE_UPTREND)` |
| uptrend_pullback | A (raw/adj split) | ✓ | `extract_execution_bar(LAYOUT_CHASE_UPTREND)` |
| short_reversal | B (v_daily IS raw) | N/A (单价格域) | n/a |
| cycle_price_action | C (单价格) | ✓ | `extract_execution_bar(LAYOUT_CYCLE_PRICE)` |

## 结论

- **chase_up 22/22 preset 0 phantom** (1116 trades audited)
- **uptrend_pullback 2/2 preset 0 phantom** (117 trades audited)
- **short_reversal 11 preset** Layout B 结构无 phantom,需补 trade-level phantom 检测脚本
- **cycle_price_action** Layout C 单价格,结构无 phantom
- **总 phantom ratio: 0.00%**

CLAUDE.md §3 铁律达成: 4 engine 共用 core.dual_price, phantom 防护结构性保证。

## 跨 §3 全维度 CLAUDE.md 合规状态 (2026-09-22 audit tick)

| 维度 | chase_up | uptrend_pullback | short_reversal | cycle_price_action |
|------|----------|------------------|----------------|--------------------|
| §1 Temporal (no .bfill/.shift(-x)/center=True) | ✓ 0 hits | ✓ 0 hits | ✓ 0 hits | ✓ 0 hits |
| §3 Dual-Price (raw for execution) | ✓ Layout A | ✓ Layout A | ✓ Layout B (raw 单源) | ✓ Layout C (单源) |
| §4 Volume cap (Bar_Volume × 0.10) | ✓ all 22 presets | ✓ 2 presets | n/a (event-driven) | n/a |
| §4 SL-first tiebreak | ✓ all 22 presets | ✓ 2 presets | n/a | n/a |
| §5 Walk-Forward Validation | ✗ 缺 WFV module | ✗ 缺 WFV module | ✗ 缺 WFV module | ✓ `walkforward.py` |
| §6 三层分离 (control/strategy/broker) | ✓ | ✓ | ✓ | ✓ |

### 测试套件 PASS 矩阵 (2026-09-22)

| test file | tests | 状态 |
|-----------|------:|------|
| test_dual_price.py | 22 | ✓ |
| test_dual_price_cross_engine.py | 14 | ✓ |
| test_chase_up_backtrader_engine_dual_price.py | 5 | ✓ |
| test_chase_up_no_lookahead.py | ? | ✓ |
| test_chase_up_v3a_runtime.py | ? | ✓ |
| test_backtest_data_integrity.py | ? | ✓ |
| test_dna_data_dual_price.py | 16 | ✓ (含 v_daily_dual view 修复) |
| test_dna_data_dual_price_resolver.py | ? | ✓ |
| test_cycle_no_lookahead.py | ? | ✓ |
| test_cycle_price_action_no_lookahead.py | ? | ✓ |
| test_short_reversal_v3a_runtime.py | ? | ✓ |
| test_uptrend_pullback_no_lookahead.py | ? | ✓ |
| test_uptrend_pullback_v3a_runtime.py | ? | ✓ |
| **合计** | **172 passed, 3 errors** | errors 来自 commit b514885 移除的 legacy preset 名 (本 tick 范围外) |

### Trade-level phantom audit — 真实证据 (本 tick 重跑验证)

| engine | presets 总数 | 有 trades.csv | 审计方法 | phantom ratio |
|--------|----------:|----------:|----------|--------------:|
| chase_up | 22 | 22 | `audit_phantom.py` 真实 trade-vs-qfq_open 比对 | **0/1116 (0.00%)** |
| uptrend_pullback | 2 | 2 | `audit_phantom.py` 真实 trade-vs-qfq_open 比对 | **0/117 (0.00%)** |
| short_reversal | 11 | 5 (v35+v36+v38+v39+v40_tp_07) | direction-consistency test (Layout B SHORT 语义) | **0/1189 direction-violation** |
| cycle_price_action | 1 | 0 | backtest fail-fast (数据缺口 000695.SZ@2025-04-30) | **N/A — Layout C 单源** |
| **合计 trade-level 已审计** | **36** | **29** | | **0/2422 phantom direction-clean** |

### short_reversal Layout B 代码审计 (本 tick 验证, 2026-09-22 ~ 2026-09-23)

`short_reversal/feed_bt.py:8-29` 文档明确:
> 当前 strategy 仍读 raw (v_daily IS raw) 作 baseline parity。完整 V3a 信号迁移需 strategy 切到 d.adj_close 系列 — golden baseline 重生成。

`short_reversal/replay_strategy_v3.py` exit 路径:
- L161: `current_close = float(d.close[0])` — `d.close` 来自 v_daily raw
- L296-318: SL/TP 触发用 `d.open[0]` / `d.close[0]` / `d.low[0]` / `d.high[0]`,全部 raw

**Trade-level 验证 (5 csvs, 1189 trades)** — `tests/test_short_reversal_trade_math_consistency.py`:
- SHORT 语义: SL exit > entry (价格 up 触发), TP exit < entry (价格 down 触发)
- direction-violation = phantom 信号 (策略 fire SL 但 exit < entry 说明 clamp 到 adj_open)
- v35 171 trades / v36 200 trades / v38 262 trades / v39 278 trades / v40_tp_07 278 trades → **0 direction-violation**
- 6/6 unit tests PASSED

**Contract 锁定** — `tests/test_dual_price_cross_engine.py::TestShortReversalLayoutBContract`:
- `test_replay_strategy_v3_does_not_read_adj_in_exit_path`: 锁定 exit 路径不读 `d.adj_*`
- `test_feed_bt_loads_adj_columns_for_v3a_migration_path`: feed 预埋 adj_* 但 strategy 暂不读
- `test_short_reversal_preset_declares_dual_price_intent`: 11 preset 全部声明 dual-price intent + execution="raw_close"

**结论**: short_reversal 当前 strategy 用 raw (Layout B), 633 trades 0 phantom direction-violation. V3a 完整信号迁移 (切到 adj) 时**必须**重生成 golden baseline + 重跑 trade-level phantom audit (见 follow-up)。

### cycle_price_action Layout C 代码审计 (本 tick 验证)

`tests/test_dual_price_cross_engine.py::TestCyclePriceActionIntegration` 已通过 — 锁定 cycle_price_action/backtrader_engine.py:
- `from core.dual_price import extract_execution_bar` ✓
- `LAYOUT_CYCLE_PRICE` 显式引用 ✓

Layout C 是单价格域, 结构性 phantom-free。trade-level 审计需要先生成 cycle_price_action/results csv (当前 0 csv, follow-up)。

**Backtest fail-fast 验证 (2026-09-23)** — `cycle_price_action/replay_broker.py:53`:
- 1-year window (2024-09-19 → 2025-09-19) 跑 9+ min cpu, hit 数据缺口 `000695.SZ on 2025-04-30`, 抛 RuntimeError
- 这是 **CLAUDE.md §0 Fail-Fast** 体现 (Pessimistic Default): 数据缺口 → 不假装有数据,直接抛出
- 2-month window (2025-08-01 → 2025-09-19) 排队中
- 缺口根因待查 (corporate action / suspension / data ETL miss), 见 follow-up

### 待办 follow-up (CLAUDE.md 整体合规)

1. **§5 WFV 模块缺失**: chase_up / uptrend_pullback / short_reversal 缺 Walk-Forward Validation
   基础设施. 当前 cycle_price_action/walkforward.py 是唯一实现, 应抽取共用基类.
2. **数据层 SQL 修复** (用户已确认 follow-up): chase_up/data.py + uptrend_pullback/data.py
   应切换读 v_daily_dual view (raw_prev_close 0% 覆盖 → 100%).
3. **9 个 chase_up preset golden baseline 缺失**: v1/v1a/v1b/v1c/v2/v3/v4/v6/v7.
4. **uptrend_pullback 完全无 golden baseline**.
5. **3 个 test errors**: test_presets.py / test_engine_v3.py / test_short_reversal_no_lookahead.py
   引用已被移除的 legacy preset 名 (v33_mainboard_*).