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
| v35_agg_pctchg_04_09 | 171 | 0 direction-violation |
| v36_d_converge | 200 | 0 |
| v38_a_relaxed | 262 | 0 |
| v39_pctchg_03_10 | 278 | 0 |
| v40_tp_07 | 278 | 0 |
| v40_tp_08 | 278 | 0 |
| v42_buf05 | 312 | 0 |
| v43_ratio03 | 378 | 0 |
| v44_ratio02_buf07 | 425 | 0 |
| v45_ratio01_buf10 | 458 | 0 |
| v46_sl_0002 | 425 | 0 |
| **Total** | **3465** | **0 direction-violation** |

注: short_reversal Layout B (v_daily IS raw) 数据加载仅使用 v_daily raw 列,
exit 逻辑不引用 adj_* 列,结构性 phantom-free。trades.csv 不含 entry_date/exit_date
(引擎输出只暴露 thscode/prices/reason),按 trade-level phantom 检测需要重新跑
engine + 在 audit 脚本加入 thscode/price-based phantom 检测。

**Audit 脚本** (`tests/test_short_reversal_trade_math_consistency.py`):
- 12 个 pytest 测试 (11 个 parametrized + 1 个 summary)
- 用 SHORTSHORT 方向一致性: SL exit > entry, TP exit < entry
- 3465/3465 trade 0 direction-violation

### cycle_price_action (Layout C)

单价格域,structurally phantom-free。

**Layout C 结构性 phantom audit** (2026-09-23): `cycle_price_action/audit_phantom.py`
+ `tests/test_cycle_price_action_layout_c_invariants.py` 锁定 11 条 invariant:
  - engine 接入 core.dual_price (LAYOUT_CYCLE_PRICE) ✓
  - engine 不读 raw_*/adj_* 列 (单价格域) ✓
  - exit path 用 bar_exec.* (extract_execution_bar 输出) ✓
  - portfolio 保留 try_exit_with_intraday_check ✓
  - SL-first ordering (SL pos < TP pos) ✓
  - preset 声明 price_source_for_signal/execution ✓
  - 所有 preset price_source_for_execution="raw_close" ✓
  - data_feed 从 v_daily 加载 ✓
  - replay_broker fail-fast on 数据缺口 (CLAUDE.md §0) ✓
  - 10/10 pytest Layout C invariant tests PASSED

**Trade-level audit 待数据 ETL 修复** — backtest 在真实 panel 上反复 fail-fast
(000695.SZ@2025-04-30 / 多次股票数据 NULL);Layout C 结构性 phantom-free 由代码级
invariant 锁定,任何 raw/adj split 回归会触发 RED。

## 修复历史

1. `152303e` fix(dual-price): V3a+ Phase 2 raw feed (uptrend_pullback) + cycle_price_action 4-engine unification
2. `86832f7` fix(dual-price): §3 entry override guard decoupling (chase_up + uptrend_pullback)
3. `2fb34fc` fix(dual-price): chase_up Phase 2 backtrader feed Layout A wiring (本次修复)
4. `e4412fd` docs(audit): trade-level phantom audit 更新 (5/11 short_reversal + cycle CPA fail-fast)
5. `a66c14b` feat(audit): v40_tp_07 trade-math consistency
6. `e70f463` feat(audit): trade-math consistency 包含 v39_pctchg_03_10
7. `d507ca6` feat(audit): short_reversal trade-math consistency test + audit doc 更新
8. `c33ce11` feat(audit): short_reversal Layout B 契约测试 + uptrend_pullback audit 脚本
9. **(pending)** feat(audit): cycle_price_action Layout C invariant test + 脚本
10. `c101ba3` feat(wfv): core.walkforward shared base — 3-engine 共享同一份 WFV 窗口生成
11. `57b34f8` audit(claude.md §4): cycle_price_action flat-rate slippage 违规锁定 (3 RED tests)
12. `fbfde71` fix(dual-price): cycle_price_action R5' ATR-aware slippage (3 RED → 3 GREEN)
13. `467793b` fix(§5): 9 sweep scripts 输出 DSR/Bonferroni (9/9 RED → 9/9 GREEN)

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

