"""§6/§0: CAGR 的分母必须是**实际评估期**, 不能是**请求窗**。

缺陷 (2026-10-17, 第 8 处, 族内不对称):
    short_reversal/engine.py 的两条路径都用
        years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365   # 请求窗
    而三个姊妹引擎**全都**用实际评估期的交易日数:
        chase_up/backtest.py            years = max(len(eq) / TRADING_DAYS, 1e-9)
        uptrend_pullback/backtest.py    同上
        cycle_price_action/allocator.py years = n / TRADING_DAYS_PER_YEAR
    同一仓库里同一个 `cagr` 字段被两种口径定义, 本引擎是唯一的少数派。

为什么它不是纯口径偏好: 本引擎的**实测期可以显著偏离请求窗**。
实测 (v58_mp_2, 请求 `2018-01-01..2020-12-31`):
    请求窗        1095 天 = 3.00 年
    equity_curve  2019-02-18 .. 2021-03-01, 495 行 = 1.96 年
    ⇒ 分母长 1.53 倍 ⇒ 报告 CAGR −25.15%, 而按实测期为 −34.8%
    ⇒ **低估亏损 9.7pp**。偏差方向是美化, 与 §0「Pessimistic Default」相反,
      与 §4 跳空成交口径同族 (都在亏损腿上把结果往好处挪)。

起点为什么晚 1.13 年**仍未解** (四个假设被实验否证), 但换分母**不依赖**解开它:
实测期是引擎自己吐出的可观测事实 (equity_curve 首末行), 不是推断。

本文件三层钉桩:
  1. 静态: 请求窗公式只能出现在 `_years_between` 的 "none" 回退里 (恰 1 处);
  2. 行为 (无需 DB): `_evaluated_days` / `_years_between` 必须给出实测口径;
  3. 行为 (需 DB): 真跑一次, 断言 cagr 可由 `total_yield + evaluated_years` 复现。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


# ---------- 1. 静态 ----------

def test_request_window_formula_appears_exactly_once() -> None:
    """请求窗公式只允许留在 `_years_between` 的退化回退里。

    若有人把 `(end - start)` 再加回 `_metrics_from_holder` / `_run_ensemble`,
    这里会变 2 处或更多 ⇒ 失败。
    """
    n = len(re.findall(r"\(pd\.Timestamp\(end\) - pd\.Timestamp\(start\)\)", SRC))
    assert n == 1, (
        f"请求窗公式出现 {n} 次 —— 它必须只在 `_years_between` 的 source=='none' 回退里"
        f"(实测期是权威口径, 见 defects 说明)"
    )


def test_both_paths_delegate_the_denominator() -> None:
    """两条路径 (单策略 / ensemble) 都必须走 `_years_between`。"""
    assert SRC.count("_years_between(") >= 3, "定义 1 处 + 调用 2 处 (单策略/ensemble)"
    assert "_evaluated_days(" in SRC


def test_sibling_engines_use_row_count_basis() -> None:
    """族内一致性: 三个姊妹引擎的分母必须是权益行数口径。

    这条的作用是**反向**的 —— 钉住"多数派"的口径, 这样将来谁把姊妹引擎改成
    请求窗, 也会被同一条测试拦下。
    """
    for rel in ("chase_up/backtest.py", "uptrend_pullback/backtest.py"):
        s = (ROOT / rel).read_text(encoding="utf-8")
        assert re.search(r"years\s*=\s*max\(n_days\s*/\s*TRADING_DAYS", s), (
            f"{rel} 的 CAGR 分母已不再是 `n_days / TRADING_DAYS`"
        )
    s = (ROOT / "cycle_price_action" / "allocator.py").read_text(encoding="utf-8")
    assert re.search(r"years\s*=\s*n\s*/\s*TRADING_DAYS_PER_YEAR", s), (
        "cycle_price_action/allocator.py 的 CAGR 分母已改变"
    )


# ---------- 2. 行为 (无需 DB) ----------

def _fake_equity(first: date, last: date, n: int) -> list[dict]:
    """n 行权益曲线, 首末日期给定 (中间日期内容对本测试无意义)。"""
    mid = [date(2020, 1, 1)] * (n - 2)
    return [{"date": d} for d in [first, *mid, last]]


def test_evaluated_days_prefers_equity_curve() -> None:
    from short_reversal.engine import _evaluated_days

    ec = _fake_equity(date(2019, 2, 18), date(2021, 3, 1), 495)
    first, last, n, source = _evaluated_days(ec, [])
    assert (first, last, n) == (date(2019, 2, 18), date(2021, 3, 1), 495)
    assert source == "equity_curve"


def test_evaluated_days_falls_back_to_trades_then_none() -> None:
    from short_reversal.engine import _evaluated_days

    trades = [
        {"entry_time": "2019-03-01", "exit_time": "2019-03-05"},
        {"entry_time": "2020-07-01", "exit_time": "2020-07-09"},
    ]
    first, last, n, source = _evaluated_days(None, trades)
    assert (str(first), str(last), source) == ("2019-03-01", "2020-07-09", "trades")

    assert _evaluated_days(None, []) == (None, None, 0, "none")


def test_years_uses_evaluated_days_not_request_window() -> None:
    """核心行为断言: 495 个交易日必须是 1.96 年, 不是请求窗的 3.00 年。"""
    from short_reversal.engine import _years_between

    tight = _years_between("2018-01-01", "2020-12-31", 495, "equity_curve")
    loose = _years_between("2018-01-01", "2020-12-31", 0, "none")  # 退化回退 = 请求窗
    assert abs(tight - 495 / 252) < 1e-9
    assert abs(loose - 3.0) < 0.01
    assert loose / tight > 1.4, "两个口径必须**显著**不同, 否则本测试退化成恒真"


def test_correction_is_not_cosmetic() -> None:
    """修正必须改变结论量级 —— 用实测样本的累计收益验算。

    实测样本: final/initial 由报告 CAGR(−25.15%) 反推。
    若两个分母产出的 CAGR 相差 <1pp, 说明这条修正没有实际意义 (那就不该改)。
    """
    reported_cagr, years_request, years_evaluated = -0.2514782096843088, 3.0, 495 / 252
    final_ratio = (1.0 + reported_cagr) ** years_request
    corrected = final_ratio ** (1.0 / years_evaluated) - 1.0
    assert corrected < reported_cagr - 0.05, (
        f"按实测期 CAGR={corrected:.4f} 与报告值 {reported_cagr:.4f} 差异不足 5pp —— "
        f"这条修正没有实际后果, 应重新评估是否值得改"
    )


def test_metrics_from_holder_uses_equity_span_not_request_window() -> None:
    """**承重断言**: `_metrics_from_holder` 的分母必须来自 holder 里的权益曲线。

    这是本文件唯一能在缺陷态失败的**快速**断言, 因为它直接对比
    「请求窗 3.00 年」与「权益曲线实测 1.96 年」这两个**来源不同**的量。

    ⚠️ 反面教材 (本轮实测): 我曾经只写「cagr 可由 total_yield + evaluated_years 复现」
    这一条 —— 它在缺陷态**照样通过**, 因为缺陷态下 `evaluated_years` 与 `cagr`
    由**同一个**错误 `years` 派生, 内部自洽。一条只检查"两个字段互相一致"的断言,
    在两个字段同源时是**空泛的** (本仓库已踩过 4 个空泛 guard, 见 commit `e3d043b`)。
    承重的是这条: **披露的年数必须与曲线自己的跨度一致**。
    """
    from short_reversal.engine import _metrics_from_holder

    n_rows = 495
    eq = [{"date": date(2019, 2, 18)}] + [{"date": date(2020, 1, 1)}] * (n_rows - 2) + [
        {"date": date(2021, 3, 1)}
    ]
    holder = {"cash": 1_000_000.0 * 0.8, "trades": [], "max_dd": 0.1, "equity_curve": eq}
    m = _metrics_from_holder(holder, "2018-01-01", "2020-12-31", {"_name": "t"})

    assert abs(m["evaluated_years"] - n_rows / 252) < 1e-9, (
        f"分母取到 {m['evaluated_years']:.4f} 年 —— 权益曲线只有 {n_rows} 个交易日 "
        f"({n_rows / 252:.4f} 年)。若等于请求窗的 3.00 年, 说明又打回了请求窗口径。"
    )
    assert m["evaluated_start"] == "2019-02-18"
    assert m["evaluated_end"] == "2021-03-01"
    # cagr 也必须用同一个实测分母 (而非只改披露字段、留下 cagr 用请求窗)
    expect = (1.0 + m["total_yield"]) ** (1.0 / (n_rows / 252)) - 1.0
    assert abs(m["cagr"] - expect) < 1e-9


# ---------- 3. 行为 (需 DB) ----------

def _db_path() -> Path | None:
    """真实 DB 路径。**不要写死路径** —— 写错会让 skipif 恒真、guard 变空泛
    (本仓库已踩过: 4 个成本 guard 里有 3 个是空泛的, 见 commit `e3d043b`)。"""
    try:
        from hiagent_config import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return None


@pytest.mark.skipif(_db_path() is None, reason="需要本地 DB (§6: 缺产物时 skip, 不 error)")
def test_reported_cagr_is_reproducible_from_evaluated_years() -> None:
    """真跑一次: cagr 必须能由 `total_yield` + `evaluated_years` 复现, 且实测期
    必须等于 equity_curve 的首末日期。
    """
    from short_reversal.engine import run_backtest_v3

    db = _db_path()
    assert db is not None
    m = run_backtest_v3("v58_mp_2", "2018-01-01", "2020-12-31", db)
    ec = m["equity_curve"]
    if not ec:
        pytest.skip("本次运行未产出权益曲线, 无法核对实测期")

    dates = [r["date"] for r in ec if r.get("date")]
    assert m["evaluated_start"] == str(min(dates))
    assert m["evaluated_end"] == str(max(dates))
    assert abs(m["evaluated_years"] - len(dates) / 252) < 1e-9

    recomputed = (1.0 + m["total_yield"]) ** (1.0 / m["evaluated_years"]) - 1.0
    assert abs(recomputed - m["cagr"]) < 1e-9, (
        f"cagr={m['cagr']:.6f} 不能由 total_yield={m['total_yield']:.6f} 与 "
        f"evaluated_years={m['evaluated_years']:.4f} 复现 —— 分母与披露字段不同源"
    )

    # 请求窗口径必须与实测口径**可区分**, 否则这条断言在该样本上无信息量。
    request_years = (date(2020, 12, 31) - date(2018, 1, 1)).days / 365
    assert abs(request_years - m["evaluated_years"]) > 0.5, (
        f"本样本请求窗 {request_years:.2f}y 与实测期 {m['evaluated_years']:.2f}y 太接近 —— "
        f"该样本无法区分两种口径, 请换一个偏离明显的窗口"
    )
