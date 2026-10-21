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

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


def test_sharpe_uses_canonical_net_return() -> None:
    assert 'np.array([t["net"] for t in trades])' not in SRC
    assert 'np.array([t["net_return"] for t in trades])' in SRC


# ⚠️ 2026-10-19 (§13.20): 这里原有 `test_reported_sharpe_matches_net_return_basis`
# —— 读 `/tmp/hiagent_mining/sr_over_shfix_pure1_W2.json`, 断言 `sharpe` 能用 `net_return` 口径复现。
# **已删除**, 两个理由 (第二个才是决定性的):
#
#  ① **重复**: 同一性质已由**每次真跑回测**的守常驻覆盖 ——
#     `tests/test_metrics_self_consistency_4engine.py::_check_all` **第 ④ 条**,
#     且第 ④ 条**更强**: 它按**引擎自己声明的**基准复算并且直接断言,
#     而本臂只按 `net_return` 硬编码。skip 条件是 `/tmp` 产物存在 ⇒ 换机器就静默跳过。
#
#  ② ⚠️ **它的注释承诺了一条它没有的断言** (这条值得单独记, 见 §13.20(c)):
#     原第 59-63 行写着
#         "# 本样本两个口径必须**差异显著**, 否则这条断言退化成恒真。
#          # 实测: 按 net -0.897 vs 按 net_return -2.521 (差 1.62 点)。"
#     —— 而**下面没有任何 `assert`**。注释在**描述**一条非退化前置条件,
#     **代码里没有它**。⇒ 这条断言**本来就可能是恒真的**, 而注释让人以为不是。
#
#     **这正是 §13.19 查的那个形态的第三变体**:
#       * §13.19: **条件恒真**的 skip ⇒ 永远不跑;
#       * 作者三次注入 (§13.18(c)): **断言看着在、其实没被执行到**;
#       * **本条**: **注释看着有断言, 代码里没有** —— 守卫的**说明书**与**实体**不一致。
#     兄弟文件 `test_short_reversal_win_rate_basis.py` 里**同一个位置**是真的有
#     `assert abs(by_pnl - by_net) > 1e-6` 的 ⇒ 两边不对称, 是抄写时掉的。
