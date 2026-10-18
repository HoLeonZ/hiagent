"""声明的产物必须真的产出: `equity_curve.csv` / `cash_walk.csv`。

缺陷 (2026-10-17): `main.py` 写这两个文件的开关是
    eq_rows = m.get("equity_curve")
    if eq_rows: _write_equity_curve(...)
而 `_metrics_from_holder()` **从不把 `holder["equity_curve"]` 拷进返回的 metrics**
⇒ 开关恒为假 ⇒ 两个文件**从未被写出**, 尽管注释写着 "§2/§3 Tick 51 GREEN"。
(strategy 一直在累积那串数据, 只是没人把它带出来。)

**发现过程本身值得记**: 本轮想核对 `max_dd` 与权益曲线是否一致, 结果短侧**根本没有
这份产物**; 我在同目录里读到了 **chase_up** 留下的同名文件 (两个引擎写**同一套列名**
`date,cash,position_value,total_equity,drawdown`), 于是把 chase_up 的 85.95% 回撤
当成了 short_reversal 的, 先报了一个错误的"不一致"。**文件名不携带引擎身份。**

更正后的事实 (用短侧自己的曲线): 报告 max_dd 72.61% **与曲线逐位一致**;
但 Sharpe 口径确实不同 —— 同一次运行 日口径(+0.2618) vs 报告逐笔(-2.3858)。
"""
from __future__ import annotations

from pathlib import Path

ENGINE = (Path(__file__).parent.parent / "short_reversal" / "engine.py").read_text(
    encoding="utf-8"
)


def test_metrics_carry_the_equity_curve() -> None:
    """metrics 必须带出 equity_curve —— 否则 main.py 的写盘开关恒为假。"""
    assert '"equity_curve": holder.get("equity_curve", [])' in ENGINE


# ⚠️ 2026-10-19 (§13.20): 这里原有第二条断言 `test_artifact_matches_reported_max_dd`,
# 它读 `/tmp/sr_iso3/equity_curve.csv` + `m.json` 并核对 `max_dd` == 曲线最大回撤。
# **已删除, 因为它被更新的守卫完全覆盖, 而它的 skip 条件让它在本机之外从不运行**:
#
#   * **覆盖它的守卫**: `tests/test_metrics_self_consistency_4engine.py` 里的 `_check_all`
#     第 ② 条 —— 每次都**真跑一次回测**, 用**它自己那条 NAV 序列**复算 `max_dd` 并断言相等。
#     同一性质, 但**不依赖 `/tmp`**, 因此在任何机器、任何时刻都真的会跑。
#   * **原断言的问题**: `/tmp` 是**设计上易失**的 (§7 的产物本地化)。它在我这台机器上此刻
#     存在, 于是会跑; 但**换一台机器、或清一次 `/tmp`, 它就静默跳过** ——
#     而 `-rs` 里的样子与"合法的缺库 skip"完全一样。
#     ⇒ 这正是 §13.19 那条的另一半: **不是"构造上永远跳过", 而是"在正常情形下永远跳过"**。
#   * **保留它的成本**: 会让人以为这条性质"有两个守卫", 实际只有一个在跑 ——
#     **覆盖面的假象比没有守卫更糟。**
#
# 本文件保留的 `test_metrics_carry_the_equity_curve` 是**结构臂**, 不依赖任何产物,
# 且在整套件里真的会跑 —— 它才是本文件的承重部分。
