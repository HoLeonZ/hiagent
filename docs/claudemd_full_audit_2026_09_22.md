# CLAUDE.md Full Compliance Audit — 2026-09-22 (in progress)

Goal set 2026-09-22 via /goal: "按照claude.md的要求，检查所有preset、回测过程和测试用例是否都满足了规范和要求".

Scope: all 6 sections of CLAUDE.md × 3 layers (preset declarations, backtest engine code, test cases).

**Status legend:**
- ✓ Compliant (evidence file:line cited)
- △ Partial / known gap (documented in code as TODO)
- ✗ Violation (needs fix)

---

## §1 Temporal Determinism — Banned Functions Scan

| Pattern | Hits | Status |
|---------|------|--------|
| `df.bfill()` | 0 | ✓ |
| `shift(-N)` (negative shift) | 0 | ✓ |
| `rolling(center=True)` | 0 | ✓ |
| Global `.mean()`/`.std()` before split | 0 (uses causal .expanding()) | ✓ |

**Result: 0 violations.**

---

## §3 Data Integrity — Dual-Price System (Actual Loading)

| Strategy | Data feed loads adj_*? | Loads raw_*? | Status |
|----------|------------------------|--------------|--------|
| chase_up | `data.py:39-91` reads `v_daily_qfq` for adj | reads `raw_open/high/low/close/prev_close` | ✓ real dual-price |
| uptrend_pullback | `data.py:46-59` reads `v_daily_qfq` | reads `raw_open/high/low/close/prev_close` | ✓ real dual-price |
| short_reversal | `engine.py:50-65` LEFT JOINs `v_daily_hfq` adding `adj_*` columns | uses `v_daily` raw columns | △ strategy still reads raw (parity preservation; full V3a migration pending) |
| cycle_price_action | `data_feed.py` only reads `v_daily` (single close) | n/a | ✗ **actual loading is single-price; preset declaration is misleading** |

**Result: 1 violation (cycle_price_action data_feed.py).** Preset declares
`price_source_for_signal="adj_close"` and `price_source_for_execution="raw_close"`
but data feed cannot honor this since only `v_daily.close` is loaded.

Fix needed: cycle_price_action/data_feed.py should load dual-price columns
(via `v_daily_qfq` for adj + raw via separate view/table) and split
signal/execution accordingly.

---

## §4 Microstructure & Liquidity

### 4.1 Volume Participation Cap (Max_Fill_Qty ≤ Bar_Volume × 0.10)

| Strategy | Implementation | Status |
|----------|----------------|--------|
| chase_up | `portfolio.py` enforces (need file:line verification in entry path) | △ preset declared, backtrader-engine entry path uses `self.buy(size=...)` — verify size is capped |
| uptrend_pullback | `portfolio.py:128` default + `backtrader_engine.py:228` passes param | ✓ |
| cycle_price_action | `portfolio.py:69` + `backtrader_engine.py:116` passes `bar_volume=bar.get("volume")` | ✓ |
| short_reversal | `engine.py:196` reads param | △ backtrader-style, need to verify enforcement |

### 4.2 ATR-Aware Slippage

| Strategy | Implementation | Status |
|----------|----------------|--------|
| chase_up | `portfolio.py:381` formula `slip_eff = max(static_slippage, atr_pct × participation × scale)` | ✓ |
| uptrend_pullback | `portfolio.py:111` formula | ✓ |
| short_reversal | `replay_strategy_v3.py:70` formula | ✓ |
| cycle_price_action | n/a (single-price, no ATR-aware slippage) | ✗ **no ATR slippage implementation** |

### 4.3 SL-First Intraday Tiebreak

| Strategy | Implementation | Status |
|----------|----------------|--------|
| chase_up | preset declared, implementation needs verification | △ |
| uptrend_pullback | `portfolio.py:259` enforces `intraday_tiebreak == "sl_first"` | ✓ |
| cycle_price_action | `portfolio.py:168` `try_exit_with_intraday_check` | ✓ |
| short_reversal | `replay_strategy_v3.py:282` `assert intraday_tiebreak == "sl_first"` | ✓ |

**Result: 2 violations (§3 cycle_price_action data feed, §4.2 cycle_price_action ATR slippage).**

---

## §2 Capital & State Determinism — All-In Sizing + Atomic Locks

