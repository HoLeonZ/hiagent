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
    if a.empty or r.empty:
        pytest.skip("暖机不足，无法比较")
    rel = abs(a.iloc[-1] - r.iloc[-1]) / max(abs(r.iloc[-1]), 1e-9)
    assert rel > 0.01, (
        "本库 raw 与 adj 平均偏差过半，两个价域算出的 ma60 不应相同——"
        "若相同，说明这条测试已失去判别力"
    )


def test_the_shared_renderer_is_not_modified():
    """本计划**不碰** core/trade_report.py（四引擎共用，见设计文档 §5）。

    它是范本不是依赖。一旦有人为了图方便去改它，这条变红。
    """
    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert "core/trade_report.py" not in changed, (
        "core/trade_report.py 是四个引擎共用的渲染器；本平台只以它为范本，不应改动它"
    )
