"""§5/§6 (第 9 处): short_reversal 的 `sharpe` 与三个姊妹引擎**不是同一个统计量**。

    引擎                              定义                        年化因子
    chase_up/backtest.py              日权益收益 mean/std         sqrt(243)
    uptrend_pullback/backtest.py      日权益收益 mean/std         sqrt(243)
    cycle_price_action/allocator.py   日权益收益 mean/std         sqrt(252)
    short_reversal/engine.py          逐笔 net_return mean/std    sqrt(min(n, 250))

逐笔口径 (per-trade IR) 是合法统计量, 但它**不含空仓日**, 也不含持仓重叠 -->
与日权益口径**不可跨族比较**。而本挖掘循环用 `sharpe` 排过序
(`short_reversal/walkforward.py`、`wf_vNN_focused.py` 十余个脚本),
所以"short_reversal vs uptrend 谁的 Sharpe 高"这个问题此前问得**不成立**。

实测 (v58_mp_2 / 2018-01-01..2020-12-31):
    逐笔口径  -1.761      (年化因子 15.811 = sqrt(min(686,250)) )
    日权益口径 -1.440      (年化因子 15.875 = sqrt(252) )
    空仓日占比 28.95%      ⇒ 两把尺子量的不是一件事
注意方向**不系统**: 与本案前 8 处缺陷不同, 它不是"美化", 空仓日越多日权益口径被
稀释越多。它的问题不是偏差, 是**换了一把尺子**。

**本轮决定: 登记 + 披露, 不覆盖 `sharpe`。**
理由: 逐笔 Sharpe 是合法且已发布的统计量, 换掉它属结果变更/口径选择 —— 按长期授权
「结果变更 / 口径选择 ⇒ 登记, 不擅自改」。本仓库对 `avg_pnl` 用过同一处理
(commit `4b6fbe1`: 保留既有定义 + 给出按名义额加权的版本)。

⚠️ 写本文件的教训 (Iteration 73): 我上一轮写出过一条**空泛 guard** ——
只断言"两个字段互相一致", 而两者同源时恒真。所以本文件的每一条都对比**来源不同**
的两个量, 并且每条都在**缺陷态**跑过一遍确认会红。
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")


# ---------- 1. 静态: 口径差异必须仍然存在且被登记 ----------

def test_reported_sharpe_is_still_the_trade_basis() -> None:
    """`sharpe` 必须仍是逐笔口径 —— 本轮**故意不改**它。

    这条是**双向**的: 若有一天有人把 `_approx_sharpe` 换成日权益口径, 本测试会红,
    提醒他这是结果变更, 必须重跑全部历史数字并改 §5 的 n_trials 记账。
    """
    assert 'arr = np.array([t["net_return"] for t in trades])' in SRC
    assert "math.sqrt(min(len(arr), 250))" in SRC, (
        "`_approx_sharpe` 的年化因子变了 —— 这是结果变更, 不是重构。"
        "若确属有意, 需同步更新本文件与 docs/strategy_mining_log.md 的登记。"
    )


def test_siblings_use_daily_equity_basis() -> None:
    """三个姊妹引擎必须是日权益口径 (反向钉桩: 防止有人把姊妹改成逐笔)。"""
    for rel in ("chase_up/backtest.py", "uptrend_pullback/backtest.py"):
        s = (ROOT / rel).read_text(encoding="utf-8")
        assert "rets = np.diff(eq) / eq[:-1]" in s, f"{rel} 的 sharpe 已不是日权益口径"
        assert re.search(r"sharpe = \(float\(np\.mean\(rets\)\) / std \* math\.sqrt", s), (
            f"{rel} 的 sharpe 公式结构变了"
        )
    s = (ROOT / "cycle_price_action" / "allocator.py").read_text(encoding="utf-8")
    assert "TRADING_DAYS_PER_YEAR ** 0.5" in s


def test_trading_days_constant_divergence_is_documented() -> None:
    """243/252 的常数分歧必须**紧贴常量定义**登记 —— 它是未统一项, 不能无声存在。

    没人会去读四个引擎的常量定义; 分歧只有写在常量旁边才可能被发现。

    ⚠️ 本测试的第一版是 `assert "243" in SRC` —— **它是空泛的**: 我实测把整段注释
    删掉后测试**仍然全绿**, 因为文件别处的 docstring 里也有 "243" 三个字符。
    裸子串判定会被无关出现满足 (审计 §(c) 点名的形态)。所以改成**块作用域**:
    必须匹配「紧贴常量的连续注释行」。
    """
    m = re.search(r"((?:^#.*\n)+)^TRADING_DAYS_PER_YEAR = 252", SRC, re.M)
    assert m, "TRADING_DAYS_PER_YEAR 的正上方必须紧跟一段登记注释"
    block = m.group(1)
    for token in (
        "chase_up/backtest.py",
        "uptrend_pullback/backtest.py",
        "cycle_price_action/allocator.py",
        "243",
        "252",
    ):
        assert token in block, f"常量上方那段登记注释缺 {token!r}"
    for rel, const in (("chase_up/backtest.py", "243"), ("uptrend_pullback/backtest.py", "243")):
        s = (ROOT / rel).read_text(encoding="utf-8")
        assert re.search(rf"^TRADING_DAYS = {const}", s, re.M), (
            f"{rel} 的 TRADING_DAYS 已不是 {const} —— 请同步本引擎的登记注释"
        )


# ---------- 2. 行为 (无需 DB): 两个口径必须真的不同 ----------

def test_equity_sharpe_matches_sibling_formula() -> None:
    """`_equity_sharpe` 必须与姊妹引擎公式**逐字等价** (用一个可手算的序列验)。"""
    import numpy as np

    from short_reversal.engine import _equity_sharpe

    eq = [100.0, 110.0, 99.0, 121.0, 121.0, 133.1]
    got = _equity_sharpe([{"equity": v} for v in eq])

    arr = np.asarray(eq)
    rets = np.diff(arr) / arr[:-1]
    std = float(np.std(rets, ddof=1))
    expect = float(np.mean(rets) / std * math.sqrt(252))
    assert got is not None and abs(got - expect) < 1e-12


def test_equity_sharpe_uses_252_not_243() -> None:
    """必须用 252。与 chase_up/uptrend 的 243 差 1.8% —— 差异可测, 故可断言。"""
    import numpy as np

    from short_reversal.engine import _equity_sharpe

    eq = [100.0, 110.0, 99.0, 121.0, 121.0, 133.1]
    arr = np.asarray(eq)
    rets = np.diff(arr) / arr[:-1]
    std = float(np.std(rets, ddof=1))
    base = float(np.mean(rets) / std)
    got = _equity_sharpe([{"equity": v} for v in eq])
    assert got is not None
    assert abs(got / (base * math.sqrt(243)) - math.sqrt(252 / 243)) < 1e-9


def test_equity_sharpe_is_none_on_degenerate_input() -> None:
    """退化输入必须给 None (不可量), 不能给一个看似有意义的 0.0。"""
    from short_reversal.engine import _equity_sharpe

    assert _equity_sharpe(None) is None
    assert _equity_sharpe([]) is None
    assert _equity_sharpe([{"equity": 1.0}, {"equity": 1.0}]) is None  # 行数不足
    assert _equity_sharpe([{"equity": 1.0}] * 5) is None  # 零方差


def test_two_bases_are_not_confounded_on_a_flat_heavy_series() -> None:
    """承重断言: 空仓日必须**改变**两个口径的相对大小。

    构造一条 30% 日子不变的权益曲线 —— 日权益口径会被稀释, 逐笔口径不会。
    若两者在本构造下相等, 说明我的 `_equity_sharpe` 其实在算逐笔口径 (写错了)。
    """
    import numpy as np

    from short_reversal.engine import _equity_sharpe

    # 每 10 天里 3 天不动, 其余交替 ±2%
    eq = [100.0]
    for i in range(60):
        eq.append(eq[-1] if i % 10 < 3 else eq[-1] * (1.02 if i % 2 else 0.98))
    trade_rets = [0.02 if i % 2 else -0.02 for i in range(60)]

    eq_sharpe = _equity_sharpe([{"equity": v} for v in eq])
    arr = np.asarray(trade_rets)
    trade_sharpe = float(arr.mean() / arr.std(ddof=1) * math.sqrt(min(len(arr), 250)))

    assert eq_sharpe is not None
    assert abs(eq_sharpe - trade_sharpe) > 0.5, (
        f"日权益口径 {eq_sharpe:.3f} 与逐笔口径 {trade_sharpe:.3f} 几乎相同 —— "
        f"要么本构造失效, 要么 `_equity_sharpe` 算的是逐笔口径"
    )


# ---------- 3. 行为 (需 DB) ----------

def _db_path() -> Path | None:
    """真实 DB 路径。**不要写死** —— 写错会让 skipif 恒真、guard 变空泛。"""
    try:
        from hiagent_config import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return None


@pytest.mark.skipif(_db_path() is None, reason="需要本地 DB (§6: 缺产物时 skip)")
def test_disclosure_field_is_populated_and_differs_from_reported() -> None:
    from short_reversal.engine import run_backtest_v3

    db = _db_path()
    assert db is not None
    m = run_backtest_v3("v58_mp_2", "2018-01-01", "2020-12-31", db)

    assert "sharpe_equity_basis" in m, "披露字段缺失 —— 不可比性会重新隐形"
    if m["sharpe_equity_basis"] is None:
        pytest.skip("本次运行未产出权益曲线, 无法计算姊妹口径")

    # 该字段必须真的来自权益曲线, 且与逐笔口径**确实不同** —— 否则它是恒等复制。
    assert abs(m["sharpe"] - m["sharpe_equity_basis"]) > 0.05, (
        f"逐笔 {m['sharpe']:.3f} 与日权益 {m['sharpe_equity_basis']:.3f} 几乎相同 —— "
        f"要么该字段是复制品 (缺陷), 要么本样本区分不出两种口径"
    )