**Preset layer:** Fully remediated in commit `acc7d31` (2026-09-22).
All 36 presets declare `position_sizing="all_in"`, `max_positions=1`,
`position_fraction=1.0`, `MAX_POSITION_PCT=1.0`.

**Engine layer — atomic cash lock verification:**

| Strategy | File:line | Pattern | Status |
|----------|-----------|---------|--------|
| chase_up | `portfolio.py:404-413` | `if notional + fee_in > cash: size -= 100; retry; reject` | ✓ |
| chase_up | `replay_broker.py:54` | `self.cash -= notional * STAMP_DUTY` | ✓ |
| uptrend_pullback | `portfolio.py:388-397` | same `cost > cash` rejection pattern | ✓ |
| uptrend_pullback | `replay_broker.py:77` | stamp duty cash deduction | ✓ |
| cycle_price_action | `portfolio.py:117, 122, 133` | triple-check `cost > cash` with min-lot floor | ✓ |
| short_reversal | `replay_strategy_v3.py:240-243` | NAV-based sizing with floor truncate; **no `cost > cash` guard** but uses short-sale proceeds model (entry receives cash, fees deducted) — appropriate for short mechanics | △ acceptable per §2 short mechanics |

**Result: ✓ compliance** for long-only strategies (3/4). short_reversal
uses a fundamentally different mechanic (short sale with NAV-budget sizing
+ proceeds offsetting fees) where the long-only `cost > cash` guard is
mathematically inappropriate. Volume Participation Cap is still enforced
at `replay_strategy_v3.py:230-236` ✓.

---

## §5 Statistical Rigor — Walk-Forward + DSR/Bonferroni

### 5.1 Walk-Forward Validation strictness

| Strategy | Window pattern | Train/test split? | Status |
|----------|---------------|-------------------|--------|
| chase_up | `monthly_windows(window_months=2)` sliding | ✗ no split |
| short_reversal | `build_windows(window_months=2)` sliding | ✗ no split |
| uptrend_pullback | `yearly_windows` + `monthly_windows(window_months=2)` | ✗ no split |
| cycle_price_action | `walkforward_windows(train_months=12, test_months=12)` | ✓ explicit WFV |

**Interpretation:** CLAUDE.md §5 mandates "WFV with strict OOS testing
windows." chase_up/short_reversal/uptrend only run rolling evaluation
windows without an OOS holdout — this is **partial compliance**: each
window is treated as independent, not as "train → test". This satisfies
"don't in-sample grid-search" but does not satisfy "strict OOS testing."

### 5.2 DSR / Bonferroni application

**Infrastructure:** `dna_stats/walkforward_report.py:69-80` and
`dna_stats/deflated.py:103` implement `deflated_sharpe_ratio` and
`bonferroni_p_value` correctly. ✓

**Callers — sweep scripts passing `n_comparisons`:**

| Sweep script | n_comparisons hits | Status |
|-----------|-------------------|--------|
| `chase_up/sweep_all.py`, `sweep.py`, `wf_sweep_all.py` | 0 | ✗ |
| `uptrend_pullback/sweep_v33_long_*.py` (×6) + `grid.py` | 0 | ✗ |
| `short_reversal/wf_v3*_focused.py` (×13) + `grid_runner.py` | 0 | ✗ |
| `cycle_price_action/walkforward.py` | 0 | ✗ |

**Result: ✗ Violation.** DSR/Bonferroni infrastructure exists but no caller
threads `n_comparisons` from the actual grid size through to the report.
Every reported Sharpe is un-corrected → inflated significance → cherry-picking
risk. Per CLAUDE.md §5: "Banned In-Sample Grids" + "DSR or Bonferroni" —
the absence means any walkforward result with N>1 param configs is
**statistically un-corrected**, and we cannot claim the metrics are
deflation-safe.

### 5.3 No-banned-grids check

`grep -rn "argmax.*sharpe\|max.*sharpe.*param"` across all strategies
should return 0 hits — sweep scripts must rank by walkforward mean,
not in-sample max.

---

## §6 Architecture — Control Plane / Strategy / Execution Broker

### 6.1 Module separation by file role