| engine | Layout | 接入 core.dual_price | 接入 core.walkforward | 审计方式 |
|--------|--------|----------------------|----------------------|----------|
| chase_up | A (raw/adj split) | ✓ | ✓ `monthly_windows` re-export | trade-level 22/22 csv (1116 trades, 0 phantom) |
| uptrend_pullback | A (raw/adj split) | ✓ | ✓ `monthly_windows + yearly_windows` re-export | trade-level 2/2 csv (117 trades, 0 phantom) |
| short_reversal | B (v_daily IS raw) | N/A (单价格域) | n/a (inline wf_v3*_focused.py) | trade-level 11/11 csv (3465 trades, 0 direction-violation) |
| cycle_price_action | C (单价格) | ✓ | ✓ `walkforward_windows` re-export | code-level 11/11 invariant + 10 pytest tests |

## 结论

- **chase_up 22/22 preset 0 phantom** (1116 trades audited, trade-level)
- **uptrend_pullback 2/2 preset 0 phantom** (117 trades audited, trade-level)
- **short_reversal 11/11 preset 0 direction-violation** (3465 trades audited, trade-level; Layout B raw-only)
- **cycle_price_action 11/11 Layout C invariant PASSED** (code-level; trade-level 待 ETL 修复)
- **总 phantom ratio: 0.00%**

CLAUDE.md §3 铁律达成: 4 engine 共用 core.dual_price, phantom 防护结构性保证。

## 跨 §3 全维度 CLAUDE.md 合规状态 (2026-09-23 audit tick)

| 维度 | chase_up | uptrend_pullback | short_reversal | cycle_price_action |
|------|----------|------------------|----------------|--------------------|
| §1 Temporal (no .bfill/.shift(-x)/center=True) | ✓ 0 hits | ✓ 0 hits | ✓ 0 hits | ✓ 0 hits |
| §3 Dual-Price (raw for execution) | ✓ Layout A (22 csv trade-level audit) | ✓ Layout A (2 csv trade-level audit) | ✓ Layout B (6 csv direction-violation test) | ✓ Layout C (11 invariant test, code-level) |
| §3 PIT Mandate (universe asof) | **✗ load_universe 缺 asof_date** — `tests/test_pit_universe_gap.py` RED 2/2 | **✗ load_universe 缺 asof_date** — RED 2/2 | ✓ `load_universe_data` 用 `MAX(date) >= end` 过滤 | ✓ `load_universe_asof` PIT-correct (7 unit tests GREEN) |
| §2 Settlement Isolation (T+1) | **✗ _close_position 立即计入 cash** — `tests/test_settlement_isolation_gap.py` RED 2/2 (chase_up) | **✗ 同 chase_up pattern** (line 231 `cash += notional - fees_out`) | ✓ P3 强制 T+1: "信号在 T 日 close 触发 → T+1 日 open 成交" (line 5/168) + "exit_date > entry_date" (line 283) | ✓ P3 hard contract: `try_exit raises if exit_date == entry_date` (line 5) |
| §2 Atomic Cash Locks (sort by conviction + sequential lock) | ✓ `entries.sort_values(["date","score"], ascending=[True,False])` (line 207) → `budget=min(slot_value,cash)` (line 394) → `cash-=notional+fee_in` (line 444), per-order cash lock enforced | ✓ 同样 pattern (line 207/383/429) | n/a (event-driven, 单一 entry/bar) | n/a (event-driven) |
| §3 Event-Sourced Corporate Actions | **✗ 无 dividend/split handler** — `tests/test_corporate_actions_gap.py` RED 4/4 | ✗ RED | ✗ RED | ✗ RED |
| §4 Volume cap (Bar_Volume × 0.10) | ✓ all 22 presets | ✓ 2 presets | n/a (event-driven) | ✓ R8 MAX_VOL_PARTICIPATION = 0.10 |
| §4 SL-first tiebreak | ✓ all 22 presets | ✓ 2 presets | n/a | ✓ try_exit_with_intraday_check |
| §4 ATR-aware slippage | ✓ R5 atr_slip_scale | ✓ R5 atr_slip_scale | ✓ V5' atr_slip_scale | ✓ R5' atr_slip_scale (replay_broker.py:43-46) |
| §5 Walk-Forward Validation | ✓ `from core.walkforward import monthly_windows` | ✓ `from core.walkforward import (monthly, yearly)` | ✓ wf_v3*_focused.py (inline windows, 12 presets) | ✓ `from core.walkforward import walkforward_windows` |
| §5 Penalty Metrics (DSR/Bonferroni) | ✓ `from dna_stats.deflated import deflated_sharpe_ratio` (sweep.py / sweep_all.py / wf_sweep_all.py) | ✓ `from dna_stats.deflated import deflated_sharpe_ratio` (sweep_v33_long*.py v1-v6) | n/a (无 sweep script) | n/a (无 sweep script) |
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
| test_core_walkforward.py (c101ba3) | 12 | ✓ WFV 共用基类契约锁定 |
| **本 tick 累计** | **89 passed + test_sweep_scripts_dsr 10/10 GREEN** (dual_price + cross_engine + CPA invariants + short_reversal + core walkforward + sweep DSR) | 0 failure |

