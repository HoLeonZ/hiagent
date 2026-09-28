"""CLAUDE.md §4 TP/SL compliance header — exit-threshold policy documentation.

CLAUDE.md §4 (verbatim):
  "Stop-loss and take-profit exit thresholds are policy decisions, NOT
   execution costs. They MAY be either fixed (e.g., `sl_pct=0.0005`) or
   ATR-based (`sl_pct = atr × mult`). Both are valid; document the
   choice in the preset's compliance header."

Required header fields (above each preset):
  - exit_policy: fixed | atr_based
  - sl_pct: <value or "atr_mult × atr">
  - tp_pct: <value or "atr_mult × atr">
  - max_hold: <days>
  - atr_period: <N>   # only if atr_based
  - Note: <remarks>

Header MUST start with the marker `# CLAUDE.md §4`.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PRESET_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "presets.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "presets.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "presets.py",
}

REQUIRED_FIELDS = ("exit_policy", "sl_pct", "tp_pct", "max_hold")
HEADER_MARKER = "CLAUDE.md §4"
LOOKBACK_LINES = 20


def _extract_presets(file_path: Path) -> list[tuple[str, int, str]]:
    """Yield (preset_name, lineno, preceding_comment_block) for each preset dict."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    source_lines = source.splitlines()

    results: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue

        try:
            preset_dict = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            continue

        if not isinstance(preset_dict, dict):
            continue

        preset_keys = set(preset_dict.keys())
        if not (
            "universe" in preset_keys
            or "max_hold" in preset_keys
            or "max_positions" in preset_keys
        ):
            continue

        # Find preset name by walking parent Dicts
        preset_name = "<unknown>"
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.Dict):
                continue
            for key_node, value_node in zip(parent.keys, parent.values):
                if value_node is node and isinstance(key_node, ast.Constant):
                    preset_name = str(key_node.value)
                    break
            if preset_name != "<unknown>":
                break

        # Collect comment lines immediately above (lookback window)
        start = max(0, node.lineno - 1 - LOOKBACK_LINES)
        preceding_lines: list[str] = []
        for idx in range(start, node.lineno - 1):
            line = source_lines[idx].strip()
            if line.startswith("#"):
                preceding_lines.append(line)
        comment_block = "\n".join(preceding_lines)

        results.append((preset_name, node.lineno, comment_block))

    return results


def _has_required_fields(comment_block: str) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields)."""
    missing = [f for f in REQUIRED_FIELDS if f not in comment_block]
    return (len(missing) == 0, missing)


def _has_header_marker(comment_block: str) -> bool:
    return HEADER_MARKER in comment_block


def _assert_engine(engine: str, file_path: Path) -> None:
    if not file_path.exists():
        raise AssertionError(f"{engine}: preset file not found at {file_path}")

    presets = _extract_presets(file_path)
    if not presets:
        raise AssertionError(f"{engine}: no preset dicts detected in {file_path}")

    failures: list[str] = []
    for name, lineno, block in presets:
        ok, missing = _has_required_fields(block)
        marker_ok = _has_header_marker(block)
        if not ok or not marker_ok:
            problems: list[str] = []
            if not marker_ok:
                problems.append(f"missing marker '{HEADER_MARKER}'")
            if not ok:
                problems.append(f"missing fields {missing}")
            failures.append(f"  - {name} (line {lineno}): {'; '.join(problems)}")

    if failures:
        msg = (
            f"§4 TP/SL compliance header missing in {engine} "
            f"({len(failures)}/{len(presets)} presets non-compliant):\n"
            + "\n".join(failures)
            + "\nFix: add `# CLAUDE.md §4 TP/SL compliance header` block with "
            "`exit_policy`, `sl_pct`, `tp_pct`, `max_hold` above each preset."
        )
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chase_up_presets_have_compliance_header() -> None:
    """§4 RED→GREEN: every chase_up preset has CLAUDE.md §4 compliance header
    with exit_policy / sl_pct / tp_pct / max_hold documented."""
    _assert_engine("chase_up", PRESET_FILES["chase_up"])


def test_uptrend_pullback_presets_have_compliance_header() -> None:
    """§4 RED→GREEN: every uptrend_pullback preset has CLAUDE.md §4 compliance
    header with exit_policy / sl_pct / tp_pct / max_hold documented."""
    _assert_engine("uptrend_pullback", PRESET_FILES["uptrend_pullback"])


def test_short_reversal_presets_have_compliance_header() -> None:
    """§4 RED→GREEN: every short_reversal preset has CLAUDE.md §4 compliance
    header with exit_policy / sl_pct / tp_pct / max_hold documented."""
    _assert_engine("short_reversal", PRESET_FILES["short_reversal"])


def test_compliance_header_is_documented() -> None:
    """Every compliance header across the 3 engines starts with the
    `# CLAUDE.md §4` marker — proves §4 documentation is explicit, not
    implicit."""
    total_presets = 0
    total_with_marker = 0
    missing_marker: list[str] = []

    for engine, file_path in PRESET_FILES.items():
        for name, lineno, block in _extract_presets(file_path):
            total_presets += 1
            if _has_header_marker(block):
                total_with_marker += 1
            else:
                missing_marker.append(f"{engine}::{name} (line {lineno})")

    if missing_marker:
        raise AssertionError(
            f"{len(missing_marker)}/{total_presets} presets lack the "
            f"'{HEADER_MARKER}' marker:\n  - "
            + "\n  - ".join(missing_marker)
        )