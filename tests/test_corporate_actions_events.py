"""§3 事件化公司行为守卫（审计 P2-10，2026-10-15）。

CLAUDE.md §3 逐字要求：
  - "Cash dividends must explicitly trigger a physical cash deposit into
     `Free_Cash`."
  - "Stock splits must trigger an atomic multiplier adjustment to
     `Position_Quantity` and `Average_Cost`."

为什么必须有：执行域是**原始价**，除权日 raw 价向下跳空。没有事件源时，那个缺口
被当成真实盈亏 —— 长仓系统性少计分红。实测 preset `chase_v1_atr_tp4_sl1`
(2025-09-19..2026-09-19) 少计 **¥4,340.00**（¥1M 起始资金）。

本文件锁定：
  1. 分红 → `free_cash` 入账（按除权后持仓数量）。
  2. 送股 → 数量 ×(1+bonus)，**总成本基不变**（`ep × size` 保持不变，
     从而与 `_close_position` 的 `release_margin(ep*size + entry_fee)` 兼容）。
  3. 净值跨除权日**连续**（缺口被分红补偿，不出现物理上不存在的跳变）。
  4. 现金守恒含分红项：`final_equity == initial + Σnet_pnl + Σdividends`。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chase_up.portfolio import simulate_portfolio
from core.corporate_actions import apply_corporate_action
from core.dual_price import portfolio_nav


def _panel(ex_bar: int, kind: str, n: int = 8) -> pd.DataFrame:
    """8 根 bar；bar 1 建仓 10.0；bar 2 为除权日，raw 价按事件下跳。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_ex = i == ex_bar
        raw = 9.0 if (is_ex and kind == "div") else (5.0 if (is_ex and kind == "bonus") else 10.0)
        div = 1.0 if (is_ex and kind == "div") else 0.0
        bonus = 1.0 if (is_ex and kind == "bonus") else 0.0
        rows.append({
            "thscode": "TEST.SH", "date": d,
            "open": raw, "high": raw + 0.2, "low": raw - 0.2, "close": raw,
            "volume": 1e6, "amount": 1e7,
            "raw_open": raw, "raw_high": raw + 0.2, "raw_low": raw - 0.2,
            "raw_close": raw, "raw_prev_close": 10.0,
            "div_per_share": div, "bonus_ratio": bonus, "rights_ratio": 0.0,
        })
    return pd.DataFrame(rows)


def _entries(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": panel.iloc[0]["date"], "thscode": "TEST.SH", "score": 1.0,
        "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
        "sig_breakout_score": 0.5, "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan, "sig_mom120": 0.05, "sig_amount60": 5e7,
        "atr_pct": 0.03, "sub_signal_type": "A",
    }])


