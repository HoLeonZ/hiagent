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

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


def test_engine_does_not_use_legacy_net_for_wins() -> None:
    assert 'if t["net"] > 0' not in SRC
    assert 't["net_pnl"] > 0' in SRC


def test_engine_does_not_average_legacy_net() -> None:
    assert 'np.mean([t["net"] for t in' not in SRC
    assert 'np.mean([t["net_return"] for t in' in SRC


# ⚠️ 2026-10-19 (§13.20): 这里原有 `test_reported_win_rate_matches_the_canonical_field`
# —— 读 `/tmp/hiagent_mining/sr_over_winfix_cap50_W2.json`, 断言 `win_rate` == (net_pnl>0) 占比。
# **已删除**: 同一性质已由**每次都真跑一次回测**的守常驻覆盖 ——
#   `tests/test_metrics_self_consistency_4engine.py::_check_all` 第 ③ 条,
#   (该断言经 §6 双向验证: chase_up 注入 `win_rate × 0.5` ⇒ 红)。
# 而本臂的 skip 条件是 **`/tmp` 产物存在** ⇒ 换台机器 / 清一次 `/tmp` 就**静默跳过**,
# 在 `-rs` 里与"合法的缺库 skip"向量完全相同。**两个守卫看起来是两道, 实际只有一道在跑。**
#
# **但它有一样东西是第 ③ 条没有的, 记在这里而不是丢掉** (§13.20(b)):
#   第 54 行那条 `abs(by_pnl - by_net) > 1e-6` —— **非退化前置条件**。
#   第 ③ 条本身**没有**这个前提: 若某窗口上两个口径恰好一致, 它是**恒真**的。
#   ⇒ 这是一个**已知的、被登记的空转口子**, 不在本文件里修 (修它需要选窗口 = 口径选择)。