| Strategy | Strategy/Inference | Orchestrator/Data | Execution/Broker |
|----------|-------------------|-------------------|------------------|
| chase_up | `signals.py` | `walkforward.py`, `data.py`, `universe.py`, `presets.py`, `sweep*.py` | `portfolio.py`, `replay_broker.py`, `backtrader_engine.py`, `backtest.py` |
| short_reversal | `signals.py`, `indicators_bt.py` | `walkforward.py`, `engine.py`, `feed_bt.py`, `universe.py`, `presets.py`, `wf_*.py`, `grid_runner.py` | `replay_strategy_v3.py` (per §3 v3a migration note in audit baseline) |
| uptrend_pullback | `signals.py` | `walkforward.py`, `data.py`, `universe.py`, `presets.py`, `sweep_v33_*.py`, `grid.py` | `portfolio.py`, `replay_broker.py`, `replay_strategy.py`, `replay_feed.py`, `backtrader_engine.py`, `backtest.py` |
| cycle_price_action | `signals.py` | `walkforward.py`, `data_feed.py`, `universe.py`, `presets.py`, `time_windows.py` | `portfolio.py`, `replay_broker.py`, `backtrader_engine.py`, `backtest.py` |

### 6.2 Pure-function topology check (Strategy has no side-effect deps)

Verified `signals.py` imports across all 4 strategies:

| File | Imports | Result |
|------|---------|--------|
| `chase_up/signals.py` | `__future__`, `logging`, `numpy`, `pandas` | ✓ pure |
| `short_reversal/signals.py` | (empty / `__future__` only) | ✓ pure |
| `uptrend_pullback/signals.py` | `__future__`, `logging`, `numpy`, `pandas` | ✓ pure |
| `cycle_price_action/signals.py` | `__future__`, `numpy`, `pandas` | ✓ pure |

**No portfolio / DB / network imports** in any `signals.py`. Strategy layer
is pure functional: receives `State(T)`, returns `Signal(T)`. ✓

### 6.3 Result: ✓ Compliance** (separated concern, no smuggling)

Short_reversal partially deviates because `replay_strategy_v3.py` plays both
strategy+execution roles (the V3a migration is in progress per §3 audit
note), but pure `signals.py` is clean.

---

## Test Coverage Audit

### Existing test files

```
tests/test_chase_up_no_lookahead.py              1196 lines
tests/test_short_reversal_no_lookahead.py         390 lines
tests/test_cycle_no_lookahead.py                   47 lines
tests/test_cycle_price_action_no_lookahead.py     282 lines
tests/test_dna_data_dual_price.py                  57 lines
tests/test_dna_data_dual_price_resolver.py        183 lines
tests/test_cycle_data_feed.py                     105 lines
tests/test_cycle_portfolio.py                     262 lines
tests/test_cycle_replay_broker.py                  46 lines
tests/test_cycle_signals.py                       142 lines
tests/test_cycle_walkforward.py                    25 lines
tests/test_dna_stats_deflated.py                  108 lines
tests/test_dna_stats_walkforward_report.py         51 lines
tests/test_compliance_audit_all_presets.py         91 lines
tests/test_claudemd_full_audit.py                 211 lines
```

### Coverage matrix (CLAUDE.md dimension × strategy)

| Dim | chase_up | short_reversal | uptrend_pullback | cycle_price_action |
|-----|---------|----------------|------------------|--------------------|
| §1 no-lookahead | ✓ `test_chase_up_no_lookahead` | ✓ `test_short_reversal_no_lookahead` | ✓ via chase template | ✓ `test_cycle_no_lookahead` + `test_cycle_price_action_no_lookahead` |
| §2 atomic cash lock | △ implicit via simulate integration | △ implicit | △ implicit | △ implicit via `test_cycle_portfolio` |
| §3 dual-price | △ indirect via `test_chase_up_no_lookahead` | △ via `test_short_reversal_v3a_runtime` | △ via no_lookahead | ✗ `test_cycle_data_feed` covers only single-price loading |
| §4 vol cap | ✓ `test_chase_up_no_lookahead` | ✓ `test_short_reversal_v8_plumbing` | ✓ `test_uptrend_pullback_no_lookahead` | ✓ `test_cycle_portfolio` |
| §4 ATR slippage | ✓ chase no_lookahead | ✓ v8_plumbing | ✓ uptrend no_lookahead | ✗ no ATR slippage to test |
| §4 SL-first | ✓ chase no_lookahead | ✓ short_reversal no_lookahead | ✓ uptrend no_lookahead | ✓ `test_cycle_portfolio` `try_exit_with_intraday_check` |
| §5 WFV | △ implicit | △ implicit | △ implicit | ✓ `test_cycle_walkforward` |
| §5 DSR/Bonferroni | ✓ `test_dna_stats_deflated` + `_walkforward_report` (infra only) | same infra | same infra | same infra |
| §6 architecture | ✗ gap | ✗ gap | ✗ gap | ✗ gap |
| Banned function scan | ✗ gap | ✗ gap | ✗ gap | ✗ gap |

