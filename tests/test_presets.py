"""PRESETS dict + get_preset() 完整覆盖。"""
from __future__ import annotations

import pytest

from short_reversal.presets import PRESETS, get_preset


EXPECTED_KEYS = {
    "v33_mainboard_tp2_sl05_dneg",
    "v33_mainboard_tp6_sl005_mh5_realistic",
}


def test_presets_has_all_v33_variants():
    assert set(PRESETS.keys()) == EXPECTED_KEYS


@pytest.mark.parametrize("name", list(EXPECTED_KEYS))
def test_preset_required_fields(name):
    p = PRESETS[name]
    assert "universe" in p
    assert "tp_pct" in p
    assert "sl_pct" in p
    assert "max_hold" in p
    assert p["sl_pct"] > 0
    assert p["tp_pct"] > 0
    assert p["max_hold"] > 0


def test_get_preset_returns_dict():
    p = get_preset("v33_mainboard_tp6_sl005_mh5_realistic")
    assert p["universe"] == "mainboard_only"
    assert p["tp_pct"] == 0.06


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        get_preset("v33_does_not_exist")