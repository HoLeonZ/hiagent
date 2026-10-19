"""§4 执行滑点：**买入腿与卖出腿必须用同一个模型** (§13.95, 2026-10-19)。

## 本节修的是什么
§4 原文: 「Execution slippage (price impact between signal trigger and fill) MUST be
modeled dynamically as a function of the asset's **current ATR** and the order's
participation rate.」

「price impact between signal trigger and fill」是**每一笔 execution** 的性质 ——
买入腿与卖出腿**同样成立**。而在 §13.95 之前:
1. **四个引擎全都只在买入腿计费**, 出场腿零冲击 ⇒ **单一方向的乐观** (§0);
2. `core/dual_price.atr_slippage` (规范助手) **全仓只有 1 处 import, 而那处零读取**
   (它的 docstring 还写着"用于 chase_up" —— 假的);
3. 更根本: ATR 的来源是**为 ATR-TP 建的信号日表** (`atr_lookup`), 出场发生在**非信号日**
   ⇒ 出场腿**永远查不到 ATR**, 滑点静默为 0。实测 `atr_slip_scale>0` 时
   `出场价/触发价` **恒为 1.000000**。

## 本文件的两类判据 (强 + 弱, 都要有)
* **弱 (结构)**: 每个 `_close_position` 调用点的价格实参**必须**是 `_exit_fill_px(...)`;
  `_exit_fill_px` 与入场腿**必须**都走 `core.dual_price.effective_slippage`,
  且**必须**都从 `atr_by_bar` 取 ATR。
* **强 (行为)**: 真的跑一次 —— `atr_slip_scale>0` 时**每一笔出场都必须比其触发价更差**。
  ⚠️ 只有这一条能证明机制**真的咬**。本册记过 15 轮的失效正是"结构判据被『提到』满足"。
"""
from __future__ import annotations

import ast
import itertools
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 已接线的族 (§13.95 接 chase_up; §13.96 接 uptrend_pullback)。
# ⚠️ `uptrend_pullback` / `short_reversal` 里**只有出场腿**曾是缺陷 ——
#    它们的**入场腿本来就能取到 ATR** (chase/uptrend 靠 `ent` 兜底、short 靠自己的
#    `indi["atr"]` bar 指标)。这一点在 §13.96 被实测更正过, 见 §13.95(c) 的更正条。
ENGINES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
}


def _src(fam: str) -> str:
    return ENGINES[fam].read_text(encoding="utf-8")


def _tree(fam: str) -> ast.Module:
    return ast.parse(_src(fam))


def _calls(tree: ast.Module, name: str) -> list[ast.Call]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            fn = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if fn == name:
                out.append(n)
    return out


# ---------------------------------------------------------------------------
# 1) core 的规范助手 (单一来源, §2)
# ---------------------------------------------------------------------------


def test_helper_exists_and_is_imported_by_core_public_api() -> None:
    from core import dual_price as dp

    assert hasattr(dp, "effective_slippage"), (
        "§13.95: core.dual_price.effective_slippage 不存在 —— 它是"
        "「取静态值与 ATR 项的较大者」这条规则的**唯一**定义处 (§2 defined exactly once)。"
    )
    assert "effective_slippage" in dp.__all__, "§13.95: 未导出 ⇒ 各引擎无法引它"


def test_helper_matches_the_pre_2026_10_19_inline_rule_on_the_zero_drift_domain() -> None:
    """它在**零漂移域**上必须与旧的各引擎内联式**逐点相同**。

    旧内联式 (chase/uptrend/cycle 三处同形):
        eff = static;  if scale>0 and atr 是有效数: eff = max(static, atr*part*scale)
    本断言只覆盖 `scale <= 0` (即全部 81 个 preset 的真实取值域) ——
    那正是"改它零漂移"所依赖的全部。
    """
    from core.dual_price import effective_slippage as eff

    cases = list(itertools.product(
        [0.0, 0.0005, 0.001], [None, float("nan"), -0.01, 0.0, 0.02], [0.0, 0.1, 1.0], [0.0, -1.0]
    ))
    for static, atr, part, scale in cases:
        assert eff(static, atr, part, scale) == static, (
            f"§13.95: scale<=0 时必须**原样返回静态值** (零漂移的前提), "
            f"而 eff({static}, {atr}, {part}, {scale}) = {eff(static, atr, part, scale)}"
        )


