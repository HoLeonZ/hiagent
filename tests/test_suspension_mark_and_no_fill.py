"""§1 守卫:停牌(缺 bar)期间**按 last raw_close 盯市**,且**不得产生 fill**。

## 缺陷(审计 §3.2 的 HIGH×1,2026-10-16 复核确认成立)

`mark_price` 旧签名是 `(pi, j, fallback, price_source_for_execution)`,两个
DataFrame 引擎(chase_up / uptrend_pullback)在 `j is None`(当日无 bar)时
返回 `fallback`,而调用方一律传 `pos["entry_price"]`。于是:

  1. **盯市价 = 入场价** —— 停牌期内该仓位的浮盈浮亏全部消失,复牌当日
     再一次性跳回:一段真实行情在权益曲线上被抹掉又还回来;
  2. NAV 闸门(§2)拿这个假净值判断是否击穿,停牌股让闸门看不见亏损;
  3. 窗口末日强平按 `entry_price` 成交 —— 既**造出一笔现实中不可能成交的
     "≈0 盈亏"交易**,又把 §1 明令禁止的 fill 写进成交列表。

§1 原文:「Trading halts produce *missing bars*, not synthetic ones. ...
positions in suspended names are marked at the **last `raw_close`** and
**MUST NOT generate fills until trading resumes**.」

## 暴露面(实测,只读库,黄金窗口 2025-09-19→2026-09-19)

| 量 | 值 |
|---|---|
| universe / 交易日 | 3159 只 / 242 日 |
| 有缺口的股票数 | **299** |
| 缺口 (股票, 日) 事件总数 | **1348** |
| 窗口末日仍无 bar 的股票数 | **10** |
| 黄金批次(13 preset / 216 笔成交)中持仓区间跨越停牌日的笔数 | **0** |

**最后一行是本文件存在的理由**:缺陷真实且数据里天天发生,但黄金窗口的成交
集合**从未踩中**它(入场都是活跃票、持有期又短)。因此真实数据既无法暴露它、
也无法回归它 —— 只能靠合成夹具;而黄金基线的 sha256 也因此**零漂移**
(修复前后都通过),这正是"基线的绿不能替代守卫"的又一例。

## 本文件覆盖

- 行为层(端到端,chase_up):停牌日的盯市价 == last raw_close ≠ entry_price;
  停牌期间无成交;末日仍停牌 ⇒ 不入成交列表、按 last raw_close 留在净值里。
- 单元层(`core.dual_price.mark_price`):缺 bar 向前回退 / 无 bar fail-fast。
- 结构层:两个引擎都不得再把 `entry_price` 当盯市回退,且都必须有末日跳过分支。
"""
from __future__ import annotations

import logging
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.dual_price import mark_price
from core.trade_schema import EQUITY_COLS

REPO_ROOT = Path(__file__).resolve().parents[1]

_A, _B = "600001.SH", "600002.SH"
_DAYS = [f"2025-01-{d:02d}" for d in range(1, 21)]
_SUSPENDED = {"2025-01-06", "2025-01-07", "2025-01-08"}
# 信号日(= 次日开盘成交),第 3 天
_SIGNAL_DAY = "2025-01-02"
_ENTRY_PRICE = 10.0
# 停牌前最后一根 bar 的收盘价(≠ 入场价,相差 20% —— 两种实现必须能区分)
_LAST_RAW_BEFORE_HALT = 12.0


def _bar(code: str, day: str, o: float, c: float, h: float | None = None,
         lo: float | None = None) -> dict:
    return {
        "thscode": code, "date": pd.Timestamp(day),
        "open": o, "high": h if h is not None else max(o, c),
        "low": lo if lo is not None else min(o, c), "close": c,
        # 双价域夹具:无公司行为 ⇒ raw == adj(但 raw 列的存在让 raw-first 生效)
        "raw_open": o, "raw_high": h if h is not None else max(o, c),
        "raw_low": lo if lo is not None else min(o, c), "raw_close": c,
        "raw_prev_close": np.nan,
    }


