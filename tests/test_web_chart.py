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
    on_adj = _indicators_on_adj("short_reversal", bars)

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

#: ⚠️ **锚到本文件的位置。** 用 `Path("core/trade_report.py")` 这种相对路径时，
#: 它相对的是 **pytest 的启动目录**：从仓库根跑绿、换目录跑红，
#: 而红了的消息会是"文件被删或被改名"——把"找错了地方"说成"文件没了"。
#: 假警报会诱使人把这条守卫改弱或删掉。
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_shared_renderer_is_not_modified():
    """本计划**不碰** `core/trade_report.py`（四引擎共用，见设计文档 §5）。

    它是范本不是依赖。这条锁**内容哈希**，所以改动提交与否都拦得住。
    """
    import hashlib

    p = REPO_ROOT / "core" / "trade_report.py"
    assert p.is_file(), "文件被删或被改名，同样算改动"
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    assert got == TRADE_REPORT_SHA256, (
        "core/trade_report.py 变了。它是四个引擎共用的渲染器，本平台只以它为范本。\n"
        f"  期望 {TRADE_REPORT_SHA256}\n"
        f"  实际 {got}\n"
        "若这次改动是有意的：请在 PR 里说明理由，并同步更新 TRADE_REPORT_SHA256。"
    )


def test_exit_levels_are_omitted_when_the_engine_does_not_use_them():
    """**引擎不按这两个百分比出场时，就不许画那条线。**

    实测（2026-10-19）：`chase_up/backtrader_engine.py:43-47` 在给了 `atr_*_mult` 时改用
    信号日 ATR 自适应，而 **chase_up 的 22/22 个预设都带 `atr_*_mult`** ——
    于是 `sl_pct` / `tp_pct` 是引擎**根本不看**的 fallback。
    原实现一律按 `entry × (1 ± sl_pct)` 画，差别不小：
    `atr_tp_mult=6.0`、典型 `atr_pct=3%` → 真实止盈约 **+18%**，而画出来是 **+30%**。

    **画一条引擎没用过的线，比不画更坏** —— 它让用户以为策略是按那条线退出的。
    """
    from web.chart import exit_levels

    ATR_FULL = {"sl_pct": 0.05, "tp_pct": 0.30, "atr_sl_mult": 1.5, "atr_tp_mult": 6.0}
    # 带全 atr_* 且这一笔的 atr_pct 有效 → 引擎走 ATR 分支 → **不画**
    assert exit_levels(ATR_FULL, 10.0, "long", 0.03) is None
    # ⚠️ `atr_pct` 是**逐笔**的运行时值。它缺失或 NaN 时，引擎**同样**回落到 fixed
    # —— 那时平台就**应该**照画。少镜像这一项 = 过度抑制。
    for bad in (None, float("nan")):
        sl, tp = exit_levels(ATR_FULL, 10.0, "long", bad)
        assert (sl, tp) == (9.5, 13.0), f"atr_pct={bad!r} 时引擎回落 fixed，平台必须照画"
    # 只给一个 atr_* 时，引擎的条件（两个都非 None）不成立 → 回落 fixed → 照画
    sl, tp = exit_levels({"sl_pct": 0.05, "tp_pct": 0.30, "atr_sl_mult": 1.5}, 10.0, "long")
    assert (sl, tp) == (9.5, 13.0), "只给了一半 atr_* → 引擎走 fixed 分支 → 平台应当照画"
    # 没给 atr_*_mult：引擎走 fixed 分支 → 画
    sl, tp = exit_levels({"sl_pct": 0.05, "tp_pct": 0.30}, 10.0, "long")
    assert (sl, tp) == (9.5, 13.0)
    # 缺失 ≠ 0：原实现用 `params.get("sl_pct", 0.0)`，缺失被折成真 0，
    # 于是止损线与止盈线**同时落在入场价上**，看起来"设了止损"其实是 0。
    assert exit_levels({"tp_pct": 0.30}, 10.0, "long") is None
    assert exit_levels({"sl_pct": 0.05}, 10.0, "long") is None
    # 空头方向相反
    sl, tp = exit_levels({"sl_pct": 0.0005, "tp_pct": 0.06}, 8.01, "short")
    assert sl > 8.01 > tp


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_chase_up_trade_gets_no_sl_tp_lines_from_the_platform():
    """端到端：**chase_up 的任何一笔都不该拿到 SL/TP 价位**（它按 ATR 出场）。"""
    from web.chart import chart_payload, exit_levels
    from web.params import split_params

    params = dict(split_params("chase_up", "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16")["tunable"])
    assert params.get("atr_sl_mult") is not None and params.get("atr_tp_mult") is not None, \
        "这个预设本该带 atr_*_mult —— 若不再带，这条测试的前提就变了"
    trade = {"thscode": "000001.SZ", "entry_date": "2026-03-02", "exit_date": "2026-03-10",
             "entry_price": 12.0, "exit_price": 12.5, "exit_reason": "TP"}
    # 给这一笔一个**有效的** atr_pct —— 这正是真实 chase_up 成交的形态
    trade["atr_pct"] = 0.03
    d = chart_payload("chase_up", params, trade, _db())
    assert d["sl_price"] is None and d["tp_price"] is None, \
        "chase_up 这一笔按 ATR 出场，平台不许替它编一条百分比止损/止盈线"
    # 反例：这一笔的 atr_pct 缺失 → 引擎回落 fixed → 平台**应当**画
    trade["atr_pct"] = None
    d2 = chart_payload("chase_up", params, trade, _db())
    assert d2["sl_price"] is not None and d2["tp_price"] is not None, \
        "atr_pct 缺失时引擎走 fixed 分支，平台应当照画（否则是过度抑制）"


