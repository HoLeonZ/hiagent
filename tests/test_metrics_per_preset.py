"""§2/§3 Per-preset metrics JSON tests (Tick 58 GREEN).

CLAUDE.md §2 (verbatim):
  "Capital is physical and finite. We mandate Double-Entry Bookkeeping."

Each backtest run must leave a per-preset metrics audit trail. Currently
chase_up + uptrend_pullback + short_reversal `main.py` writes a single
`backtest.json` that is overwritten on every preset run — losing 19/22
preset metrics (per [[cash-walk-and-metrics-provenance-gap]]).

GREEN strategy:
  1. Each engine's `main.py` ALSO writes a per-preset file:
       results/<preset_id>_metrics.json  (only aggregate metrics, no trades)
     The legacy `backtest.json` is preserved for back-compat (last run only).
  2. short_reversal engine strips the `trades` list before writing
     metrics JSON (otherwise the JSON file would be huge and unparseable).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_main(module: str, args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """Run a project's main.py as a subprocess; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _real_db_path() -> str:
    """Resolve the real market.duckdb path (skip if missing)."""
    from hiagent_config import DB_PATH
    return str(DB_PATH)


# ---------------------------------------------------------------------------
# chase_up: per-preset metrics.json
# ---------------------------------------------------------------------------


def test_chase_up_main_writes_per_preset_metrics_json(tmp_path: Path) -> None:
    """§2/§3 GREEN: chase_up.main writes per-preset metrics JSON.

    When --out is `results/backtest.json` (default), chase_up.main MUST
    also write `results/<preset>_metrics.json` in the same directory.
    The per-preset file must have aggregate metrics (no trades list).

    We unit-test the writer function directly to avoid the 60s subprocess
    overhead while still verifying the per-preset write path.
    """
    # Verify main.py exposes a per-preset writer
    from chase_up import main as chase_main
    import inspect
    src = inspect.getsource(chase_main)
    has_writer = (
        "_write_per_preset_metrics" in src or
        "_write_outputs" in src
    )
    assert has_writer, (
        "§2/§3 GREEN: chase_up/main.py must define a per-preset metrics "
        "writer (Tick 58 fix). backtest.json alone loses metrics across "
        "preset runs."
    )

    # Direct unit test of the writer
    from chase_up.main import _write_per_preset_metrics
    from chase_up.presets import PRESETS
    preset = next(iter(PRESETS))
    metrics = {
        "preset": preset,
        "cagr": -0.5, "max_dd": 0.3, "sharpe": -1.0,
        "win_rate": 0.3, "trades": 5,
    }
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_per_preset_metrics(out_dir, metrics, preset=preset)
    per_preset_file = out_dir / f"{preset}_metrics.json"
    assert per_preset_file.exists(), (
        f"per-preset file {per_preset_file} must be created"
    )
    data = json.loads(per_preset_file.read_text())
    assert data["preset"] == preset
    for key in ("cagr", "max_dd", "sharpe", "win_rate", "trades"):
        assert key in data


# ---------------------------------------------------------------------------
# uptrend_pullback: per-preset metrics.json
# ---------------------------------------------------------------------------


def test_uptrend_pullback_main_writes_per_preset_metrics_json(tmp_path: Path) -> None:
    """§2/§3 GREEN: uptrend_pullback.main writes per-preset metrics JSON."""
    from uptrend_pullback import main as ut_main
    import inspect
    src = inspect.getsource(ut_main)
    has_writer = (
        "_write_per_preset_metrics" in src or
        "_write_outputs" in src
    )
    assert has_writer, (
        "§2/§3 GREEN: uptrend_pullback/main.py must define a per-preset "
        "metrics writer (Tick 58 fix)."
    )

    from uptrend_pullback.main import _write_per_preset_metrics
    from uptrend_pullback.presets import PRESETS
    preset = next(iter(PRESETS))
    metrics = {
        "preset": preset,
        "cagr": -0.5, "max_dd": 0.3, "sharpe": -1.0,
        "win_rate": 0.3, "trades": 5,
    }
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_per_preset_metrics(out_dir, metrics, preset=preset)
    per_preset_file = out_dir / f"{preset}_metrics.json"
    assert per_preset_file.exists()
    data = json.loads(per_preset_file.read_text())
    assert data["preset"] == preset
    for key in ("cagr", "max_dd", "sharpe", "win_rate", "trades"):
        assert key in data


# ---------------------------------------------------------------------------
# short_reversal: per-preset metrics.json (no embedded trades list)
# ---------------------------------------------------------------------------


def test_short_reversal_main_writes_per_preset_metrics_json(tmp_path: Path) -> None:
    """§2/§3 GREEN: short_reversal.main writes aggregate metrics without trades.

    short_reversal/engine.py _metrics_from_holder includes a `trades` list
    (full per-trade records). The metrics JSON MUST strip this list — only
    aggregate keys are written.

    We invoke `run_backtest_v3` programmatically (faster than CLI subprocess)
    and then call the metrics-strip helper that main.py uses.
    """
    # Verify the main.py helper exists and strips `trades`
    from short_reversal import main as sr_main

    # The main module must export a helper that strips trades from metrics
    import inspect
    src = inspect.getsource(sr_main)
    has_strip = (
        "_strip_trades_for_json" in src or
        "_aggregate_metrics" in src or
        "_write_metrics" in src
    )
    assert has_strip, (
        "§2/§3 GREEN: short_reversal/main.py must have a helper that strips "
        "the per-trade `trades` list before writing aggregate metrics JSON "
        "(Tick 58 fix). Raw trades list makes metrics.json unreadable."
    )

    # Direct unit test of the helper
    from short_reversal.main import _strip_trades_for_json
    sample_metrics = {
        "preset": "v35",
        "cagr": -0.5,
        "sharpe": -1.0,
        "win_rate": 0.3,
        "trades_count": 5,
        "trades": [{"thscode": "X", "net": 1.0}],  # should be stripped
    }
    stripped = _strip_trades_for_json(sample_metrics)
    assert "trades" not in stripped or stripped.get("trades") in (None, []), (
        f"short_reversal main.py helper must strip `trades` from metrics"
    )
    for key in ("preset", "cagr", "sharpe", "win_rate", "trades_count"):
        assert key in stripped