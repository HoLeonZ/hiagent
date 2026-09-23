"""§4 TP/SL Compliance Header — Exit Threshold Policy Documentation (Tick 75).

CLAUDE.md §4 (verbatim):
  "Stop-loss and take-profit exit thresholds are policy decisions, NOT
   execution costs. They MAY be either fixed (e.g., `sl_pct=0.0005`) or
   ATR-based (`sl_pct = atr × mult`). Both are valid; document the
   choice in the preset's compliance header."

**核心发现 (FRESH 2026-09-23):**

A. **Background**:
   - chase_up presets: ATR-adaptive (`atr_tp_mult` / `atr_sl_mult`) with
     `tp_pct` / `sl_pct` fallback (lines 49-50)
   - short_reversal presets: FIXED-only (`tp_pct` / `sl_pct` ONLY, no
     ATR multipliers) per line 62-63 example
   - uptrend_pullback presets: similar to chase_up (ATR-adaptive)
   - cycle_price_action presets: mixed (line 21-22 shows
     `atr_sl_mult=1.5` + `tp_pct=0.06`)

B. **Compliance header pattern**:
   - All 4 engines have V5/V6/V3a/V7/§2 compliance comments
   - BUT NO preset has explicit exit-threshold compliance header
   - Per CLAUDE.md §4: "document the choice in the preset's
     compliance header"
   - Current state: presets document SL-first tiebreak (V6), volume
     participation (V5), dual-price (V3a), statistical rigor (V7),
     sizing (§2) — but skip the §4 EXIT THRESHOLD CHOICE

C. **Why this matters**:
   - Per §4: TP/SL is a POLICY DECISION, not execution cost
   - Per §0 Pessimistic Default: assume worst case — over-fitting
     parameter search benefits from explicit policy choice
   - Per §5 Statistical Rigor: ATR-adaptive has different statistical
     properties than fixed (different noise model)
   - Audit trail: reader needs to see WHICH presets use fixed vs ATR

D. **Detection scope**:
   - AST scan presets.py for preset dict literals
   - For each preset, identify TP/SL key set:
     - ATR_ADAPTIVE: has `atr_tp_mult` AND/OR `atr_sl_mult`
     - FIXED: only `tp_pct` / `sl_pct` (no ATR multipliers)
     - HYBRID: has both ATR multipliers AND fixed fallback
   - Search preceding 10 lines for §4 compliance header marker
   - RED if no marker for the chosen policy

E. **Expected outcome**:
   - RED for presets without explicit §4 exit-threshold compliance
     comment
   - PASS for presets with explicit comment such as:
     - "§4 exit threshold: ATR-adaptive" / "fixed / fallback" etc.
     - "TP/SL policy: ATR × mult" / "TP/SL policy: fixed pct"
     - Any marker mentioning ATR or fixed in TP/SL context

F. **Why this is a §4 violation, not just stylistic**:
   - CLAUDE.md §4 EXPLICITLY mandates "document the choice in the
     preset's compliance header"
   - Without documentation, downstream readers cannot distinguish
     ATR-adaptive from fixed presets without reading the code
   - This affects reproducibility ([[reproducibility-audit-2026-09-23]]
     Tick 36) — sha256 baselines are useless if policy choice is
     implicit
"""
from __future__ import annotations

import ast
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


# Preset files per engine
PRESET_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "presets.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "presets.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "presets.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "presets.py",
}


# Compliance markers indicating §4 exit-threshold policy choice
# Matches: "§4 exit", "TP/SL", "TP/SL policy", "exit threshold",
# "ATR-adaptive", "fixed fallback", "exit policy"
COMPLIANCE_MARKER_PATTERNS = (
    re.compile(r"§4.{0,40}(exit|TP/?SL|ATR|fixed)", re.IGNORECASE),
    re.compile(r"TP/?SL.{0,40}(policy|adaptive|fixed|ATR)", re.IGNORECASE),
    re.compile(r"exit.{0,40}(threshold|policy|adaptive)", re.IGNORECASE),
    re.compile(r"ATR.{0,40}(adaptive|自适应|fallback)", re.IGNORECASE),
    re.compile(r"(fixed|固定).{0,20}(TP/?SL|exit|stop|take.?profit)", re.IGNORECASE),
)


def _identify_tp_sl_policy(preset_dict: dict[str, object]) -> str:
    """Identify TP/SL policy from preset key set."""
    keys_lower = {k.lower() for k in preset_dict.keys()}

    has_atr = bool(
        "atr_tp_mult" in keys_lower or "atr_sl_mult" in keys_lower
    )
    has_fixed = "tp_pct" in keys_lower or "sl_pct" in keys_lower

    if has_atr and has_fixed:
        return "HYBRID"  # ATR-adaptive with fixed fallback
    if has_atr:
        return "ATR_ADAPTIVE"
    if has_fixed:
        return "FIXED"
    return "MISSING"  # no TP/SL keys at all