def _synthetic_bars(n=80):
    """一段合成日线（不查库）。只为让 MACD 有足够暖机。"""
    import numpy as np
    import pandas as pd

    close = pd.Series(10.0 + np.sin(np.arange(n) / 5.0) + np.arange(n) * 0.01)
    return pd.DataFrame({
        "thscode": "000001.SZ",
        "date": pd.bdate_range("2025-01-01", periods=n),
        "raw_open": close, "raw_close": close + 0.1, "raw_low": close - 0.2, "raw_high": close + 0.3,
        "adj_open": close, "adj_close": close + 0.1, "adj_low": close - 0.2, "adj_high": close + 0.3,
        "volume": 1000.0, "amount": 1e6,
    })


def test_indicators_come_from_each_engines_OWN_definition_not_one_of_them():
    """**按引擎分派**，不能拿 short_reversal 那一份给所有引擎。

    实测（2026-10-19）三个引擎的 `macd_bar` 口径不同：

      short_reversal   `(dif - dea) * 2`   （render_trade_detail.py:73）
      chase_up         `dif - dea`         （chase_up/signals.py，**没有 ×2**）
      uptrend_pullback `dif - dea`         （uptrend_pullback/signals.py）

    原实现对四个引擎都用 short_reversal 的，于是 chase_up / uptrend 的图上
    **MACD 柱是策略所见的 2 倍** —— 符号与交叉点相同，所以**看起来仍然合理**。
    图要解释的是"策略当时看到了什么"（§4.6.1），不是"看起来像什么"。

    判据取**两个引擎在同一段价格上的 `macd_bar` 之比**：正好 2 倍才算分派到位。
    """
    from web.chart import _indicators_on_adj

    bars = _synthetic_bars()
    sr = _indicators_on_adj("short_reversal", bars)
    cu = _indicators_on_adj("chase_up", bars)
    up = _indicators_on_adj("uptrend_pullback", bars)
    assert sr is not None and cu is not None and up is not None

    import numpy as np

    a = sr["macd_bar"].dropna().to_numpy()
    b = cu["macd_bar"].dropna().to_numpy()
    c = up["macd_bar"].dropna().to_numpy()
    n = min(len(a), len(b), len(c))
    assert n > 20, "暖机不足，这条测试失去判别力"
    # short_reversal 恰好是另两个的两倍
    assert np.allclose(a[-n:], b[-n:] * 2.0, rtol=1e-9), "chase_up 的 macd_bar 用错了口径"
    assert np.allclose(a[-n:], c[-n:] * 2.0, rtol=1e-9), "uptrend 的 macd_bar 用错了口径"
    # dif/dea 三家一致（只有 bar 的口径不同）—— 别把整份实现换成两套
    assert np.allclose(sr["macd_dif"].dropna().to_numpy()[-n:],
                       cu["macd_dif"].dropna().to_numpy()[-n:], rtol=1e-12)


