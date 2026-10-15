"""Full CLAUDE.md compliance audit across all presets.

Extends test_compliance_audit_all_presets.py with §2 Capital & State
Determinism and additional §3/§4/§5 dimensions, since the original test
only covered intraday_tiebreak / volume / dual-price / n_comparisons.

CLAUDE.md sections audited at the preset level:
  §2 — Capital & State Determinism:
       - All-In Sizing Policy (2026-09-21):
         position_sizing 必须是引擎**已实现**的模式(all_in | ensemble_split),
         position_fraction=1.0(§2 verbatim)。
       - max_positions 必须是正整数。**不要求等于 1** —— §2 verbatim 说
         "Capacity is bounded by the preset's `max_positions`",即多仓容量是
         §2 明确**容许**的;多仓时每个 slot 的预算是 free_cash/max_positions,
         合计仍是 100% 部署,没有 §2 禁止的"开仓前预留现金缓冲"。
         (2026-10-15 修正:原规则断言 max_positions 必须为 1,并把
         position_sizing 钉成 'all_in' —— 两条都超出 §2 原文,会把 v58 多仓
         与 v63/v64/v79 集成这三类**合规**设计判成违规。)
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

#: §2 真正被引擎实现的 sizing 模式。`all_in` = 单腿全仓;`ensemble_split` =
#: 集成路径(资金等分到 N 条腿)。两者都不是 §2 的偏离 —— 前者是政策默认,
#: 后者在主策略层仍是"把钱全投出去"。名单由引擎侧 `resolve_position_sizing`
#: 的 `allowed` 集合决定,这里必须与之保持一致(2026-10-15)。
VALID_SIZING_MODES = frozenset({"all_in", "ensemble_split"})


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

        if sizing not in VALID_SIZING_MODES:
            gaps.append(
                f"[{strategy_name}] {name}: §2 position_sizing={sizing!r} "
                f"不在引擎已实现的模式 {sorted(VALID_SIZING_MODES)} 内 —— "
                "声明一个引擎不实现的模式 = 承诺被静默丢弃。"
            )
        elif sizing == "ensemble_split" and "ensemble_substrategies" not in p:
            gaps.append(
                f"[{strategy_name}] {name}: §2 position_sizing='ensemble_split' "
                "但未声明 ensemble_substrategies —— 与引擎的分流开关不一致。"
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
                "(§2 verbatim:每个 preset 必须显式声明 max_positions)"
            )
        elif not isinstance(max_pos, int) or isinstance(max_pos, bool) or max_pos < 1:
            gaps.append(
                f"[{strategy_name}] {name}: §2 max_positions={max_pos!r} "
                "必须是 ≥1 的整数。"
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
        # 集成 preset 自身不设 TP/SL:阈值由每条**子策略**各自声明(§4 要求"在
        # preset 的合规头里写明选择",集成 preset 的合规头写的是 per_sub_strategy
        # 并列出子策略)。故 `ensemble_substrategies` 是等价的合规证据。
        delegates = "ensemble_substrategies" in p
        if not (has_fixed or has_atr or delegates):
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
