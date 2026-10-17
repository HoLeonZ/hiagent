"""§4 做空可行性: **逐 bar** 的 ST/风险警示 (不可融券) 检查。

为什么必须逐 bar: A 股 ST/风险警示股涨跌停 ±5% 且不在融资融券名单 ⇒ 不可做空。
**静态宇宙过滤只剔掉约 2% 的成交** —— 因为该状态在窗口内随时间变化 (一只票可能在
窗口中途才被实施风险警示)。逐 bar 判定的命中率是 **7.1%** (v50_slope, W2 实测:
140 笔中剔掉 10 笔)。

判据: 信号日之前 `st_lookback_bars` 根 bar 内出现过"封死 ±5%" ——
`|单日涨跌幅| ≈ 5%` 且 `high == low` (全天一个价)。非风险警示的主板股几乎不可能
出现 `high == low`, 故信噪比很高。PIT: 只回看已发生的 bar。

**性能影响 (据实记录, 不夸大)**: 该过滤**不是绩效杠杆** —— W2 上 CAGR +30.5% → +47.2%、
Calmar 0.8 → 1.4, 但 IND 上 CAGR -25.7% → -36.8% (更差)、HOLD 基本不变。
它的价值在于**让回测只算下得出去的成交**, 而不是让策略更好。
"""
from __future__ import annotations

from pathlib import Path

from short_reversal.replay_strategy_v3 import Phase3V3Strategy as S

SRC = (Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py").read_text(
    encoding="utf-8"
)


def test_filter_is_opt_in_and_off_by_default() -> None:
    assert S.params.require_shortable_st_filter is False
    assert S.params.st_lookback_bars == 60


def test_check_only_looks_backwards() -> None:
    """PIT 结构断言: 检查函数只使用负偏移 (-1 及更早), 不得读当日高开低收。"""
    i = SRC.index("def _suspected_st_now")
    body = SRC[i:SRC.index("def _conviction", i)]
    assert "for i in range(1, upper + 1)" in body, "回看必须从 -1 开始 (不含当日)"
    for bad in ("d.high[0]", "d.low[0]", "d.close[0]", "d.open[0]"):
        assert bad not in body, f"PIT 违规: {bad} 读到了当日"
    assert "d.close[-i - 1]" in body, "需与再前一根 bar 比较才能算当日涨跌幅"


def test_sealed_band_matches_five_percent() -> None:
    """判据必须锚在 ±5% 停板, 且要求 high == low (封死)。"""
    i = SRC.index("def _suspected_st_now")
    body = SRC[i:SRC.index("def _conviction", i)]
    assert "high" in body and "== lo" in body.replace("hi == lo", "hi == lo")
    assert "0.05" in body, "停板幅度必须锚在 5%"


def test_engine_plumbs_both_keys() -> None:
    eng = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert 'require_shortable_st_filter=cfg.get("require_shortable_st_filter", False)' in eng
    assert 'st_lookback_bars=cfg.get("st_lookback_bars", 60)' in eng