def _extract_compliance_comments_above(
    source_lines: list[str],
    dict_start_line: int,
    window: int = 15,
) -> str:
    """Extract preceding lines (comments + blank) before a dict literal.

    Returns concatenated text from up to `window` lines before
    dict_start_line, skipping non-comment lines.
    """
    start = max(0, dict_start_line - window)
    preceding_text: list[str] = []
    for line_idx in range(start, dict_start_line):
        line = source_lines[line_idx].strip()
        # Keep comments and blank lines (for paragraph context)
        if line.startswith("#") or not line:
            preceding_text.append(line)
    return "\n".join(preceding_text)


def _has_compliance_marker(comment_text: str) -> bool:
    """Check if comment text contains a §4 exit-threshold marker."""
    for pattern in COMPLIANCE_MARKER_PATTERNS:
        if pattern.search(comment_text):
            return True
    return False


def _scan_presets_for_compliance(
    file_path: Path,
) -> list[tuple[str, int, str, str]]:
    """Scan preset file for presets without §4 compliance header.

    Returns list of (preset_name, line, policy, preceding_comments).
    """
    if not file_path.exists():
        return []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        source_lines = source.splitlines()
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []

    non_compliant: list[tuple[str, int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        if not hasattr(node, "lineno"):
            continue

        # Convert dict to Python object for inspection
        try:
            preset_dict = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            continue

        if not isinstance(preset_dict, dict):
            continue

        # Skip non-preset dicts (e.g., signal sub-dicts)
        # Presets have a recognizable set of keys (universe, max_hold, etc.)
        preset_keys = set(preset_dict.keys())
        if not (
            "universe" in preset_keys
            or "max_hold" in preset_keys
            or "max_positions" in preset_keys
        ):
            continue

        policy = _identify_tp_sl_policy(preset_dict)
        if policy == "MISSING":
            continue  # No TP/SL keys at all — different concern

        # Find the preset name (the dict key in the parent Dict)
        # Walk up to find the enclosing Dict where this is a value
        preset_name = "<unknown>"
        for parent in ast.walk(tree):
            if isinstance(parent, ast.Dict):
                for key_node, value_node in zip(parent.keys, parent.values):
                    if value_node is node and isinstance(key_node, ast.Constant):
                        preset_name = str(key_node.value)
                        break
                if preset_name != "<unknown>":
                    break

        preceding = _extract_compliance_comments_above(
            source_lines, node.lineno
        )

        if not _has_compliance_marker(preceding):
            non_compliant.append(
                (preset_name, node.lineno, policy, preceding[:200])
            )

    return non_compliant


def _engine_red_message(
    engine: str, violations: list[tuple[str, int, str, str]]
) -> str:
    sample = violations[:3]
    sample_lines = "\n".join(
        f"  - {name} (line {line}, policy={policy})"
        for name, line, policy, _ in sample
    )
    return (
        f"§4 TP/SL COMPLIANCE HEADER MISSING: {engine} has "
        f"{len(violations)} presets without explicit §4 exit-threshold "
        f"compliance comment.\n"
        f"Per CLAUDE.md §4: 'document the choice in the preset's "
        f"compliance header'.\n"
        f"Per §0 Pessimistic Default: exit-threshold policy must be "
        f"explicit (ATR-adaptive vs fixed vs hybrid).\n"
        f"First {len(sample)} violations:\n{sample_lines}\n"
        f"Fix: add comment like '§4 TP/SL: ATR-adaptive' or "
        f"'§4 TP/SL: fixed (sl_pct=0.0005 fallback)' before each preset."
    )


# ---------------------------------------------------------------------------
# RED baselines: presets without §4 TP/SL compliance headers
# ---------------------------------------------------------------------------


def test_chase_up_tp_sl_compliance_header() -> None:
    """§4 RED: chase_up presets lack explicit exit-threshold compliance header."""
    violations = _scan_presets_for_compliance(PRESET_FILES["chase_up"])
    if violations:
        raise AssertionError(_engine_red_message("chase_up", violations))


def test_uptrend_pullback_tp_sl_compliance_header() -> None:
    """§4 RED: uptrend_pullback presets lack §4 exit-threshold compliance."""
    violations = _scan_presets_for_compliance(
        PRESET_FILES["uptrend_pullback"]
    )
    if violations:
        raise AssertionError(
            _engine_red_message("uptrend_pullback", violations)
        )


def test_short_reversal_tp_sl_compliance_header() -> None:
    """§4 RED: short_reversal presets use FIXED TP/SL (line 62-63 example)
    without explicit §4 compliance comment."""
    violations = _scan_presets_for_compliance(PRESET_FILES["short_reversal"])
    if violations:
        raise AssertionError(
            _engine_red_message("short_reversal", violations)
        )


def test_cycle_price_action_tp_sl_compliance_header() -> None:
    """§4 RED: cycle_price_action presets lack §4 exit-threshold compliance."""
    violations = _scan_presets_for_compliance(
        PRESET_FILES["cycle_price_action"]
    )
    if violations:
        raise AssertionError(
            _engine_red_message("cycle_price_action", violations)
        )
