"""§1: `chase_up` 的指标层**截尾不变** (§13.148)。

为什么单开一条
--------------
本仓唯一那条强因果性守卫 (`test_regime_and_indicators_are_causal.py`) **只 import 了
`uptrend_pullback` 的那一份** `compute_indicators` —— 而**每个族各有一份自己的指标层**。
⇒ `chase_up` 的指标层此前**只有弱覆盖** (禁用函数扫描: 无 `bfill`/`shift(-N)`/`center=True`),
  **没有截尾不变性检验**。

判据 (§13.105 的方法, 但**比全部列**, 不写硬编码列表)
----------------------------------------------------
把面板在第 T 天**从尾部**截断后重算, 因果实现必须让前 T 天的**每一列**逐位不变。

⚠️ **为什么不写硬编码列清单**: §13.147 —— 邻居那条守卫写死了 10 个列名, 而信号选择器读 16 个,
  于是 6 列**从未被验**, 且一个真实的 `macd_bar_prev` 前视能在它下面**静默通过**
  (已用注入证明)。本守卫因此**遍历 `compute_indicators` 产出的全部数值列**。

⚠️ **为什么必须从尾部截**: 任何 `cumprod`/`cumsum` 类的锚点都在面板首日 (§13.105 的教训)。

⚠️ **本判据可能失败** —— 已注入验证: 把 `signals.py` 里第一个 `rolling(w)` 改成
  `rolling(w, center=True)` ⇒ **8 列变红** (ma5/ma10/ma20/ma60/ma120/ma20_minus_ma60/…)。
  一条不可能失败的守卫等于没有守卫。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

W0, W1 = "2024-10-08", "2026-09-18"


@pytest.fixture(scope="module")
def panel():
    from chase_up.data import load_panel
    from chase_up.presets import get_preset
    from chase_up.signals import compute_indicators
    from chase_up.universe import load_universe

    from hiagent_config import DB_PATH

    p = get_preset(
        "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082"
    )
    uni = set(load_universe(p["universe"], DB_PATH, asof_date=W0))
    return compute_indicators(load_panel(DB_PATH, W0, W1, universe=uni))


@pytest.mark.parametrize("frac", [0.5, 0.75, 0.9])
def test_chase_indicators_are_causal(panel, frac: float) -> None:
    from chase_up.signals import compute_indicators

    dates = np.sort(panel["date"].unique())
    t = int(len(dates) * frac)
    T = dates[t - 1]
    got = compute_indicators(panel[panel["date"] <= T].copy())

    a = (panel[panel["date"].isin(dates[:t])]
         .sort_values(["thscode", "date"]).reset_index(drop=True))
    b = got.sort_values(["thscode", "date"]).reset_index(drop=True)
    assert len(a) == len(b), f"行数不一致: {len(a)} vs {len(b)}"

    bad: list[tuple[str, int]] = []
    n_cols = 0
    for c in panel.columns:
        if c in ("thscode", "date"):
            continue
        try:
            va = a[c].to_numpy(dtype=float)
            vb = b[c].to_numpy(dtype=float)
        except (TypeError, ValueError):
            continue          # 非数值列跳过
        n_cols += 1
        same = (np.isnan(va) & np.isnan(vb)) | np.isclose(va, vb, rtol=0, atol=1e-9)
        n_bad = int((~same).sum())
        if n_bad:
            bad.append((c, n_bad))

    assert n_cols >= 20, (
        f"只比较到 {n_cols} 列 —— 判据的扫描单位太窄, 这个绿是**虚的** (§13.147 的教训)"
    )
    assert not bad, (
        f"§1: `chase_up` 的 `compute_indicators` **不是因果的** —— "
        f"截到 {str(T)[:10]} (前 {t} 天) 时, 这些列变了: {bad}\n"
        f"⇒ 至少一列用到了 T 之后的信息。"
    )
