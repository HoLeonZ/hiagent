"""§1 修正: 浮动止损的止损位只能用**截至上一根 bar** 的信息构造。

缺陷 (2026-10-17 发现并修):
    旧实现
        lowest = min(pos["lowest_price"], low)   # 用**本 bar 的 low** 定出止损位
        ...
        elif high >= sl_p:                       # 又用**本 bar 的 high** 判触发
    两者同处一根 bar, 等价于假设"当日最低价出现在最高价之前" —— 而日线数据不
    提供这个次序。随着 trailing_stop_pct → 0, 成交价趋近当日最低价, 于是指标
    **单调**改善、**无拐点** —— 这是在区间内取最大有利偏移, 不是优势。
    (原此处列了当时实测的一串 Calmar 数值; 那些数与下面的 60.1/51.0 同属
     §4 修正前的代码状态, 已按 §7 删除 —— **缺陷的指纹是"单调且无拐点"这个形状,
     不需要那串数字**。)

修法: 触发判定用 `prev_lowest` (截至上一根 bar 的最低), 本 bar 的 low 只在出场
判定之后并入跟踪价。悲观方向, 与 §4「同一 bar 内不确定次序时取最坏情形」同精神。

本文件是**纯结构**钉桩 (2026-10-19 §13.20 更正 —— 原有一条"行为臂"用真实回测
锁定量级, 已删除, 理由见文件末尾的详注):
  - 结构断言锁定因果顺序 (防止有人把 min(...) 挪回判定之前)。

⚠️ **并更正本文件曾经写下的一个数字**: 原文说"修好后 v73 在 W2 上的 Calmar
从 60.1 降到 51.0, 即该缺陷虚增了约 18% 的风险调整收益"。
**这两个数都已作废** —— 它们量自 **§4 跳空成交口径修正之前**的代码状态,
而那次修正之后 `short_reversal` 整族的优势被判为填充口径的产物 (§4 / §6.1–§6.5),
**旧数字全部作废**。在**当前**代码上跑同一预设/窗口 (v73_trailing, W2):
`cagr -0.0960 / max_dd 0.3315 / Calmar -0.290` —— 与 51.0 差两个数量级、符号相反。
**§7: 不能由"当前代码 + 一条命令"重新生成的数字, 一律删掉。**
"""
from __future__ import annotations

import re
from pathlib import Path

ENGINE = Path(__file__).parent.parent / "short_reversal" / "replay_strategy_v3.py"
SRC = ENGINE.read_text(encoding="utf-8")


def test_trailing_trigger_uses_previous_bar_low() -> None:
    """止损位必须由 prev_lowest (截至上一根 bar) 构造, 不能用本 bar 的 low。"""
    assert "prev_lowest = pos[\"lowest_price\"]" in SRC, (
        "浮动止损必须显式取上一根 bar 的 lowest_price 作为止损位输入"
    )
    assert "trail_p = prev_lowest * (1 + self.p.trailing_stop_pct)" in SRC, (
        "止损位必须由 prev_lowest 构造 —— 用本 bar 的 low 是 §1 within-bar 缺陷"
    )


def test_no_same_bar_low_updates_the_stop() -> None:
    """禁止 `lowest = min(pos['lowest_price'], low)` 出现在出场判定之前。"""
    assert 'lowest = min(pos["lowest_price"], low)' not in SRC, (
        "本 bar 的 low 不得参与本 bar 的止损位构造 (that is the within-bar look-ahead)"
    )


def test_tracking_low_is_updated_only_after_the_exit_decision() -> None:
    """跟踪最低价的更新必须排在 `_close(...)` 之后 (即出场判定之后)。"""
    close_at = SRC.index('self._close(d, price, reason)\n            return')
    update_at = SRC.index('"lowest_price": min(prev_lowest, low)')
    assert update_at > close_at, (
        "跟踪最低价必须在出场判定之后更新, 否则下一根 bar 会用到本 bar 的信息"
    )


def test_trailing_still_off_by_default() -> None:
    """默认必须关闭 —— 该机制是 opt-in, 不得静默改变既有 preset。"""
    m = re.search(r"trailing_stop_pct=([0-9.]+)", SRC)
    assert m and float(m.group(1)) == 0.0


