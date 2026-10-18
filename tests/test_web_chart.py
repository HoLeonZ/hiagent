"""图表数据：SL/TP 方向、K 线价域、指标价域（§3、§4、§4.6.1）。"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from web.chart import ENGINE_DIRECTION, chart_payload, sl_tp_prices

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


def _db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    return REAL_DB if REAL_DB.exists() else None


def test_short_puts_stop_above_and_target_below_entry():
    sl, tp = sl_tp_prices(10.0, sl_pct=0.05, tp_pct=0.08, direction="short")
    assert sl == pytest.approx(10.5)
    assert tp == pytest.approx(9.2)


def test_long_puts_stop_below_and_target_above_entry():
    sl, tp = sl_tp_prices(10.0, sl_pct=0.05, tp_pct=0.08, direction="long")
    assert sl == pytest.approx(9.5)
    assert tp == pytest.approx(10.8)


def test_every_engine_declares_a_direction():
    assert set(ENGINE_DIRECTION) == {
        "short_reversal", "chase_up", "uptrend_pullback", "cycle_price_action"
    }
    assert set(ENGINE_DIRECTION.values()) <= {"short", "long"}


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_direction_matches_the_run_results_pnl_sign():
    """方向的**可判别性**检查：如果某个引擎的方向标反了，这条必须变红。

    空头的 gross_pnl = (entry - exit) × size（replay_strategy_v3.py:117），
    故对一个盈利的空头交易，exit < entry。方向标反会让 SL/TP 画在错误的一侧。
    """
    from web.runners import run

    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    winners = [t for t in got.trades if t.get("gross_pnl", 0) > 0]
    if not winners:
        pytest.skip("该窗口没有盈利交易，无法做方向判别")
    t = winners[0]
    assert t["exit_price"] < t["entry_price"], "空头盈利交易必须 exit < entry"
    assert ENGINE_DIRECTION["short_reversal"] == "short"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_chart_payload_has_raw_candles_and_sl_tp():
    from web.runners import run

    db = _db()
    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    if not got.trades:
        pytest.skip("该窗口没有交易")
    params = got.metrics.get("_params") or {"sl_pct": 0.0005, "tp_pct": 0.08}
    payload = chart_payload("short_reversal", params, got.trades[0], db)
    assert {"bars", "entry", "exit", "sl_price", "tp_price", "direction"} <= set(payload)
    bar = payload["bars"][0]
    for col in ("date", "raw_open", "raw_high", "raw_low", "raw_close"):
        assert col in bar, f"K 线缺列 {col}"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_indicators_come_from_the_ADJUSTED_domain_not_raw():
    """§4.6.1：既有报告在**原始价**上算 MA，与策略决策所用（复权价）不是同一组数字。

    本平台必须喂**复权**价。这条测试的可判别性在于：同一只票用两个价域算出的
    ma60 必须**不同**（本库 raw 与 adj 平均偏差过半），且 payload 给的是复权那一组。
    """
    from short_reversal.render_trade_detail import compute_indicators

    from web.runners import run
    from web.chart import _load_dual_bars, _indicators_on_adj

    db = _db()
    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    if not got.trades:
        pytest.skip("该窗口没有交易")
    code = got.trades[0]["thscode"]
    bars = _load_dual_bars(db, code, "2025-09-12", "2026-09-12")
    if bars.empty:
        pytest.skip("该票在窗口内无 bar")

    # 复权域：平台实际给图表用的那一组
    on_adj = _indicators_on_adj(bars)

    # 原始域：既有的报告层就是这么算的（把 raw_close 当作 close 直接喂进去）
    raw_work = bars.copy()
    raw_work["close"] = raw_work["raw_close"]
    on_raw = compute_indicators(raw_work)

    a = on_adj["ma60"].dropna()
    r = on_raw["ma60"].dropna()
    # ⚠️ **不能 skip**。原先这里写的是 `pytest.skip("暖机不足，无法比较")`，
    # 于是当 `PAD_DAYS` 取 75（日历日 ≈ 46 根）时，`ma60` 整段全是 NaN、
    # `dropna()` 为空 → **这条测试报 skipped**，而它正是唯一守住 §4.6.1 的那条。
    # **"暖机不足"是缺陷，不是合法情形**：它意味着图上那条 MA60 线根本不会出现。
    assert not a.empty and not r.empty, (
        f"暖机不足：复权域 ma60 有效值 {len(a)} 个、原始域 {len(r)} 个。"
        "载入窗口必须足够长（见 PAD_DAYS 的说明）——"
        "暖机不足会让 MA60 整条线从图上消失，而这条测试的存在意义就是拦住它。"
    )
    rel = abs(a.iloc[-1] - r.iloc[-1]) / max(abs(r.iloc[-1]), 1e-9)
    assert rel > 0.01, (
        "本库 raw 与 adj 平均偏差过半，两个价域算出的 ma60 不应相同——"
        "若相同，说明这条测试已失去判别力"
    )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_the_PAYLOAD_itself_carries_adjusted_domain_indicators():
    """**§4.6.1 真正的守门测试：断言落在 `chart_payload` 的输出版上。**

    上面那条只比较 `_indicators_on_adj(bars)` 与本地 raw 域结果，
    **一次都没碰 `chart_payload`**。于是 `chart_payload` 哪天不再走
    `_indicators_on_adj`（例如有人重构时直接在原始价上算），那条**仍然全绿**——
    **它守的是辅助函数，不是用户真正看到的那份数据**。

    本条自足地判定。payload 自带 `raw_close` 与 `adj_close`，
    所以可以**只用 payload 自己的 bar 序列**在两域上各算一次 ma60，
    再断言 payload 里的 `ma60` 等于**复权**那一组、且**明显不等于**原始那一组。
    不需要跑回测（用合成交易即可），所以它是秒级的——
    上面那条要跑一整年全 universe，40 分钟。
    """
    import numpy as np
    import pandas as pd

    from web.chart import chart_payload

    db = _db()
    # 合成一笔交易：本测试只检验**价域与暖机**，不检验策略逻辑，
    # 故不需要真实成交记录（那要跑 13 分钟的全 universe 回测）。
    trade = {"thscode": "000001.SZ", "entry_date": "2026-03-02",
             "exit_date": "2026-03-10", "entry_price": 12.0, "exit_price": 11.5,
             "exit_reason": "SL"}
    d = chart_payload("short_reversal", {"sl_pct": 0.05, "tp_pct": 0.08}, trade, db)
    assert d["bars"], "没有 bar 就无法判定"

    df = pd.DataFrame(d["bars"])
    assert {"raw_close", "adj_close", "ma60"} <= set(df.columns)

    ma_adj = df["adj_close"].rolling(60).mean()
    ma_raw = df["raw_close"].rolling(60).mean()
    got = df["ma60"]
    usable = ma_adj.notna() & ma_raw.notna() & got.notna()

    # 判别力自检：可比较的 bar 必须够多，否则"未发现不一致"是一句空话
    assert usable.sum() >= 20, (
        f"只有 {usable.sum()} 根 bar 可比 —— 暖机不足（见 PAD_DAYS 的说明），"
        "这条测试会失去判别力"
    )

    assert np.allclose(got[usable], ma_adj[usable], rtol=1e-9), \
        "payload 里的 ma60 **不是**复权域算出来的（§4.6.1）"
    rel = ((ma_raw[usable] - ma_adj[usable]).abs() / ma_adj[usable].abs()).max()
    assert rel > 0.01, (
        f"两个价域算出的 ma60 差异只有 {rel:.4f} —— 本库 raw 与 adj 偏差过半，"
        "这条测试已失去判别力"
    )


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_the_entry_bar_actually_has_indicators_not_None():
    """**入场那根 bar 上，指标必须真的算得出来。**

    这是上面那条 §4.6.1 测试的**独立姊妹**：那条证明"价域对"，这条证明"算得出来"。
    两者都会因暖机不足而失去意义——只是那条会 skip（已被改成 assert），这条直接红。

    实测过它抓得住：`PAD_DAYS=75`（日历日）时只载入 46 根 bar，`ma60` 在
    **整段窗口**都是 NaN，入场 bar 上 `bars[-1]["ma60"] is None`。
    `macd_*` 不会 NaN（`ewm` 初值有偏），所以**必须单独断言 ma60**——
    只看 `macd_dif is not None` 会让这条测试在暖机不足时也是绿的。
    """
    from web.params import split_params
    from web.runners import run
    from web.chart import chart_payload

    db = _db()
    got = run("short_reversal", "v50_slope", "2025-09-12", "2026-09-12")
    if not got.trades:
        pytest.skip("该窗口没有交易")
    trade = got.trades[0]
    params = dict(split_params("short_reversal", "v50_slope")["tunable"])

    d = chart_payload("short_reversal", params, trade, db)
    assert d["bars"], "没有 bar 就不可能画出图"

    entry_bar = next((b for b in d["bars"] if b["date"] == str(trade["entry_date"])[:10]), None)
    assert entry_bar is not None, "入场 bar 必须落在载入窗口内"
    for col in ("ma5", "ma20", "ma60", "macd_dif"):
        assert entry_bar[col] is not None, (
            f"入场 bar 上 {col} 是 None —— 暖机不足，图上会缺线（见 PAD_DAYS 的说明）"
        )


#: `core/trade_report.py` 在平台动工时的内容哈希（§6 golden 惯例）。
#:
#: **为什么用哈希、不用 `git diff HEAD`**：原实现跑的是
#: `git diff --name-only HEAD`，比的是**工作树 vs HEAD** ——
#: 一旦改动被**提交**，diff 就是空的，这条守卫**永远绿**，
#: 与它 docstring 说的"一旦有人改它就变红"**正好相反**。
#: 哈希锁的是**内容**，与提交与否无关。
#: 真要改这个共用文件，就重生成该常量并在 PR 里说明漂移（§6 对 golden 基线的要求）。
TRADE_REPORT_SHA256 = "5d85f72f2783b543d63f4d7841ea41df0d36c78e5089f012ec4aad73bffe6823"


def test_the_shared_renderer_is_not_modified():
    """本计划**不碰** `core/trade_report.py`（四引擎共用，见设计文档 §5）。

    它是范本不是依赖。这条锁**内容哈希**，所以改动提交与否都拦得住。
    """
    import hashlib
    from pathlib import Path

    p = Path("core/trade_report.py")
    assert p.is_file(), "文件被删或被改名，同样算改动"
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    assert got == TRADE_REPORT_SHA256, (
        "core/trade_report.py 变了。它是四个引擎共用的渲染器，本平台只以它为范本。\n"
        f"  期望 {TRADE_REPORT_SHA256}\n"
        f"  实际 {got}\n"
        "若这次改动是有意的：请在 PR 里说明理由，并同步更新 TRADE_REPORT_SHA256。"
    )