def _panel(*, halted_to_end: bool) -> pd.DataFrame:
    """构造两周面板。

    A 在入场后停牌 3 天(第 6~8 天)再复牌;`halted_to_end=True` 时改为
    **一直停到窗口结束**(末日无 bar,触发"不得强平"分支)。
    B 全程交易,**只用于让日历包含停牌日** —— 这正是缺陷成立的前提:
    `cal` 是面板日期的并集,循环会走到 A 没有 bar 的日子。
    """
    rows: list[dict] = []
    for day in _DAYS:
        d = int(day[-2:])
        # B **每天**都有 bar(必须无条件追加,否则日历里就不会有停牌日,
        # 而"日历含停牌日"正是本缺陷成立的前提 —— 夹具自己也要守这个前提)。
        rows.append(_bar(_B, day, 20.0, 20.0))
        if d <= 3:
            rows.append(_bar(_A, day, 10.0, 10.0))
        elif d in (4, 5):
            # 入场日(第 3 天开盘成交)之后:收盘走到 12.0
            rows.append(_bar(_A, day, 10.0 if d == 4 else 12.0, 12.0))
        elif day in _SUSPENDED:
            continue  # 停牌 = 缺 bar,不是合成 bar
        elif halted_to_end:
            continue  # A 从此再无 bar(退市/长停)
        else:
            rows.append(_bar(_A, day, 12.0, 12.0))
    return pd.DataFrame(rows)


def _entries() -> pd.DataFrame:
    """一天一条信号:第 2 天对 A 发信号 ⇒ 第 3 天开盘成交。"""
    import chase_up.signals as sg

    row = {c: np.nan for c in sg.ENTRY_COLS}
    row.update({
        "date": pd.Timestamp(_SIGNAL_DAY), "thscode": _A,
        "score": 9.9, "sub_signal_type": "fixture",
        "sig_close": 10.0, "atr_pct": 0.02,
    })
    return pd.DataFrame([row])


def _run(*, halted_to_end: bool):
    from chase_up.portfolio import simulate_portfolio

    return simulate_portfolio(
        _entries(), _panel(halted_to_end=halted_to_end),
        tp_pct=9.9, sl_pct=0.99, max_hold=10_000, max_positions=1,
        start_date=_DAYS[0], end_date=_DAYS[-1],
        initial_capital=1_000_000.0,
        price_source_for_execution="raw_close",
        # 夹具不含 volume 列 ⇒ 不施加量比约束(与本用例无关)
        max_volume_participation=0.10,
    )


def _holdings_by_day(eq: pd.DataFrame) -> dict[str, float]:
    return {
        pd.Timestamp(r["date"]).strftime("%Y-%m-%d"): float(r["holdings"])
        for _, r in eq.iterrows()
    }


# ---------------------------------------------------------------------------
# 行为层(端到端)
# ---------------------------------------------------------------------------


def test_suspended_days_are_marked_at_last_raw_close_not_entry_price() -> None:
    """§1: 停牌日盯市 == last raw_close,且**不等于**入场价。

    夹具刻意让两者相差 20%(_LAST_RAW_BEFORE_HALT vs _ENTRY_PRICE)——
    旧实现(回退 `entry_price`)必然失败,故本断言是双向的。
    """
    trades, eq = _run(halted_to_end=False)
    assert len(trades) == 1, "夹具应恰好成交一笔"
    size = float(trades.iloc[0]["size"])
    assert float(trades.iloc[0]["entry_price"]) == pytest.approx(_ENTRY_PRICE)

    holdings = _holdings_by_day(eq)
    for day in sorted(_SUSPENDED):
        assert day in holdings, f"日历缺少停牌日 {day}(夹具前提被破坏)"
        marked = holdings[day]
        assert marked == pytest.approx(size * _LAST_RAW_BEFORE_HALT), (
            f"§1 VIOLATION {day}: 停牌日盯市 {marked:,.2f} "
            f"!= size × last_raw_close = {size * _LAST_RAW_BEFORE_HALT:,.2f}"
        )
        assert marked != pytest.approx(size * _ENTRY_PRICE), (
            f"§1 VIOLATION {day}: 盯市回退到了入场价 —— "
            "停牌期间的行情被抹平,复牌当日会一次性跳回"
        )