def _run(panel: pd.DataFrame, *, sl_pct: float = 0.99, tp_pct: float = 0.99,
         max_hold: int = 3):
    trades, eq = simulate_portfolio(
        _entries(panel), panel,
        tp_pct=tp_pct, sl_pct=sl_pct, max_hold=max_hold, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0, position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    return trades, eq


def test_cash_dividend_is_deposited_into_free_cash() -> None:
    """分红必须显式进入现金账，且净值跨除权日连续。"""
    panel = _panel(ex_bar=2, kind="div")
    trades, eq = _run(panel)
    assert "cum_dividends" in eq.columns
    div_total = float(eq["cum_dividends"].iloc[-1])
    assert div_total > 0, "除权日未入账任何分红"

    # 入场 bar 1：all_in 在 raw 10.0 成交 → size=10000 → 除权日分红 1.0/股 = 10,000
    assert div_total == pytest.approx(10_000.0), f"分红金额不符: {div_total}"

    # 净值连续性：除权日前后 equity 的变化只应来自当日行情，除权缺口 0.2*size 已由
    # 分红补偿。这里 bar 2 之后无行情变化，故 equity 不应因除权而永久下台阶。
    eq_dates = list(eq["date"])
    i_ex = next(i for i, d in enumerate(eq_dates) if pd.Timestamp(d) == panel.iloc[2]["date"])
    after = float(eq["equity"].iloc[i_ex])
    assert after >= 100_000.0 - 1e-6, (
        f"除权后净值 {after:.2f} 低于初始 —— 分红未补偿除权缺口(§3 Reality Mapping)"
    )


def test_stock_bonus_adjusts_quantity_and_keeps_cost_basis() -> None:
    """送股：数量 ×(1+bonus)，总成本基不变（ep × size 不变量）。"""
    panel = _panel(ex_bar=2, kind="bonus")
    trades, eq = _run(panel)
    assert len(trades) == 1
    size = float(trades.iloc[0]["size"])
    # 送股 1:1 → 数量翻倍，成本价减半；总成本基不变
    assert size == pytest.approx(20_000.0), f"送股后数量应为 2 倍, 实际 {size}"
    assert float(trades.iloc[0]["entry_price"]) == pytest.approx(5.0), (
        "送股后成本价未按总量不变重新定标"
    )


def _bonus_panel_continuous(n: int = 8, ex_bar: int = 2) -> pd.DataFrame:
    """送股除权后价格**留在**调整后水平(物理场景),而不是弹回原价。

    bar 0-1 raw 10.0;bar 2 起 raw 5.0(10送10)。事件列与 `_panel` 同口径。
    """
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_ex = i >= ex_bar
        raw = 5.0 if is_ex else 10.0
        rows.append({
            "thscode": "TEST.SH", "date": d,
            "open": raw, "high": raw + 0.2, "low": raw - 0.2, "close": raw,
            "volume": 1e6, "amount": 1e7,
            "raw_open": raw, "raw_high": raw + 0.2, "raw_low": raw - 0.2,
            "raw_close": raw, "raw_prev_close": 10.0,
            "div_per_share": 0.0,
            "bonus_ratio": 1.0 if i == ex_bar else 0.0,
            "rights_ratio": 0.0,
        })
    return pd.DataFrame(rows)


def test_bonus_ex_date_does_not_trigger_a_stale_stop() -> None:
    """送股除权日不得因**陈旧**止损被强制出场(§4 相对百分比 × §3 除权调整)。

    CLAUDE.md §4 逐字要求 TP/SL 以**相对百分比**传导:
      "TP/SL and slippage must always be communicated from Strategy to Broker as
       relative percentages (e.g. sl_pct = 0.05), NEVER as absolute point
       differences derived from adjusted prices, to guarantee reality mapping on
       raw execution prices."

    若在入场时把阈值算成**绝对价**存进持仓(sl = 10.0 × 0.95 = 9.5),那么除权日
    `apply_corporate_action` 把 entry_price 重定为 5.0 之后,阈值**不动** ⇒
    除权价 5.0 必然穿越 9.5 ⇒ 一笔与真实行情无关的强制出场,且理由被记成 SL。
    现算(entry_price × 百分比)则由构造自动传导:sl → 5.0 × 0.95 = 4.75,不触发。
    """
    panel = _bonus_panel_continuous()
    ex_date = panel.iloc[2]["date"]
    stale_sl = 10.0 * (1 - 0.05)
    # 非空转前提:除权价必须**确实**穿越陈旧止损,否则本用例测不到这条路径
    assert panel.iloc[2]["open"] <= stale_sl, (
        f"夹具失效:除权开盘 {panel.iloc[2]['open']} 未穿越陈旧止损 {stale_sl}"
    )

    trades, _ = _run(panel, sl_pct=0.05, max_hold=4)
    assert len(trades) == 1, f"应恰好一笔成交,实际 {len(trades)}"
    t = trades.iloc[0]

    assert pd.Timestamp(t["exit_date"]) != pd.Timestamp(ex_date), (
        "§4 VIOLATION: 在送股除权日被强制出场 —— 止损阈值是入场时算死的绝对价,"
        "没有随 entry_price 的除权重定而传导"
    )
    assert t["exit_reason"] != "SL", (
        f"§4 VIOLATION: 出场理由被记成 {t['exit_reason']!r} —— 除权不是止损事件"
    )
    # §3 的账本面:数量按 (1+bonus) 调整、总成本基不变 ⇒ 除权不产生盈亏
    assert float(t["size"]) == pytest.approx(20_000.0), "送股后数量未翻倍"
    assert float(t["entry_price"]) == pytest.approx(5.0), "送股后成本价未重定"
    assert float(t["net_pnl"]) == pytest.approx(0.0, abs=1.0), (
        f"除权日产生了幻影盈亏 {t['net_pnl']:.2f} —— §3 要求除权前后净值连续"
    )


def _position_dict_key_sets(tree) -> list[set]:
    """持仓字面量的键集合:含 `entry_price` + `atr_pct` + `bars`,且不含 `exit_price`。

    选择器要同时排除两类"长得像"的 dict(两版误报各自踩中一个):
      * **成交记录 schema** —— 也有 entry_price/atr_pct,但必然带
        `exit_price`/`exit_reason`;
      * **kwargs 转发字典** —— 形如 `{"entry_price": …, "size": …}`,没有
        `atr_pct`/`bars`。
    """
    import ast as _ast

    out = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, _ast.Constant)}
            if ({"entry_price", "atr_pct", "bars"} <= keys) and "exit_price" not in keys:
                out.append(keys)
    return out


