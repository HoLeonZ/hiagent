"""Locks the price-domain equivalence established on 2026-10-17.

`v44_ratio02_buf07` declares no `signal_price_domain`, and the engine default is
now "adj" (see `signal_price_domain=cfg.get("signal_price_domain", "adj")` in
short_reversal/engine.py — cite the expression, not a line number, which Task 7
shifts) — so it behaves exactly like `v81_adj` (v44 + explicit
adj domain). This test is the observable evidence that the preset library
carries no re-introduced raw-domain signal path.

If this goes red, do NOT simply regenerate the baselines: a divergence here means
some preset's signal domain semantics changed, which invalidates every recorded
performance number for that family.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
A = "sr_v44_ratio02_buf07_baseline.json"
B = "sr_v81_adj_baseline.json"


@pytest.fixture(scope="module")
def baselines() -> tuple[dict, dict]:
    pa, pb = GOLDEN / A, GOLDEN / B
    if not pa.exists() or not pb.exists():
        pytest.skip(f"baselines absent ({A} / {B}) — regenerate via the capture script")
    return json.loads(pa.read_text(encoding="utf-8")), json.loads(pb.read_text(encoding="utf-8"))


def test_v44_and_v81_adj_have_identical_trade_lists(baselines: tuple[dict, dict]):
    a, b = baselines
    assert a["trades_rows"] == b["trades_rows"], (
        f"row count diverged: v44 {a['trades_rows']} vs v81_adj {b['trades_rows']}"
    )
    assert a["trades_sha256"] == b["trades_sha256"], (
        "trade lists diverged. The engine default signal_price_domain is 'adj' "
        "(the `cfg.get(\"signal_price_domain\", \"adj\")` call site in "
        "short_reversal/engine.py), so v44 and v81_adj must be the same strategy. A "
        "divergence means some preset's signal domain semantics changed — do "
        "not regenerate the baselines to silence this; investigate first."
    )


def test_v44_and_v81_adj_have_identical_metrics(baselines: tuple[dict, dict]):
    a, b = baselines
    # Compare canonically, NOT with `==`: JSON round-trips a NaN as `NaN` and
    # two distinct NaN objects compare unequal, so `a["metrics"] == b["metrics"]`
    # would fail spuriously the day any metric becomes undefined. (Today none
    # can — `_approx_sharpe` guards the empty case and returns 0.0 — but the
    # comparison should not depend on that staying true.)
    assert json.dumps(a["metrics"], sort_keys=True, default=str) == \
        json.dumps(b["metrics"], sort_keys=True, default=str)


def test_the_pair_is_captured_on_the_same_window_and_gate(baselines: tuple[dict, dict]):
    """Equivalence is only meaningful on one window and one min_bars."""
    a, b = baselines
    assert (a["start"], a["end"], a["min_bars"]) == (b["start"], b["end"], b["min_bars"])