def test_helper_is_monotone_in_scale_and_takes_the_max() -> None:
    from core.dual_price import effective_slippage as eff

    assert eff(0.0, 0.02, 0.1, 1.0) == pytest.approx(0.002)
    assert eff(0.05, 0.02, 0.1, 1.0) == 0.05, "静态值更大时必须取静态值 (不是相加)"
    assert eff(0.0, 0.02, 0.1, 3.0) > eff(0.0, 0.02, 0.1, 1.0), "对 scale 必须单调"
    assert eff(0.0, 0.02, 0.0, 1.0) == 0.0, "参与率 0 ⇒ 无冲击 (不是拿不到 ATR)"
    assert math.isclose(eff(0.0, float("nan"), 0.1, 1.0), 0.0), "NaN ⇒ 退回静态值"


# ---------------------------------------------------------------------------
# 2) 结构: 每个出场调用点都必须带冲击; 两条腿都走同一个 helper / 同一个 ATR 源
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fam", sorted(ENGINES))
def test_every_close_position_call_passes_the_slippage_adjusted_price(fam: str) -> None:
    """**逐调用点**判定 —— 不是"文件里出现过 `effective_slippage`"。

    (本册 15 轮失效的共同形态就是后一种: 判据的单位弱于它声称的性质。)
    """
    calls = _calls(_tree(fam), "_close_position")
    assert len(calls) >= 1, "§13.95: 找不到 _close_position 调用点 —— 扫描单位失效"
    bad = []
    for c in calls:
        assert len(c.args) >= 3, f"第 {c.lineno} 行的 _close_position 实参不足"
        third = ast.unparse(c.args[2])
        if "_exit_fill_px" not in third:
            bad.append((c.lineno, third))
    assert not bad, (
        "§13.95: 这些出场调用点**没有**经过出场冲击 ⇒ 卖出腿零冲击 = 单一方向乐观 (§0)。\n"
        f"{bad}\n请把它们改成 _exit_fill_px(...)。"
    )


@pytest.mark.parametrize("fam", sorted(ENGINES))
def test_exit_helper_reads_atr_from_the_per_bar_table(fam: str) -> None:
    """出场腿的 ATR **必须**来自 `atr_by_bar`, 不能来自 `atr_lookup`。

    ⚠️ 这是本节的**根因**: `atr_lookup` 是**为 ATR-TP 建的信号日表**, 而出场发生在
    非信号日 ⇒ 用它查出场腿**永远查不到** ⇒ 滑点静默为 0。
    """
    fn = next((n for n in ast.walk(_tree(fam))
               if isinstance(n, ast.FunctionDef) and n.name == "_exit_fill_px"), None)
    assert fn is not None, "§13.95: 找不到 _exit_fill_px 的定义"
    # ⚠️ §13.78 的教训: `ast.unparse` **包含 docstring** ⇒ 纯文本判据会被注释满足。
    # 本判据只允许看**可执行代码**, 故把 docstring 摘掉。
    body_node = ast.Module(
        body=[n for n in fn.body if not (isinstance(n, ast.Expr)
                                         and isinstance(n.value, ast.Constant))],
        type_ignores=[],
    )
    body = ast.unparse(body_node)
    assert "atr_by_bar" in body, (
        "§13.95: 出场腿的 ATR 不来自 atr_by_bar ⇒ 它一定查不到 (信号日表里没有出场日)。"
    )
    assert "atr_lookup" not in body, (
        "§13.95: 出场腿仍在用 atr_lookup —— 那是**信号日**表, 出场日不在其中, "
        "会静默退化成零滑点。"
    )


