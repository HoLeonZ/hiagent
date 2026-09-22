# CLAUDE.md Preset Compliance Audit — 2026-09-22

Goal: enumerate every preset in every strategy against the new `CLAUDE.md`
mandates (project root) and classify violations.

**Audit script:** `tests/test_claudemd_full_audit.py` (extends
`tests/test_compliance_audit_all_presets.py`, which only covered §3/§4/§5
field declarations — not §2 Capital).

**Preset inventory:** 36 presets across 4 strategies.
| Strategy | Count | File |
|----------|-------|------|
| cycle_price_action | 1 | `cycle_price_action/presets.py` |
| uptrend_pullback | 2 | `uptrend_pullback/presets.py` |
| short_reversal | 11 | `short_reversal/presets.py` |
| chase_up | 22 | `chase_up/presets.py` |
| **Total** | **36** | |

---

## Dimension-by-dimension findings

### §2 Capital & State Determinism — All-In Sizing Policy (2026-09-21)

> `position_sizing = "all_in"`, `MAX_POSITION_PCT = 1.0`,
> `position_fraction = 1.0`, `max_positions = 1`.

Two kinds of violations:

**(A) Engine behaviorally compliant but declaration missing** — engine
hardcodes 100%-of-cash, preset doesn't declare the field. Engine still
behaves correctly but the preset does not document the policy.

- **cycle_price_action / PRESET_V1** — 4 gaps (all §2 fields missing).
  Engine code (`cycle_price_action/portfolio.py:65`):
  `MAX_POSITION_PCT = 1.0` is hardcoded → **engine is compliant**.
- **short_reversal (all 11 presets)** — 44 gaps (4 fields × 11).
  Engine code (`short_reversal/engine.py:173`,
  `replay_strategy_v3.py:47`): hardcodes `position_fraction=1.0` →
  **engine is compliant**.
- **uptrend_pullback (both presets)** — `position_sizing="all_in"`,
  `max_positions=1` already declared; only `position_fraction` and
  `MAX_POSITION_PCT` missing → **declaration-only, engine compliant**.

**(B) Behavioral violations** — preset **explicitly** violates §2,
engine will use the values. **These are real compliance failures.**

- **chase_up presets with `position_sizing='equal'`**: v2, v5, v7, v8, v9,
  v10, v11, v12, v13, v14, v15, v16, v17, v18, v19
  → engine `portfolio.py:325`: `slot_value = cash / max_positions`,
    so each slot gets ≤ 100/N % — NOT all-in per slot.
- **chase_v6_atr_tp4_sl1_pos3** (`position_sizing='all_in'`,
  `max_positions=3`): semantically contradictory. Engine tries to fill
  3 slots each with 100% of remaining cash. After slot 1 fills, no cash
  left → slot 2-3 must reject for cost > cash. Effectively serializes
  to single-slot exposure but the preset is **structurally dishonest**
  about its intent. Per memory
  `chase-up-conservative-cash-fixes.md`, implicit margin was Bug A
  fixed 2026-09-21, so 3-slot-all-in is exactly the failure mode that
  bug was fixing.
- All 22 chase_up presets: missing `position_fraction=1.0` and
  `MAX_POSITION_PCT=1.0` declaration even when behavior is all-in.

**Verdict:** 16 chase_up presets in (B) are **real §2 violations**. The
remaining 20 presets fall in (A) — declaration cleanup needed but no
behavioral change.

### §3 Data Integrity — Dual-Price System

All 36 presets declare `price_source_for_signal="adj_close"` and
`price_source_for_execution="raw_close"`. **0 gaps.**

### §4 Microstructure & Liquidity

Three sub-rules audited:

| Field | Expected | Failures |
|-------|----------|----------|
| `intraday_tiebreak` | `"sl_first"` | 0 |
| `max_volume_participation` | `0.10` | 0 |
| Exit policy: `sl_pct` **or** `atr_sl_mult` declared | one of them | 0 |

All 36 presets compliant. **0 gaps.**

Note: §4 also bans "flat-rate slippage" — but presets declare
`sl_pct`/`atr_sl_mult`/`tp_pct`/`atr_tp_mult` (slippage lives in the
engine, not the preset), so this is out of scope at preset level.

### §5 Statistical Rigor

All 36 presets declare `n_comparisons ≥ 1`. **0 gaps.** The actual
Bonferroni/DSR application is a `dna_stats.walkforward_report`
responsibility (code-level, not preset-level).

### §1 Temporal Determinism & §6 Architecture

These are code-level concerns (`df.bfill()` ban, `AsOf()` rules,
control-plane separation). Preset configs cannot violate these — the
rules apply to engine/strategy code. **No preset-level audit possible.**

---

## Summary by strategy

| Strategy | Total presets | §2 engine-compliant (A) | §2 behavioral violation (B) | §3/§4/§5 |
|----------|---------------|--------------------------|--------------------------------|-----------|
| cycle_price_action | 1 | 1 | 0 | 0 |
| uptrend_pullback | 2 | 2 | 0 | 0 |
| short_reversal | 11 | 11 | 0 | 0 |
| chase_up | 22 | 6 (v1, v1a, v1b, v1c, v3, v4) | 16 (equal+N or all-in+N) | 0 |
| **Total** | **36** | **20** | **16** | **0** |

---

## Recommended remediation

Two-tier approach:

**Tier 1 — Declaration-only fixes (safe, engine behavior unchanged):**
- Add `position_fraction=1.0` and `MAX_POSITION_PCT=1.0` to **all 36**
  presets (the comment can cite CLAUDE.md §2 All-In Sizing Policy).
- For short_reversal (11) and cycle_price_action (1), also add the
  top-level `position_sizing="all_in"` and `max_positions=1` fields.

**Tier 2 — Behavioral fixes (changes engine output, requires testing):**
For the **16 chase_up presets** in (B), three options:

- **(P) Preserve** the multi-slot semantics with comments documenting
  "departure from §2 All-In; atomic cash lock + NAV-floor gate prevent
  margin", so future readers don't think it's a misconfig. Engine
  already implements conservative-cash fixes (memory
  `chase-up-conservative-cash-fixes.md`).
- **(D) Demote** those presets to non-default status: rename prefix
  (e.g. `chase_v8_multi_legacy_*`) and exclude from any "select_entries"
  default.
- **(C) Convert** them to comply with §2: change `max_positions` to 1
  and `position_sizing` to `all_in`, dropping the multi-slot signal of
  the engine. The trade-off: the v8-v19 sweet spots were searched
  under multi-position dynamics (intra-portfolio diversification),
  so re-sampling to 1-slot may invalidate the v15-v19 walk-forward
  results.

Decision requires user input — the choices aren't symmetric to the
CLAUDE.md proscription.

---

## Files touched by this audit

- New: `tests/test_claudemd_full_audit.py` (5 tests, 1 fails until
  remediated, 4 fail with detailed gaps).
- New: this report (`docs/claudemd_preset_audit_2026_09_22.md`).

## Verification

Re-run `python -m pytest tests/test_claudemd_full_audit.py -v` after
Tier 1 fixes → all 5 tests should pass. After Tier 2 (P/D/C) choice →
also pass if option (D) or (C); (P) would need to relax the audit
assertion to "engine-compliant OR explicitly annotated departure".
