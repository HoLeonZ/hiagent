"""§2 Single-Bullet: 并发容量界必须在**运行时**成立 —— 两个 pandas 族 (§13.165)。

为什么有这条 (它补的是一个**已登记的能力边界**)
-----------------------------------------------
`tests/test_single_bullet_capacity_gate_4engine.py` 是**纯文本扫描器** (按正则找
`len(positions) >= max_positions` 式的行) —— **它证明不了运行时并发 ≤ N**。
§13.161(i) 把这条能力边界登记为「**有读点 ≠ 有界**」, 并且那一节用**真实回测**量到
`short_reversal` 在 N=1 下并发峰值就是 4 (N=2 → 18, N=4 → 28)。
⇒ 本节给**两个 pandas 族**补上运行时判据 (它们便宜: 直接驱动 `simulate_portfolio`)。

判据
----
同一根 bar 上放 **K=3** 个候选 (score 3/2/1), 只动 `max_positions`:
* **N ≥ K** ⇒ **三个都该被吃下** ← ★ **这是控制格**: 没有它, "永远只开 1 个" 也会看着像"闸门好使";
* **N = 1 / 2** ⇒ 实开并发必须是 **N**, 且**恰好是 score 最高的那 N 个** (§2 原文:
  "sort them by statistical conviction … and fill **strictly in that order**")。

⚠️ 合成面板的边界: 价格是**平的**、且**没有指标层** —— 本判据只碰"容量与顺序"这条不变量,
    不碰信号层 (那由 §13.147/§13.148 的截尾不变性守卫覆盖)。
⚠️ **未覆盖**: `short_reversal` / `cycle_price_action` 是 backtrader 路径, 廉价地构造一个
    "会真的发信号" 的合成面板**没做成** ⇒ 它们的运行时证据目前只有 §13.161 的**真实回测**读数
    (N=1 → 4), **不是守卫**。已登记, 不假装覆盖了。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

K = 3
CODES = ["A.SH", "B.SH", "C.SH"]
SCORES = [3.0, 2.0, 1.0]


def _synthetic() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-01", periods=8)
    panel = pd.DataFrame([
        dict(thscode=c, date=d, open=10.0, high=10.2, low=9.9, close=10.0, volume=1e6)
        for c in CODES for d in dates
    ])
    entries = pd.DataFrame({"date": [dates[2]] * K, "thscode": CODES, "score": SCORES})
    # ⚠️ `chase_up` 的 `simulate_portfolio` 对 entries **fail-fast 要求 11 个信号列**
    # (sub_signal_type / sig_* / atr_pct) —— uptrend 不需要。这是**契约更严**, 不是缺陷:
    # 缺列时报的是 `ValueError: entries 缺少列: [...]` (响亮失败), 补上即可。
    for col, val in (("sub_signal_type", "syn"), ("sig_close", 10.0), ("sig_ma20", 10.0),
                     ("sig_ma60", 10.0), ("sig_ret1", 0.0), ("sig_breakout_score", 0.0),
                     ("sig_momentum_score", 0.0), ("sig_macross_score", 0.0),
                     ("sig_mom120", 0.0), ("sig_amount60", 1e7), ("atr_pct", 0.03)):
        entries[col] = val
    return panel, entries


def _drive(fam: str, n: int) -> list[str]:
    """跑一次合成的容量实验, 返回**被吃下的候选 (按 score 降序)**。"""
    mod = __import__(f"{fam}.portfolio", fromlist=["simulate_portfolio"])
    panel, entries = _synthetic()
    trades, _ = mod.simulate_portfolio(
        entries, panel, tp_pct=5.0, sl_pct=0.5, max_hold=10, max_positions=n,
        start_date="2024-01-01", end_date="2024-01-10",
        # ⚠️⚠️ **必须让现金不成为约束**, 否则本判据测的是"钱不够"而不是"闸门"。
        # 第一版用**默认 sizing** (`equal`, pf=1.0) ⇒ 第一个候选 all-in 吃光现金 ⇒
        # 后面的候选**因为没钱**而进不来 ⇒ **把闸门整段抽掉, 判据照样全绿** (实测)。
        # 两个族的 `kelly` 分支都是 `cash × kelly_fraction` ⇒ 用小 fraction 让每笔很小。
        # (`chase_up` **没有 `position_fraction` 键**, 只有 kelly_fraction ⇒ 用 kelly 才统一。)
        position_sizing="kelly", kelly_fraction=0.2,
    )
    df = pd.DataFrame(trades)
    if df.empty:
        return []
    # 同日同批 ⇒ 按信号里的 score 降序还原"被选中的顺序"
    order = {c: s for c, s in zip(CODES, SCORES)}
    return sorted(df["thscode"].unique().tolist(), key=lambda c: -order[c])


@pytest.mark.parametrize("fam", ["uptrend_pullback", "chase_up"])
def test_control_all_candidates_are_taken_when_capacity_is_ample(fam: str) -> None:
    """★ 控制格: N=K 时必须**三个都吃下** —— 否则下面的"恰好 N 个"什么也没证明。"""
    got = _drive(fam, K)
    assert len(got) == K, (
        f"{fam}: max_positions={K} 而同日有 {K} 个候选, 却只开了 {len(got)} 个 "
        f"({got}) ⇒ 引擎**本来**就不会开满 ⇒ 本文件的容量判据是空转的。"
    )


@pytest.mark.parametrize("fam", ["uptrend_pullback", "chase_up"])
@pytest.mark.parametrize("n", [1, 2])
def test_runtime_concurrency_is_bounded_by_max_positions(fam: str, n: int) -> None:
    """§2: 运行时实开并发必须**恰好**是 `min(N, K)`, 且是 score 最高的那 N 个。"""
    got = _drive(fam, n)
    expect = CODES[:n]                     # CODES 已按 score 降序
    assert got == expect, (
        f"{fam}: max_positions={n}, 同日 {K} 个候选 ⇒ 期望**恰好** {expect} "
        f"(§2: 按 conviction 排序、严格照序成交), 实测 {got}\n"
        f"⇒ 要么并发界没被守住 (开多了), 要么**成交顺序**没按 conviction。"
    )
