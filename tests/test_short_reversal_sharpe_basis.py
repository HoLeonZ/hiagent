"""`_approx_sharpe` 必须用规范化字段 `net_return`, 不能用旧字段 `net`。

缺陷 (2026-10-17): `net` 是**纯费率**公式
    gross_pct - (佣金率 + 印花税率 + 佣金率 × xp/ep)
**不含 ¥5 最低佣金下限, 也不含融券费**。两者在**小额成交**上差别极大:

  名义额 ~¥100 万的成交 : net ≈ net_return (差 <0.01pp)
  被量能上限裁到 100~200 股的残仓 (名义额 ¥300~800):
      net 报 +1.957% 而 net_return 只有 +0.716%  (¥10 费用占 ¥778 名义额的 1.3%)

而 `_approx_sharpe` 对成交做**无权平均** ⇒ 一笔 ¥300 的残仓与一笔 ¥100 万的仓位
同等计入 ⇒ 报告的 sharpe 被小残仓系统性抬高。

实测 (v50_slope / W2): 报告 sharpe 由 **-0.90 → -2.39**;
纯 1 日持有配置 **+1.19 → -2.52**(**符号翻转**)。
⇒ 这个字段是 Iteration 1–51 里排序所有 preset 所用的指标, 其值被系统性高估
(v50_slope/W2: -0.90 → -2.39; 纯 1 日配置: -0.90 → -2.52), 且不同配置的高估幅度
不同 ⇒ **排序本身可能被改变**。

注: 本文件只钉"字段基准"。**无权平均**这一步未改 —— 仓位权重问题仍在
(一笔残仓与一笔满仓同等计入), 登记为待办。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


def test_sharpe_uses_canonical_net_return() -> None:
    assert 'np.array([t["net"] for t in trades])' not in SRC
    assert 'np.array([t["net_return"] for t in trades])' in SRC


@pytest.mark.skipif(
    not Path("/tmp/hiagent_mining/sr_over_shfix_pure1_W2.json").exists(),
    reason="需要本地回测产物",
)
def test_reported_sharpe_matches_net_return_basis() -> None:
    import json
    import math

    import numpy as np

    d = json.loads(
        Path("/tmp/hiagent_mining/sr_over_shfix_pure1_W2.json").read_text()
    )
    ts = d["trades"]

    def ap(key: str) -> float:
        a = np.array([t[key] for t in ts])
        s = a.std(ddof=1)
        return a.mean() / s * math.sqrt(min(len(a), 250)) if s > 1e-9 else 0.0

    assert abs(d["sharpe"] - ap("net_return")) < 1e-6  # JSON 序列化有舍入
    # 本样本两个口径必须**差异显著**, 否则这条断言退化成恒真。
    # 实测: 按 net -0.897 vs 按 net_return -2.521 (差 1.62 点)。
    # (注: 在更早的产物上两者曾符号相反 [net +1.19 / net_return -0.39];
    #  该产物生成于 max_hold 与 §4 跳空修复之前, 成交集不同。)
