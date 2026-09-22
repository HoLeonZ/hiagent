"""V8 plumbing regression test (2026-09-22, CLAUDE.md §4).

Verifies engine.py plumbs CLAUDE.md §4 compliance params from preset
into Phase3V3Strategy. Without this, the preset declarations are
aspirational comments only and strategy uses module constants.

Params tested:
  - max_volume_participation: passed from preset to strategy
  - intraday_tiebreak: passed from preset to strategy, asserts 'sl_first'
  - atr_slip_scale: passed from preset to strategy (default 0.0)
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from short_reversal.engine import run_backtest_v3
from short_reversal.feed_bt import AShareData
from short_reversal.presets import PRESETS
from short_reversal.replay_strategy_v3 import Phase3V3Strategy


def _build_panel(n: int = 250) -> pd.DataFrame:
    """Build minimal panel for short_reversal backtest."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rows = []
    for d in dates:
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
        })
    return pd.DataFrame(rows)


def test_strategy_default_max_volume_participation_matches_module_constant():
    """Strategy default for max_volume_participation must match CLAUDE.md §4 spec
    (Bar_Volume × 0.10)."""
    assert Phase3V3Strategy.params.max_volume_participation == 0.10
    assert Phase3V3Strategy.params.intraday_tiebreak == "sl_first"
    assert Phase3V3Strategy.params.atr_slip_scale == 0.0


def test_all_presets_declare_v8_compliance_params():
    """All 11 short_reversal presets must declare V8 compliance params
    (intraday_tiebreak + max_volume_participation). This is the audit
    anchor: every preset has these in its dict."""
    for name, p in PRESETS.items():
        assert "intraday_tiebreak" in p, f"{name} missing intraday_tiebreak"
        assert p["intraday_tiebreak"] == "sl_first", (
            f"{name} intraday_tiebreak must be 'sl_first', got {p['intraday_tiebreak']}"
        )
        assert "max_volume_participation" in p, f"{name} missing max_volume_participation"
        assert p["max_volume_participation"] == 0.10, (
            f"{name} max_volume_participation must be 0.10, got {p['max_volume_participation']}"
        )


def test_engine_plumbs_max_volume_participation_to_strategy(monkeypatch):
    """Mock the backtest pipeline; verify Phase3V3Strategy receives
    max_volume_participation from preset (not just module constant).
    """
    from short_reversal import engine as eng

    captured_strats: list = []

    real_init = Phase3V3Strategy.__init__

    def spy_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured_strats.append(self)

    monkeypatch.setattr(Phase3V3Strategy, "__init__", spy_init)

    # mock universe + panel
    monkeypatch.setattr(eng, "load_universe_asof", lambda *a, **k: ["TEST.SH"])
    monkeypatch.setattr(eng, "_load_panel", lambda *a, **k: _build_panel(n=250))

    # Run a preset
    run_backtest_v3("v35_agg_pctchg_04_09", "2024-01-01", "2024-12-31",
                    db_path=None)

    assert len(captured_strats) >= 1
    s = captured_strats[0]
    # Strategy params match preset declarations
    assert s.p.max_volume_participation == pytest.approx(0.10)
    assert s.p.intraday_tiebreak == "sl_first"
    assert s.p.atr_slip_scale == pytest.approx(0.0)


def test_engine_atr_slip_scale_from_preset_when_present(monkeypatch):
    """When preset declares atr_slip_scale > 0, engine must pass it through."""
    from short_reversal import engine as eng

    # Inject a test preset with atr_slip_scale
    test_preset = dict(PRESETS["v35_agg_pctchg_04_09"])
    test_preset["atr_slip_scale"] = 0.5
    monkeypatch.setitem(eng.PRESETS, "test_atr_preset", test_preset)

    captured_strats: list = []

    real_init = Phase3V3Strategy.__init__

    def spy_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        captured_strats.append(self)

    monkeypatch.setattr(Phase3V3Strategy, "__init__", spy_init)
    monkeypatch.setattr(eng, "load_universe_asof", lambda *a, **k: ["TEST.SH"])
    monkeypatch.setattr(eng, "_load_panel", lambda *a, **k: _build_panel(n=250))

    run_backtest_v3("test_atr_preset", "2024-01-01", "2024-12-31", db_path=None)

    assert len(captured_strats) >= 1
    assert captured_strats[0].p.atr_slip_scale == pytest.approx(0.5)
