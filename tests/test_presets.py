"""PRESETS dict + get_preset() 完整覆盖。

NOTE: 2026-09-23 rebase (commit acc7d31) 移除 v33-v49 旧 series, 保留
canonical presets v35_agg_pctchg_04_09 与 v46_sl_0002 作为覆盖参照.
本测试断言两个 canonical preset 必须存在, get_preset() 可正常返回.
"""
from __future__ import annotations

import pytest

from short_reversal.presets import PRESETS, get_preset


# Canonical presets — 必须保留 (用于回测对比参照)
REQUIRED_KEYS = {
    "v35_agg_pctchg_04_09",
    "v46_sl_0002",
}


def test_presets_contains_required_canonical_baselines():
    """Required canonical baselines must remain in PRESETS."""
    assert REQUIRED_KEYS.issubset(set(PRESETS.keys()))


@pytest.mark.parametrize("name", sorted(REQUIRED_KEYS))
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
    p = get_preset("v35_agg_pctchg_04_09")
    assert p["universe"] == "mainboard_only"
    assert p["tp_pct"] == 0.06


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        get_preset("v33_does_not_exist")