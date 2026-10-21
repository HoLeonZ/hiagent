"""报告必须披露"残仓污染"—— 一笔 ¥300 的残仓不得与一笔 ¥100 万的仓位同等计入。

缺陷 (2026-10-17, Iteration 62 发现自己也踩了):
`avg_pnl` 等指标是**无权**平均。实测 (v50_slope/W2):

    全部 170 笔       : avg_pnl = -0.9723%   t = -2.39
    剔除 63 笔残仓后  : avg_pnl = -0.2263%   t = -0.43
    而那 63 笔只占**名义额的 0.052%**

⇒ **无权平均会把一个不显著的结论变成"显著为负"。** 这不是风格问题, 它会改变结论。

修法 (加法式, 不改既有字段): 同时报出
  `avg_pnl_notional_weighted` —— 按名义额加权
  `micro_trade_count` / `micro_trade_notional_share` —— 残仓的数量与占比
让"两个数差多少、差在哪"直接写在产物里。

(注: 残仓从何而来 —— 量能上限 `max_volume_participation` 与现金闸门会把订单裁到
 100~200 股。它们是被其他规则正确裁出来的, 问题只在于**不该与满仓单同权**。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SRC = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
    encoding="utf-8"
)
# 需要**保留成交明细**的产物 (main.py 会把 trades 剥掉, 故用 sr_over 的)
ARTIFACT = Path("/tmp/hiagent_mining/sr_over_mw_n4_W2.json")


def test_engine_reports_the_weighted_average_and_micro_stats() -> None:
    for key in (
        '"avg_pnl_notional_weighted"',
        '"micro_trade_count"',
        '"micro_trade_notional_share"',
    ):
        assert key in SRC, f"metrics 必须报出 {key}"


def test_unweighted_average_is_unchanged() -> None:
    """既有字段不得被改动 (加法式修补)。"""
    assert '"avg_pnl": avg_pnl,' in SRC


@pytest.mark.skipif(not ARTIFACT.exists(), reason="需要本地回测产物")
def test_two_averages_differ_materially_and_agree_on_direction() -> None:
    d = json.loads(ARTIFACT.read_text())
    raw, w = d["avg_pnl"], d["avg_pnl_notional_weighted"]
    assert raw < 0 and w < 0, "本样本两者应为负"
    assert abs(raw - w) > 1e-3, (
        f"无权({raw:.6f}) 与加权({w:.6f}) 差异过小, 用例失去意义"
    )
    assert 0 < d["micro_trade_notional_share"] < 0.01, "残仓应占名义额的极小比例"
    assert d["micro_trade_count"] > 0


@pytest.mark.skipif(not ARTIFACT.exists(), reason="需要本地回测产物")
def test_weighted_average_matches_a_direct_recomputation() -> None:
    """行为层: 加权值必须等于用成交明细直接算出的 notional 加权平均。"""
    d = json.loads(ARTIFACT.read_text())
    ts = d["trades"]
    num = sum(t["entry_price"] * t["size"] * t["net_return"] for t in ts)
    den = sum(t["entry_price"] * t["size"] for t in ts)
    assert d["avg_pnl_notional_weighted"] == pytest.approx(num / den, rel=1e-9)
