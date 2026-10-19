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