### Gaps identified

1. **§1 banned-function regression test** — no test asserts no banned
   patterns (`bfill`, `shift(-N)`, `rolling(center=True)`, global
   `.mean()/.std()` before split) appear in any strategy source.
2. **§2 atomic cash lock** — no direct unit test for `cost > cash`
   rejection (relies on integration of simulate into the full pipeline).
3. **§3 cycle_price_action dual-price** — `test_cycle_data_feed` covers
   only single-price loading; need a dual-price variant.
4. **§4 cycle_price_action ATR slippage** — implementation missing, no test.
5. **§6 architecture** — no test asserts `signals.py` has no portfolio/DB
   imports across all 4 strategies.
6. **§5 DSR sweep callers** — `dna_stats/walkforward_report.format_walkforward_stats`
   exists but no caller passes `n_comparisons` — needs test + fix.

---

## Next iterations

1. §2 engine code: atomic cash locks, free_cash isolation
3. §6 architecture separation
4. Test coverage matrix (which dimensions × strategies lack tests)
5. Remediation plan for §3 cycle_price_action + §4.2 cycle_price_action ATR slippage

---

## Summary — Compliance Score Card

| Section | Preset | Engine | Test | Status |
|---------|--------|--------|------|--------|
| §1 Temporal Determinism | n/a | ✓ 0 violations | △ gap (no banned-fn regression test) | △ |
| §2 Capital & State | ✓ (acc7d31) | ✓ 3/4 explicit + 1/4 short-model OK | △ gap | ✓ |
| §3 Data Integrity | ✓ declared | △ 1/4 violation (cycle_price_action data_feed.py single-price) | ✓ infra + 3/4 strategy | ✗ |
| §4 Microstructure | ✓ declared | △ 2/4 violations (cycle_price_action ATR slippage + SL-first tiebreak in chase_up needs re-verify) | ✓ 3/4 strategy | △ |
| §5 Statistical Rigor | △ (n_comparisons not threaded) | ✗ 0 sweep scripts pass n_comparisons | ✓ infra | ✗ |
| §6 Architecture | n/a | ✓ separated (signals.py pure, no portfolio/db imports) | ✗ gap (no regression test) | △ |

**4 violations remaining (after acc7d31 baseline pass):**
1. §3 `cycle_price_action/data_feed.py` — only loads `v_daily.close` (single price).
2. §4.2 `cycle_price_action` — no ATR-aware slippage implementation.
3. §5 all sweep scripts — `n_comparisons` not threaded to `format_walkforward_stats`.
4. §5 WFV strictness — 3/4 strategies use sliding windows, not train/test split.

---

## Remediation Plan (Prioritized)

### P0 — Statistical rigor (§5 DSR/Bonferroni threading)

**Action:** Modify each sweep script to import and pass `n_comparisons`:

```python
# In sweep_v33_long_v3.py / wf_v*_focused.py / etc:
from dna_stats.walkforward_report import format_walkforward_stats

# After collecting grid results:
N_COMPARISONS = len(grid_results)  # actual grid size
text = format_walkforward_stats(
    wf_df,
    n_comparisons=N_COMPARISONS,
    preset_name=preset_name,
)
```

Add a regression test in `tests/test_dna_stats_walkforward_report.py`
asserting `deflated_sharpe_ratio` is invoked with `n_trials = actual_grid_size`.

### P1 — Dual-price data feed (§3 cycle_price_action)

**Action:** Modify `cycle_price_action/data_feed.py` to load dual-price
columns via `v_daily_qfq` (adj) + raw view (raw_open/high/low/close/prev_close).
Then split signal vs execution paths accordingly. Add
`tests/test_cycle_data_feed_dual_price.py`.

### P1 — ATR-aware slippage (§4 cycle_price_action)

**Action:** Add `atr_aware_slippage(atr_pct, participation, scale)` helper
in `cycle_price_action/portfolio.py` and apply at entry/exit. Update
`tests/test_cycle_portfolio.py` with new test case.

### P2 — Walk-forward strictness (§5 WFV)

