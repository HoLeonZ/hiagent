"""Cross-strategy CLAUDE.md compliance audit (2026-09-22).

Single test that audits EVERY preset under EVERY strategy type for
CLAUDE.md §4 Microstructure compliance declarations. This is the
authoritative reference: if a preset is missing any required field,
this test fails with the specific gap.

Compliance dimensions audited (each maps to CLAUDE.md §):
  - intraday_tiebreak='sl_first' (§4 SL-first tiebreak)
  - max_volume_participation=0.10 (§4 Volume cap)
  - price_source_for_execution='raw_close' (§3 Dual-Price execution source)
  - price_source_for_signal='adj_close' (§3 Dual-Price signal source)
  - n_comparisons > 0 (§5 Statistical rigor — sweep size for DSR/Bonferroni)
"""
from __future__ import annotations

import pytest


def _audit_presets(presets_dict: dict, strategy_name: str) -> list[str]:
    """Returns a list of compliance gap descriptions (empty = compliant)."""
    gaps = []
    required_fields = {
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_execution": "raw_close",
        "price_source_for_signal": "adj_close",
    }
    for name, p in presets_dict.items():
        if not isinstance(p, dict):
            continue  # legacy alias (e.g. PRESET_V1 = dict(...) literal)
        for field, expected in required_fields.items():
            actual = p.get(field)
            if actual is None:
                gaps.append(f"[{strategy_name}] {name}: missing {field!r}")
            elif actual != expected:
                gaps.append(
                    f"[{strategy_name}] {name}: {field}={actual!r} (expected {expected!r})"
                )
        if "n_comparisons" not in p or p["n_comparisons"] < 1:
            gaps.append(f"[{strategy_name}] {name}: n_comparisons < 1 (§5 Statistical Rigor)")
    return gaps


def test_cycle_price_action_compliance():
    from cycle_price_action.presets import PRESET_V1
    gaps = _audit_presets({"PRESET_V1": PRESET_V1}, "cycle_price_action")
    assert not gaps, "Compliance gaps found:\n" + "\n".join(gaps)


def test_uptrend_pullback_compliance():
    from uptrend_pullback.presets import PRESETS
    gaps = _audit_presets(PRESETS, "uptrend_pullback")
    assert not gaps, "Compliance gaps found:\n" + "\n".join(gaps)


def test_short_reversal_compliance():
    from short_reversal.presets import PRESETS
    gaps = _audit_presets(PRESETS, "short_reversal")
    assert not gaps, "Compliance gaps found:\n" + "\n".join(gaps)


def test_chase_up_compliance():
    from chase_up.presets import PRESETS
    gaps = _audit_presets(PRESETS, "chase_up")
    assert not gaps, "Compliance gaps found:\n" + "\n".join(gaps)


def test_all_presets_summary():
    """One-shot summary of total preset count + compliance rate."""
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
    gaps = []
    for strat, presets in all_presets.items():
        gaps.extend(_audit_presets(presets, strat))
    print(f"\nCompliance summary: {total - len({g.split(']')[0] for g in gaps})}/{total} "
          f"presets compliant across {len(all_presets)} strategies")
    if gaps:
        for g in gaps:
            print(f"  GAP: {g}")
    assert not gaps, f"{len(gaps)} compliance gaps across all presets"
