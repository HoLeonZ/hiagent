"""PRESETS dict + get_preset() 完整覆盖。

NOTE: `short_reversal/presets.py` 增长为 19 个 preset (含 v33-v49 系列);
本测试从 "key 数量硬等于" 放宽为 "至少包含 v33 双 baseline 且 get_preset()
可正常返回"。
"""
from __future__ import annotations

import pytest

from short_reversal.presets import PRESETS, get_preset


# v33 baselines — 必须保留 (用于回测对比参照)
REQUIRED_KEYS = {
    "v33_mainboard_tp2_sl05_dneg",
    "v33_mainboard_tp6_sl005_mh5_realistic",
}


def test_presets_contains_required_v33_baselines():
    """Required v33 baselines must remain in PRESETS (注释中明确为破产/对比参照)。"""
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
    p = get_preset("v33_mainboard_tp6_sl005_mh5_realistic")
    assert p["universe"] == "mainboard_only"
    assert p["tp_pct"] == 0.06


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        get_preset("v33_does_not_exist")