**Action:** Add a `walkforward_windows(train_months, test_months)` to
`chase_up/walkforward.py`, `short_reversal/walkforward.py`, and
`uptrend_pullback/walkforward.py` parallel to `cycle_price_action`'s.
Update sweep scripts to call strict-WFV instead of sliding windows.

### P2 — Architecture regression test (§6)

**Action:** Add `tests/test_signals_pure_imports.py` asserting each
`signals.py` only imports stdlib + numpy + pandas (no portfolio/db/network).

### P2 — Banned-function regression test (§1)

**Action:** Add `tests/test_no_banned_functions.py` scanning all 4 strategies
for `bfill`, `shift(-`, `rolling(center=True)`, global `.mean()/.std()`
in feature code paths.

### P3 — Atomic cash lock direct test (§2)

**Action:** Add `tests/test_atomic_cash_lock.py` that constructs a portfolio
where `size * price + fees > cash` and asserts the entry is rejected
with no cash movement.

---

## Appendix A — 2026-09-23 Audit Update (FRESH evidence)

### A.1 §0/§3 Cost Model Violations (NEW today)

A-share fee convention (CLAUDE.md §0 + 数据准确性):
- Commission: 万 2.5 双边 = 0.00025
- Stamp Duty: 万 5 卖出单边 = 0.0005 (post-Aug 2023)
- ¥5 commission minimum floor
- Round-trip: 万 2.5×2 + 万 5 = 万 10

| # | File | Line | Violation | Severity |
|---|---|---|---|---|
| 1 | `short_reversal/engine.py` | 24 | `COMMISSION_RATE = 0.0006` (万6) | ⚠ |
| 2 | `short_reversal/engine.py` | 25 | `STAMP_DUTY_RATE = 0.001` (万10) | ⚠ |
| 3 | `short_reversal/engine.py` | 185-186 | passes wrong rates to backtrader | ⚠ |
| 4 | `short_reversal/replay_strategy_v3.py` | 69-70 | override 同样错 | ⚠ |
| 5 | `short_reversal/replay_strategy_v3.py` | 264-267 | entry_fee 错收 stamp | ✗ structural |
| 6 | `short_reversal/replay_strategy_v3.py` | 329 | exit_fee 漏收 stamp | ✗ structural |
| 7 | `short_reversal/lookahead_trade_trace.py` | 75-78, 104 | entry/exit 错位 | ✗ structural |
| 8 | `short_reversal/scan_signals.py` | 119-120 | uses wrong constants | ⚠ |
| 9 | `cycle_price_action/portfolio.py` | 62 | `STAMP_TAX_SELL = 0.001` (万10 outdated) | ⚠ |
| 10 | `cycle_price_action/replay_broker.py` | 77 | hardcoded 0.001 | ⚠ |

**Tests LOCKING wrong behavior**:
- `tests/test_phase3_v3_strategy.py:50-51` — `commission_rate=0.0006, stamp_duty_rate=0.001`
- `tests/test_short_reversal_no_lookahead.py:257` — same

**Round-trip impact (short_reversal)**:
- Wrong: entry 万16 + exit 万6 = 万22
- Correct: entry 万2.5 + exit 万7.5 = 万10
- **Net overcharge: +万12 = 0.12% per round-trip**

**Per-sell impact (cycle_price_action)**:
- Wrong: 万10
- Correct: 万5
- **Net overcharge: +万5 = 0.05% per sell**

### A.2 §2 Settlement Isolation RED tests (locked 2026-09-23)

**FRESH 2026-09-23**: Settlement Isolation 是 **4 引擎普适违规**，不只是 chase_up。

| Engine | 现场 | Violation |
|---|---|---|
| chase_up | `cash += notional - fees_out` (RED test locked) | ✗ |
| uptrend_pullback | `cash += notional - fees_out` (portfolio.py:231) | ✗ |
| cycle_price_action | `self.cash += proceeds` (line 172), `self.cash += net_out` (line 242) | ✗ |
| short_reversal | `self.cash += pnl - exit_fee` (replay_strategy_v3.py:330) | ✗ |

`grep "Settling_Funds|settling_funds|pending_cash|deferred_cash"` 在 4 引擎 0 命中 — 无引擎实现 Settling_Funds 状态机。