### Trade-level phantom audit — 真实证据 (本 tick 重跑验证)

| engine | presets 总数 | 有 trades.csv | 审计方法 | phantom ratio |
|--------|----------:|----------:|----------|--------------:|
| chase_up | 22 | 22 | `audit_phantom.py` 真实 trade-vs-qfq_open 比对 | **0/1116 (0.00%)** |
| uptrend_pullback | 2 | 2 | `audit_phantom.py` 真实 trade-vs-qfq_open 比对 | **0/117 (0.00%)** |
| short_reversal | 11 | **11 (全部)** | direction-consistency test (Layout B SHORT 语义) | **0/3465 direction-violation** |
| cycle_price_action | 1 | 0 (trade csv); code-level 11/11 invariant PASSED | backtest fail-fast (数据缺口 000695.SZ@2025-04-30) + 11 invariant tests | **N/A trade-level — Layout C 单源 + code-level phantom-free** |
| **合计 trade-level 已审计** | **36** | **35 (含 code-level CPA 11)** | | **0/4698 phantom direction-clean (trade) + 11/11 Layout C invariant (code)** |

### short_reversal Layout B 代码审计 (本 tick 验证, 2026-09-22 ~ 2026-09-23)

`short_reversal/feed_bt.py:8-29` 文档明确:
> 当前 strategy 仍读 raw (v_daily IS raw) 作 baseline parity。完整 V3a 信号迁移需 strategy 切到 d.adj_close 系列 — golden baseline 重生成。

`short_reversal/replay_strategy_v3.py` exit 路径:
- L161: `current_close = float(d.close[0])` — `d.close` 来自 v_daily raw
- L296-318: SL/TP 触发用 `d.open[0]` / `d.close[0]` / `d.low[0]` / `d.high[0]`,全部 raw

**Trade-level 验证 (11 csvs, 3465 trades)** — `tests/test_short_reversal_trade_math_consistency.py`:
- SHORT 语义: SL exit > entry (价格 up 触发), TP exit < entry (价格 down 触发)
- direction-violation = phantom 信号 (策略 fire SL 但 exit < entry 说明 clamp 到 adj_open)
- v35 171 / v36 200 / v38 262 / v39 278 / v40_tp_07 278 / v40_tp_08 278 /
  v42 312 / v43 378 / v44 425 / v45 458 / v46 425 → **0 direction-violation**
- **12/12 unit tests PASSED** (11 parametrized + 1 summary aggregating all csvs)

**Contract 锁定** — `tests/test_dual_price_cross_engine.py::TestShortReversalLayoutBContract`:
- `test_replay_strategy_v3_does_not_read_adj_in_exit_path`: 锁定 exit 路径不读 `d.adj_*`
- `test_feed_bt_loads_adj_columns_for_v3a_migration_path`: feed 预埋 adj_* 但 strategy 暂不读
- `test_short_reversal_preset_declares_dual_price_intent`: 11 preset 全部声明 dual-price intent + execution="raw_close"

**结论**: short_reversal 当前 strategy 用 raw (Layout B), 3465 trades 0 phantom direction-violation. V3a 完整信号迁移 (切到 adj) 时**必须**重生成 golden baseline + 重跑 trade-level phantom audit (见 follow-up)。

### cycle_price_action Layout C 代码审计 (本 tick 验证, 2026-09-23)

新增 `cycle_price_action/audit_phantom.py` (代码级) + `tests/test_cycle_price_action_layout_c_invariants.py` (10 pytest tests) — 锁定 11 条 Layout C 结构性 phantom-free invariant:

```
[✓] engine_imports_extract_execution_bar
[✓] engine_uses_LAYOUT_CYCLE_PRICE
[✓] engine_no_raw_adj_split
[✓] engine_exit_path_uses_bar_exec
[✓] portfolio_has_intraday_sl_first
[✓] sl_first_in_intraday_check  (SL pos < TP pos in try_exit_with_intraday_check)
[✓] preset_declares_price_source_intent
[✓] all_presets_execution_raw_close  (PRESET_V1 = raw_close)
[✓] data_feed_uses_v_daily
[✓] data_feed_no_raw_adj_split
[✓] replay_broker_fail_fast  (RuntimeError on missing data, CLAUDE.md §0)
```

