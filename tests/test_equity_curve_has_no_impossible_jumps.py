"""§0/§3: 权益曲线的单日变动不得超过 **A 股涨跌停的物理界** (§13.114, 2026-10-19)。

## 修之前
`uptrend_pullback/portfolio.py` 的市值用**前复权价** (`pidx[code]["close"]`) 去减
**raw** 的 `pos["entry_price"]` —— **两个价源相减** (§3 明文要求市值用 raw)。
持仓跨除权日时前复权价按复权因子**阶梯跳变**, 而 raw 入场价不动
⇒ 权益曲线出现**物理上不可能**的单日跳变: 实测最高 **+252.78%**, **14/244** 天超 ±10%。

**后果**: 当前最优的中位 Sharpe 由 **0.6208** 掉到 **0.0036** (↓170×) ——
**那个 0.62 几乎全部是这处违反的产物。**

## 本文件的判据 (**物理界, 不依赖任何实现细节**)
多头、无杠杆、单票单日最多 ±10% ⇒ **组合单日权益变动 ≤ ±10% × 总仓位权重 ≤ ±10%**。
⇒ 这条判据**本来就会抓到本节这个洞**, 且它与"Sharpe 怎么算"无关。

## ⚠️ 为什么把判据写成"物理界"而不是"Sharpe 应当自洽"
因为后者需要一个口径; 而"权益一天涨了 253%"是**在任何口径下都错**的事实 (§13.114(e))。
§13.9 的那条: **"被污染"是关于**数据**的事实; "因此结论不能用"是关于**度量**的判断。**
这里量的是前者。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 主板 ±10%; 留一点容差 (撮合/复权边界), 但远小于观测到的 +253%
LIMIT_BOUND = 0.105


def _db_available() -> bool:
    try:
        from hiagent_config import DB_PATH
    except Exception:
        return False
    return Path(str(DB_PATH)).exists()


@pytest.mark.skipif(not _db_available(), reason="本地 DB 缺失")
@pytest.mark.parametrize("window", [("2017-09-01", "2018-09-01"), ("2018-09-01", "2019-09-01")])
def test_uptrend_equity_has_no_impossible_daily_jumps(window) -> None:
    """**行为式**: 真的跑一次, 量权益曲线的单日变动。"""
    from uptrend_pullback.backtest import run_backtest
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.presets import get_preset
    from uptrend_pullback.signals import compute_indicators
    from uptrend_pullback.universe import load_universe
    from hiagent_config import DB_PATH

    w0, w1 = window
    uni = set(load_universe("mainboard_only", DB_PATH))
    panel = compute_indicators(load_panel(DB_PATH, w0, w1, universe=uni))
    r = run_backtest(get_preset("v33_long_reverse_v22"), w0, w1, DB_PATH, panel_ind=panel)
    e = r["equity"]["equity"].to_numpy(dtype=float)
    rets = np.diff(e) / e[:-1]
    worst = float(np.abs(rets).max())
    n_bad = int((np.abs(rets) > LIMIT_BOUND).sum())
    assert n_bad == 0, (
        f"§0/§3: 权益曲线在 {w0}..{w1} 上有 **{n_bad} 天**的单日变动超过 {LIMIT_BOUND:.1%} "
        f"(最大 {worst:.2%})。\n"
        f"⇒ 多头 + 无杠杆 + A 股 ±10% 涨跌停 ⇒ **组合单日权益变动有物理上限**。\n"
        f"最可能的来源: **市值与入场价用了不同价源** (前复权 vs raw) —— §3 要求市值用 raw。\n"
        f"⚠️ 这条判据不依赖任何实现细节, 也不依赖 Sharpe 的口径。"
    )


def test_the_bound_is_actually_binding_not_vacuous() -> None:
    """反空转: 证明这条界**真的在**判, 不是恒真。

    造一条含 +253% 跳变的序列 ⇒ 同一个判据必须**失败**。
    """
    fake = np.array([1.0, 1.01, 3.57, 3.58])       # 中间一跳 +253%
    rets = np.diff(fake) / fake[:-1]
    assert int((np.abs(rets) > LIMIT_BOUND).sum()) == 1, (
        "反空转失败: 含 +253% 跳变的序列竟未触发判别 ⇒ 本判据恒真。"
    )