**实际影响**（FRESH analysis）：max_positions=1 隐式阻断 same-day sell+buy on different assets，所以理论违规不会在当前 35 preset 下产生 phantom PnL。但若 max_positions 放宽或 equal sizing 启用，违规立即变现 — RED test 是前瞻性防御。

| # | Test | Status |
|---|---:|---|
| 1 | `test_settling_funds_state_exists` (chase_up only) | ✗ RED |
| 2 | `test_close_position_does_not_credit_cash_immediately` (chase_up only) | ✗ RED |
| 3 | `test_settling_funds_state_exists[uptrend_pullback]` | ⚠ NOT YET ADDED |
| 4 | `test_settling_funds_state_exists[cycle_price_action]` | ⚠ NOT YET ADDED |
| 5 | `test_settling_funds_state_exists[short_reversal]` | ⚠ NOT YET ADDED |

**CORRECTION (FRESH 2026-09-23)**: Audit doc originally listed 5 parametrized RED tests; reality is **only 2 RED tests exist, both chase_up-only** (no parametrize). Other 3 engines (uptrend_pullback / cycle_price_action / short_reversal) have NO RED test lock. Add parametrize for all 4 engines to fully capture the gap.

### A.3 §3 Corporate Actions RED tests (locked 2026-09-23)

4 RED tests, one per engine:
- `test_engine_has_dividend_or_split_handler[chase_up.portfolio]`
- `test_engine_has_dividend_or_split_handler[uptrend_pullback.portfolio]`
- `test_engine_has_dividend_or_split_handler[short_reversal.replay_strategy_v3]`
- `test_engine_has_dividend_or_split_handler[cycle_price_action.portfolio]`

### A.4 §3 PIT Universe RED tests (locked 2026-09-23)

| # | Test | Status |
|---|---|---|
| 1 | `test_chase_up_load_universe_accepts_asof_parameter` | ✗ RED (TypeError: unexpected asof_date) |
| 2 | `test_uptrend_pullback_load_universe_accepts_asof_parameter` | ✗ RED (same) |

### A.5 §2 NAV Gate — cycle_price_action missing (CORRECTED 2026-09-23)

3/4 engines enforce `initial_capital × 0.05` NAV gate:
- chase_up: `NAV_GATE_RATIO = 0.05` (line 64), enforced at line 338
- uptrend_pullback: `NAV_GATE_RATIO = 0.05` (line 48), enforced at line 320
- short_reversal: `min_cash_ratio = 0.05` (line 73), enforced at lines 182, 293
- **cycle_price_action: NO NAV gate** (only `cost > cash` rejection, no mark-to-market NAV check)

**CORRECTION (FRESH 2026-09-23)**: audit doc originally listed cycle_price_action as also missing ATR slippage, but R5' (2026-09-23, CLAUDE.md §4) has already added `atr_slip_scale` to both `cycle_price_action/portfolio.py:79-82` AND `cycle_price_action/replay_broker.py:34-37`. Only NAV gate remains missing.

**A.10 P2 correction**: remove "Add ATR-aware slippage (use core/dual_price.atr_slippage)" from cycle_price_action P2. Already done.

### A.6 §5 DSR Test Coverage Gap

`tests/test_sweep_scripts_dsr.py` glob: `**/sweep*.py`, `**/wf_sweep*.py` (10 covered, 16 NOT covered).

**FRESH count (2026-09-23)**:
- Scripts COVERED by test: 10 (3 chase_up + 6 uptrend_pullback + 1 inventory check)
- Scripts NOT covered (16): glob misses `grid*.py` + `wf_v*_focused.py` patterns

**Scripts NOT covered (FRESH count: 16, not 10 as previously documented)**:
- `uptrend_pullback/grid.py` (NO DSR, 0 hits)
- `uptrend_pullback/iter_reverse.py` (NO DSR, 0 hits)
- `short_reversal/grid_runner.py` (NO DSR, 0 hits)
- `short_reversal/wf_v34_focused.py` to `wf_v46_focused.py` (13 files, NO DSR, 0 hits each)

**Remediation**: extend glob to `**/sweep*.py`, `**/wf_sweep*.py`, `**/grid*.py`, `**/wf_v*_focused.py`. New tests RED until scripts either (a) use DSR or (b) are deleted.

### A.7 Compliance Test Field Coverage Gap

