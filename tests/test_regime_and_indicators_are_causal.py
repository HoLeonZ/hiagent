"""§1: `compute_regime` 与 `compute_indicators` 必须**因果** —— 且这一点必须可执行。

## 为什么需要这条
`uptrend_pullback/regime.py` 的 docstring **声称**「无未来函数：T 日的 regime 只用 ≤T 的数据」。
而 `regime` 闸门是**当前最优的关键路径**上最承重的部件之一 (§6.3.5: 去掉它两窗口都深负)。
**一条只写在 docstring 里的 §1 断言, 和一个不响的守卫是同一种东西。**

## 判据 (标准做法, 不依赖任何内部实现细节)
**截尾不变性**: 把输入面板在第 T 天截断, 重算一遍。
若实现是因果的, 则**前 T 天的一切输出必须逐位不变**。
任何 `shift(-x)` / `bfill` / `center=True` / 全域统计 都会被这条判据抓住。

⚠️ 截尾必须从**尾部**截 (保留同一个起点):
`ew_index` 是 `cumprod`, **锚在面板首日** ⇒ 只从尾部截才能保证锚点不变。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _db_available() -> bool:
    try:
        from hiagent_config import DB_PATH
    except Exception:
        return False
    return Path(str(DB_PATH)).exists()


@pytest.fixture(scope="module")
def panel():
    if not _db_available():
        pytest.skip("本地 DB 缺失")
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.signals import compute_indicators
    from uptrend_pullback.universe import load_universe
    from hiagent_config import DB_PATH

    codes = set(load_universe("mainboard_only", DB_PATH))
    p = load_panel(DB_PATH, "2024-10-01", "2024-12-01", universe=codes)
    return compute_indicators(p)


def _truncate(panel: pd.DataFrame, keep_days: int) -> pd.DataFrame:
    days = np.sort(panel["date"].unique())[:keep_days]
    return panel[panel["date"].isin(days)].copy()


# ---------------------------------------------------------------------------
# compute_regime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("t", [80, 150, 220])
def test_compute_regime_is_causal(panel, t: int) -> None:
    """截尾不变性: 在第 t 天截断重算, 前 t 天的 regime 输出必须逐位不变。"""
    from uptrend_pullback.regime import compute_regime

    full = compute_regime(panel, ma_window=20, breadth_window=20, min_breadth=0.45,
                          require_rising=False)
    cut = _truncate(panel, t)
    part = compute_regime(cut, ma_window=20, breadth_window=20, min_breadth=0.45,
                          require_rising=False)

    assert len(part) == t, f"截尾后应有 {t} 天, 实为 {len(part)}"
    a = full.head(t).reset_index(drop=True)
    b = part.reset_index(drop=True)
    for col in ("ew_index", "ew_ma", "breadth_sm"):
        va, vb = a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float)
        same = (np.isnan(va) & np.isnan(vb)) | np.isclose(va, vb, rtol=0, atol=1e-12)
        bad = int((~same).sum())
        assert bad == 0, (
            f"§1: `compute_regime` 的 `{col}` **不是因果的** —— 在第 {t} 天截尾后, "
            f"前 {t} 天里有 {bad} 天取值变了。\n"
            f"⇒ 说明它用到了 T 之后的信息 (§1 前视)。"
        )
    assert (a["regime_ok"] == b["regime_ok"]).all(), (
        f"§1: `regime_ok` 在截尾后变了 ⇒ 闸门用到了未来数据。"
    )


@pytest.mark.parametrize("t", [150, 220])
def test_compute_indicators_is_causal(panel, t: int) -> None:
    """同一判据施加到 `compute_indicators` —— 它是**四族共用**的指标层。

    (本族人手一份; 这条是针对 `uptrend_pullback/signals.py` 的那一份。)
    """
    from uptrend_pullback.signals import compute_indicators

    cut = _truncate(panel, t)
    got = compute_indicators(cut)
    days = np.sort(panel["date"].unique())[:t]
    # ⚠️ §13.147: 本列表面是**硬编码的 10 个**, 而信号选择器
    # (`select_entries_v33_long_mirror`) 实际读的指标列**比它多 6 个** ——
    # `above_ma60_ratio` / `amount60` / `down_streak` / `macd_bar_prev` /
    # `macd_dea` / `macd_dif` 从未被截尾检验过。
    # ⇒ **一个只验了部分列的判据, 会让人以为"整个指标层已验"** ——
    #   这正是本册反复记的「判据的**作用域**弱于它声称的性质」。
    # 现按**选择器真正读的列**取 (ns 与 _select_inputs 交叉核对)。
    cols = [c for c in ("ma5", "ma20", "ma60", "ma120", "mom120", "atr_pct",
                        "above_ma20", "ret1", "prev_down_streak", "macd_bar",
                        # ↓ §13.147 补齐: 选择器读、而上面那 10 个没覆盖的
                        "above_ma60_ratio", "amount60", "down_streak",
                        "macd_bar_prev", "macd_dea", "macd_dif")
            if c in got.columns and c in panel.columns]
    assert cols, "找不到任何可比指标列 ⇒ 判据的扫描单位不存在 (那样本断言恒真)"
    a = panel[panel["date"].isin(days)].sort_values(["thscode", "date"]).reset_index(drop=True)
    b = got.sort_values(["thscode", "date"]).reset_index(drop=True)
    assert len(a) == len(b), f"行数不一致: {len(a)} vs {len(b)}"
    for c in cols:
        va, vb = a[c].to_numpy(dtype=float), b[c].to_numpy(dtype=float)
        same = (np.isnan(va) & np.isnan(vb)) | np.isclose(va, vb, rtol=0, atol=1e-9)
        bad = int((~same).sum())
        assert bad == 0, (
            f"§1: `compute_indicators` 的 `{c}` **不是因果的** —— 截尾后前 {t} 天里有 {bad} 个值变了。"
        )


def test_the_truncation_probe_actually_bites(panel) -> None:
    """★ 反空转: 证明这套判据**真的能抓到前视**。

    手法: 故意造一个**违规**的指标 (用了未来信息), 让它过同一套比对 —— 必须**不通过**。
    否则上面那些 `assert bad == 0` 可能只是在比"两个都正确的东西"。
    """
    from uptrend_pullback.regime import compute_regime

    t = 150
    cut = _truncate(panel, t)
    good = compute_regime(cut, ma_window=20, breadth_window=20, min_breadth=0.45,
                          require_rising=False)
    # 违规版: 用**未来**的天数做 breadth 的均值
    bad = good.copy()
    bad["breadth_sm"] = good["breadth_sm"].iloc[::-1].to_numpy()   # 尾部对调 ⇒ 必然不同
    va = bad["breadth_sm"].to_numpy(dtype=float)
    vb = good["breadth_sm"].to_numpy(dtype=float)
    same = (np.isnan(va) & np.isnan(vb)) | np.isclose(va, vb, rtol=0, atol=1e-12)
    assert not same.all(), (
        "反空转失败: 把序列**反转**后本判据竟然还认为相同 ⇒ 比对逻辑写错了, "
        "上面的因果断言不可信。"
    )