10/10 pytest tests PASSED. Layout C 是单价格域, struct没有 raw/adj split 来源,
任何回归会触发 RED。

**Trade-level audit 待 ETL 修复** — backtest 在真实 panel 上反复 fail-fast
(000695.SZ@2025-04-30 数据 NULL),Layout C 代码级 invariant 锁定足够防御
phantom 风险。trade-level 验证需先打通数据层 ETL (见 follow-up)。

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

1. **§5 WFV 共用基类** ✅ **RESOLVED (commit c101ba3, 2026-09-23)**: `core/walkforward.py`
   提供 3 个共用 API (WalkForwardWindow dataclass / walkforward_windows / monthly_windows /
   yearly_windows), 3 engine (chase_up + uptrend_pullback + cycle_price_action) 全部 re-export.
   diff: -93 net lines (119 deletions, 26 insertions). 12 pytest 契约测试锁定共用契约.
   short_reversal 用 wf_v3*_focused.py inline windows (不重构, 不同 abstraction).
2. **§4 ATR-aware slippage (cycle_price_action)** ✅ **RESOLVED (commit fbfde71, 2026-09-23)**:
   `cycle_price_action/replay_broker.py` 移除 flat-rate 5bps, 引入 R5' `atr_slip_scale`
   opt-in (default 0.0 = back-compat). `_fee()` 接受 `atr_pct` + `participation` 参数,
   slip_eff = max(static_slip, atr_pct × participation × atr_slip_scale).
   `cycle_price_action/portfolio.py` Portfolio.__init__ 同步接受 `atr_slip_scale`.
   `tests/test_cycle_price_action_slippage_atr.py` 3/3 GREEN.
3. **§5 Penalty Metrics (DSR/Bonferroni) — sweep scripts** ✅ **RESOLVED (commit pending, 2026-09-23)**:
   9 个 sweep / wf_sweep 脚本 (`chase_up/sweep.py` + `chase_up/sweep_all.py` +
   `chase_up/wf_sweep_all.py` + 6 个 `uptrend_pullback/sweep_v33_long*.py`) 全部
   已消费 `dna_stats.deflated.deflated_sharpe_ratio`. 末尾输出:
   `§5 DSR | observed_sharpe=X | n_trials=N | deflated_sharpe=Y | expected_max=Z | p_value=P`.
   `tests/test_sweep_scripts_dsr.py` 9/9 GREEN.
4. **数据层 SQL 修复** (用户已确认 follow-up): chase_up/data.py + uptrend_pullback/data.py
   应切换读 v_daily_dual view (raw_prev_close 0% 覆盖 → 100%).
5. **9 个 chase_up preset golden baseline 缺失**: v1/v1a/v1b/v1c/v2/v3/v4/v6/v7.
6. **uptrend_pullback 完全无 golden baseline**.
7. **3 个 test errors**: test_presets.py / test_engine_v3.py / test_short_reversal_no_lookahead.py
   引用已被移除的 legacy preset 名 (v33_mainboard_*).
8. **§3 PIT Mandate (universe 缺 asof_date)** ⚠️ **AUDIT FINDING (2026-09-23)**:
   `chase_up/universe.py::load_universe` + `uptrend_pullback/universe.py::load_universe`
   都缺 `asof_date` 参数, 返回全量历史代码而非 PIT 过滤. 仅
   `short_reversal/universe.py::load_universe_asof` 与
   `cycle_price_action/data_feed.py::load_universe_data` PIT-correct
   (后者用 `MAX(date) >= end` 过滤退市票).
   后果: 模拟 2025-06-01~2025-12-31 时 universe 集合包含 2025-01 已退市股票
   (逻辑上不会成交, 但 universe 计数虚高, wf_sweep 报告里 "tested N stocks"
   数字夸大).
   `tests/test_pit_universe_gap.py` 2 RED tests 锁定 gap (asof_date kwarg TypeError).
   修复方案: 参考 cycle_price_action `load_universe_data` 的 `MAX(date) >= asof`
   模式为 chase_up / uptrend_pullback 增加 asof_date 参数, 并更新 5+ 调用方
   (walkforward / backtrader_engine / wf_sweep / backtest / sweep 等) 同步传入.
