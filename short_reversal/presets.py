"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

PRESETS: dict[str, dict] = {
    "v33_final": {
        "universe": "exclude_hs300_zhongtou_finance",
        "tp_pct": 0.03,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
    "v33_mainboard": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
    "v33_mainboard_tp3": {
        "universe": "mainboard_only",
        "tp_pct": 0.03,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]