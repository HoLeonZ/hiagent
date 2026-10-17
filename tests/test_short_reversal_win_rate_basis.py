"""`win_rate` / `avg_pnl` 必须按**规范化字段**算, 不能用旧兼容字段 `net`。

缺陷 (2026-10-17): `engine.py` 里
    wins = sum(1 for t in trades if t["net"] > 0)
    avg_pnl = mean([t["net"] for t in trades])
而 `net` 是**纯费率**公式 (`gross_pct - total_fee_ratio`), **不含 ¥5 最低佣金下限** ——
代码自己的 Round-29a 注释就写着 "only the per-trade `net` field is slightly optimistic
on tiny trades"。小额单 (notional < ¥20,000) 的下限约 ¥2.50-5.00/腿不进 `net`,
于是**真亏的单可能被记成胜**。

实测 (cap50 / W2): 845 笔里 3 笔两字段符号相反 ⇒ 报告 win_rate 高 0.6pp
(旧 0.542012 vs 新 0.536095)。

方向: **虚增** (第 6 项)。规范化字段 `net_pnl` / `net_return` 走含下限的 cash walk,
是权威口径 —— 这也是本仓库自己的 `core/trade_schema` 所声明的。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


def test_engine_does_not_use_legacy_net_for_wins() -> None:
    assert 'if t["net"] > 0' not in SRC
    assert 't["net_pnl"] > 0' in SRC


def test_engine_does_not_average_legacy_net() -> None:
    assert 'np.mean([t["net"] for t in' not in SRC
    assert 'np.mean([t["net_return"] for t in' in SRC


@pytest.mark.skipif(
    not Path("/tmp/hiagent_mining/sr_over_winfix_cap50_W2.json").exists(),
    reason="需要本地回测产物",
)
def test_reported_win_rate_matches_the_canonical_field() -> None:
    """报告的 win_rate 必须等于"按 net_pnl 判胜"的比例 (旧口径会差 0.6pp)。"""
    import json

    d = json.loads(
        Path("/tmp/hiagent_mining/sr_over_winfix_cap50_W2.json").read_text()
    )
    ts = d["trades"]
    by_pnl = sum(1 for t in ts if t["net_pnl"] > 0) / len(ts)
    by_net = sum(1 for t in ts if t["net"] > 0) / len(ts)
    assert abs(d["win_rate"] - by_pnl) < 1e-12, (
        f"报告 {d['win_rate']} 与 net_pnl 口径 {by_pnl} 不符"
    )
    assert abs(by_pnl - by_net) > 1e-6, "本用例需要两个口径确实不同的样本"
