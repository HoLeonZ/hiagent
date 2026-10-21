"""§2 双式记账: 恒等式 `末值 = 初值 + Σ net_pnl` 必须在**运行时**成立 (§13.172)。

为什么有这条 (§13.130 → §13.170 → §13.171 的固化)
-------------------------------------------------
§13.130(b) 立过这条恒等式, 并**在 uptrend 上 5/5 逐元验证**; 它撑起一个**方法**:
> 对 `max_positions=1`, 「去掉最好 k 笔」是**精确减法**, 不是重跑。

§13.170 把它推到别的族 ⇒ **`short_reversal` 上 6/6 格全部为正** (+6,855 … +16,251);
§13.171 把差**定位到现金侧**, 并给出**两个具名成因**:
* **①`entry_fee` 被"锁"而不被"扣"** —— 入场 `reserve_for_entry(notional+entry_fee)` 只是搬进
  `locked_margin`, 平仓 `released = entry_cost − margin_fees_paid` ⇒ **原额回到 free_cash**
  ⇒ 财富侧**从未真正支出**这笔费, 而台账扣了它;
* **②每日融券利息** —— `_charge_margin_fees` 逐 bar 扣 `size×ep×margin_rate/365` 并**直接减
  `locked_margin`** (真实财富) ⇒ 却**不在 `net_pnl` 里**。
⇒ 逐笔恒等式应为 `差 ≈ entry_fee − margin_fees`, 实测**解释 ~94%** (残差 ~800 未钉住)。

⚠️ **方向单一**: 6/6 格都是"权益更好" ⇒ **报出的收益永远偏乐观** (每窗 ≈ 初始资金的 1.2%–1.6%)
   —— 这正是 §0 最忌讳的形状。
⚠️ **两族精确、一族不闭合** ⇒ 族内不对称。修法**两侧都改结果** (且须先定哪一侧是权威口径)
   ⇒ 按授权**只登记不修**; 本测试就是那次登记的**可执行形态**: 精确的族**断言 0**,
   不闭合的族 `xfail(strict)` **带实测值** —— 一旦哪侧被修好, XPASS 会立刻叫人回头看。

⚠️ 成本: 两个 pandas 族用**一年窗** (各 ~3.5 秒); `short_reversal` 用**40 只名册** (~4.3 秒,
   2 笔成交就够 —— 这是**记账**性质, 不是统计性质)。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hiagent_config import DB_PATH  # noqa: E402

W0, W1 = "2023-10-01", "2024-09-30"          # 便宜的一年窗 (实测: uptrend 17 笔 / chase 9 笔)
CHASE = "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082"
TOL = 1e-6


def _diff(engine_mod, preset: str, w0: str, w1: str) -> tuple[float, int]:
    p = dict(engine_mod.get_preset(preset)) if hasattr(engine_mod, "get_preset") else None
    if p is None:
        from importlib import import_module
        p = dict(import_module(f"{engine_mod.__name__.split('.')[0]}.presets").get_preset(preset))
    assert int(p["max_positions"]) == 1, (
        "本恒等式的前提是 `max_positions=1` (§13.130(b)) —— 换 preset 就要重看这条断言。"
    )
    r = engine_mod.run_backtest(p, w0, w1, DB_PATH)
    t = pd.DataFrame(r["trades"])
    s = float(t["net_pnl"].sum())
    fin = float(r["metrics"]["final_equity"])
    return fin - engine_mod.INITIAL_CAPITAL - s, len(t)


@pytest.mark.skipif(not Path(DB_PATH).exists(), reason="本地 DB 不在 ⇒ §6: 跳过而不是报错")
@pytest.mark.parametrize("fam,preset", [
    ("uptrend_pullback", "v33_long_reverse_v22"),
    ("chase_up", CHASE),
])
def test_ledger_identity_is_exact_2long(fam: str, preset: str) -> None:
    """两个 pandas 族: `末值 − 初值 − Σ net_pnl` 必须**逐元为 0**。"""
    eng = importlib.import_module(f"{fam}.backtest")
    d, n = _diff(eng, preset, W0, W1)
    assert n >= 5, f"{fam}: 只有 {n} 笔成交 ⇒ 台账太空, 这条恒等式测不出东西 (反空转)"
    assert abs(d) <= TOL, (
        f"{fam} (`{preset}`, {W0}..{W1}): 恒等式破了 —— 差 = {d:,.4f}\n"
        f"§2 双式记账: 权益与逐笔台账必须闭合。参见 §13.170/§13.171。"
    )


@pytest.mark.skipif(not Path(DB_PATH).exists(), reason="本地 DB 不在 ⇒ §6: 跳过而不是报错")
@pytest.mark.xfail(
    strict=True,
    reason="§13.170/§13.171 登记在案: 本族的两套记账**记的不是同一组项目** —— "
           "`entry_fee` 被锁而不被扣 (+), 每日融券利息扣了财富却不在台账里 (−) "
           "⇒ 差值 6/6 格**全为正** (权益永远比台账乐观, 每窗 ≈ 初始资金的 1.2%–1.6%)。 "
           "修法两侧都改结果且须先定权威口径 ⇒ 只登记不修; 修好后这条会 XPASS(strict) 叫人回头看。",
)
def test_ledger_identity_is_exact_short_reversal(monkeypatch) -> None:
    """`short_reversal`: 同名判据, 预期**不成立** (登记在案)。"""
    import short_reversal.engine as eng
    from short_reversal.presets import PRESETS

    assert int(PRESETS[_SR_PRESET]["max_positions"]) == 1, "前提: max_positions=1"
    full = eng.load_universe_asof("mainboard_only", W0_SR, DB_PATH)
    monkeypatch.setattr(eng, "load_universe_asof",
                        (lambda sub: (lambda *a, **k: sub))(sorted(full)[:_SR_CODES]))
    r = eng.run_backtest_v3(_SR_PRESET, W0_SR, W1_SR, DB_PATH)
    t = pd.DataFrame(r["trades"])
    d = float(r["final_capital"]) - eng.INITIAL_CAPITAL - float(t["net_pnl"].sum())
    assert len(t) >= 1, "台账为空 ⇒ 测不出东西"
    assert abs(d) <= TOL, (
        f"`short_reversal` (`{_SR_PRESET}`, 名册 {_SR_CODES} 只, {W0_SR}..{W1_SR}): "
        f"恒等式差 = **{d:+,.2f}** ⇒ §2 的双式记账在本族**没有闭合** (§13.170/§13.171)。"
    )


_SR_PRESET = "v35_agg_pctchg_04_09"     # 声明 max_positions=1
_SR_CODES = 40                          # 实测 4.3 秒, 2 笔成交 ⇒ 差 +1,058 (够判定)
W0_SR, W1_SR = "2024-10-08", "2026-09-18"


# ---------------------------------------------------------------------------
# §13.180: `short_reversal` 的**解析式**恒等式 —— 不闭合**不是**谜
# ---------------------------------------------------------------------------
_SR_MARGIN_RATE_DEFAULT = 0.08


@pytest.mark.skipif(not Path(DB_PATH).exists(), reason="本地 DB 不在 ⇒ §6: 跳过而不是报错")
def test_short_reversal_gap_equals_entry_fee_minus_margin_fee(monkeypatch) -> None:
    """**解析式**: `差 == Σ entry_fee − Σ margin_fees_paid` (逐元, 不是"~94%")。

    §13.171 把差拆成两个具名成因 (① `entry_fee` 被锁而不被扣; ② 每日融券利息扣了财富却不进台账),
    但只对到 ~94% —— 那个 6% 我一度当成"引擎里还有第三件事"。
    §13.180 用**只观测**的 spy 量到**实际**的 `margin_fees_paid` ⇒ 残差 **0**;
    而 6% 的来源是**我当时拿 `hold_days` 去估** Σmargin (实测每笔平均收 **1.07** 次, 而 hold_days 均值 1.00)。

    ⇒ 本测试把那条关系**钉成等式**: 它**应当是绿的** (与上面那条 `xfail` 的"不闭合"**不矛盾** ——
      不闭合说的是"权益 ≠ 台账"; 这一条说的是"两者的差**恰好等于**两项之和")。
    """
    import backtrader as bt
    import short_reversal.engine as eng
    import short_reversal.replay_strategy_v3 as R
    from short_reversal.presets import PRESETS

    assert int(PRESETS[_SR_PRESET]["max_positions"]) == 1, "前提: max_positions=1"

    seen: dict = {}
    orig_close = R.Phase3V3Strategy._close

    def spy(self, d, price, reason):
        # ⚠️ §13.182(d) 的教训: **两个量都从引擎读回来**, 不要用"我以为我注入成了什么"。
        #   `entry_fee` 与 `margin_fees_paid` 都躺在将平仓的 pos 里 ⇒ 一次捕获两个成因。
        pos = self._holds.get(d._name)
        if pos is not None:
            seen[(str(bt.num2date(d.datetime[0]).date()), d._name)] = (
                float(pos.get("entry_fee", 0.0)), float(pos.get("margin_fees_paid", 0.0)))
        return orig_close(self, d, price, reason)

    monkeypatch.setattr(R.Phase3V3Strategy, "_close", spy)
    full = eng.load_universe_asof("mainboard_only", W0_SR, DB_PATH)
    monkeypatch.setattr(eng, "load_universe_asof",
                        (lambda sub: (lambda *a, **k: sub))(sorted(full)[:_SR_CODES]))
    r = eng.run_backtest_v3(_SR_PRESET, W0_SR, W1_SR, DB_PATH)
    monkeypatch.setattr(R.Phase3V3Strategy, "_close", orig_close)

    trades = pd.DataFrame(r["trades"])
    gap = float(r["final_capital"]) - eng.INITIAL_CAPITAL - float(trades["net_pnl"].sum())
    # ★ 两个成因**各自**从引擎读回 (§13.182 的教训: 不用"我以为"), 因此**不需要任何注入" ———
    #  也就绕开了"任何注入都会改入场集合"(§13.182(c): 2 笔 → 7 笔) 那个混淆。
    fees_engine = sum(v[0] for v in seen.values())      # 成因①的载体: entry_fee (锁而不扣)
    margin = sum(v[1] for v in seen.values())           # 成因②的载体: 每日融券利息 (扣而不记)

    # 反空转: 两个成因都必须**非零** —— 否则等式退化成只含一项的弱式子, 本测试空转。
    assert seen, "spy 没抓到任何平仓 ⇒ 判据空转 (引擎的 _close 接口变了吗?)"
    assert fees_engine > 0, f"Σ entry_fee(引擎读回) = {fees_engine} ⇒ **成因①不在这一跑里**, 本测试空转"
    assert margin > 0, f"Σ margin_fees_paid(引擎读回) = {margin} ⇒ **成因②不在这一跑里**, 本测试空转"

    resid = gap - (fees_engine - margin)
    assert abs(resid) <= 1e-6, (
        f"§13.180/§13.182: 解析式不成立 —— 差 = {gap:,.4f}, "
        f"而 Σentry_fee(引擎读回) − Σmargin(引擎读回) = {fees_engine - margin:,.4f} "
        f"(残差 {resid:,.4f})\n"
        f"⇒ 两套记账之间的关系**变了**: 要么 §13.171 的两个成因不再完备 (出现了第三项), "
        f"要么引擎里这两个量有一个换了载体。\n"
        f"⚠️ 本判据的两个量**都从引擎读回**, 所以残差**不能再被解释成「我的模型不准」** (§13.182(d))。"
    )