def test_no_fill_is_generated_while_the_name_is_halted() -> None:
    """§1: 停牌期间不得产生任何 fill(成交日期不得落在缺口里)。"""
    trades, eq = _run(halted_to_end=False)
    halted = {pd.Timestamp(d) for d in _SUSPENDED}
    for _, t in trades.iterrows():
        for col in ("entry_date", "exit_date"):
            assert pd.Timestamp(t[col]) not in halted, (
                f"§1 VIOLATION: 停牌日 {t[col]} 上产生了成交 {t['thscode']}"
            )
    # 停牌期间权益**连续**:缺口前后不出现跳空(两版实现的差别就在这里)
    eq_indexed = eq.set_index(pd.to_datetime(eq["date"]))["equity"]
    for d in sorted(halted):
        assert d in eq_indexed.index


def _entry_size() -> float:
    """从"复牌"夹具里读回 size —— 两个夹具的建仓路径完全相同,不硬编码。"""
    trades, _ = _run(halted_to_end=False)
    assert len(trades) == 1
    return float(trades.iloc[0]["size"])


def test_position_still_halted_at_window_end_is_not_force_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§1: 末日仍停牌的持仓**不得**被强平 —— 不入成交列表,但按 last raw_close 留在净值里。"""
    size = _entry_size()
    with caplog.at_level(logging.WARNING):
        trades, eq = _run(halted_to_end=True)

    assert len(trades) == 0, (
        f"§1 VIOLATION: 末日仍停牌的持仓被强平并入表 —— "
        f"造出一笔现实中不可能成交的交易: {trades.to_dict('records')}"
    )
    last = eq.iloc[-1]
    assert float(last["holdings"]) > 0, "未平仓市值必须仍计入净值"
    assert float(last["holdings"]) == pytest.approx(size * _LAST_RAW_BEFORE_HALT), (
        "未平仓市值必须按 last raw_close 计量"
    )
    assert any(_A in r.getMessage() for r in caplog.records), (
        "未强平必须留下可见痕迹(warning),不能静默吞掉"
    )


def test_cash_identity_still_holds_with_an_unclosed_position() -> None:
    """§2: 有未平仓仓位时,equity = 初始 + Σ已实现 + 未平仓净额(市值 − 成本基础)。"""
    trades, eq = _run(halted_to_end=True)
    last = eq.iloc[-1]
    realised = float(trades["net_pnl"].sum()) if len(trades) else 0.0
    open_net = float(last["holdings"]) - float(last["locked_margin"])
    assert float(last["equity"]) == pytest.approx(
        1_000_000.0 + realised + float(last["cum_dividends"]) + open_net, rel=1e-9
    )
    for col in EQUITY_COLS:
        assert col in eq.columns


# ---------------------------------------------------------------------------
# 单元层:核心函数的回退方向
# ---------------------------------------------------------------------------


def test_mark_price_walks_back_to_the_last_available_bar() -> None:
    pi = {
        "dates": np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[ns]"),
        "close": np.array([10.0, 11.0]),
        "raw_close": np.array([10.0, 11.0]),
    }
    day = np.datetime64("2025-01-05", "ns")
    assert mark_price(pi, day, "raw_close") == pytest.approx(11.0)


def test_mark_price_refuses_to_invent_a_price() -> None:
    pi = {
        "dates": np.array(["2025-01-05"], dtype="datetime64[ns]"),
        "close": np.array([10.0]),
    }
    with pytest.raises(ValueError, match="无法盯市"):
        mark_price(pi, np.datetime64("2025-01-01", "ns"), "raw_close")


# ---------------------------------------------------------------------------
# 结构层:两个 DataFrame 引擎都不得退回旧写法
# ---------------------------------------------------------------------------

_ENGINES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
}


def _stmt_after(tree: ast.AST, line: int) -> ast.stmt:
    """锚点注释**之后**的第一条语句(注释进不了 AST,故只用它定位**行号**)。"""
    cands = [n for n in ast.walk(tree)
             if isinstance(n, ast.stmt) and n.lineno >= line + 1]
    assert cands, "锚点之后找不到任何语句 —— 该段结构变了"
    return min(cands, key=lambda n: n.lineno)


@pytest.mark.parametrize("engine,path", sorted(_ENGINES.items()))
def test_no_engine_marks_with_entry_price_as_fallback(engine: str, path: Path) -> None:
    """盯市不得再接受"调用方给的成本价"这个输入 —— 它没有一句话说得通。"""
    src = path.read_text(encoding="utf-8")
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "mark_price(" in code
    for ln in code.splitlines():
        if "mark_price(" in ln and "def " not in ln:
            assert "entry_price" not in ln, (
                f"§1 VIOLATION {engine}: 盯市仍在回退到入场价 —— {ln.strip()}"
            )


@pytest.mark.parametrize("engine,path", sorted(_ENGINES.items()))
def test_every_engine_guards_the_window_end_force_close(engine: str, path: Path) -> None:
    """末日强平必须先判当日是否有 bar(§1:停牌不得成交)。

    ⚠️ 2026-10-22 (附一百八十七): 本用例此前是**文本切片 + 字面量**判据 ——

        start = src.index("末日强制平仓"); block = src[start:start + 1400]
        assert "_row_at(pi, day) is None" in block

    而实现已经从「**直接比较**」改成「**先绑定再判 None**」:

        j = _row_at(pi, day)          # ← 必须绑定: 下游 `_exit_fill_px(..., j, ...)` 要用
        if j is None:
            _unclosed_at_window_end.append(code); continue

    (该行注释里写明理由: 不绑定的话 `j` 会退化成上一轮循环残留的行号 ⇒ 拿**别的票的 bar**
     算成交量。)⇒ 判据找的那个字面量**再也不存在**, 而它要保的性质**一直都在**。
    另有 1400 字符的魔数窗口 —— 上游加几行注释就够不着了。

    现改为 AST: 用注释**只定位行号**, 然后断言**性质** ——
      `_row_at` 被调用 → 结果**被绑定** → 该绑定名被判 `None` → 分支里 `continue`(不产生 fill)
      → 且**同一个绑定名**被传给 `_close_position`(这正是"必须绑定"的理由)。
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    line = next((i for i, l in enumerate(src.splitlines(), 1) if "末日强制平仓" in l), None)
    assert line is not None, (
        f"§1 VIOLATION {engine}: 找不到「末日强制平仓」段 —— 该段被删除或改名了"
    )
    block = _stmt_after(tree, line)

    def _calls_row_at(node: ast.AST) -> bool:
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == "_row_at" for c in ast.walk(node))

    assert _calls_row_at(block), (
        f"§1 VIOLATION {engine}: 末日强平不判当日是否有 bar(`_row_at` 未出现)"
    )

    # 1) 结果必须**被绑定**(理由见该行注释: 否则下游读到上一轮残留的行号)
    bound = {
        t.id
        for a in ast.walk(block) if isinstance(a, ast.Assign)
        for t in a.targets if isinstance(t, ast.Name)
        if _calls_row_at(a.value)
    }
    assert bound, (
        f"§1 VIOLATION {engine}: `_row_at(...)` 的结果未被绑定 —— "
        f"下游会读到上一轮循环残留的行号(拿别的票的 bar 算成交量)"
    )

    # 2) 绑定名必须被判 None, 且该分支 `continue`(不产生 fill)
    guards = [
        i for i in ast.walk(block)
        if isinstance(i, ast.If)
        and isinstance(i.test, ast.Compare)
        and any(isinstance(op, (ast.Is, ast.Eq)) for op in i.test.ops)
        and any(isinstance(x, ast.Constant) and x.value is None for x in i.test.comparators)
        and isinstance(i.test.left, ast.Name) and i.test.left.id in bound
    ]
    assert guards, f"§1 VIOLATION {engine}: 没有对 {sorted(bound)} 的 None 判定"
    assert any(any(isinstance(st, ast.Continue) for st in ast.walk(g)) for g in guards), (
        f"§1 VIOLATION {engine}: 停牌持仓未被跳过(缺 continue)⇒ 会造出一笔现实中不存在的假成交"
    )

    # 3) 同一个绑定名必须被**复用**到成交价计算 —— 这正是"必须绑定"的理由
    reused = any(
        isinstance(c, ast.Call)
        and any(isinstance(arg, ast.Name) and arg.id in bound for arg in c.args)
        for c in ast.walk(block)
    )
    assert reused, (
        f"§1 VIOLATION {engine}: 绑定名 {sorted(bound)} 未被复用到成交价计算 —— "
        f"'必须绑定'这条注释的理由不再成立, 说明该段被改写过"
    )
