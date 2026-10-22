"""四引擎适配器：统一返回形状、窗口计算、以及在窗口太短时给出**具名**错误。"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from web.catalog import all_presets
from web.runners import (
    EngineInputError,
    PREVIEW_DAYS,
    RunResult,
    WindowTooShortError,
    _as_trades,
    effective_window,
    run,
)

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


def test_preview_window_is_the_last_n_days():
    """preview = 从 `end` 往回数 `PREVIEW_DAYS` 个自然日（不早于用户给的 `start`）。

    **判据从常量推，不写死日期。** 原版写死 `assert start == "2026-04-01"  # 90 天`，
    于是"`PREVIEW_DAYS` 该取多少"这件事在测试里是隐形的：改常量时它只报
    "日期不对"，读的人看不出这条测的到底是哪条性质，很容易顺手把期望值改新了事——
    而那恰恰放过了下面这条真正的约束（面板必须凑够 min_bars）。
    """
    import datetime as dt

    start, end = effective_window("preview", "2020-01-01", "2026-06-30")
    assert end == "2026-06-30"
    want = (dt.date(2026, 6, 30) - dt.timedelta(days=PREVIEW_DAYS)).isoformat()
    assert start == want, f"preview 应从 end 往回数 {PREVIEW_DAYS} 个自然日"


def test_preview_window_never_goes_earlier_than_the_requested_start():
    start, _ = effective_window("preview", "2026-06-01", "2026-06-30")
    assert start == "2026-06-01"


def test_full_window_is_returned_unchanged():
    assert effective_window("full", "2020-01-01", "2026-06-30") == ("2020-01-01", "2026-06-30")


# --- _as_trades 的三条归一分支（不依赖 DB；brief 原稿恰有两处写错） ---


def test_as_trades_normalizes_a_dataframe():
    """chase_up / uptrend_pullback：`res["trades"]` 是 pandas DataFrame。"""
    df = pd.DataFrame([
        {"thscode": "000001.SZ", "pnl": 1.5},
        {"thscode": "600000.SH", "pnl": -0.5},
    ])
    got = _as_trades(df)
    assert got == [
        {"thscode": "000001.SZ", "pnl": 1.5},
        {"thscode": "600000.SH", "pnl": -0.5},
    ]


def test_as_trades_normalizes_a_frozen_dataclass_list():
    """cycle：TradeRecord 是 **frozen dataclass**，不可迭代 —— `dict(t)` 会抛
    `TypeError: 'TradeRecord' object is not iterable`（brief 原稿写错的地方）。
    必须走 `dataclasses.asdict`。"""
    import datetime as _dt

    from cycle_price_action.metrics import TradeRecord

    rec = TradeRecord(
        thscode="002189.SZ",
        entry_date=_dt.date(2025, 10, 8),
        exit_date=_dt.date(2025, 10, 15),
        entry_price=10.0,
        exit_price=11.0,
        shares=100,
        pnl=100.0,
        hold_days=5,
        k_line_score=2.0,
        phase_score=1.0,
        calendar_score=0.0,
    )
    got = _as_trades([rec])
    assert isinstance(got, list) and len(got) == 1
    assert isinstance(got[0], dict)
    assert got[0]["thscode"] == "002189.SZ" and got[0]["pnl"] == 100.0


def test_as_trades_normalizes_a_list_of_dicts():
    """short_reversal：`t2 = dict(t)` 逐笔重建出的 list[dict]。"""
    assert _as_trades([{"thscode": "000001.SZ"}]) == [{"thscode": "000001.SZ"}]


def test_as_trades_treats_none_and_empty_as_no_trades():
    assert _as_trades(None) == []
    assert _as_trades([]) == []


def test_run_injects_the_real_preset_name_into_params(monkeypatch):
    """评审焦点 2：平台走 **dict** 通路，`run()` 必须在调引擎前把真名注入 `params["_name"]`。

    否则 short_reversal 引擎把 metrics["preset"] 落成 `"<dict>"`（实测），
    与 `RunResult.preset` 口径不一致、并在报错消息里串入整个 dict。
    用替身 runner 捕获 params：不跑引擎、不碰 DB。
    """
    import web.runners as runners_mod

    captured: dict = {}

    def fake(preset, start, end, db, params):
        captured["params"] = dict(params)
        return RunResult("short_reversal", preset, start, end, {}, [])

    monkeypatch.setitem(runners_mod._RUNNERS, "short_reversal", fake)
    got = run(
        "short_reversal", "v50_slope", "2025-01-01", "2025-06-30",
        overrides={"tp_pct": 0.30},
    )

    assert captured["params"]["_name"] == "v50_slope"
    # 覆盖值仍照常并入 params（注入不吞掉 clean）
    assert captured["params"]["tp_pct"] == 0.30
    assert got.preset == "v50_slope"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_run_returns_the_uniform_shape_for_short_reversal():
    """full 模式用引擎默认 min_bars；窗口足够宽，不应触发 F-01。"""
    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    assert isinstance(got, RunResult)
    assert got.engine == "short_reversal" and got.preset == "v50_slope"
    assert isinstance(got.trades, list)
    assert isinstance(got.metrics, dict)
    assert "trades_count" in got.metrics


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_window_too_short_raises_a_named_error_not_a_bare_valueerror():
    """F-01 守卫在面板跨度过小时抛 ValueError。

    平台必须把它转成**具名**错误，好让 API 回 400 而不是 500——
    否则用户看到的是"服务器错误"，而不是"窗口太短"。
    """
    with pytest.raises(WindowTooShortError, match="min_bars"):
        run("short_reversal", "v50_slope", "2026-01-05", "2026-01-20")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_empty_universe_raises_a_named_engine_input_error_not_a_bare_valueerror():
    """评审焦点 1：空 universe 守卫抛的 ValueError 消息里**不含** `min_bars`。

    只靠 `"min_bars" in str(exc)` 判据会把它漏成裸 `ValueError` → HTTP 层 500，
    而它和"窗口太短"同类（数据覆盖问题），该是 400。修后统一具名化为 EngineInputError。

    实测触发窗口：as-of（2016-01-05）早于数据地板 → `load_universe_asof` 返回 []。
    """
    assert not issubclass(EngineInputError, WindowTooShortError)
    with pytest.raises(EngineInputError):
        run("short_reversal", "v50_slope", "2016-01-05", "2016-02-05")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_overrides_are_applied_and_visible_in_the_run():
    """改了 tp_pct 必须真的进到这次运行里（不能静默忽略）。"""
    base = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    changed = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12",
                  overrides={"tp_pct": 0.30})
    assert changed.metrics["trades_count"] != base.metrics["trades_count"] or \
           changed.metrics["final_capital"] != base.metrics["final_capital"], \
        "覆盖 tp_pct 后结果必须变化——否则参数没有真的传进去"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_short_reversal_accepts_a_params_dict_not_just_a_name():
    """平台必须能传入被覆盖的参数。

    `run_backtest_v3(preset: str)` 内部 `cfg = dict(get_preset(preset))`，
    于是平台侧改的 params 会被**静默丢弃**——用户改了 tp_pct 却拿到原 preset 的结果。
    另三个引擎的入口都收 `str | dict`，此处与它们对齐。
    """
    from short_reversal.engine import run_backtest_v3
    from web.catalog import all_presets

    db = _db()
    params = dict(all_presets()["short_reversal"]["v50_slope"])
    by_name = run_backtest_v3("v50_slope", "2025-09-12", "2026-09-12", db)

    params["tp_pct"] = 0.30
    by_dict = run_backtest_v3(params, "2025-09-12", "2026-09-12", db)

    assert by_dict["trades_count"] != by_name["trades_count"] or \
           by_dict["final_capital"] != by_name["final_capital"], \
        "传入 dict 时覆盖必须生效——否则参数被静默丢弃"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_passing_a_name_still_behaves_identically():
    """向后兼容：传字符串的行为必须逐个字节不变。"""
    from short_reversal.engine import run_backtest_v3

    db = _db()
    m = run_backtest_v3("v50_slope", "2025-09-12", "2026-09-12", db)
    assert m["trades_count"] == 74, "v50_slope 在 golden 窗口上仍是 74 笔"


# --- 其余三个引擎的统一形状（评审焦点 3：适配器只测了 1/4 个引擎）---
#
# 用 preview（chase_up / uptrend 的 preview ≈ 5 秒）或 cycle 的**无缺口**极小窗口。
# cycle 在含停牌缺口的窗口上会崩（引擎自身缺陷，已登记，非本适配器问题），
# 故 2025-10-08..2025-10-20 是实测无缺口、可稳定出笔的窗口。


def _assert_uniform_shape(got: RunResult, *, engine: str, preset: str) -> None:
    assert isinstance(got, RunResult)
    assert got.engine == engine and got.preset == preset
    assert isinstance(got.trades, list)
    assert all(isinstance(t, dict) for t in got.trades), "trades 必须归一为 list[dict]"
    assert isinstance(got.metrics, dict)
    assert "trades_count" in got.metrics, "适配器必须保证统一键 trades_count 存在"
    assert got.metrics["trades_count"] == len(got.trades)


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_run_returns_the_uniform_shape_for_chase_up():
    """chase_up：包装 dict + DataFrame trades → 统一 RunResult（此前零覆盖）。"""
    got = run("chase_up", "chase_v1_atr_tp4_sl1", "2025-09-12", "2026-03-12", mode="preview")
    _assert_uniform_shape(got, engine="chase_up", preset="chase_v1_atr_tp4_sl1")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_run_returns_the_uniform_shape_for_uptrend_pullback():
    """uptrend_pullback：同 chase_up（包装 dict + DataFrame）→ 统一 RunResult（此前零覆盖）。"""
    got = run("uptrend_pullback", "v33_long_reverse_v21", "2025-09-12", "2026-03-12",
              mode="preview")
    _assert_uniform_shape(got, engine="uptrend_pullback", preset="v33_long_reverse_v21")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_run_returns_the_uniform_shape_for_cycle_price_action():
    """cycle_price_action：date 入参 + frozen-dataclass 出参 → 统一 RunResult。

    窗口必须无停牌缺口（含缺口时引擎自身抛 RuntimeError，非本适配器问题）。
    """
    got = run("cycle_price_action", "PRESET_V1", "2025-10-08", "2025-10-20")
    _assert_uniform_shape(got, engine="cycle_price_action", preset="PRESET_V1")


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_the_preview_window_yields_enough_bars_on_the_DEFAULT_ui_path():
    """**preview 必须在 UI 默认路径上真的跑得起来。**

    这是本会话实测漏掉的一条：平台原来有一条"真实 preview 端到端"测试，
    它用 `end="2026-09-12"`，**恰好**凑到 200 根 bar（== min_bars，零余量）而通过；
    而 UI 默认 `end` 是**今天** —— 那时引擎的 `+60d` 后置窗口里没有数据，
    面板只剩 270 天 ≈ **178 根**，`short_reversal`（101 个预设里的 75 个）
    必然抛 `WindowTooShortError`。

    **所以这条测试的判据是 realized bar 数，不是"能不能跑"**：
    它复现 UI 的默认输入、按引擎自己的面板算术算出**实际**能拿到多少根 bar，
    并要求比 `min_bars` 多留 10%。"恰好等于"不叫通过。
    """
    import datetime as dt

    import duckdb

    from web.runners import STRICTEST_MIN_BARS

    db = _db()
    con = duckdb.connect(str(db), read_only=True)
    try:
        last = con.execute("SELECT max(date) FROM v_daily_hfq").fetchone()[0]
        assert last is not None, "库内没有日线数据"

        # UI 默认：end = 今天（这里用库内最后一个交易日等价地代表它）
        start, end = effective_window("preview", "2000-01-01", last.isoformat())
        # 引擎的面板 = [start - 180d, end + 60d]，但**可用的只有到 last 为止的 bar**
        panel_start = dt.date.fromisoformat(start) - dt.timedelta(days=180)
        panel_end = min(dt.date.fromisoformat(end) + dt.timedelta(days=60), last)
        n = con.execute(
            "SELECT count(DISTINCT date) FROM v_daily_hfq WHERE date BETWEEN ? AND ?",
            [panel_start.isoformat(), panel_end.isoformat()],
        ).fetchone()[0]
    finally:
        con.close()

    need = int(STRICTEST_MIN_BARS * 1.1)
    assert n >= need, (
        f"preview 在 UI 默认路径（end={last}）上面板只有 {n} 个交易日，"
        f"低于所需 {need}（= 1.1 × min_bars={STRICTEST_MIN_BARS}）。\n"
        f"面板实际覆盖 {panel_start}..{panel_end}，窗口 {start}..{end}"
        f"（PREVIEW_DAYS={PREVIEW_DAYS}）。\n"
        "这会让 short_reversal（75/101 个预设）在 preview 下必然抛 "
        "WindowTooShortError —— 调大 PREVIEW_DAYS，别把余量卡到边界上。"
    )


def test_the_equity_curve_of_a_wrapped_engine_is_kept_not_dropped():
    """**chase_up / uptrend_pullback 的净值曲线本来就有，不该被适配器丢掉。**

    实测（2026-10-22）：这两个引擎的 `run_backtest` 返回
    `{"metrics": …, "trades": …, "equity": equity_df}`（`equity_df` 的列是
    `date/cash/holdings/equity`，见 `chase_up/portfolio.py`），
    而适配器只取了 `metrics` 与 `trades`，**把 `equity` 扔了**。

    丢掉的后果不是"少一张图"：没有曲线时平台的结果页**头部收益曲线、每日收益、
    每日持仓全都没有**，指标表也退化成引擎口径 —— 而聚宽那边每个策略都有这些。

    （`cycle_price_action` 是真的没有组合级曲线，它保持引擎口径并被**标注**出来。）
    """
    import pandas as pd

    from web.runners import _as_equity_curve

    df = pd.DataFrame({"date": ["2025-01-02", "2025-01-03"],
                       "cash": [1e6, 1e6], "holdings": [0, 100],
                       "equity": [1_000_000.0, 1_005_000.0]})
    curve = _as_equity_curve(df)
    assert curve == [{"date": "2025-01-02", "equity": 1_000_000.0},
                     {"date": "2025-01-03", "equity": 1_005_000.0}]
    # 没有曲线（cycle）→ 空列表，而不是崩
    assert _as_equity_curve(None) == []
    assert _as_equity_curve(pd.DataFrame()) == []
    # 形状不对（缺列）→ 空列表，而不是编一条
    assert _as_equity_curve(pd.DataFrame({"date": ["2025-01-02"]})) == []


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_chase_up_run_now_carries_an_equity_curve():
    """端到端：chase_up 跑一次应当**带曲线** —— 头部图表、每日收益、每日持仓都靠它。"""
    # 用 golden 里那个**已知有成交**的预设与窗口 —— 随手挑一个窗口会撞上"0 笔信号"，
    # 而引擎对空成交有一条**早返回**分支（`chase_up/backtest.py:33`），
    # 它**不带 `equity`**，于是这条测试会红在一个与"曲线被丢"无关的原因上（实测踩过）。
    got = run("chase_up", "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16",
              "2025-09-19", "2026-09-19")
    assert got.trades, "该窗口应当有成交（否则测的是空成交早返回分支，不是本缺陷）"
    curve = got.metrics.get("equity_curve")
    assert curve, "chase_up 的曲线被丢了 —— 结果页会没有收益曲线/每日收益/每日持仓"
    assert {"date", "equity"} <= set(curve[0]), f"曲线形状不对：{curve[0]}"
    assert len(curve) > 20, "曲线点数太少，可能是空帧"


def test_all_four_engines_are_registered_without_needing_the_database():
    """**四个引擎都注册了适配器** —— 这条不该被 DB 门控。

    原来只有 DB 门控的测试守着它：没有本地库时，`_RUNNERS` 少一项**整套全绿**。
    而"少一个引擎"意味着它的所有预设**在界面上直接消失**（目录会少 22 或 3 个预设），
    没有任何测试会察觉。

    这条只读模块里的注册表，**不需要数据库**。
    """
    from web.runners import _RUNNERS

    assert set(_RUNNERS) == {
        "short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"
    }, f"适配器注册表少了引擎：{set(_RUNNERS)}"
    for name, fn in _RUNNERS.items():
        assert callable(fn), f"{name} 的适配器不可调用"