# ⚠️ 2026-10-19 (§13.20): 这里原有**行为臂** `test_corrected_v73_is_not_the_inflated_number`
# (断言 `calmar = cagr/max_dd < 58.0`)。它经历了三步, 三步都值得记:
#
#  第 1 步 —— **它在正常情形下从不运行**: 一个测试里"产物在哪"有**三个互不相同的答案** ——
#    ① `skipif` 查 `short_reversal/results/`;
#    ② 体内**又**嵌了一个 `pytest.skip`;
#    ③ 实际读 `/tmp/hiagent_mining/sr6/fix_v73.json`。
#    ⇒ 与 §13.19 同形态: 换台机器 / 清一次 `/tmp` 就静默跳过, 在 `-rs` 里与"合法的缺库 skip"向量相同。
#
#  第 2 步 —— 我把它**改成真跑一次回测** (预设与窗口沿用原产物自己记录的
#    `v73_trailing` / 2024-10-08..2026-09-29, 阈值 58.0 原样保留), 以为这样就修好了。
#    **实测结果否定了这个修法**:
#        旧产物 (max_dd 修复前):  cagr +1.8046  max_dd 0.0354  Calmar  50.97  成交 6017
#        当前代码 (同一预设/窗口): cagr -0.0960  max_dd 0.3315  Calmar **-0.290**  成交 5727
#    ⇒ **差两个数量级, 且符号相反。**
#
#  第 3 步 —— 为什么差这么多, 以及为什么**必须删掉而不是重新标定**:
#    旧产物里的 `cagr = +1.80` 属于 **§4 跳空成交口径修正之前**的代码状态。
#    那次修正是把止损/止盈的成交价从**乐观方向**改成跳空后按开盘价成交 ——
#    修完之后 `short_reversal` **整族**的优势被判为"填充口径的产物"、**旧数字全部作废**
#    (§4 / §6.1–§6.5)。所以 `51.0` 与它要防的 `60.1` **是同一时代的一对数**,
#    两者都已被取代 **⇒ `58.0` 这个阈值今天在**任何**代码状态下都不再可及**
#    (当前实测 -0.29, 距 58 有两个数量级)。
#    **一个"永远满足"的断言, 与 §13.19 的"永远不跑"是同一个东西的两种死法。**
#
#  第 4 步 —— 这一节真正的新发现 (§13.20(d)):
#    > **§13.19 查的是"条件恒真的 skip"; 本节这一条是"阈值来自一个已被取代的代码状态"。**
#    > 两者在 `-rs` 里**都长得像普通的 pass / skip** —— 而这第二种更隐蔽:
#    > 它**真的在跑、真的在断言**, 只是那个断言今天不可能失败。
#    **判据 (可复用): 一个数值阈值型守卫, 必须能说出"它上一次失败是什么时候、
#      以及在什么代码状态下" —— 若那个状态已经不存在, 这个守卫就只剩装饰。**
#
#  第 5 步 —— 删除之后**没有丢掉防护** (§1 由结构臂完整接管):
#    `test_trailing_trigger_uses_previous_bar_low` (钉 `prev_lowest = pos["lowest_price"]`
#    与 `trail_p = prev_lowest * (1 + ...)`)、`test_no_same_bar_low_updates_the_stop`、
#    `test_tracking_low_is_updated_only_after_the_exit_decision` (钉更新顺序)。
#    **这三条对"本 bar 的 low 参与止损位构造"这个缺陷类是完备的** ——
#    理由是**任何**忠实的缺陷重引入都必然改动它们钉住的那三处字面文本:
#      * 想用本 bar 的 low 构造止损位 ⇒ 必须改 `trail_p = ...` 那行 ⇒ 红;
#      * 想改回 `lowest = min(pos["lowest_price"], low)` ⇒ 该子串覆盖 `prev_lowest = min(...)`
#        ⇒ 红;
#      * 想调换更新顺序 ⇒ 第三条红。
#    ⇒ **行为臂在这个缺陷类上是被结构臂严格支配的**: 更贵 (7 分钟 vs 毫秒) 而覆盖面是子集。