@pytest.mark.parametrize("fam", sorted(ENGINES))
def test_atr_by_bar_is_built_from_the_panel_and_used_by_both_legs(fam: str) -> None:
    src = _src(fam)
    assert "atr_by_bar" in src, "§13.95: 没有全 bar 的 ATR 表"
    assert "panel[[" in src or "panel.atr_pct" in src, (
        "§13.95: atr_by_bar 必须从 panel 的 atr_pct 列构建"
    )
    # 入场腿也必须用它 (否则两条腿的 ATR 来源不同 ⇒ 又是不对称)
    fn = next((n for n in ast.walk(_tree(fam))
               if isinstance(n, ast.FunctionDef) and n.name == "simulate_portfolio"), None)
    assert fn is not None
    entry_calls = [c for c in _calls(fn, "effective_slippage")]
    assert len(entry_calls) >= 1, "§13.95: 入场腿没有走规范助手"
    entry_txt = ast.unparse(fn)
    assert entry_txt.count("atr_by_bar") >= 1, "§13.95: 入场腿没有用 atr_by_bar"


@pytest.mark.parametrize("fam", sorted(ENGINES))
def test_entry_leg_still_uses_the_canonical_helper_not_an_inline_formula(fam: str) -> None:
    """§2: 不得再内联重写 `atr_pct * participation * scale`。"""
    fn = next((n for n in ast.walk(_tree(fam))
               if isinstance(n, ast.FunctionDef) and n.name == "simulate_portfolio"), None)
    assert fn is not None, "§13.95: 找不到 simulate_portfolio (引擎函数改名了? 判据要跟着改)"
    txt = ast.unparse(fn)
    assert "effective_slippage" in txt, "§13.95: 入场腿未走规范助手"
    # 内联形态的特征: 同时出现 atr_slip_scale 与一次乘法赋值
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            s = ast.unparse(node)
            if "atr_slip_scale" in s and "*" in s and "effective_slippage" not in s:
                raise AssertionError(
                    f"§13.95/§2: 第 {node.lineno} 行仍在**内联重写**滑点公式: {s}\n"
                    f"⇒ 那正是 §13.95 修掉的「同一公式写了三遍」。请走 effective_slippage。"
                )


# ---------------------------------------------------------------------------
# 3) 行为 (最强的一档): 真的跑一次, 出场必须更差
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from hiagent_config import DB_PATH
    except Exception:
        return False
    return Path(str(DB_PATH)).exists()


# 每族的 (模块前缀, 用哪个 preset, universe)
_BEHAV = {
    "chase_up": ("chase_up", "chase_v5_pos2_equal_atr_tp6_sl15_mh10", "mainboard_only"),
    "uptrend_pullback": ("uptrend_pullback", "v33_long_reverse_v22", "mainboard_only"),
}


