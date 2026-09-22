"""Full CLAUDE.md compliance audit across all presets.

Extends test_compliance_audit_all_presets.py with §2 Capital & State
Determinism and additional §3/§4/§5 dimensions, since the original test
only covered intraday_tiebreak / volume / dual-price / n_comparisons.

CLAUDE.md sections audited at the preset level:
  §2 — Capital & State Determinism:
       - All-In Sizing Policy (2026-09-21):
         position_sizing="all_in", MAX_POSITION_PCT=1.0,
         max_positions=1 (so each slot uses 100% of cash),
         position_fraction=1.0.
       Note: explicit dual-key (single-slot + all-in) is what enforces
       the policy at the engine level, since equal sizing with N positions
       gives 1/N fraction which is not "all_in" for the trade slot.
  §3 — Data Integrity:
       - price_source_for_signal = "adj_close"
       - price_source_for_execution = "raw_close"
  §4 — Microstructure & Liquidity:
       - intraday_tiebreak = "sl_first"
       - max_volume_participation = 0.10
       - Exit thresholds: either fixed (sl_pct present) OR
         ATR-based (atr_sl_mult present). Documented choice either way.
  §5 — Statistical Rigor:
       - n_comparisons ≥ 1 (sweep size used for DSR / Bonferroni)
       - Optional: mark "best parameters based on max Sharpe" as not allowed.
         This is enforced at code level (sweep scripts), not in presets.

Sections §1 (Temporal) and §6 (Architecture) are code-level concerns,
not preset-level. They are referenced as informational reminders only.
"""
from __future__ import annotations

import pytest


def _audit_full(presets_dict: dict, strategy_name: str) -> list[str]:
    """Return list of CLAUDE.md compliance gaps (empty = compliant)."""
    gaps: list[str] = []

    for name, p in presets_dict.items():
        if not isinstance(p, dict):
            gaps.append(
                f"[{strategy_name}] {name}: preset is not a dict (legacy bare literal)"
            )
            continue

        # §2 — Capital & State Determinism (All-In Sizing Policy 2026-09-21)
        sizing = p.get("position_sizing")
        max_pos = p.get("max_positions")
        position_fraction = p.get("position_fraction")
        max_position_pct = p.get("MAX_POSITION_PCT")

        if sizing != "all_in":
            gaps.append(
                f"[{strategy_name}] {name}: §2 position_sizing={sizing!r} "
                f"(must be 'all_in' — CLAUDE.md All-In Sizing Policy 2026-09-21)"
            )
        # position_fraction is recommended for clarity even when redundant
        if position_fraction is None:
            gaps.append(
                f"[{strategy_name}] {name}: §2 position_fraction missing "
                f"(expected 1.0 — CLAUDE.md All-In Sizing Policy)"
            )
        elif position_fraction != 1.0:
            gaps.append(
                f"[{strategy_name}] {name}: §2 position_fraction={position_fraction!r} "
                f"(must be 1.0 — CLAUDE.md All-In Sizing Policy)"
            )

        if max_pos is None:
            gaps.append(
                f"[{strategy_name}] {name}: §2 max_positions missing "
                f"(expected 1 — single trade slot, full cash)"
            )
        elif max_pos != 1:
            gaps.append(
                f"[{strategy_name}] {name}: §2 max_positions={max_pos!r} "
                f"(must be 1 — 'all_in' requires single-slot per CLAUDE.md 2026-09-21)"
            )

        # MAX_POSITION_PCT convention (uppercase, mirrors Python constant)
        if max_position_pct is None:
            gaps.append(
                f"[{strategy_name}] {name}: §2 MAX_POSITION_PCT missing "
                f"(expected 1.0 — CLAUDE.md All-In Sizing Policy)"
            )
        elif max_position_pct != 1.0:
            gaps.append(
                f"[{strategy_name}] {name}: §2 MAX_POSITION_PCT={max_position_pct!r} "
                f"(must be 1.0 — CLAUDE.md All-In Sizing Policy)"
            )

        # §3 — Dual-Price System
        if p.get("price_source_for_signal") != "adj_close":
            gaps.append(
                f"[{strategy_name}] {name}: §3 price_source_for_signal "
                f"={p.get('price_source_for_signal')!r} (must be 'adj_close')"
            )
        if p.get("price_source_for_execution") != "raw_close":
            gaps.append(
                f"[{strategy_name}] {name}: §3 price_source_for_execution "
                f"={p.get('price_source_for_execution')!r} (must be 'raw_close')"
            )

        # §4 — Microstructure
        if p.get("intraday_tiebreak") != "sl_first":
            gaps.append(
                f"[{strategy_name}] {name}: §4 intraday_tiebreak "
                f"={p.get('intraday_tiebreak')!r} (must be 'sl_first')"
            )
        if p.get("max_volume_participation") != 0.10:
            gaps.append(
                f"[{strategy_name}] {name}: §4 max_volume_participation "
                f"={p.get('max_volume_participation')!r} (must be 0.10)"
            )

        # §4 — Exit thresholds (policy, either fixed or ATR-based)
        has_fixed = "sl_pct" in p
        has_atr = "atr_sl_mult" in p
        if not (has_fixed or has_atr):
            gaps.append(
                f"[{strategy_name}] {name}: §4 exit policy missing — "
                f"either fixed 'sl_pct' or ATR-based 'atr_sl_mult' must be declared"
            )

        # §5 — Statistical Rigor
        n_comp = p.get("n_comparisons")
        if n_comp is None or n_comp < 1:
            gaps.append(
                f"[{strategy_name}] {name}: §5 n_comparisons={n_comp!r} "
                f"(must be ≥ 1 — sweep size for DSR/Bonferroni)"
            )

    return gaps


