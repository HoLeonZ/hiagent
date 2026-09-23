"""§0/§6 Preset-to-engine API conformance audit (meta-audit).

CLAUDE.md §0 Pessimistic Default: preset declarations must be ENFORCED.
If preset declares `intraday_tiebreak='sl_first'` and engine never reads
that key, the preset's promise is silently dropped — a Pessimistic Default
violation (worst-case = silent).

This test audits: for every leaf key in every preset dict, does the engine
module reference that key (or an equivalent alias) somewhere in its code?

Method:
  1. Load all preset dicts per engine
  2. For each leaf key (excluding nested config like `signal: {...}`):
     - search the engine module source for the key as a string literal
     - if NOT found → engine silently drops this preset claim → GAP
  3. PASS baseline: every declared key is referenced in engine code

Engine-to-source mapping:
  - chase_up → chase_up/portfolio.py + chase_up/backtrader_engine.py
  - uptrend_pullback → uptrend_pullback/portfolio.py + uptrend_pullback/backtrader_engine.py
  - short_reversal → short_reversal/engine.py + short_reversal/replay_strategy_v3.py
  - cycle_price_action → cycle_price_action/portfolio.py + cycle_price_action/backtest.py

FRESH 2026-09-23 audit tick: this catches the meta-pattern that allowed
cycle_price_action's `intraday_tiebreak` to be silently dropped (Tick 30/31).
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


# Engine source files to search per engine
ENGINE_SOURCES = {
    "chase_up": [
        "chase_up/portfolio.py",
        "chase_up/backtrader_engine.py",
        "chase_up/main.py",
    ],
    "uptrend_pullback": [
        "uptrend_pullback/portfolio.py",
        "uptrend_pullback/backtrader_engine.py",
        "uptrend_pullback/main.py",
    ],
    "short_reversal": [
        "short_reversal/engine.py",
        "short_reversal/replay_strategy_v3.py",
        "short_reversal/portfolio.py",
    ],
    "cycle_price_action": [
        "cycle_price_action/portfolio.py",
        "cycle_price_action/backtest.py",
        "cycle_price_action/backtrader_engine.py",
    ],
}


# Nested config blocks that we don't audit as leaves (they're structured
# config dicts passed as a single kwarg)
NESTED_KEYS = {"signal", "universe", "periods", "weights"}


def _collect_leaf_keys(preset: dict[str, Any]) -> set[str]:
    """Return the set of leaf keys (excluding nested config blocks)."""
    leaves: set[str] = set()
    for k, v in preset.items():
        if k in NESTED_KEYS:
            continue
        if isinstance(v, dict):
            # Also flatten nested signal dict keys
            leaves.update(v.keys())
        else:
            leaves.add(k)
    return leaves


def _load_engine_source(engine: str) -> str:
    """Concatenate all engine source files for one engine into a single string."""
    chunks: list[str] = []
    for path in ENGINE_SOURCES[engine]:
        try:
            chunks.append(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
    return "\n".join(chunks)


def _audit_preset_to_engine(
    engine_name: str,
    presets_module_path: str,
    presets_attr: str,
) -> list[tuple[str, str]]:
    """For all presets in an engine, find leaf keys NOT referenced in engine source.

    Returns: list of (preset_name, dropped_key) tuples.
    """
    mod = importlib.import_module(presets_module_path)
    if presets_attr == "PRESETS":
        presets_dict = mod.PRESETS
    else:
        # cycle uses PRESET_V1 (singleton)
        preset_singleton = getattr(mod, presets_attr)
        presets_dict = {presets_attr: preset_singleton} if isinstance(preset_singleton, dict) else {}

    engine_src = _load_engine_source(engine_name)
    dropped: list[tuple[str, str, str]] = []

    for preset_name, preset_cfg in presets_dict.items():
        if not isinstance(preset_cfg, dict):
            continue
        leaf_keys = _collect_leaf_keys(preset_cfg)
        for key in sorted(leaf_keys):
            # Search for the key as a string literal in engine source.
            # Two patterns:
            #   1. dict access: preset['key'] or preset["key"]
            #   2. kwargs: key= (kwarg in function signature)
            #   3. attribute: .key
            patterns = [
                f"preset['{key}']",
                f'preset["{key}"]',
                f'["{key}"]',
                f"['{key}']",
                f".{key}",
                f"{key}=",
                f"cfg['{key}']",
                f'cfg["{key}"]',
                f'p["{key}"]',
                f"p['{key}']",
                f"self.{key}",
            ]
            if not any(p in engine_src for p in patterns):
                dropped.append((engine_name, preset_name, key))
    return dropped


def test_chase_up_presets_all_reach_engine() -> None:
    """§0/§6: every chase_up preset leaf key must be referenced in engine code."""
    dropped = _audit_preset_to_engine(
        "chase_up",
        "chase_up.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: chase_up has preset keys declared but NEVER "
        "referenced in engine source. Engine silently drops these "
        "preset claims (Pessimistic Default violation):\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total dropped keys)"
    )


def test_uptrend_pullback_presets_all_reach_engine() -> None:
    """§0/§6: every uptrend_pullback preset leaf key must reach engine."""
    dropped = _audit_preset_to_engine(
        "uptrend_pullback",
        "uptrend_pullback.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: uptrend_pullback has preset keys declared but "
        "NEVER referenced in engine source:\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total)"
    )


def test_short_reversal_presets_all_reach_engine() -> None:
    """§0/§6: every short_reversal preset leaf key must reach engine."""
    dropped = _audit_preset_to_engine(
        "short_reversal",
        "short_reversal.presets",
        "PRESETS",
    )
    assert not dropped, (
        "GAP CAPTURED: short_reversal has preset keys declared but "
        "NEVER referenced in engine source:\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total)"
    )


def test_cycle_price_action_presets_all_reach_engine() -> None:
    """§0/§6: every cycle_price_action preset leaf key must reach engine.

    Known gap (Tick 30/31): `intraday_tiebreak` declared in PRESET_V1
    but never referenced in cycle/portfolio.py or backtest.py.
    """
    dropped = _audit_preset_to_engine(
        "cycle_price_action",
        "cycle_price_action.presets",
        "PRESET_V1",
    )
    assert not dropped, (
        "GAP CAPTURED: cycle_price_action has preset keys declared but "
        "NEVER referenced in engine source. Pinning this exact pattern "
        "from Tick 30/31 (intraday_tiebreak dropped silently):\n"
        + "\n".join(f"  - preset={p!r} key={k!r}" for _, p, k in dropped[:10])
        + f"\n  ({len(dropped)} total dropped keys)"
    )


def test_audit_method_finds_intraday_tiebreak_in_cycle() -> None:
    """§6 Meta-test: this audit method correctly captures the Tick 30/31 gap.

    Sanity check: when cycle is in its current state, this audit should
    find `intraday_tiebreak` as a dropped key. If it doesn't, the audit
    is broken (false negative — would let violations slip through).
    """
    dropped = _audit_preset_to_engine(
        "cycle_price_action",
        "cycle_price_action.presets",
        "PRESET_V1",
    )
    dropped_keys = {k for _, _, k in dropped}
    assert "intraday_tiebreak" in dropped_keys, (
        "AUDIT METHOD BROKEN: this audit failed to detect the known "
        "intraday_tiebreak gap from Tick 30/31. The audit must be "
        "sharpened — currently produces false negatives."
    )