def test_an_engine_without_its_own_indicator_definition_gets_none():
    """`cycle_price_action` **没有指标定义** → 不下发任何指标列。

    它的主程序不叠任何指标（设计 §4.5 那一行就是 `—`）。
    原实现给它套了 short_reversal 的公式 —— 那是**凭空造一组策略从没算过的数**。
    **没有就不画**，而不是拿别人的补上。
    """
    import pytest

    from web.chart import INDICATORS_BY_ENGINE, _indicators_on_adj

    assert "cycle_price_action" not in INDICATORS_BY_ENGINE, \
        "cycle 一旦有了自己的指标定义，这条测试的前提就变了 —— 那时应改的是它"
    assert _indicators_on_adj("cycle_price_action", _synthetic_bars()) is None


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_a_cycle_trade_payload_carries_candles_but_no_indicators():
    """端到端：cycle 的 payload 有 K 线、**没有** ma/macd 列。"""
    import datetime as dt

    from web.chart import chart_payload

    trade = {"thscode": "000001.SZ", "entry_date": "2026-03-02", "exit_date": "2026-03-10",
             "entry_price": 12.0, "exit_price": 12.5, "exit_reason": "TP"}
    d = chart_payload("cycle_price_action", {"sl_pct": 0.05, "tp_pct": 0.08}, trade, _db())
    assert d["bars"], "K 线仍要有"
    assert "raw_close" in d["bars"][0], "K 线是原始价"
    for col in ("ma5", "ma20", "ma60", "macd_dif", "macd_dea", "macd_bar"):
        assert col not in d["bars"][0], f"cycle 不该有 {col} —— 它没有自己的指标定义"


def test_the_columns_the_chart_uses_exist_in_the_shared_trade_schema():
    """**`web/chart.py` 用到的列必须来自 `core.trade_schema.TRADE_COLS`**。

    四引擎共用那 14 列规范（§6），而 `chart_payload` 直接写列名字面量。schema 改一次
    列名，这里就变成运行时的 `KeyError` → HTTP **500**，而**没有任何测试会察觉** ——
    因为测试各自造自己的残缺 trade（实测：测试里的 trade 只有 3–8 个字段）。

    `web/chart.py` 现在在导入时就校验一次（fail-fast），这里钉住那条不变式。
    """
    from core.trade_schema import TRADE_COLS

    from web.chart import _USED_TRADE_COLS

    missing = [c for c in _USED_TRADE_COLS if c not in TRADE_COLS]
    assert not missing, (
        f"web.chart 用到了不在共享 schema 里的列: {missing}；"
        "schema 与调用方已漂移（§6）"
    )
    # 反方向：schema 的列必须是**真实存在**的（防止有人往 TRADE_COLS 里塞幽灵列）
    assert len(TRADE_COLS) == 14, f"14 列规范变成了 {len(TRADE_COLS)} 列：{TRADE_COLS}"