# ---- Per-strategy tests ----


def test_cycle_price_action_full_audit():
    from cycle_price_action.presets import PRESET_V1
    gaps = _audit_full({"PRESET_V1": PRESET_V1}, "cycle_price_action")
    assert not gaps, "CLAUDE.md gaps found:\n" + "\n".join(gaps)


def test_uptrend_pullback_full_audit():
    from uptrend_pullback.presets import PRESETS
    gaps = _audit_full(PRESETS, "uptrend_pullback")
    assert not gaps, "CLAUDE.md gaps found:\n" + "\n".join(gaps)


def test_short_reversal_full_audit():
    from short_reversal.presets import PRESETS
    gaps = _audit_full(PRESETS, "short_reversal")
    assert not gaps, "CLAUDE.md gaps found:\n" + "\n".join(gaps)


def test_chase_up_full_audit():
    from chase_up.presets import PRESETS
    gaps = _audit_full(PRESETS, "chase_up")
    assert not gaps, "CLAUDE.md gaps found:\n" + "\n".join(gaps)


# ---- One-shot summary / diagnostic ----


def test_full_audit_summary():
    """Diagnostic: enumerate every gap, but do not enforce (so failures
    surface as actionable list, not a single opaque assert)."""
    from chase_up.presets import PRESETS as chase
    from short_reversal.presets import PRESETS as short
    from uptrend_pullback.presets import PRESETS as up
    from cycle_price_action.presets import PRESET_V1

    all_presets = {
        "cycle_price_action": {"PRESET_V1": PRESET_V1},
        "uptrend_pullback": up,
        "short_reversal": short,
        "chase_up": chase,
    }
    total = sum(len(p) for p in all_presets.values())
    all_gaps: list[str] = []
    for strat, presets in all_presets.items():
        all_gaps.extend(_audit_full(presets, strat))

    print(f"\nFull CLAUDE.md audit: {total} presets across "
          f"{len(all_presets)} strategies")
    print(f"Total gaps: {len(all_gaps)}")
    if all_gaps:
        # Group by strategy for readability
        from collections import defaultdict
        by_strat: dict[str, list[str]] = defaultdict(list)
        for g in all_gaps:
            strat = g.split("]")[0].lstrip("[")
            by_strat[strat].append(g)
        for strat, gs in by_strat.items():
            print(f"\n=== {strat} ({len(gs)} gaps) ===")
            # Deduplicate by rule
            rule_count: dict[str, int] = defaultdict(int)
            rule_presets: dict[str, set] = defaultdict(set)
            for g in gs:
                # Extract rule key (first ':' after '§N')
                key = g.split(":", 2)[1].strip() if ":" in g else g
                rule_count[key] += 1
                preset = g.split("]")[1].split(":")[0].strip()
                rule_presets[key].add(preset)
            for rule, n in sorted(rule_count.items()):
                presets = sorted(rule_presets[rule])
                print(f"  {rule}: {n} presets → {presets[:3]}"
                      f"{' …' if len(presets) > 3 else ''}")