@pytest.mark.skipif(not _db_available(), reason="本地 DB 缺失")
@pytest.mark.parametrize("fam", sorted(_BEHAV))
def test_with_a_nonzero_coefficient_every_exit_fills_worse_than_its_trigger(fam: str) -> None:
    """★ 只有这一条能证明机制**真的咬**。

    ⚠️ **第一版这个断言是错的, 而且它当场抓到了我自己的假修复** (§13.95):
    初版写的是"scale=1 时出场价必须低于 scale=0 时的出场价" —— 但 scale>0 会
    **抬高入场价** ⇒ TP/SL 价位随之抬高 ⇒ 出场价自然更高。实测出现
    「更低 1 / 相同 4 / 更高 8」, 差一点被我读成"机制反了"。
    ⇒ 正确做法是**隔离出场腿**: 只看 `time` 退出 (触发价 = 当日 close, 与入场价无关),
    比较 `出场价 / 当日 close`。

    ⚠️ **它同时是 §13.95(c) 那处过强结论的更正工具**: 对 `uptrend_pullback`,
    接线**之前**本断言必红 (出场腿静默为零), 接线**之后** `ratio < 1` 全部成立
    —— 这一个前后对照就是"机制是否真的接上了"的判据。
    """
    import importlib

    import pandas as pd

    mod, preset_name, universe = _BEHAV[fam]
    bt = importlib.import_module(f"{mod}.backtest")
    data = importlib.import_module(f"{mod}.data")
    presets = importlib.import_module(f"{mod}.presets")
    signals = importlib.import_module(f"{mod}.signals")
    universe_mod = importlib.import_module(f"{mod}.universe")
    from hiagent_config import DB_PATH

    w0, w1 = "2025-09-19", "2026-03-19"
    panel = signals.compute_indicators(
        data.load_panel(DB_PATH, w0, w1,
                        universe=set(universe_mod.load_universe(universe, DB_PATH)))
    )
    ref = "raw_close" if "raw_close" in panel.columns else "close"

    def px_lookup(code: str, day: str) -> float:
        sub = panel[panel["thscode"].astype(str) == code]
        sub = sub[sub["date"].map(lambda d: str(pd.Timestamp(d).date())) == day]
        return float(sub.iloc[0][ref]) if not sub.empty else float("nan")

    def time_exits(scale: float) -> pd.DataFrame:
        p = dict(presets.get_preset(preset_name))
        p["atr_slip_scale"] = scale
        tr = bt.run_backtest(p, w0, w1, DB_PATH, panel_ind=panel)["trades"]
        tr = tr[tr["exit_reason"] == "time"].copy()
        if tr.empty:
            return tr
        tr["close"] = [
            px_lookup(str(c), str(pd.Timestamp(d).date()))
            for c, d in zip(tr["thscode"], tr["exit_date"])
        ]
        tr["ratio"] = tr["exit_price"] / tr["close"]
        return tr

    t0 = time_exits(0.0)
    t1 = time_exits(1.0)
    assert len(t0) >= 1 and len(t1) >= 1, (
        f"{fam}: time 退出样本不足 (t0={len(t0)}, t1={len(t1)}) ⇒ 本断言无法判定, "
        f"这是**未判定**而不是通过。请换一个更长/更活跃的窗口。"
    )
    assert (t0["ratio"] == 1.0).all(), (
        f"{fam}: 系数为 0 时出场价必须**恰等于**触发价 (零漂移的前提), "
        f"实测 {t0['ratio'].tolist()}"
    )
    assert (t1["ratio"] < 1.0).all(), (
        f"§4/§0 [{fam}]: 系数 > 0 时 **每一笔**出场都必须比触发价更差 (卖出 ⇒ 更低)。\n"
        f"实测比值: {t1['ratio'].tolist()}\n"
        f"若恒等于 1.0 ⇒ 出场腿的冲击**没生效** (最可能的原因: ATR 查表查不到 ⇒ 静默为 0)。"
    )

# ---------------------------------------------------------------------------
# 3b) short_reversal (§13.97) —— 结构与另两族**不同** (类方法, 空头方向相反)
# ---------------------------------------------------------------------------

_SHORT = REPO_ROOT / "short_reversal" / "replay_strategy_v3.py"


def _short_tree() -> ast.Module:
    return ast.parse(_SHORT.read_text(encoding="utf-8"))


