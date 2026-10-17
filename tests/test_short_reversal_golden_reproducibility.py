"""Runtime §0 golden reproducibility for short_reversal (the REAL baseline).

Why this file exists
--------------------
`tests/test_reproducibility_audit.py::test_short_reversal_has_trades_csv_sha256_baseline`
decides whether short_reversal has a determinism baseline by substring-scanning
`tests/test_short*` for the token "sha256". Before this file the only match was a
dict-KEY READ in `tests/test_short_reversal_price_domain_equivalence.py`
(`a["trades_sha256"] == b["trades_sha256"]`) — it compares two COMMITTED
snapshots and never re-runs the engine, so it can never fire on a real
behavioural regression, yet it satisfied the audit's proxy. That disarmed the
gate.

This file is the real thing: it re-runs each preset through
`run_backtest_v3` on the SAME golden window the baselines were captured on and
compares the COMPUTED `trades_sha256` against `tests/golden/sr_*_baseline.json`.
A trade list that drifts is now caught by an executed run, not by a file scan.

COST
----
~8-10 minutes per preset on the golden window (245 bars across the whole
universe). At the time of writing there are three committed baselines, so a full
run is tens of minutes — calibrated against the repo's existing expensive suites
(`tests/test_live_signal_job.py` ~19 min, `tests/test_short_reversal_daily_equity.py`
~17 min). The runtime test is marked `golden` so it can be deselected:

    python3 -m pytest tests/ -m "not golden"

It skips (never errors) when the local DuckDB or the baselines are absent (§6).
Do NOT regenerate a baseline to silence a red run: a divergence means the trade
list changed and MUST be justified in the PR (§6).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"


def trades_sha256(trades: list[dict]) -> str:
    """Canonical, order-stable hash of the trade list (CLAUDE.md §0).

    MUST stay byte-identical to `tests/golden/_capture_short_reversal_baseline.py`
    (the writer of these baselines); `test_hash_matches_the_capture_script`
    pins that parity so the two cannot drift.
    """
    canon = json.dumps(trades, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _baseline_paths() -> list[Path]:
    if not GOLDEN.exists():
        return []
    return sorted(GOLDEN.glob("sr_*_baseline.json"))


def _can_run() -> bool:
    """True only if there is a DB to run against AND a baseline to check."""
    if not _baseline_paths():
        return False
    try:
        from hiagent_config import get_db_path
    except Exception:  # pragma: no cover - import environment issue
        return False
    return get_db_path().exists()


pytestmark = pytest.mark.skipif(
    not _can_run(),
    reason="no golden baseline / local DuckDB — §6: skip, do not error",
)


def test_hash_matches_the_capture_script():
    """The reload hash and the capture-script hash MUST be the same function.

    If they diverge, every baseline would be "reproduced" by a different
    algorithm than the one that wrote it — a false green. Load the capture
    script by path (it is not a package) and compare on a shape that exercises
    the canonicalisation: nested dict, non-ASCII, and a non-JSON-serialisable
    value routed through `default=str`.
    """
    path = GOLDEN / "_capture_short_reversal_baseline.py"
    assert path.exists(), f"capture script missing at {path}"
    spec = importlib.util.spec_from_file_location(
        "_capture_short_reversal_baseline", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    sample = [
        {"thscode": "000001.SZ", "net": -1234.5, "note": "中文",
         "nested": {"a": 1, "b": [1, 2, 3]}},
        {"thscode": "600000.SH", "net": float("nan"), "entry_price": 11.68},
    ]
    assert trades_sha256(sample) == module.trades_sha256(sample), (
        "the runtime runner's hash differs from the capture script's hash — the "
        "baselines would be compared with the wrong algorithm (a false green)"
    )


@pytest.mark.golden
@pytest.mark.parametrize("baseline_name", [p.name for p in _baseline_paths()])
def test_rerun_reproduces_the_committed_trade_list(baseline_name: str):
    """§0: re-run the preset on the golden window; the COMPUTED trade-list hash
    must equal the committed one. ~8-10 min per preset — see the module cost
    note; deselect with `-m "not golden"`.
    """
    base = json.loads((GOLDEN / baseline_name).read_text(encoding="utf-8"))
    from hiagent_config import get_db_path
    from short_reversal.engine import run_backtest_v3

    m = run_backtest_v3(
        base["preset"], base["start"], base["end"], get_db_path(),
        min_bars=base["min_bars"],
    )
    actual_rows = len(m["trades"])
    actual_hash = trades_sha256(m["trades"])

    assert actual_rows == base["trades_rows"], (
        f"{base['preset']}: trade COUNT drifted on "
        f"[{base['start']}..{base['end']}] min_bars={base['min_bars']}: "
        f"committed {base['trades_rows']} vs re-run {actual_rows}. Do NOT "
        f"regenerate the baseline to silence this — investigate the drift (§6)."
    )
    assert actual_hash == base["trades_sha256"], (
        f"{base['preset']}: trade-list sha256 drifted on "
        f"[{base['start']}..{base['end']}] min_bars={base['min_bars']}:\n"
        f"  committed: {base['trades_sha256']}\n"
        f"  re-run:    {actual_hash}\n"
        f"A different trade list means some engine behaviour changed; justify it "
        f"in the PR before regenerating (§6)."
    )