@pytest.mark.parametrize("module", ["chase_up.portfolio", "uptrend_pullback.portfolio"])
def test_positions_hold_tp_sl_as_percentages_not_absolute_prices(module: str) -> None:
    """§4 家族守卫:两个多头引擎的持仓必须存**百分比**、且无人读绝对价键。

    为什么是结构而不是行为:上面那条行为用例建在 chase 的 entries 夹具上
    (`sig_*` 列),姊妹引擎的 entries schema 不同 ⇒ 同一夹具跑不了两边。
    故此处钉**结构**(AST 解析持仓字面量 + 扫 `pos["tp"]/["sl"]` 下标读取),
    行为证据由 chase 那条提供 —— 与 `test_preset_declarations_are_load_bearing`
    同法。**这是形状守卫,不替代行为证据。**
    """
    import ast as _ast
    import importlib

    from pathlib import Path

    mod = importlib.import_module(module)
    tree = _ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))

    key_sets = _position_dict_key_sets(tree)
    assert key_sets, f"{module}: 找不到持仓字面量 —— 本守卫已失效,请修正选择器"
    for keys in key_sets:
        assert {"tp_pct", "sl_pct"} <= keys, (
            f"§4 VIOLATION {module}: 持仓没有 tp_pct/sl_pct(实际键 {sorted(keys)})—— "
            f"绝对阈值在除权日会失效"
        )
        assert "tp" not in keys and "sl" not in keys, (
            f"§4 VIOLATION {module}: 持仓仍在存绝对价键 tp/sl —— §4 明文禁止 "
            f"absolute point differences"
        )
    # 顺带:模块里不得再出现 `pos["tp"]` / `pos["sl"]` 这类下标读取
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Subscript) and isinstance(node.slice, _ast.Constant):
            assert node.slice.value not in ("tp", "sl"), (
                f"§4 VIOLATION {module}: 仍在读绝对价键 pos[{node.slice.value!r}]"
            )


def test_apply_corporate_action_is_pure_and_reports_rights() -> None:
    """core 纯函数语义:不改入参、返回 cash_delta、配股显式告警(不静默)。"""
    out = apply_corporate_action(
        size=1000, entry_price=10.0, dividend_per_share=0.5, bonus_ratio=0.0,
        rights_ratio=0.0,
    )
    assert out.cash_delta == pytest.approx(500.0)
    assert out.size == 1000, "无送股时数量不变"
    assert out.entry_price == pytest.approx(10.0)
    assert out.warnings == ()

    # 送股:数量 ×2、成本价 ÷2、总成本基不变
    out2 = apply_corporate_action(size=1000, entry_price=10.0, bonus_ratio=1.0)
    assert out2.size == 2000
    assert out2.entry_price == pytest.approx(5.0)
    assert out2.entry_price * out2.size == pytest.approx(10_000.0)
    assert out2.cash_delta == 0.0, "送股不产生现金流"

    # 配股:不建模但必须显式告警
    out3 = apply_corporate_action(size=1000, entry_price=10.0, rights_ratio=0.4)
    assert out3.warnings and "配股" in out3.warnings[0], (
        "配股未建模时必须产出告警 —— 不能静默吞掉"
    )

    # 空头方向由调用方取负 —— 共享函数不替调用方决定符号
    assert apply_corporate_action(
        size=1000, entry_price=10.0, dividend_per_share=0.5,
    ).cash_delta == pytest.approx(500.0), "core 返回多头口径的正值"


def test_buying_on_the_ex_date_earns_no_dividend() -> None:
    """§3 权益归属:除权日**当天买入不享有**本次分红。

    除权日的定义就是"该日起股票不含本次分红交易"。持仓端因此按"bar 起始时
    已持有"计息 —— 入场当日不应用事件。这条语义很容易写反(写成"只要持有期
    与除权日有交集就发钱"),而那会让每笔在除权日进场的交易凭空多拿一笔现金。

    独立核算(chase_up chase_v1_atr_tp4_sl1, 2025-09-19..2026-09-19):
    应计 1 笔 = ¥4,340.00,与实测 Σdiv 一致;且"入场日=除权日"事件为 0 笔。
    """
    # 入场 bar 1;除权日 = bar 1(入场当日)
    panel = _panel(ex_bar=1, kind="div")
    trades, eq = _run(panel)
    div_total = float(eq["cum_dividends"].iloc[-1])
    assert div_total == pytest.approx(0.0), (
        f"除权日当天买入不应获得分红,实际入账 {div_total:.2f}"
    )