def test_short_reversal_every_close_call_passes_the_slippage_adjusted_price() -> None:
    """**逐调用点**: 每个 `self._close(...)` 的价格实参必须是 `self._exit_fill_px(...)`。

    (与上面两族同一条命题 —— 但这里的判据单位是**调用点**, 不是"文件提到过"。)
    """
    calls = [n for n in ast.walk(_short_tree())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_close"]
    assert len(calls) >= 1, "§13.97: 找不到 self._close 调用点 —— 扫描单位失效"
    bad = []
    for c in calls:
        assert len(c.args) >= 2, f"第 {c.lineno} 行的 _close 实参不足"
        second = ast.unparse(c.args[1])
        if "_exit_fill_px" not in second:
            bad.append((c.lineno, second))
    assert not bad, (
        "§13.97: 这些平仓调用点**没有**经过出场冲击 ⇒ 平仓腿零冲击 = 单一方向乐观 (§0)。\n"
        f"{bad}"
    )


def test_short_reversal_exit_takes_the_positive_sign() -> None:
    """⚠️ **反号**: 本族是**空头**, 平仓是**买入** ⇒ 冲击让平仓价更**高** = 悲观。

    这与另两族（多头, 出场是卖出 ⇒ `×(1−slip)`）**相反**, 也与本族**入场腿**
    （卖出 ⇒ `×(1−slip)`）**相反**。把它"顺手统一"成减号会把悲观改成乐观。
    """
    src = _SHORT.read_text(encoding="utf-8")
    assert "return float(raw_px) * (1.0 + slip)" in src, (
        "§13.97: short_reversal 的**出场**腿符号不对。空头平仓是**买入**, "
        "悲观方向是平仓价更**高** ⇒ 必须是 `(1.0 + slip)`。"
    )
    assert "return float(raw_px) * (1.0 - slip)" not in src, (
        "§13.97: 出场腿用了减号 —— 那是**多头**的方向 (卖出更便宜), "
        "对空头平仓是**乐观** ⇒ §0 违规。"
    )


@pytest.mark.skipif(not _db_available(), reason="本地 DB 缺失")
def test_short_reversal_with_a_nonzero_coefficient_every_exit_fills_worse() -> None:
    """★ 行为档 (short_reversal): `atr_slip_scale>0` 时**每一笔**平仓都比触发价更差。

    ⚠️ **隔离手法沿用 §13.95 的教训**: 只看 `time` 退出 (触发价 = 当日 close,
    **与入场价无关**); 不看 `exit_price` 的绝对值, 而看它与**触发价**的关系。
    ⚠️ 本族是空头 ⇒ "更差" = 平仓价**更高**。
    ⚠️ **本族不提供 panel**, 触发价直接从 DB 取 `raw_kline_daily.close`。

    ⚠️⚠️ **本测试的第一版是"永远跳过"的 (§13.19 那一类)**:
    它跨两次运行按 (entry_date, thscode) 配对, 但 `atr_slip_scale>0` 会改变成交集合
    ⇒ 每次都不匹配 ⇒ 每次都 skip。**一个永远 skip 的守卫比没有守卫更糟**
    (它长得像覆盖)。⇒ 改成**单次运行 + 直接查触发价**, 不依赖跨运行配对。
    """
    import duckdb

    import short_reversal.presets as SRP
    from short_reversal.engine import run_backtest_v3
    from hiagent_config import DB_PATH

    name = "v50_slope"
    if name not in SRP.PRESETS:
        pytest.fail(f"找不到 preset {name} —— 本断言**无法判定**, 这是失败不是跳过")
    w0, w1 = "2025-10-01", "2025-12-31"
    SRP.PRESETS[name]["atr_slip_scale"] = 1.0
    try:
        r = run_backtest_v3(name, w0, w1, DB_PATH)
    finally:
        SRP.PRESETS[name]["atr_slip_scale"] = 0.0
    tr = r.get("trades") or []
    tr = [t for t in tr if t.get("exit_reason") == "time"]
    assert len(tr) >= 1, (
        f"窗口 {w0}..{w1} 内没有 time 退出 ⇒ **未判定** (不是通过)。"
        f"请换窗口 —— 但没有样本时**不得**把本判据当成绿的。"
    )
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        bad = []
        for t in tr:
            row = con.execute(
                "SELECT close FROM raw_kline_daily WHERE thscode = ? AND date = ?",
                [t["thscode"], t["exit_date"]],
            ).fetchone()
            if row is None or row[0] is None:
                continue
            trig = float(row[0])
            if not (float(t["exit_price"]) > trig):
                bad.append((t["thscode"], str(t["exit_date"]), t["exit_price"], trig))
    finally:
        con.close()
    assert not bad, (
        f"§4/§0 [short_reversal]: 系数 > 0 时**每一笔**平仓都必须比触发价更**差** "
        f"(空头平仓是买入 ⇒ 更高)。\n实测未通过的: {bad}\n"
        f"若全部相等 ⇒ 出场腿的冲击**没生效**(ATR 取不到 ⇒ 静默为 0)。"
    )
