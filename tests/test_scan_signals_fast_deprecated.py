"""Locks the known divergence of scan_signals_fast vs the strategy (§2.2).

This test does NOT assert equivalence. It asserts that the divergence is
DOCUMENTED, so nobody re-adopts the module believing its old claim.
"""
from __future__ import annotations

from short_reversal import scan_signals_fast


def test_module_docstring_warns_it_is_not_equivalent():
    doc = (scan_signals_fast.__doc__ or "").lower()
    assert "not equivalent" in doc or "不等价" in doc, (
        "scan_signals_fast must warn that it does NOT match the strategy; "
        "see docs/superpowers/specs/2026-10-17-short-reversal-live-monitor-design.md §2.2"
    )
    assert "do not use" in doc or "不可用于生产" in doc


def test_docstring_enumerates_the_documented_divergences():
    """The warning is only useful if it names what actually differs.

    This asserts DOCUMENTATION COMPLETENESS, not that any defect persists —
    if someone later makes these thresholds cfg-driven, the warning should be
    narrowed and this list shortened, not deleted outright.
    """
    doc = scan_signals_fast.__doc__ or ""
    for token in ("below_ratio_60", "close_ma60_buffer", "converge_strict",
                  "require_ma20_slope_neg", "signal_price_domain"):
        assert token in doc, f"warning does not mention the {token} divergence"


def test_the_withdrawn_claim_does_not_reappear():
    """The presence checks above guard against the warning being DELETED. They do
    NOT guard against the old claim being RE-INSERTED alongside it — a docstring
    could carry both the warning and a fresh equivalence sentence and still pass
    every assertion above. That is the failure this task exists to prevent.

    A naive `"100% 等价" not in doc` would be WRONG: the warning legitimately
    quotes the retracted phrasing. So assert the stronger, mechanisable form —
    the phrase may appear at most once, and that one occurrence must be framed
    as retracted.
    """
    doc = scan_signals_fast.__doc__ or ""
    hits = [line for line in doc.splitlines() if "100% 等价" in line]
    assert len(hits) <= 1, (
        f"the withdrawn claim appears {len(hits)} times; a re-inserted claim "
        f"alongside the warning would make the docstring contradict itself. "
        f"Lines: {hits}"
    )
    if hits:
        assert "曾声称" in hits[0], (
            f"the only mention of the withdrawn claim must be framed as retracted, "
            f"but reads: {hits[0].strip()!r}"
        )