@pytest.mark.skipif(_db() is None, reason=SKIP_REASON)
def test_the_chart_indicators_are_the_numbers_the_strategy_actually_used():
    """**图上的指标必须逐位等于策略当时算的那一组**（§4.6.1）。

    实测缺陷（2026-10-22）：`chase_up` 的策略用**前复权**（`chase_up/data.py`：
    "前复权价 v_daily_qfq"、"signal 仍用 adj (… from v_daily_qfq)"），
    而图用的是 `v_daily_dual.adj_*` —— 那个视图的定义是 `FROM v_daily_hfq`（**后复权**）。
    同一只票、同一天的 `ma20` 差 **+43.838%**（逐日同一个常数比）。

    **而且它看起来是对的** —— 后复权恰好接近原始价，MA 线正好贴着蜡烛。
    **看着对、其实是错**，是这类缺陷最阴险的形态：肉眼看不出任何问题。

    这条测试把**引擎自己的指标**与**图上的指标**放在同一天直接比 ——
    不是比"复权域对不对"，而是比**那个数**。
    """
    from chase_up.data import load_panel
    from chase_up.signals import compute_indicators

    from web.chart import PRICE_DOMAIN_BY_ENGINE, _indicators_on_adj, _load_dual_bars

    db = _db()
    code = "603843.SH"
    start, end = "2024-08-19", "2025-09-24"

    # 引擎自己那一组（它自己的面板 + 它自己的 compute_indicators）
    panel = load_panel(db, "2025-06-01", "2025-12-31", universe={code})
    eng = compute_indicators(panel)[["date", "ma20"]].copy()
    eng["date"] = eng["date"].astype(str).str[:10]
    eng_ma = eng.set_index("date")["ma20"]

    # 图上的那一组
    bars = _load_dual_bars(db, code, start, end,
                           PRICE_DOMAIN_BY_ENGINE["chase_up"])
    chart = _indicators_on_adj("chase_up", bars)
    chart["date"] = chart["date"].astype(str).str[:10]
    chart_ma = chart.set_index("date")["ma20"]

    # ⚠️ 必须同时挡掉 NaN —— 引擎的 ma20 在面板起点附近是 NaN（暖机不足），
    # 而 `x is not None` 挡不住 NaN，于是比较会变成 `nan < 1e-6` → 恒假。
    import math as _math

    common = [d for d in eng_ma.index if d in chart_ma.index
              and eng_ma[d] is not None and chart_ma[d] is not None
              and _math.isfinite(float(eng_ma[d])) and _math.isfinite(float(chart_ma[d]))]
    assert len(common) >= 5, f"可比的日子太少（{len(common)}）——这条测试会失去判别力"
    for d in common[:8]:
        e, c = float(eng_ma[d]), float(chart_ma[d])
        assert abs(c - e) / abs(e) < 1e-6, (
            f"{d}: 图上的 ma20={c:.4f}，引擎自己算的是 {e:.4f} —— 差 {(c-e)/e*100:+.2f}%。"
            "图上画的必须是策略当时看到的那一组数（§4.6.1）"
        )


def test_every_engines_direction_is_pinned_not_just_its_key():
    """**每个引擎的方向值都要被钉住**，不是只钉"键在不在"。

    原来那条测试只断言（a）四个键都在映射里、（b）取值 ∈ {short, long} ——
    (b) 对一个二值字段**近乎恒真**，它区分不出"谁是多、谁是空"。
    而方向标反的后果是**图上止损画在入场价下方、止盈画在上方**，与 §4 完全相反，
    且**没有任何守卫会喊**。

    这里把**每个引擎的具体方向**写下来，标反即红。
    """
    from web.chart import ENGINE_DIRECTION

    # 逐引擎的实测定论（2026-10-22 核对引擎源码）：
    #   short_reversal   空头（`replay_strategy_v3.py`：tp_p = ep*(1-tp_pct)）→ 止损在上、止盈在下
    #   chase_up         多头（`backtrader_engine.py`：tp = entry*(1+a*atr_tp_mult)）→ 止损在下、止盈在上
    #   uptrend_pullback 多头（同 chase_up 的口径）
    #   cycle_price_action 多头（`portfolio.py`：先买后卖）
    assert ENGINE_DIRECTION["short_reversal"] == "short"
    assert ENGINE_DIRECTION["chase_up"] == "long"
    assert ENGINE_DIRECTION["uptrend_pullback"] == "long"
    assert ENGINE_DIRECTION["cycle_price_action"] == "long"