`tests/test_compliance_audit_all_presets.py` checks 5 fields:
1. `intraday_tiebreak='sl_first'` ✓
2. `max_volume_participation=0.10` ✓
3. `price_source_for_execution='raw_close'` ✓
4. `price_source_for_signal='adj_close'` ✓
5. `n_comparisons >= 1` ✓

**Missing assertions**:
- ❌ `max_positions=1` (CLAUDE.md §2)
- ❌ `position_sizing="all_in"` (CLAUDE.md §2)
- ❌ `position_fraction=1.0` (CLAUDE.md §2)
- ❌ `MAX_POSITION_PCT=1.0` (CLAUDE.md §2)
- ❌ NAV gate fields (CLAUDE.md §2)
- ❌ Cost model fields (commission_rate, stamp_duty_rate, min_commission) (CLAUDE.md §0)

### A.8 Total Violations (FRESH 2026-09-23)

```
Engine violations:                  20 (cost:6, corp:4, settle:4 engines, PIT:2, NAV:1, ATR:1, WFV:1, +1 cycle NAV)
Test infrastructure gaps:           2 (DSR sweep glob + compliance fields)
  └ §5 DSR Coverage Gap:            1 gap (16 sweep scripts NOT covered, FRESH count)
  └ Compliance Test Coverage:       1 gap (compliance fields missing)

Total: 20 known violations across 4 engines + 2 test infrastructure gaps
       (其中 §2 Settlement Isolation 升级为 4 引擎普适违规, 不是仅 chase_up)
       (其中 §5 DSR gap 影响 16 个 sweep script, 不是原文档的 10)
```

### A.9 Test Infrastructure Stats (FRESH)

```
Total tests:               371 collected
no_lookahead:              84/84 PASS (4:07 wall) [CORRECTION: was 105, now 84]
§5 DSR + compliance:       15/15 PASS
dual_price infra:          49/49 PASS
RED-locked gap tests:      8 stable
core/dual_price.py:        202 lines (adopted by all 4 engines)
core/walkforward.py:       118 lines (shared WFV window generator)
```

**Per-file no_lookahead breakdown (FRESH 2026-09-23)**:
- `test_chase_up_no_lookahead.py`: 33 tests
- `test_uptrend_pullback_no_lookahead.py`: 17 tests
- `test_cycle_price_action_no_lookahead.py`: 22 tests
- `test_short_reversal_no_lookahead.py`: 7 tests
- `test_cycle_no_lookahead.py`: 5 tests (legacy)
- **Total: 84** (audit doc had 105, FRESH corrected)

### A.10 Pending Fix Priority

**P0 — Cost Model (highest impact, simplest fix)**:
- TDD: write `tests/test_short_reversal_cost_model.py` + `tests/test_cycle_price_action_cost_model.py` to assert correct rates
- Fix: engine.py / replay_strategy_v3.py / lookahead_trade_trace.py / scan_signals.py / cycle portfolio.py + replay_broker.py
- Update test locks: tests/test_phase3_v3_strategy.py:50-51 + tests/test_short_reversal_no_lookahead.py:257
- Regenerate affected trades.csv + backtest.json
- Expected PnL increase: short_reversal +0.12% per round-trip, cycle +0.05% per sell

**P1 — Settlement Isolation (T+1 contract)**:
- Add Settling_Funds state to chase_up portfolio.py
- Modify _close_position to defer cash credit until T+1

**P1 — PIT Universe (point-in-time correctness)**:
- Add asof_date parameter to chase_up.load_universe + uptrend_pullback.load_universe
- Thread asof_date through walkforward / backtrader_engine / sweep callers

**P2 — Corporate Actions (event-sourced)**:
- Add dividend_handler + split_handler to all 4 engines
- cash dividend → Free_Cash deposit, split → quantity × ratio + cost / ratio

**P2 — cycle_price_action parity**:
- Add NAV_GATE_RATIO + mark-to-market NAV check
- ~~Add ATR-aware slippage (use core/dual_price.atr_slippage)~~ **DONE in R5' (2026-09-23)** — see A.5 correction

**P2 — Test infrastructure**:
- Extend `tests/test_sweep_scripts_dsr.py` glob: add `**/grid*.py`, `**/wf_v*_focused.py` patterns
  - 16 scripts currently NOT covered (was reported as 10 — FRESH count correction)
  - 15 of those 16 lack DSR/Bonferroni — RED tests will surface real §5 violations
- Add §2 cost model fields + max_positions + position_sizing assertions to test_compliance_audit_all_presets.py

---