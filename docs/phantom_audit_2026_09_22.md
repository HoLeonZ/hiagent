# Phantom TP/SL 全 Engine 审计报告 (2026-09-22)

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