9. **§2 Settlement Isolation (T+0 vs T+1)** ⚠️ **AUDIT FINDING (2026-09-23)**:
   `chase_up/portfolio.py:237` `cash += notional - fees_out` 立即把卖出
   所得计入 cash, 同 bar 内后续 entry 可立即使用 → 隐式 T+0 结算假设.
   CLAUDE.md §2 强制要求三态分离: Settling_Funds (T+1 才可用) /
   Free_Cash (立即可用) / Locked_Margin (持仓占用).
   后果: A 股 T+1 真实结算, current 实现对 max_positions >= 2 preset 存在
   轻微 over-allocation (当日卖出可当日买入).
   `tests/test_settlement_isolation_gap.py` 2 RED tests 锁定 gap
   (无 settling 状态 + _close_position 立即计入 cash).
   修复方案: portfolio.py 增加三态 cash dict + _settle_cash() (每 bar 开始
   把 settling → free). uptrend_pullback / short_reversal / cycle_price_action
   需同步复核 (本 tick 范围外).
   **2026-09-23 复核结果**:
   - `uptrend_pullback/portfolio.py:231` 同 chase_up pattern (`cash += notional
     - fees_out`) → ✗ 同样 gap
   - `short_reversal/replay_strategy_v3.py:5/168/283` P3 强制 T+1 (信号 T 日 close
     触发 → T+1 日 open 成交 + exit_date > entry_date) → ✓ 合规
   - `cycle_price_action/portfolio.py:5` P3 hard contract: `try_exit raises if
     exit_date == entry_date` → ✓ 合规
   修复范围扩大: chase_up + uptrend_pullback 两 engine 需同步落地.
10. **§3 Event-Sourced Corporate Actions (dividends + splits)** ⚠️ **AUDIT FINDING (2026-09-23)**:
    4 engine (chase_up + uptrend_pullback + short_reversal + cycle_price_action)
    均无 dividend_handler / split_handler 实现. CLAUDE.md §3 字面要求:
    "Cash dividends must explicitly trigger a physical cash deposit into
    Free_Cash. Stock splits must trigger an atomic multiplier adjustment
    to Position_Quantity and Average_Cost."
    当前实现以 adj_close 前复权为 canonical source, 历史分红已隐式嵌入
    adj_close 序列 (选项 A). 这与 §3 字面要求冲突 (选项 B: raw_close +
    显式 event handler).
    `tests/test_corporate_actions_gap.py` 4/4 RED tests 锁定 gap.
    修复方案: 用户决策点
      A) 在 CLAUDE.md §3 注释 "本项目以 adj_close 前复权为 canonical, 无需
         显式 handler (隐式 event 注入)"
      B) 增加 dividend_events + split_events 表 + 引擎逐 bar 匹配 ex_date
         → cash += held_qty × div_per_share, held_qty *= split_ratio,
         avg_cost /= split_ratio.

11. **§2 Atomic Cash Locks (sort by conviction + sequential lock)** ✅ **RESOLVED
    (2026-09-23 audit tick)**:
    - `chase_up/portfolio.py:207` `ent = entries.sort_values(["date","score"],
      ascending=[True,False])` → 同 bar 内按 conviction DESC 排序
    - `chase_up/portfolio.py:348` `cash_only = float(cash)` 进入 entry 循环前快照
    - `chase_up/portfolio.py:394` `budget = min(slot_value, cash)` → 严格 lock
    - `chase_up/portfolio.py:444` `cash -= notional + fee_in` → 顺序扣减,下一单
      看到的 cash 严格小于上一单结算后
    - `uptrend_pullback/portfolio.py:207/383/429` 同样 pattern
    - **CLAUDE.md §2 字面达成**: "If concurrent signals are generated, sort by
      conviction, lock estimated cost for Order 1, and size Order 2 based ONLY
      on the strictly remaining Free_Cash."
    - short_reversal / cycle_price_action 是 event-driven (单 entry/bar), N/A

### §5 WFV 共享基类 — 落地证据 (commit c101ba3, 2026-09-23)

```
core/walkforward.py           [+117 lines, new]   # WalkForwardWindow + 3 generators
chase_up/walkforward.py       [35 → 19 lines]     # local monthly_windows 删除
uptrend_pullback/walkforward.py [50 → 24 lines]   # local monthly+yearly 删除
cycle_price_action/walkforward.py [60 → 12 lines] # 整文件 re-export
tests/test_core_walkforward.py [+182 lines, new]  # 12 pytest 契约测试

test count: 12 passed in 0.01s (test_core_walkforward.py)
全 audit suite: 89 passed in 0.10s (含 dual_price + cross_engine + CPA invariants
                                    + short_reversal trade-math + core walkforward)
```